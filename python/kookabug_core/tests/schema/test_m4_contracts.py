"""M4 계약 (M4 계획 2.12): 녹화 임대권 소유자, 훅 메시지, 가짜 각본, 커밋 조각, daemon 녹화 메서드.

새 필드는 기존 파일이 그대로 읽히게 선택이거나 새 종류다. 예전 임대권 옆 파일(M0b: kind 둘·device
없음, M1: device)이 그대로 맞아야 한다.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from kookabug_core.inputs.lease import LeaseOwner as CoreLeaseOwner
from kookabug_core.recorder.continuity import ContinuityChecker
from kookabug_core.recorder.contract import BATCH_MAX_EVENTS, OBS_MAX_SKEW_NS, obs_usable
from kookabug_core.recorder.fragment import fragment_problems
from kookabug_core.schema import check_shape, metaschema
from kookabug_core.schema.models.daemon_rpc import LeaseFile, RecorderStep, RecorderStepsResult
from kookabug_core.schema.models.recorder_fragment import RecorderFragment
from kookabug_core.schema.models.recorder_hook import RecorderHookMessage
from kookabug_core.schema.models.recorder_script import RecorderScriptLine
from kookabug_core.schema.models.workspace import Workspace
from kookabug_core.schema.shape import validator

RPC_DEFS: dict[str, Any] = metaschema("daemon-rpc")["$defs"]
HOOK_DEFS: dict[str, Any] = metaschema("recorder-hook")["$defs"]
SCRIPT_DEFS: dict[str, Any] = metaschema("recorder-script")["$defs"]
MS = 1_000_000
CREATED = 133_700_000_000_000_000  # FILETIME (2^53 넘음)
MARK = 0x4B4F4F4B  # 검사용 임의 표식 값 (제품 상수는 T2가 정한다)


def errors(kind: Any, name: str, value: Any) -> list[str]:
    return [e.message for e in validator(kind, f"#/$defs/{name}").iter_errors(value)]


def rpc(name: str, value: Any) -> list[str]:
    return errors("daemon-rpc", name, value)


def hook_message(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def roundtrip_hook(message: dict[str, Any]) -> None:
    assert check_shape(message, "recorder-hook") == [], message
    model = RecorderHookMessage.model_validate(message)
    assert model.model_dump(mode="json", exclude_unset=True) == message


# ------------------------------------------------------------------ 임대권 소유자


def owner_json(kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "workspace": "D:/ws",
        "run_id": None,
        "run_dir": None,
        "pid": 4242,
        "created": CREATED,
        **fields,
    }


def test_lease_owner_kind_recorder_and_old_files_valid() -> None:
    # M0b 옆 파일: kind 둘, device 없음 (LeaseOwner.to_json 그대로)
    m0b = CoreLeaseOwner.current("runner", run_id="abcd1234", run_dir="D:/ws/runs/x").to_json()
    assert "device" not in m0b
    old_files = [
        {"owner": m0b, "clean": False},
        {"owner": None, "clean": True, "last_owner": m0b},
        # M1: 장치를 함께 적는다
        {"owner": {**m0b, "device": {"kind": "windows"}}, "clean": False},
        {
            "owner": {**m0b, "kind": "supervisor", "device": {"kind": "fake", "input_log": "D:/l"}},
            "clean": False,
        },
    ]
    for data in old_files:
        assert rpc("LeaseFile", data) == [], data
        LeaseFile.model_validate(data)

    # 녹화 소유자: daemon, 실행 없음(run_id·run_dir null), 장치 none
    recorder = owner_json("recorder", device={"kind": "none"})
    assert rpc("LeaseOwner", recorder) == []
    assert rpc("LeaseFile", {"owner": None, "clean": True, "last_owner": recorder}) == []
    without_run = {k: v for k, v in recorder.items() if k not in ("run_id", "run_dir", "device")}
    assert rpc("LeaseOwner", without_run) == []
    # 녹화 소유자에게 실행·입력 장치가 있으면 계약 위반
    assert rpc("LeaseOwner", {**recorder, "run_id": "abcd1234"}) != []
    assert rpc("LeaseOwner", {**recorder, "device": {"kind": "windows"}}) != []
    assert rpc("LeaseOwner", owner_json("mcp")) != []

    # 알림·오류: created는 10진 문자열 (값 규칙 밖 정수)
    wire = {**recorder, "created": str(CREATED)}
    assert rpc("LeaseChangedParams", {"owner": wire}) == []
    assert rpc("LeaseChangedParams", {"owner": None}) == []
    # M2 렌더러 검사가 쓰던 최소 소유자도 맞는다
    minimal = {"kind": "runner", "run_id": "abcd1234", "pid": 7, "created": "133000000000000000"}
    assert rpc("LeaseChangedParams", {"owner": minimal}) == []
    busy = {"code": "input_lease_busy", "owner": wire}
    assert rpc("RequestFailedData", busy) == []
    assert rpc("RequestFailedData", {"code": "input_lease_busy", "owner": None}) == []
    # 복구 기록의 주체 종류도 같은 열거값
    recovered = {
        "event": "input.recovered",
        "run": "abcd1234",
        "seq": 3,
        "t": "2026-11-04T01:02:03.004Z",
        "by": {"kind": "recorder"},
        "from_run": "zzzz9999",
        "inputs": [],
    }
    assert check_shape(recovered, "events") == []


# ------------------------------------------------------------------ 훅 이벤트


def mouse(event_id: int, t_ms: float, kind: str = "mouse_move", **f: Any) -> dict[str, Any]:
    event = {
        "event_id": event_id,
        "t_ns": int(t_ms * MS),
        "kind": kind,
        "x": 100,
        "y": 200,
        "injected": False,
        "injected_lower_il": False,
        "extra_info": 0,
        **f,
    }
    return event


def key(event_id: int, t_ms: float, crit: int, kind: str = "key_down", **f: Any) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "crit_seq": crit,
        "t_ns": int(t_ms * MS),
        "kind": kind,
        "vk": 0x41,
        "scan": 0x1E,
        "extended": False,
        "injected": False,
        "injected_lower_il": False,
        "extra_info": 0,
        **f,
    }


def test_hook_event_shape_ids_monotonic_ns() -> None:
    good = [
        mouse(1, 0.5),
        mouse(3, 1.0, "mouse_down", crit_seq=1, button="left"),
        mouse(4, 1.2, "mouse_up", crit_seq=2, button="left"),
        mouse(5, 2.0, "wheel", crit_seq=3, delta=-120),
        mouse(6, 2.1, "wheel", crit_seq=4, delta=120, horizontal=True),
        key(9, 3.0, 5),
        key(10, 3.1, 6, "key_up", extra_info=str(2**60), injected=True),
    ]
    for event in good:
        assert errors("recorder-hook", "HookEvent", event) == [], event
    bad = {
        # 이동은 crit_seq를 쓰지 않는다 (2차 N1)
        "move_with_crit": mouse(1, 0.5, crit_seq=1),
        # 중요 이벤트는 crit_seq가 반드시 있다
        "down_without_crit": mouse(2, 1.0, "mouse_down", button="left"),
        "key_without_crit": {k: v for k, v in key(3, 1.0, 1).items() if k != "crit_seq"},
        "down_without_button": mouse(2, 1.0, "mouse_down", crit_seq=1),
        "wheel_without_delta": mouse(2, 1.0, "wheel", crit_seq=1),
        "key_with_point": key(3, 1.0, 1, x=1, y=2),
        "key_without_vk": {k: v for k, v in key(3, 1.0, 1).items() if k != "vk"},
        # 시각은 녹화 기준 시각부터 잰 단조 ns 정수 (벽시계 문자열·음수 아님)
        "wall_clock": {**key(3, 1.0, 1), "t_ns": "2026-11-04T01:02:03.004Z"},
        "negative_t": {**key(3, 1.0, 1), "t_ns": -1},
        "float_t": {**key(3, 1.0, 1), "t_ns": 1.5},
        "zero_event_id": {**key(3, 1.0, 1), "event_id": 0},
        "zero_crit": key(3, 1.0, 0),
        "big_extra_info_int": key(3, 1.0, 1, extra_info=2**60),
    }
    for name, event in bad.items():
        assert errors("recorder-hook", "HookEvent", event) != [], name
    # 묶음 안 event_id는 빈 번호가 있어도 되고(이동 합치기·표식 제외), 받는 쪽 검사기가 차례만 본다
    checker = ContinuityChecker()
    batch = events_batch(1, good, crit=(1, 6))
    roundtrip_hook(hook_message("hook.events", batch))
    assert checker.feed_events(batch) is None
    reordered = events_batch(2, [key(8, 4.0, 7)], crit=(7, 7))
    assert checker.feed_events(reordered) is not None
    assert checker.violation is not None and checker.violation.reason == "event_order"


# ------------------------------------------------------------------ 즉시 관측


def obs(cause: int, at_ms: float, changed_ms: float = 0.0, **f: Any) -> dict[str, Any]:
    return {
        "cause_event_id": cause,
        "obs_at_ns": int(at_ms * MS),
        "fg": 1001,
        "fg_thread": 77,
        "focus": 1002,
        "hkl": "4120412",
        "table_changed_ns": int(changed_ms * MS),
        "zorder_rev": 5,
        **f,
    }


def test_hook_obs_shape_and_undetermined() -> None:
    sample = obs(9, 3.5, point_window=1001, point_owner=None, fg_owner=None, focus_password=True)
    assert errors("recorder-hook", "ImmediateObs", sample) == []
    # 읽지 못한 값은 null (판정 불가의 재료)
    unread = obs(9, 3.5, fg=None, fg_thread=None, focus=None, hkl=None, focus_password=None)
    assert errors("recorder-hook", "ImmediateObs", unread) == []
    roundtrip_hook(hook_message("hook.obs", {"batch": [sample, unread]}))
    for missing in ("cause_event_id", "obs_at_ns", "table_changed_ns", "zorder_rev"):
        broken = {k: v for k, v in sample.items() if k != missing}
        assert errors("recorder-hook", "ImmediateObs", broken) != [], missing
    assert errors("recorder-hook", "ImmediateObs", {**sample, "hkl": "0x0412"}) != []

    event = key(9, 3.0, 5)
    assert obs_usable(event, obs(9, 3.5))
    # 판정 불가: 다른 이벤트의 관측, 50 ms 넘게 늦은 관측, 이벤트 뒤 표가 바뀐 관측, 관측 없음
    assert not obs_usable(event, obs(8, 3.5))
    late = 3.0 + OBS_MAX_SKEW_NS / MS + 0.001
    assert obs_usable(event, obs(9, 3.0 + OBS_MAX_SKEW_NS / MS))
    assert not obs_usable(event, obs(9, late))
    assert not obs_usable(event, obs(9, 3.5, changed_ms=3.2))
    assert obs_usable(event, obs(9, 3.5, changed_ms=3.0))
    assert not obs_usable(event, None)


# ------------------------------------------------------------------ IME 표본


def ime(at_ms: float, status: str = "ok", mode: str = "native", **f: Any) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "query_started_ns": int((at_ms - 0.2) * MS),
        "sampled_at_ns": int(at_ms * MS),
        "fg": 1001,
        "fg_thread": 77,
        "hkl": "4120412",
        "mode": mode,
        "status": status,
        "trigger": "key",
        **f,
    }
    if status == "ok" and "conversion" not in f:
        sample["conversion"] = 1 if mode == "native" else 0
    return sample


def test_hook_ime_sample_shape() -> None:
    ok_native, ok_alpha = ime(10), ime(260, mode="alphanumeric", trigger="periodic")
    # 3차 검수 N6: 실패 표본도 조회 구간(query_started_ns ~ sampled_at_ns)을 실어 보낸다 — 받는 쪽이
    # 그 구간과 겹치는 키를 판정 불가로 만든다 (앞 정상 표본으로 건너뛰어 확정하지 않음)
    timeout = ime(170, "timeout", "unknown")
    timeout["query_started_ns"] = 120 * MS
    failed = ime(400, "failed", "unknown", fg=None, fg_thread=None, hkl=None, trigger="foreground")
    no_ime = ime(500, "no_ime", "unknown", trigger="hkl")
    for sample in (ok_native, ok_alpha, timeout, failed, no_ime):
        assert errors("recorder-hook", "ImeSample", sample) == [], sample
    roundtrip_hook(hook_message("hook.ime", {"batch": [ok_native, timeout, ok_alpha]}))
    assert timeout["sampled_at_ns"] - timeout["query_started_ns"] == 50 * MS
    bad = {
        # 정상이면 모드를 알고 원래 비트가 있다
        "ok_unknown": ime(10, mode="unknown", conversion=0),
        "ok_without_conversion": {k: v for k, v in ok_native.items() if k != "conversion"},
        # 실패면 모드는 unknown, 비트 없음 (실패를 정상처럼 보이게 하지 않는다)
        "timeout_with_mode": ime(170, "timeout", "native"),
        "timeout_with_conversion": {**timeout, "conversion": 1},
        "no_query_start": {k: v for k, v in timeout.items() if k != "query_started_ns"},
        "bad_trigger": {**ok_native, "trigger": "guess"},
    }
    for name, sample in bad.items():
        assert errors("recorder-hook", "ImeSample", sample) != [], name


# ------------------------------------------------------------------ 묶음 번호·누적 개수


def events_batch(
    batch_no: int,
    events: list[dict[str, Any]],
    *,
    crit: tuple[int, int] | None,
    dropped_marker: int = 0,
    coalesced_moves: int = 0,
    overflow: int = 0,
) -> dict[str, Any]:
    return {
        "batch_no": batch_no,
        "events": events,
        "crit_first": None if crit is None else crit[0],
        "crit_last": None if crit is None else crit[1],
        "dropped_marker": dropped_marker,
        "coalesced_moves": coalesced_moves,
        "overflow": overflow,
    }


def test_hook_events_batch_counters() -> None:
    batch = events_batch(1, [mouse(1, 0.1), key(2, 0.2, 1)], crit=(1, 1), coalesced_moves=4)
    assert errors("recorder-hook", "HookEventsParams", batch) == []
    moves_only = events_batch(2, [mouse(9, 1.0)], crit=None, dropped_marker=2)
    assert errors("recorder-hook", "HookEventsParams", moves_only) == []
    empty = events_batch(3, [], crit=None)
    assert errors("recorder-hook", "HookEventsParams", empty) == []
    bad = {
        "half_range": {**batch, "crit_last": None},
        "range_without_first": {**moves_only, "crit_last": 3},
        "batch_zero": {**batch, "batch_no": 0},
        "negative_counter": {**batch, "overflow": -1},
        "missing_counter": {k: v for k, v in batch.items() if k != "coalesced_moves"},
        "too_many": {
            **moves_only,
            "events": [mouse(i + 1, i) for i in range(BATCH_MAX_EVENTS + 1)],
        },
    }
    for name, value in bad.items():
        assert errors("recorder-hook", "HookEventsParams", value) != [], name
    health = {
        "batch_no": 0,
        "last_event_ns": None,
        "last_input_tick": 4_000_000_000,
        "sent_at_ns": 0,
    }
    roundtrip_hook(hook_message("hook.health", health))
    hello = {
        "pid": 5150,
        "created": str(CREATED),
        "dpi_awareness": "per_monitor_v2",
        "mono_base_ns": "987654321012345678",
        "protocol": 1,
        "hooks": {"mouse": True, "keyboard": True},
    }
    roundtrip_hook(hook_message("hook.hello", hello))
    roundtrip_hook(hook_message("hook.stop", {}))
    assert check_shape(hook_message("hook.hello", {**hello, "protocol": 2}), "recorder-hook") != []
    assert check_shape(hook_message("hook.nope", {}), "recorder-hook") != []


def test_continuity_rules_mixed_stream() -> None:
    # 2차 N1: 같은 스트림에 이동 합치기·우리 표식 제외·실제 중요 이벤트 유실을 섞는다.
    # event_id 2·3(합쳐진 이동), 5(우리 표식으로 버린 키)는 빈 번호이고 crit_seq를 쓰지 않았다
    stream = [
        events_batch(1, [mouse(1, 0.1), mouse(4, 0.4)], crit=None, coalesced_moves=2),
        events_batch(
            2,
            [key(6, 0.6, 1), key(7, 0.7, 2, "key_up")],
            crit=(1, 2),
            coalesced_moves=2,
            dropped_marker=1,
        ),
        events_batch(
            3,
            [mouse(9, 0.9, "mouse_down", crit_seq=3, button="left")],
            crit=(3, 3),
            coalesced_moves=5,
            dropped_marker=3,
        ),
    ]
    checker = ContinuityChecker()
    for batch in stream:
        assert errors("recorder-hook", "HookEventsParams", batch) == []
        assert checker.feed_events(batch) is None, batch["batch_no"]
    health = {"batch_no": 3, "last_event_ns": 9 * MS, "last_input_tick": 1, "sent_at_ns": 10 * MS}
    assert checker.feed_health(health) is None
    # 실제 유실: 중요 큐가 차서 crit_seq 5를 버렸다 (번호는 쓰였으니 빈틈, overflow 누적 1)
    lost = events_batch(
        4,
        [mouse(10, 1.0, "mouse_up", crit_seq=4, button="left"), key(12, 1.2, 6)],
        crit=(4, 6),
        coalesced_moves=5,
        dropped_marker=3,
        overflow=1,
    )
    violation = checker.feed_events(lost)
    assert violation is not None
    assert (violation.reason, violation.batch_no, violation.cut_crit_seq) == ("overflow", 4, 5)
    # 위반은 끈적하다: 뒤 묶음은 이어 붙이지 않는다
    assert checker.feed_events(events_batch(5, [], crit=None, overflow=1)) is violation

    # overflow 표시 없이 생긴 빈틈(보내는 쪽 버그·잃은 묶음)도 위반
    gap = ContinuityChecker()
    assert gap.feed_events(stream[0]) is None
    skipped = events_batch(2, [key(6, 0.6, 2)], crit=(2, 2), coalesced_moves=2)
    v = gap.feed_events(skipped)
    assert v is not None and (v.reason, v.cut_crit_seq) == ("crit_gap", 1)
    # 묶음 번호 빈틈
    batch_gap = ContinuityChecker()
    assert batch_gap.feed_events(stream[0]) is None
    v = batch_gap.feed_events({**stream[2], "batch_no": 3})
    assert v is not None and (v.reason, v.cut_crit_seq) == ("batch_gap", 1)
    # 생존 보고가 받은 것보다 뒤 묶음을 말함 = 묶음을 잃음
    health_gap = ContinuityChecker()
    assert health_gap.feed_events(stream[0]) is None
    v = health_gap.feed_health(
        {"batch_no": 2, "last_event_ns": None, "last_input_tick": 0, "sent_at_ns": 1}
    )
    assert v is not None and v.reason == "batch_gap"
    # 누적 개수가 줄면 위반, crit 범위가 이벤트와 다르면 위반
    regress = ContinuityChecker()
    assert regress.feed_events(stream[0]) is None
    v = regress.feed_events(events_batch(2, [], crit=None, coalesced_moves=1))
    assert v is not None and v.reason == "counter_regressed"
    wrong_range = ContinuityChecker()
    v = wrong_range.feed_events(events_batch(1, [key(1, 0.1, 1)], crit=(1, 2)))
    assert v is not None and v.reason == "crit_range"


# ------------------------------------------------------------------ 가짜 각본


GEOMETRY = {
    "frame_bounds": [92, 70, 1282, 751],
    "client_origin": [93, 100],
    "client_size": [1280, 720],
    "dpi": 96,
}


def test_recorder_script_line_shape() -> None:
    raw_key = {k: v for k, v in key(1, 0, 1).items() if k not in ("event_id", "crit_seq", "t_ns")}
    raw_click = {
        k: v
        for k, v in mouse(1, 0, "mouse_down", button="left").items()
        if k not in ("event_id", "t_ns")
    }
    script = [
        {
            "kind": "header",
            "format": "kookabug.recorder-script/0",
            "title": "SampleRPG",
            "geometry": GEOMETRY,
            "scene": "title",
        },
        {"kind": "observe", "t_ns": 0, "fg": "target", "point": "target", "hkl": "4090409"},
        {"kind": "ime", "t_ns": 0, "mode": "alphanumeric"},
        {"kind": "frame", "arrival_ns": 1 * MS},
        {"kind": "input", "t_ns": 500 * MS, "input": raw_click},
        {"kind": "input", "t_ns": 501 * MS, "input": {**raw_click, "extra_info": MARK}},
        {"kind": "scene", "t_ns": int(500.5 * MS), "scene": "login"},
        {
            "kind": "geometry",
            "t_ns": 600 * MS,
            "notify_ns": 700 * MS,
            "geometry": {
                **GEOMETRY,
                "frame_bounds": [192, 70, 1282, 751],
                "client_origin": [193, 100],
            },
        },
        {"kind": "frame", "arrival_ns": 650 * MS, "buffer_size": [1282, 751]},
        {"kind": "observe", "t_ns": 800 * MS, "fg": None, "delay_ms": 80},
        {"kind": "ime", "t_ns": 900 * MS, "mode": "native", "status": "timeout", "respond_ms": 50},
        {"kind": "input", "t_ns": 1000 * MS, "input": raw_key},
        {"kind": "mark", "t_ns": 1000 * MS, "label": "password_start"},
        {"kind": "fault", "t_ns": 2000 * MS, "fault": "overflow", "count": 1},
        {"kind": "fault", "t_ns": 3000 * MS, "fault": "hook_exit"},
    ]
    for line in script:
        assert check_shape(line, "recorder-script") == [], line
        model = RecorderScriptLine.model_validate(line)
        assert model.model_dump(mode="json", exclude_unset=True) == line
    bad = [
        {
            "kind": "header",
            "format": "kookabug.recorder-script/1",
            "title": "x",
            "geometry": GEOMETRY,
            "scene": "title",
        },
        # 원시 입력은 번호를 매기기 전 모양 (번호는 가짜 훅 원천이 훅 프로세스 규칙으로 매긴다)
        {"kind": "input", "t_ns": 0, "input": key(1, 0, 1)},
        {"kind": "observe", "t_ns": 0, "fg": "desktop"},
        {"kind": "fault", "t_ns": 0, "fault": "explode"},
        {"kind": "geometry", "t_ns": 0, "geometry": {**GEOMETRY, "dpi": 0}},
    ]
    for line in bad:
        assert check_shape(line, "recorder-script") != [], line

    # 원시 입력 = 훅 이벤트에서 번호·시각을 뺀 모양 (두 정의가 갈라지지 않게)
    hook_props = dict(HOOK_DEFS["HookEvent"]["properties"])
    raw_props = SCRIPT_DEFS["RawInput"]["properties"]
    assert set(hook_props) - {"event_id", "crit_seq", "t_ns"} == set(raw_props)
    for name, schema in raw_props.items():
        theirs = hook_props[name]
        if "$ref" in schema:
            assert schema["$ref"].endswith(theirs["$ref"].removeprefix("#")), name
        else:
            assert {k: v for k, v in schema.items() if k != "description"} == {
                k: v for k, v in theirs.items() if k != "description"
            }, name
    assert set(HOOK_DEFS["HookEvent"]["required"]) - {"event_id", "t_ns"} == set(
        SCRIPT_DEFS["RawInput"]["required"]
    )


def test_ring_frame_and_geometry_generation_shape() -> None:
    # 검수 H3: 링 항목은 원본 버퍼 크기·도착 시각만 (기하 없음 — 링은 자르지 않는다)
    ring = {"seq": 7, "arrival_ns": 123 * MS, "buffer_size": [1282, 751]}
    assert errors("recorder-script", "RingFrame", ring) == []
    assert set(SCRIPT_DEFS["RingFrame"]["properties"]) == {"seq", "arrival_ns", "buffer_size"}
    for extra in (
        {"client_origin": [1, 2]},
        {"dpi": 96},
        {"pixels_at": "2026-11-04T00:00:00.000Z"},
    ):
        assert errors("recorder-script", "RingFrame", {**ring, **extra}) != [], extra
    # 세대: 기하 넷 + 확정 구간 [from_ns, confirmed_at_ns]
    gen = {"gen": 2, **GEOMETRY, "from_ns": 700 * MS, "confirmed_at_ns": 900 * MS}
    assert errors("recorder-script", "GeometryGeneration", gen) == []
    assert set(SCRIPT_DEFS["GeometryGeneration"]["required"]) == {
        "gen",
        "frame_bounds",
        "client_origin",
        "client_size",
        "dpi",
        "from_ns",
        "confirmed_at_ns",
    }
    for missing in ("frame_bounds", "client_origin", "from_ns", "confirmed_at_ns"):
        broken = {k: v for k, v in gen.items() if k != missing}
        assert errors("recorder-script", "GeometryGeneration", broken) != [], missing
    assert errors("recorder-script", "GeometryGeneration", {**gen, "gen": 0}) != []


# ------------------------------------------------------------------ 커밋 조각


def new_test_fragment() -> dict[str, Any]:
    return {
        "mode": "new_test",
        "nodes": [
            {
                "local_id": "r1",
                "type": "core.app.launch",
                "version": 1,
                "title": "게임 띄우기",
                "in": {"path": {"$setting": "game.path"}},
                "next": {"ok": "r2"},
            },
            {
                "local_id": "r2",
                "type": "core.image.click",
                "version": 1,
                "title": '이미지 클릭 "시작"',
                "in": {"target": {"$target": "targets/rec/login/01_시작.target.json"}},
                "next": {"ok": "r3"},
            },
            {
                "local_id": "r3",
                "type": "core.image.wait",
                "version": 1,
                "title": "나타날 때까지 대기",
                "in": {
                    "target": {"$target": "targets/rec/login/02_bag.target.json"},
                    "timeout_ms": 10000,
                },
                "next": {"found": "r4"},
            },
            {
                "local_id": "r4",
                "type": "core.input.drag",
                "version": 1,
                "title": "끌기",
                "in": {
                    "start": {"$link": "r3.match"},
                    "end": [400, 300],
                    "via": [{"$literal": {"$link": "r9.x"}}],
                },
                "next": {"ok": "r5"},
            },
            {
                "local_id": "r5",
                "type": "core.input.type_text",
                "version": 1,
                "title": "글자 입력",
                "in": {"text": {"$secret": "game.password"}, "clear": True},
                "next": {"ok": "r6"},
            },
            {"local_id": "r6", "type": "core.test.pass", "version": 1, "title": "통과", "in": {}},
        ],
        "chain": ["r1", "r2", "r3", "r4", "r5", "r6"],
        "first_window_node": "r1",
        "warnings": [{"code": "no_assertion", "message": "검증이 없어 끝까지 가면 통과예요"}],
    }


def test_fragment_shape_local_ids_links_and_open_end() -> None:
    fragment = new_test_fragment()
    assert check_shape(fragment, "recorder-fragment") == []
    assert fragment_problems(fragment) == []
    RecorderFragment.model_validate(fragment)
    # in 값은 그래프 Value 규칙 그대로
    graph_value = validator("graph", "#/$defs/Value")
    for node in fragment["nodes"]:
        for value in node["in"].values():
            assert list(graph_value.iter_errors(value)) == [], value
    # daemon-rpc commit_prepare 결과로 실린다
    result = {
        "token": "t" * 24,
        "fragment": fragment,
        "targets": [
            {
                "path": "targets/rec/login/01_시작.target.json",
                "revision": "a" * 64 + ":" + "b" * 64,
                "reused": False,
            }
        ],
    }
    assert rpc("RecorderCommitPrepareResult", result) == []

    # 삽입: 맨 앞 창 노드·종료 노드 없이 열린 끝점
    insert = copy.deepcopy(fragment)
    insert["mode"] = "insert"
    del insert["first_window_node"]
    insert["nodes"] = insert["nodes"][1:5]
    insert["nodes"][-1]["next"] = {}
    insert["chain"] = ["r2", "r3", "r4", "r5"]
    insert["open_end"] = {"node": "r5", "exit": "ok"}
    insert["warnings"] = []
    assert check_shape(insert, "recorder-fragment") == []
    assert fragment_problems(insert) == []

    shape_bad = [
        {**insert, "first_window_node": "r2"},
        {k: v for k, v in insert.items() if k != "open_end"},
        {**fragment, "open_end": {"node": "r6", "exit": "ok"}},
        {k: v for k, v in fragment.items() if k != "first_window_node"},
        {**fragment, "chain": ["n_abcdefgh"]},
    ]
    for value in shape_bad:
        assert check_shape(value, "recorder-fragment") != []

    def broken(change: Any) -> list[str]:
        value = copy.deepcopy(insert)
        change(value)
        assert check_shape(value, "recorder-fragment") == []
        return fragment_problems(value)

    assert broken(lambda f: f["nodes"][2]["in"].update(start={"$link": "r7.match"}))
    # 뒤 노드의 출력은 쓸 수 없다
    assert broken(lambda f: f["nodes"][0]["in"].update(x={"$link": "r4.out"}))
    assert broken(lambda f: f["nodes"][0].update(next={"ok": "r9"}))
    assert broken(lambda f: f.update(chain=["r2", "r3", "r4"]))
    assert broken(lambda f: f.update(chain=["r2", "r4", "r3", "r5"]))
    assert broken(lambda f: f.update(open_end={"node": "r4", "exit": "ok"}))
    assert broken(lambda f: f["nodes"][3].update(next={"ok": "r2"}))
    assert broken(lambda f: f["nodes"][1].update(local_id="r2"))


# ------------------------------------------------------------------ 스텝·글자 규칙


def step(**f: Any) -> dict[str, Any]:
    return {
        "step": "rs4",
        "kind": "text",
        "t_ms": 1100,
        "node": {"type": "core.input.type_text", "title": "글자 입력"},
        "needs_review": [],
        "badges": [],
        **f,
    }


def test_steps_text_only_when_ordinary() -> None:
    allowed = [
        step(text_state="ordinary", text_len=5, text="hello"),
        step(text_state="ordinary", text_len=5, text="hello", reveal_confirmed=True),
        step(text_state="pending", text_len=6),
        step(text_state="secret", text_len=6, secret_key=None),
        step(text_state="secret", text_len=6, secret_key="game.password"),
        step(
            text_state="needs_review",
            text_len=6,
            needs_review=["no_evidence"],
            badges=[{"code": "secret_unknown", "severity": "review"}],
        ),
        step(
            kind="click",
            node={"type": "core.image.click", "title": '이미지 클릭 "강화"'},
            input={"point": [858, 562], "button": "left", "count": 1},
            target={"source": "draft", "spec": {"rect": [800, 540, 116, 44]}, "frame": "pre_click"},
            frames=["pre_click", "pre_hover"],
        ),
    ]
    for value in allowed:
        assert rpc("RecorderStep", value) == [], value
        RecorderStep.model_validate(value)
    # 판정 중·비밀값·확인 필요 구간의 글자는 스키마상 둘 자리가 없다 (M4 계획 2.8)
    for state in ("pending", "secret", "needs_review"):
        assert rpc("RecorderStep", step(text_state=state, text_len=6, text="hunter")) != [], state
        assert rpc("RecorderStep", step(text_state=state, reveal_confirmed=True)) != [], state
    forbidden = [
        step(text="hunter2"),  # 상태 없이 글자
        step(text_state="ordinary", secret_key="game.password"),
        step(text_state="pending", secret_key="game.password"),
        step(kind="click", node={"type": "core.image.click", "title": "x"}, text_state="ordinary"),
        step(kind="click", node={"type": "core.image.click", "title": "x"}, text_len=3),
        {k: v for k, v in step(text_state="pending").items() if k != "text_state"},
        step(text_state="ordinary", reveal_confirmed=False),
    ]
    for value in forbidden:
        assert rpc("RecorderStep", value) != [], value
    result = {"rev": 3, "steps": allowed}
    assert rpc("RecorderStepsResult", result) == []
    RecorderStepsResult.model_validate(result)
    assert rpc("RecorderStepsResult", {"rev": 3, "steps": [step(text_state="secret", text="x")]})

    # 일반 글자로 되돌리기는 보이기 확인이 있어야 한다
    patch = {"step": "rs4", "patch": {"text_state": "ordinary", "confirm_reveal": True}}
    assert rpc("RecorderStepUpdateParams", patch) == []
    assert rpc("RecorderStepUpdateParams", {"step": "rs4", "patch": {"text_state": "ordinary"}})
    for other in (
        {"text_state": "secret"},
        {"secret_key": "game.password"},
        {"delete": True},
        {"target": {"rect": [1, 2, 3, 4], "search": None, "sensitive": True}},
        {"frame": "pre_hover"},
        {},
    ):
        assert rpc("RecorderStepPatch", other) == [], other
    assert rpc("RecorderStepPatch", {"text_state": "needs_review"}) != []
    assert rpc("RecorderStepPatch", {"text_state": "pending"}) != []


def test_needs_review_reason_enum() -> None:
    plan = {
        "geometry_unresolved",
        "no_frame",
        "window_undetermined",
        "ime_unknown",
        "cursor_moved_in_field",
        "field_box_unknown",
        "no_evidence",
        "cut_by_stop",
        "secret_overlap",
        "wait_target_unknown",
    }
    assert set(RPC_DEFS["RecorderNeedsReviewReason"]["enum"]) == plan
    assert rpc("RecorderStep", step(text_state="needs_review", needs_review=["guess"])) != []
    assert set(RPC_DEFS["RecorderTextState"]["enum"]) == {
        "pending",
        "ordinary",
        "secret",
        "needs_review",
    }


# ------------------------------------------------------------------ daemon 메서드 표


M4_METHODS: dict[str, tuple[str, str]] = {
    "recorder.start": ("RecorderStartParams", "RecorderStateResult"),
    "recorder.pause": ("EmptyParams", "RecorderStateResult"),
    "recorder.resume": ("EmptyParams", "RecorderStateResult"),
    "recorder.stop": ("EmptyParams", "RecorderStateResult"),
    "recorder.discard": ("EmptyParams", "RecorderStateResult"),
    "recorder.state": ("EmptyParams", "RecorderStateResult"),
    "recorder.steps": ("RecorderStepsParams", "RecorderStepsResult"),
    "recorder.step.update": ("RecorderStepUpdateParams", "RecorderStepResult"),
    "recorder.frame": ("RecorderFrameParams", "RecorderFrameResult"),
    "recorder.insert_check": ("RecorderInsertCheckParams", "RecorderStepResult"),
    "recorder.commit_prepare": ("RecorderCommitPrepareParams", "RecorderCommitPrepareResult"),
    "recorder.commit_finish": ("RecorderCommitFinishParams", "EmptyResult"),
    "recorder.commit_abort": ("RecorderCommitTokenParams", "EmptyResult"),
    "secrets.list": ("EmptyParams", "SecretsListResult"),
    "secrets.create": ("SecretsCreateParams", "SecretKeyInfo"),
    "target.read_text": ("TargetReadTextParams", "TargetReadTextResult"),
}


def test_daemon_rpc_method_table_m4() -> None:
    table = RPC_DEFS["Methods"]["properties"]
    for name, (params, result) in M4_METHODS.items():
        row = table[name]["properties"]
        assert row["params"]["$ref"] == f"#/$defs/{params}", name
        assert row["result"]["$ref"] == f"#/$defs/{result}", name
        assert row["tool"]["const"] == "ui_only", name
        assert row["renderer"]["const"] is True, name
    # 알림은 글자 없는 상태 요약
    assert RPC_DEFS["Notifications"]["properties"]["recorder.changed"]["properties"]["params"] == {
        "$ref": "#/$defs/RecorderChangedParams"
    }
    assert rpc("RecorderChangedParams", {"state": "recording"}) == []
    assert rpc("RecorderChangedParams", {"state": "recording", "steps": []}) != []

    # 시작: 창 또는 게임 띄우기 중 하나
    hotkeys = [
        {"keys": "ctrl+shift+r", "role": "stop"},
        {"keys": "ctrl+shift+p", "role": "mark_secret"},
    ]
    assert rpc("RecorderStartParams", {"window": 1001, "hotkeys": hotkeys}) == []
    assert (
        rpc(
            "RecorderStartParams",
            {"launch": {"profile": None}, "hotkeys": hotkeys, "options": {"wait_as_appear": False}},
        )
        == []
    )
    assert rpc("RecorderStartParams", {"window": 1, "launch": {}, "hotkeys": hotkeys}) != []
    assert rpc("RecorderStartParams", {"hotkeys": hotkeys}) != []
    assert rpc(
        "RecorderStartParams", {"window": 1, "hotkeys": [{"keys": "Ctrl+R", "role": "stop"}]}
    )

    # 상태: 소유 연결은 전부, 다른 연결은 상태·경과만
    owned = {
        "state": "recording",
        "owned": True,
        "session": "k3x9q2ab",
        "window": {
            "handle": 1001,
            "title": "SampleRPG",
            "process": "python.exe",
            "client_size": [1280, 720],
            "dpi": 96,
        },
        "started_at": "2026-11-04T01:02:03.004Z",
        "elapsed_ms": 134000,
        "counts": {
            "steps": 6,
            "targets": 4,
            "ignored_injected": 0,
            "ignored_outside": 2,
            "ignored_popup": 0,
        },
        "warnings": [{"code": "injected_ignored", "count": 3}],
        "foreground": True,
    }
    assert rpc("RecorderStateResult", owned) == []
    other = {
        "state": "recording",
        "owned": False,
        "elapsed_ms": 134000,
        "started_at": "2026-11-04T01:02:03.004Z",
    }
    assert rpc("RecorderStateResult", other) == []
    for leak in ("window", "counts", "session", "warnings"):
        assert rpc("RecorderStateResult", {**other, leak: owned[leak]}) != [], leak
    stopped = {"state": "stopped", "owned": True, "stop_reason": "hook_lost"}
    assert rpc("RecorderStateResult", stopped) == []
    assert rpc("RecorderStateResult", {"state": "idle", "owned": True}) == []

    # 프레임: live는 스텝 없이, 나머지는 스텝 필수
    assert rpc("RecorderFrameParams", {"which": "live"}) == []
    assert rpc("RecorderFrameParams", {"which": "pre_click", "step": "rs3"}) == []
    assert rpc("RecorderFrameParams", {"which": "pre_click"}) != []
    assert rpc("RecorderFrameParams", {"which": "live", "step": "rs3"}) != []

    # 오류: 실행 거부·커밋 거부의 추가 필드
    assert rpc("RequestFailedData", {"code": "recording_active", "state": "starting"}) == []
    assert rpc("RequestFailedData", {"code": "secret_unresolved", "steps": ["rs4", "rs9"]}) == []
    assert rpc("RequestFailedData", {"code": "not_owner", "state": "recording"}) == []
    assert rpc("RequestFailedData", {"code": "secret_unresolved", "steps": ["4"]}) != []

    # 비밀값: 값은 RPC로 오가지 않는다
    assert (
        rpc(
            "SecretsListResult",
            {
                "keys": [{"key": "game.password", "source": "credential"}],
                "env_note": "환경 변수 비밀값은 목록에 없어요",
            },
        )
        == []
    )
    assert rpc("SecretsCreateParams", {"key": "game.password", "from_step": "rs4"}) == []
    assert (
        rpc("SecretsCreateParams", {"key": "game.password", "value": "hunter2", "from_step": "rs4"})
        != []
    )
    assert rpc("SecretKeyInfo", {"key": "game.password", "source": "credential", "value": "x"})

    # target 편집기: 미리보기 peaks(선택), 영역 글자
    peak = {"rect": [10, 10, 40, 20], "score": 0.93, "scale": 1.0}
    assert rpc("PreviewPeak", peak) == []
    assert RPC_DEFS["PreviewResult"]["properties"]["peaks"]["maxItems"] == 8
    assert "peaks" not in RPC_DEFS["PreviewResult"]["required"]
    text = {"text": "로그인", "lines": [{"text": "로그인", "rect": [1, 2, 3, 4], "score": 0.98}]}
    assert rpc("TargetReadTextResult", text) == []

    # run.start 거부 코드
    assert "recording_active" in RPC_DEFS["RequestFailedCode"]["enum"]


def test_workspace_id_for_credential_prefix() -> None:
    base = {"format": "kookabug.workspace/0"}
    with_id = {**base, "id": "3f2b8c1e-9a4d-4e7f-8b1a-2c3d4e5f6a7b"}
    assert check_shape(base, "workspace") == []
    assert check_shape(with_id, "workspace") == []
    Workspace.model_validate(with_id)
    for bad in ("3F2B8C1E-9A4D-4E7F-8B1A-2C3D4E5F6A7B", "not-a-uuid", ""):
        assert check_shape({**base, "id": bad}, "workspace") != [], bad


@pytest.mark.parametrize("kind", ["recorder-hook", "recorder-script", "recorder-fragment"])
def test_new_kinds_registered(kind: Any) -> None:
    assert metaschema(kind)["$id"] == f"urn:kookabug:{kind}:0"


# ------------------------------------------------------------------ 검수 1차 회귀 (review_T1_1)


def test_commit_options_after_recording() -> None:
    # R1: 변환 옵션은 커밋 때 적용 — 녹화 뒤 바꾼 값을 commit_prepare가 받는다
    prepare = {"mode": "new_test", "graph_path": "tests/login.graph.json"}
    assert rpc("RecorderCommitPrepareParams", {**prepare, "options": {"crop_targets": False}}) == []
    assert rpc("RecorderCommitPrepareParams", prepare) == []
    assert rpc("RecorderCommitPrepareParams", {**prepare, "options": {"guess": True}}) != []
    # 세션 옵션은 소유 연결의 상태로 읽는다 (다른 연결에는 없음)
    options = {"wait_as_appear": True, "crop_targets": False}
    assert rpc("RecorderStateResult", {"state": "stopped", "owned": True, "options": options}) == []
    assert rpc("RecorderStateResult", {"state": "stopped", "owned": False, "options": options})
    referrers = {
        name for name, schema in RPC_DEFS.items() if "#/$defs/RecorderOptions" in repr(schema)
    }
    assert referrers == {
        "RecorderStartParams",
        "RecorderCommitPrepareParams",
        "RecorderStateResult",
    }


SPEC = {
    "rect": [20, 30, 80, 40],
    "search": [0, 0, 400, 300],
    "anchor": "top_left",
    "offset": [8, 9],
    "threshold": 0.92,
    "rgb": False,
    "methods": ["template"],
    "color_tolerance": 20,
    "sensitive": True,
}


def test_target_draft_spec_roundtrip() -> None:
    # R2: 읽기(초안 spec)와 쓰기(patch.target)가 같은 모양 — 기본값이 아닌 값으로 왕복
    draft = {"source": "draft", "frame": "pre_click", "spec": SPEC}
    clicked = step(kind="click", node={"type": "core.image.click", "title": "x"}, target=draft)
    assert rpc("RecorderStepsResult", {"rev": 1, "steps": [clicked]}) == []
    read_back = RecorderStepsResult.model_validate({"rev": 1, "steps": [clicked]})
    spec = read_back.model_dump(mode="json", exclude_unset=True)["steps"][0]["target"]["spec"]
    assert spec == SPEC
    assert rpc("RecorderStepUpdateParams", {"step": "rs4", "patch": {"target": spec}}) == []
    for name, value in SPEC.items():
        assert rpc("RecorderStepPatch", {"target": {name: value}}) == [], name
    patch_target = RPC_DEFS["RecorderStepPatch"]["properties"]["target"]
    draft_spec = RPC_DEFS["RecorderTargetDraft"]["properties"]["spec"]
    assert patch_target == draft_spec == {"$ref": "#/$defs/RecorderTargetSpec"}
    assert set(RPC_DEFS["RecorderTargetSpec"]["properties"]) == set(SPEC)
    # 초안은 사양 없이 올 수 없다, 사양 밖 필드는 받지 않는다
    assert rpc("RecorderTargetDraft", {"source": "draft"}) != []
    assert rpc("RecorderTargetDraft", {"source": "none"}) == []
    assert rpc("RecorderTargetSpec", {"methods": []}) != []
    assert rpc("RecorderTargetSpec", {"image": "a.png"}) != []


def test_target_frame_choice_pinned_by_frame_id() -> None:
    # R3: 편집기에서 고른 프레임(지금 화면 포함)은 recorder.frame이 고정한 frame_id로 초안에 잇는다
    assert rpc("RecorderStepPatch", {"frame_id": "f123"}) == []
    assert rpc("RecorderStepPatch", {"frame_id": "f123", "target": {"rect": [1, 2, 3, 4]}}) == []
    assert rpc("RecorderStepPatch", {"frame": "pre_hover"}) == []
    assert rpc("RecorderStepPatch", {"frame": "pre_click", "frame_id": "f123"}) != []
    # 'live'는 조회 때와 편집 때 프레임이 달라질 수 있어 종류로는 받지 않는다
    assert rpc("RecorderStepPatch", {"frame": "live"}) != []
    assert rpc("RecorderStepPatch", {"frame_id": ""}) != []
    live = {"source": "draft", "frame": "live", "frame_id": "f123", "spec": {"rect": [1, 2, 3, 4]}}
    assert rpc("RecorderTargetDraft", live) == []
    assert rpc("RecorderTargetDraft", {k: v for k, v in live.items() if k != "frame_id"}) != []


def _numbered(raw: dict[str, Any]) -> dict[str, Any]:
    event = {**raw, "event_id": 1, "t_ns": 0}
    if raw.get("kind") != "mouse_move":
        event["crit_seq"] = 1
    return event


RAW_FLAGS = {"injected": False, "injected_lower_il": False, "extra_info": 0}
RAW_CASES: dict[str, dict[str, Any]] = {
    "move": {"kind": "mouse_move", "x": 1, "y": 2},
    "move_no_y": {"kind": "mouse_move", "x": 1},
    "move_with_button": {"kind": "mouse_move", "x": 1, "y": 2, "button": "left"},
    "move_with_vk": {"kind": "mouse_move", "x": 1, "y": 2, "vk": 65},
    "move_with_horizontal": {"kind": "mouse_move", "x": 1, "y": 2, "horizontal": True},
    "down": {"kind": "mouse_down", "x": 1, "y": 2, "button": "left"},
    "down_no_button": {"kind": "mouse_down", "x": 1, "y": 2},
    "up_no_point": {"kind": "mouse_up", "button": "right"},
    "down_with_delta": {"kind": "mouse_down", "x": 1, "y": 2, "button": "left", "delta": 120},
    "down_with_scan": {"kind": "mouse_down", "x": 1, "y": 2, "button": "left", "scan": 1},
    "wheel": {"kind": "wheel", "x": 1, "y": 2, "delta": -120},
    "wheel_horizontal": {"kind": "wheel", "x": 1, "y": 2, "delta": 120, "horizontal": True},
    "wheel_no_delta": {"kind": "wheel", "x": 1, "y": 2},
    "wheel_with_button": {"kind": "wheel", "x": 1, "y": 2, "delta": 1, "button": "left"},
    "key": {"kind": "key_down", "vk": 65, "scan": 30, "extended": False},
    "key_up": {"kind": "key_up", "vk": 65, "scan": 30, "extended": True},
    "raw_key_without_vk_scan_extended": {"kind": "key_down"},
    "key_without_scan": {"kind": "key_down", "vk": 65, "extended": False},
    "key_with_point": {"kind": "key_down", "vk": 65, "scan": 30, "extended": False, "x": 1},
    "key_with_y": {"kind": "key_up", "vk": 65, "scan": 30, "extended": False, "y": 1},
    "key_with_button": {"kind": "key_down", "vk": 65, "scan": 30, "extended": False,
                        "button": "left"},
    "key_with_horizontal": {"kind": "key_down", "vk": 65, "scan": 30, "extended": False,
                            "horizontal": False},
}  # fmt: skip
RAW_VALID = {"move", "down", "wheel", "wheel_horizontal", "key", "key_up"}


@pytest.mark.parametrize("name", sorted(RAW_CASES))
def test_raw_input_acceptance_matches_hook_event(name: str) -> None:
    # R4: 각본 원시 입력과 번호를 붙인 훅 이벤트가 같은 입력을 받고 같은 입력을 거부한다
    raw = {**RAW_CASES[name], **RAW_FLAGS}
    raw_ok = errors("recorder-script", "RawInput", raw) == []
    hook_ok = errors("recorder-hook", "HookEvent", _numbered(raw)) == []
    assert raw_ok == hook_ok == (name in RAW_VALID)
    if raw_ok:
        assert check_shape({"kind": "input", "t_ns": 0, "input": raw}, "recorder-script") == []


def _fragment_with(value: Any) -> dict[str, Any]:
    return {
        "mode": "insert",
        "nodes": [
            {"local_id": "r1", "type": "core.image.wait", "version": 1, "title": "wait",
             "in": {}, "next": {"found": "r2"}},
            {"local_id": "r2", "type": "core.input.drag", "version": 1, "title": "drag",
             "in": {"start": value}},
        ],
        "chain": ["r1", "r2"],
        "open_end": {"node": "r2", "exit": "ok"},
        "warnings": [],
    }  # fmt: skip


BAD_FRAGMENT_VALUES: dict[str, Any] = {
    "link_number": {"$link": 7},
    "link_without_output": {"$link": "r1"},
    "mixed_literal_and_link": {"$literal": 1, "$link": "r999.match"},
    "secret_number": {"$secret": 42},
    "graph_node_id_link": {"$link": "n_abcdefgh.match"},
    "nested_in_array": [1, {"$link": 7}],
    "nested_in_object": {"a": {"$secret": 42}},
    "setting_bad": {"$setting": "a b"},
    "target_bad": {"$target": "a.png"},
}


@pytest.mark.parametrize("name", sorted(BAD_FRAGMENT_VALUES))
def test_fragment_values_follow_graph_value_rules(name: str) -> None:
    # R5: in 값은 그래프 Value 규칙 + 로컬 링크. 모양 검사와 의미 검사 둘 다 거부한다
    fragment = _fragment_with(BAD_FRAGMENT_VALUES[name])
    assert check_shape(fragment, "recorder-fragment") != [], name
    assert fragment_problems(fragment) != [], name


def test_fragment_value_rules_good_values_and_unknown_dollar_key() -> None:
    good = [
        {"$link": "r1.match"},
        [{"$link": "r1.match"}, 3, None],
        {"a": {"$secret": "game.password"}, "b": [{"$setting": "game.path"}]},
        {"$literal": {"$link": 7, "$anything": 1}},
        {"$target": "targets/rec/a/01_x.target.json"},
        {},
    ]
    for value in good:
        fragment = _fragment_with(value)
        assert check_shape(fragment, "recorder-fragment") == [], value
        assert fragment_problems(fragment) == [], value
    # 메타스키마에 적을 수 없는 "모르는 $ 키"는 의미 검사(그래프 Value)가 거부한다
    unknown = _fragment_with({"$foo": 1})
    assert fragment_problems(unknown) != []


def test_continuity_first_gap_kept_with_later_disorder() -> None:
    # R6: 첫 빈 번호를 찾은 뒤 차례 오류가 와도 자르는 곳은 가장 이른 불확실 지점
    batch = events_batch(
        1, [key(1, 0.1, 1), key(3, 0.3, 3), key(2, 0.4, 4)], crit=(1, 4), overflow=1
    )
    assert errors("recorder-hook", "HookEventsParams", batch) == []
    v = ContinuityChecker().feed_events(batch)
    assert v is not None and (v.reason, v.cut_crit_seq) == ("event_order", 2)
    kept = [e["crit_seq"] for e in batch["events"] if e["crit_seq"] < v.cut_crit_seq]
    assert kept == [1]
    # 빈틈 뒤 번호 역전 (crit_seq 3 다음 2)
    reversed_seq = events_batch(1, [key(1, 0.1, 1), key(2, 0.2, 3), key(3, 0.3, 2)], crit=(1, 2))
    v = ContinuityChecker().feed_events(reversed_seq)
    assert v is not None and (v.reason, v.cut_crit_seq) == ("event_order", 2)
    # 빈틈 없는 중복: 다시 나온 번호부터 자른다
    duplicate = events_batch(1, [key(1, 0.1, 1), key(2, 0.2, 2), key(3, 0.3, 2)], crit=(1, 2))
    v = ContinuityChecker().feed_events(duplicate)
    assert v is not None and (v.reason, v.cut_crit_seq) == ("event_order", 2)
    # 묶음 사이: 앞 묶음까지는 이어졌고 다음 묶음 안에서 빈틈 + 시각 역전
    checker = ContinuityChecker()
    assert checker.feed_events(events_batch(1, [key(1, 0.1, 1)], crit=(1, 1))) is None
    later = events_batch(2, [key(2, 0.5, 3), key(4, 0.4, 4)], crit=(3, 4))
    v = checker.feed_events(later)
    assert v is not None and (v.reason, v.cut_crit_seq) == ("event_order", 2)

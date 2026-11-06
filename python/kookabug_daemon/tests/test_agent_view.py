"""에이전트로 나가는 실행 기록 (M5 계획 3.8·3.5, B2).

- 분류 있는 기록: `secret_paths` 자리는 `***`, 비밀값 스텝(안쪽 포함)·`agent_withhold` 증거는 주지
  않음. 사람(UI) 연결은 원문 그대로(D3)
- 분류 없는 옛 기록: 안전 필드만, 파일 없음, 찾기에서 건너뜀
- 기존 원문 경로(`run.index/children/step/file/compare/subscribe`, `runs/`의 `target.load_image`)는
  agent 거부. agent 결과와 UI 결과는 캐시를 나눈다

runner가 남기는 분류 자체는 `kookabug_core/tests/record/test_agent_mask.py`. 여기는 실제 runner
실행 하나(비밀값 필드·비밀값 교체)와, 파일 증거를 다루는 합성 실행 폴더로 본다(가짜 플랫폼 runner는
화면을 캡처하지 않는다).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, RunRig
from helpers.graphs import GraphBuilder, make_workspace, secret, subgraph_interface, write_json
from helpers.run import run_graph, tk

from kb_testing.proc import wait_until
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": True}
PW = "hunter2"
ENV_KEY = "KOOKABUG_SECRET_ACC_PW"
CONDITIONS = {"deadline_ms": 1000, "platform": "fake", "profile": None, "settings": {}}


# ---------------------------------------------------------------- 도움


def secret_graph() -> GraphBuilder:
    """비밀값이 입력(직접)·로그·실패 메시지·판정 사유로 들어가는 그래프 (끝은 fail)."""
    return (
        tk()
        .entry("n_take")
        .node(
            "n_take",
            "testkit.sleep",
            inputs={"ms": 1, "value": secret("acc.pw")},
            next={"done": "n_log"},
        )
        .node(
            "n_log", "core.log.message", inputs={"text": secret("acc.pw")}, next={"done": "n_cmp"}
        )
        .node("n_cmp", "core.assert.compare", inputs={"a": secret("acc.pw"), "op": "==", "b": "x"})
    )


def run_to_end(rig: RunRig, client: DaemonClient) -> str:
    run_id = client.call("run.start", {"path": TEST})["run_id"]
    wait_until(
        lambda: client.call("run.status", {"run_id": run_id})["state"] == "ended",
        timeout=60,
        interval=0.1,
    )
    return run_id


def plant(root: Path, run_id: str, events: Iterable[Mapping[str, Any]], **run_json: Any) -> Path:
    """합성 끝난 실행 폴더 (`seq`·`t`·`run`을 붙인다)."""
    folder = root / "runs" / f"2026-11-02T01-00-00_t_{run_id}"
    folder.mkdir(parents=True)
    lines = []
    for i, event in enumerate(events, start=1):
        line = {"t": f"2026-11-02T01:00:00.{i:03d}Z", **event, "seq": i, "run": run_id}
        lines.append(json.dumps(line, ensure_ascii=False))
    (folder / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    data = {
        "format": "kookabug.run/0",
        "graph": TEST,
        "run_id": run_id,
        "started_at": "2026-11-02T01:00:00.001Z",
        "ended_at": "2026-11-02T01:00:00.500Z",
        "status": "finished",
        "conditions": CONDITIONS,
        **run_json,
    }
    (folder / "run.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return folder


def start(step: str, node: str, parent: str | None = None, path: list[str] | None = None) -> dict:
    return {
        "event": "step.start",
        "attempt": 1,
        "node": node,
        "parent": parent,
        "path": path or [node],
        "step": step,
    }


def end(step: str, status: str = "success", exit: str | None = "done", **extra: Any) -> dict:
    return {
        "event": "step.end",
        "attempt": 1,
        "duration_ms": 5,
        "exit": exit,
        "outputs": {},
        "status": status,
        "step": step,
        **extra,
    }


def run_start() -> dict[str, Any]:
    return {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}}


def run_end(verdict: str, failure: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "event": "run.end",
        "verdict": verdict,
        "code": "unhandled_fail" if verdict == "fail" else "test_pass",
        "reason": extra.pop("reason", ""),
        "failure_step": failure,
        "failure_path": None if failure is None else [failure],
        "finalized_by": "runner",
        "duration_ms": 50,
        **extra,
    }


def png(width: int = 2000, height: int = 1000, shade: int = 80) -> bytes:
    import cv2
    import numpy as np

    pixels = np.full((height, width, 3), shade, np.uint8)
    pixels[100:300, 200:600] = 255
    ok, data = cv2.imencode(".png", pixels)
    assert ok
    return data.tobytes()


def jpeg(shade: int = 80) -> bytes:
    import cv2
    import numpy as np

    pixels = np.full((360, 640, 3), shade, np.uint8)
    ok, data = cv2.imencode(".jpg", pixels)
    assert ok
    return data.tobytes()


def denied(client: DaemonClient, method: str, params: Mapping[str, Any]) -> str:
    """거부 종류 (request_failed면 data.code, 형식 오류면 invalid_params)."""
    with pytest.raises(DaemonError) as caught:
        client.call(method, dict(params))
    if caught.value.kind is None and caught.value.code == -32602:
        return "invalid_params"
    return str(caught.value.kind)


def secret_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunRig:
    # daemon 사전 검증은 이 프로세스 환경에서, runner는 rig 환경에서 비밀값을 찾는다
    monkeypatch.setenv(ENV_KEY, PW)
    return RunRig.make(tmp_path, secret_graph(), KOOKABUG_SECRET_ACC_PW=PW)


def evidence_folder(root: Path) -> Path:
    """분류 있는 합성 실행: s1(호출 스텝, secret) ⊃ s2(안쪽, 이미지) / s3(보통, 이미지·썸네일) /
    s4(가림이 켜져 있었다면 빠졌을 OCR 글자) / s5(실패, 텍스트 artifact·이미지)."""
    events = [
        run_start(),
        start("s1", "n_call"),
        start("s2", "n_in", "s1", ["n_call", "n_in"]),
        end("s2", artifacts=["steps/s2_shot.png"]),
        end("s1", secret=True, secret_paths=["/outputs/pw"], outputs={"pw": PW}),
        start("s3", "n_shot"),
        end("s3", artifacts=["steps/s3_shot.png"]),
        start("s4", "n_read"),
        end("s4", artifacts=["steps/s4_ocr.txt"], agent_withhold=["steps/s4_ocr.txt"]),
        start("s5", "n_wait"),
        end(
            "s5",
            "fail",
            "timeout",
            artifacts=["steps/s5_note.json", "steps/s5_fail.png"],
            evidence={"last": "steps/s5_fail.png"},
            message="창이 안 떴다",
        ),
        run_end("fail", "s5", reason="처리되지 않은 fail: 창이 안 떴다"),
    ]
    folder = plant(root, "evid0001", events, agent_mask=1, verdict="fail", code="unhandled_fail")
    steps = folder / "steps"
    steps.mkdir()
    (steps / "s2_shot.png").write_bytes(png(shade=10))
    (steps / "s3_shot.png").write_bytes(png())
    (steps / "s4_ocr.txt").write_text(PW, encoding="utf-8")
    (steps / "s5_note.json").write_text('{"note": "보통 글자"}', encoding="utf-8")
    (steps / "s5_fail.png").write_bytes(png(800, 600))
    (folder / "thumbs").mkdir()
    (folder / "thumbs" / "s2.jpg").write_bytes(jpeg())
    (folder / "thumbs" / "s3.jpg").write_bytes(jpeg())
    video = folder / "video"
    video.mkdir()
    (video / "seg_0001.mp4").write_bytes(b"\0\0\0\x18ftypmp42")
    (video / "index.json").write_text(
        json.dumps({"format": "kookabug.video-index/0", "status": "recorded", "segments": []}),
        encoding="utf-8",
    )
    return folder


# ---------------------------------------------------------------- 실제 runner


def test_secret_fields_masked_for_agent_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = secret_rig(tmp_path, monkeypatch)
    with rig.daemon() as d, d.client() as ui, d.client(AGENT) as agent:
        run_id = run_to_end(rig, ui)
        # 사람: 원문 그대로 (record.redact_secrets 기본 false, D3)
        raw = ui.call("run.file", {"run_id": run_id, "name": "events_tail"})["text"]
        assert PW in raw
        listed = ui.call("run.list", {})["runs"][0]
        assert PW in listed["reason"]

        events = agent.call("run.events", {"run_id": run_id})
        assert events["classified"] is True and events["truncated"] is False
        assert PW not in json.dumps(events, ensure_ascii=False)
        logs = [e for e in events["events"] if e["event"] == "log"]
        assert any(e["message"] == "***" and e["secret_paths"] == ["/message"] for e in logs)
        cmp_end = [e for e in events["events"] if e["event"] == "step.end" and "message" in e]
        assert cmp_end and all(e["message"] == "***" for e in cmp_end)
        nodes = {e["step"]: e["node"] for e in events["events"] if e["event"] == "step.start"}
        ends = {e["step"]: e for e in events["events"] if e["event"] == "step.end"}
        for step, node in nodes.items():
            if node != "n_entry":
                assert ends[step].get("secret") is True, node

        failure = agent.call("run.failure", {"run_id": run_id})
        assert failure["verdict"] == "fail" and failure["failure"]["node"] == "n_cmp"
        assert failure["reason"] == "***" and failure["failure"]["message"] == "***"
        assert PW not in json.dumps(failure, ensure_ascii=False)
        agent_list = agent.call("run.list", {})
        assert agent_list["runs"][0]["reason"] == "***"
        assert PW not in json.dumps(agent.call("run.status", {"run_id": run_id}))
        assert agent.call("run.search", {"query": PW})["matches"] == []


def test_secret_changed_or_deleted_after_run_still_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = secret_rig(tmp_path, monkeypatch)
    with rig.daemon() as d, d.client() as ui:
        run_id = run_to_end(rig, ui)
    # 비밀값을 바꾸거나 지운 뒤 새 daemon이 읽어도 분류는 기록에 있다
    for value in ("changed-value", None):
        if value is None:
            rig.env.pop(ENV_KEY, None)
            monkeypatch.delenv(ENV_KEY)
        else:
            rig.env[ENV_KEY] = value
            monkeypatch.setenv(ENV_KEY, value)
        with rig.daemon() as d, d.client(AGENT) as agent:
            got = agent.call("run.events", {"run_id": run_id})
            text = json.dumps(got, ensure_ascii=False)
            assert PW not in text
            assert any(e.get("message") == "***" for e in got["events"] if e["event"] == "log")
            assert agent.call("run.failure", {"run_id": run_id})["reason"] == "***"


# ---------------------------------------------------------------- 파일 증거


def test_secret_step_images_withheld(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    folder = evidence_folder(rig.root)
    with rig.daemon() as d, d.client(AGENT) as agent, d.client() as ui:

        def artifact(path: str, **extra: Any) -> dict[str, Any]:
            return agent.call("run.artifact", {"run_id": "evid0001", "path": path, **extra})

        # 비밀값 스텝 안쪽 스텝·agent_withhold → secret_step
        for path in ("steps/s2_shot.png", "thumbs/s2.jpg", "steps/s4_ocr.txt"):
            assert denied(agent, "run.artifact", {"run_id": "evid0001", "path": path}) == (
                "secret_step"
            ), path
        # 영상 조각·기록 원문 파일·폴더 밖
        assert (
            denied(agent, "run.artifact", {"run_id": "evid0001", "path": "video/seg_0001.mp4"})
            == "video_not_served"
        )
        for path in ("events.jsonl", "run.json", "logs/runner.stderr.log", "steps/s9_x.png"):
            assert denied(agent, "run.artifact", {"run_id": "evid0001", "path": path}) == (
                "not_evidence"
            ), path
        for path in ("../x.png", "steps\\s3_shot.png", "C:/x.png"):
            assert denied(agent, "run.artifact", {"run_id": "evid0001", "path": path}) == (
                "invalid_params"
            )
        # 보통 스텝: 이미지는 긴 변 1568 이하 PNG로 agent 캐시에
        shown = artifact("steps/s3_shot.png")
        assert shown["kind"] == "image" and max(shown["width"], shown["height"]) <= 1568
        assert shown["bytes"] <= 1024 * 1024
        cached = rig.root / ".kookabug" / "cache" / "agent" / Path(shown["cache"])
        assert cached.is_file() and cached.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert artifact("thumbs/s3.jpg")["kind"] == "image"
        note = artifact("steps/s5_note.json")
        assert note["kind"] == "text" and "보통 글자" in note["text"]
        assert artifact("video/index.json")["kind"] == "text"
        frame = artifact("steps/s3_shot.png", as_frame=True)
        assert frame["kind"] == "frame" and frame["width"] == 2000
        # agent·UI 캐시 분리: 축소 이미지는 편집기 캐시에 없다
        editor = rig.root / ".kookabug" / "cache" / "editor"
        assert not editor.exists() or not any(editor.iterdir())

        failure = agent.call("run.failure", {"run_id": "evid0001"})
        assert failure["failure"]["step"] == "s5"
        assert "steps/s5_fail.png" in failure["evidence"]
        assert all("s2" not in p and "s4" not in p for p in failure["evidence"])
        # 사람은 그대로 본다 (기존 run.step)
        assert ui.call("run.step", {"run_id": "evid0001", "step": "s4"})["ocr_text"] == PW
    assert (folder / "steps" / "s2_shot.png").is_file()  # 기록은 고치지 않는다


def test_log_search_masks(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    plant(
        rig.root,
        "srch0001",
        [
            run_start(),
            start("s1", "n_login"),
            {
                "event": "log",
                "level": "info",
                "message": f"암호 {PW}",
                "node": "n_login",
                "step": "s1",
                "secret_paths": ["/message"],
            },
            {
                "event": "log",
                "level": "warn",
                "message": "로그인 화면 안 뜸",
                "node": "n_login",
                "step": "s1",
            },
            end("s1", "fail", "timeout", message=f"입력값 {PW}", secret_paths=["/message"]),
            run_end("fail", "s1", reason=f"처리되지 않은 fail: {PW}", secret_paths=["/reason"]),
        ],
        agent_mask=1,
        verdict="fail",
        reason=f"처리되지 않은 fail: {PW}",
        secret_paths=["/reason"],
    )
    # 분류 없는 옛 기록 (agent_mask 없음)
    old = plant(
        rig.root,
        "olds0001",
        [
            run_start(),
            {
                "event": "log",
                "level": "info",
                "message": "로그인 token-xyz",
                "node": None,
                "step": None,
            },
            run_end("pass", None),
        ],
        verdict="pass",
    )
    old.rename(old.with_name("2026-11-02T01-00-01_t_olds0001"))
    with rig.daemon() as d, d.client(AGENT) as agent:
        assert agent.call("run.search", {"query": PW})["matches"] == []
        found = agent.call("run.search", {"query": "로그인"})
        assert [(m["run"], m["kind"]) for m in found["matches"]] == [("srch0001", "log")]
        assert "olds0001" in found["skipped"]  # 분류 없는 기록은 찾지 않는다
        assert agent.call("run.search", {"query": "token-xyz"})["matches"] == []
        # 비밀값이 든 필드는 통째로 가려 그 안의 다른 글자로도 찾히지 않는다
        assert agent.call("run.search", {"query": "입력값", "runs": ["srch0001"]})["matches"] == []
        assert agent.call("run.search", {"query": "화면", "runs": ["srch0001"]})["matches"]


def test_unclassified_run_safe_fields_only(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    folder = plant(
        rig.root,
        "olds0002",
        [
            run_start(),
            start("s1", "n_login"),
            {
                "event": "log",
                "level": "info",
                "message": f"암호 {PW}",
                "node": "n_login",
                "step": "s1",
            },
            end(
                "s1",
                "error",
                None,
                outputs={"text": PW},
                error={"code": "boom", "message": f"실패 {PW}"},
                artifacts=["steps/s1_error.png"],
            ),
            run_end("error", "s1", reason=f"실패 {PW}"),
        ],
        verdict="error",
        code="boom",
        reason=f"실패 {PW}",
        failure_step="s1",
        failure_path=["n_login"],
        finalized_by="runner",
    )
    (folder / "steps").mkdir()
    (folder / "steps" / "s1_error.png").write_bytes(png(64, 64))
    with rig.daemon() as d, d.client(AGENT) as agent, d.client() as ui:
        got = agent.call("run.events", {"run_id": "olds0002"})
        assert got["classified"] is False
        text = json.dumps(got, ensure_ascii=False)
        assert PW not in text
        (step_end,) = [e for e in got["events"] if e["event"] == "step.end"]
        assert step_end["error"] == {"code": "boom"} and "outputs" not in step_end
        assert step_end["status"] == "error" and step_end["step"] == "s1"
        assert "artifacts" not in step_end
        (log,) = [e for e in got["events"] if e["event"] == "log"]
        assert "message" not in log and log["level"] == "info"
        (ended,) = [e for e in got["events"] if e["event"] == "run.end"]
        assert ended["verdict"] == "error" and "reason" not in ended
        assert (
            denied(agent, "run.artifact", {"run_id": "olds0002", "path": "steps/s1_error.png"})
            == "unclassified_run"
        )
        failure = agent.call("run.failure", {"run_id": "olds0002"})
        assert failure["classified"] is False and failure["evidence"] == []
        assert failure["failure"]["error"] == {"code": "boom"} and "reason" not in failure
        assert PW not in json.dumps(failure, ensure_ascii=False)
        assert "reason" not in agent.call("run.list", {})["runs"][0]
        assert PW in ui.call("run.list", {})["runs"][0]["reason"]  # 사람은 그대로


def test_diff_masks_both_runs(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    common = {"packages": {"kookabug-core": "0.3.0"}, "agent_mask": 1}
    # 기준(pass): n_w 스텝이 비밀값 스텝이고 썸네일이 있다 → 기준 쪽 파일도 주지 않는다
    base = plant(
        rig.root,
        "base0001",
        [
            run_start(),
            start("s1", "n_w"),
            end("s1", exit="found", secret=True),
            run_end("pass", None),
        ],
        started_at="2026-11-02T01:00:00.100Z",
        verdict="pass",
        **common,
    )
    run = plant(
        rig.root,
        "fail0001",
        [
            run_start(),
            start("s1", "n_w"),
            end(
                "s1",
                "fail",
                "timeout",
                artifacts=["steps/s1_fail.png"],
                evidence={"last": "steps/s1_fail.png"},
                secret=True,
            ),
            run_end("fail", "s1"),
        ],
        started_at="2026-11-02T01:00:00.300Z",
        verdict="fail",
        **common,
    )
    os.rename(run, run.with_name("2026-11-02T01-00-03_t_fail0001"))
    run = run.with_name("2026-11-02T01-00-03_t_fail0001")
    (base / "thumbs").mkdir()
    (base / "thumbs" / "s1.jpg").write_bytes(jpeg())
    (run / "steps").mkdir()
    (run / "steps" / "s1_fail.png").write_bytes(png(640, 360, 200))
    cache = rig.root / ".kookabug" / "cache" / "runs" / "fail0001.compare.json"
    with rig.daemon() as d, d.client(AGENT) as agent, d.client() as ui:
        diff = agent.call("run.diff", {"run_id": "fail0001"})
        assert diff["baseline"] == "base0001"
        screen = diff["screen"]
        assert screen["file"] is None and screen["baseline_file"] is None
        assert screen["reason"] == "secret_step"
        assert "diff_ratio" not in screen and "regions" not in screen
        assert not cache.exists()  # agent 결과는 UI 비교 캐시에 쓰지 않는다
        # 사람: 파일·차이 그대로
        shown = ui.call("run.compare", {"run_id": "fail0001"})["screen"]
        assert shown["file"] == "steps/s1_fail.png" and shown["baseline_file"] == "thumbs/s1.jpg"
        assert cache.is_file()
        # UI 캐시가 있어도 agent는 그 결과를 쓰지 않는다
        again = agent.call("run.diff", {"run_id": "fail0001"})["screen"]
        assert again["file"] is None and again["reason"] == "secret_step"


# ---------------------------------------------------------------- 원문 경로 거부


def test_agent_raw_paths_denied(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    folder = evidence_folder(rig.root)
    # target.save까지 판정을 통과시킨다 (원문 경로 거부는 판정과 무관하게 먼저 걸린다)
    write_json(
        rig.root,
        ".kookabug/local.json",
        {"format": "kookabug.local/0", "permissions": {"preset": "full"}},
    )
    with rig.daemon() as d, d.client(AGENT) as agent, d.client() as ui:
        rid = {"run_id": "evid0001"}
        for method, params in (
            ("run.index", rid),
            ("run.children", {**rid, "parent": "s1", "offset": 0, "limit": 10}),
            ("run.step", {**rid, "step": "s3"}),
            ("run.file", {**rid, "name": "events_tail"}),
            ("run.compare", rid),
            ("run.subscribe", {**rid, "after_seq": 0}),
        ):
            assert denied(agent, method, params) == "agent_use_safe_api", method
            ui.call(method, params)  # 사람은 그대로
        rel = f"runs/{folder.name}/steps/s2_shot.png"
        assert denied(agent, "target.load_image", {"path": rel}) == "agent_use_safe_api"
        assert (
            denied(agent, "target.load_image", {"path": f"runs/{folder.name}/steps/s3_shot.png"})
            == "agent_use_safe_api"
        )
        assert ui.call("target.load_image", {"path": rel})["frame_id"]
        # kb_target_create{run, file}: 비밀값 스텝 이미지는 거부, 보통 스텝은 저장
        save = {"base_revision": None, "spec": {}}
        crop = {"run_id": "evid0001", "rect": [0, 0, 100, 100]}
        assert (
            denied(
                agent,
                "target.save",
                {
                    **save,
                    "path": "targets/a.target.json",
                    "crop": {**crop, "file": "steps/s2_shot.png"},
                },
            )
            == "secret_step"
        )
        assert not (rig.root / "targets" / "a.target.json").exists()
        saved = agent.call(
            "target.save",
            {
                **save,
                "path": "targets/b.target.json",
                "crop": {**crop, "file": "steps/s3_shot.png"},
            },
        )
        assert saved["revision"]
        # agent 캐시와 UI 캐시는 다른 폴더
        shown = agent.call("run.artifact", {**rid, "path": "steps/s3_shot.png"})
        assert shown["cache"].startswith("c")
        agent_dir = rig.root / ".kookabug" / "cache" / "agent"
        editor_dir = rig.root / ".kookabug" / "cache" / "editor"
        assert {p.name for p in editor_dir.iterdir()}.isdisjoint(
            {p.name for p in agent_dir.rglob("*.png")}
        )


# ---------------------------------------------------------------- B2 검수 반례 (2라운드)


def write_events(folder: Path, run_id: str, events: Iterable[Mapping[str, Any]]) -> None:
    lines = [
        {"t": "2026-11-02T01:00:00.001Z", **e, "seq": i, "run": run_id}
        for i, e in enumerate(events, 1)
    ]
    (folder / "events.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in lines), encoding="utf-8"
    )


def test_secret_parent_unfinished_artifact_denied(tmp_path: Path) -> None:
    """H1: 비밀 호출이 끝나기 전(부모 step.end 없음 — 실행 중·중단 기록)에는 안쪽 스텝 증거를
    주지 않는다. 실제 실행기 이벤트의 앞부분(안쪽 스텝 step.end 직후)으로 본다."""
    ws = make_workspace(tmp_path / "source")
    inner = (
        tk("subgraph", interface=subgraph_interface(inputs={"pw": "secret"}))
        .entry("n_shot")
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"save": True, "name": "shot.png"},
            next={"done": "n_exit"},
        )
        .exit("n_exit", "done")
    )
    inner.write(ws, "subgraphs/s.graph.json")
    graph = (
        tk()
        .entry("n_call")
        .call(
            "n_call", "subgraphs/s.graph.json", inputs={"pw": secret("pw")}, next={"done": "n_pass"}
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, graph, frames=["a", "b"], secrets={"pw": PW})
    assert ran.result.verdict == "pass"
    assert ran.end("n_call")["secret"] is True
    shot = ran.end("n_shot")
    assert "secret" not in shot  # 안쪽 스텝 자체는 비밀값을 받지 않았다
    prefix = ran.events[: ran.events.index(shot) + 1]
    call_step = ran.step_of("n_call")
    assert not any(e.get("event") == "step.end" and e.get("step") == call_step for e in prefix)

    rig = RunRig.make(tmp_path / "rpc")
    write_json(
        rig.root,
        ".kookabug/local.json",
        {"format": "kookabug.local/0", "permissions": {"preset": "full"}},
    )
    folder = plant(rig.root, "live0001", prefix, agent_mask=1, status="running")
    rel = shot["artifacts"][0]
    (folder / "steps").mkdir()
    (folder / rel).write_bytes(png(64, 64))
    with rig.daemon() as d, d.client(AGENT) as agent:
        rid = {"run_id": "live0001", "path": rel}
        # 진행 중(부모 끝나지 않음): 같은 refusal()을 쓰는 모든 길이 거부한다
        assert denied(agent, "run.artifact", rid) == "secret_step"
        assert denied(agent, "run.artifact", {**rid, "as_frame": True}) == "secret_step"
        assert denied(
            agent,
            "target.save",
            {"path": "targets/x.target.json", "base_revision": None, "spec": {},
             "crop": {"run_id": "live0001", "file": rel, "rect": [0, 0, 8, 8]}},
        ) == "secret_step"  # fmt: skip
        assert not (rig.root / "targets" / "x.target.json").exists()
        assert agent.call("run.failure", {"run_id": "live0001"})["evidence"] == []
        # 부모가 끝나 비밀 분류가 드러나도 거부 그대로
        write_events(folder, "live0001", ran.events)
        assert denied(agent, "run.artifact", rid) == "secret_step"


class _MarkOcr:
    name = "mark"

    def __init__(self) -> None:
        self.calls = 0

    def read(self, image: Any, *, region: Any = None, deadline: Any = None) -> list[Any]:
        from kookabug_platform.ocr.engine import OcrLine

        self.calls += 1
        return [OcrLine(PW, tuple(region), 0.99)]


def test_ui_loaded_secret_run_frame_not_reusable_by_agent(tmp_path: Path) -> None:
    """H2: UI가 연 비밀 실행 이미지의 frame_id를 agent가 OCR·미리보기·저장에 쓰지 못한다 (agent는
    자기 연결이 만든 정지 화면만)."""
    rig = RunRig.make(tmp_path)
    write_json(
        rig.root,
        ".kookabug/local.json",
        {"format": "kookabug.local/0", "permissions": {"preset": "full"}},
    )
    folder = evidence_folder(rig.root)
    rel = (folder / "steps/s2_shot.png").relative_to(rig.root).as_posix()
    engine = _MarkOcr()
    with rig.daemon() as d, d.client() as ui, d.client(AGENT) as agent:
        d.daemon.targets.ocr_factory = lambda: engine
        assert denied(agent, "target.load_image", {"path": rel}) == "agent_use_safe_api"
        frame = ui.call("target.load_image", {"path": rel})["frame_id"]
        assert denied(agent, "screen.read_text", {"frame_id": frame, "rect": [0, 0, 20, 20]}) == (
            "frame_not_owned"
        )
        assert denied(
            agent,
            "target.preview",
            {"frame_id": frame, "spec": {}, "seq": 1,
             "template": {"crop": {"frame_id": frame, "rect": [0, 0, 20, 20]}}},
        ) == "frame_not_owned"  # fmt: skip
        assert denied(
            agent,
            "target.save",
            {"path": "targets/y.target.json", "base_revision": None, "spec": {},
             "crop": {"frame_id": frame, "rect": [0, 0, 20, 20]}},
        ) == "frame_not_owned"  # fmt: skip
        assert engine.calls == 0 and not (rig.root / "targets" / "y.target.json").exists()
        # 사람은 그대로 읽는다
        assert ui.call("target.read_text", {"frame_id": frame, "rect": [0, 0, 20, 20]})["text"]
        # agent가 실행 증거에서 직접 연 보통 스텝 화면은 자기 것이라 쓴다
        own = agent.call(
            "run.artifact", {"run_id": "evid0001", "path": "steps/s3_shot.png", "as_frame": True}
        )["frame_id"]
        assert agent.call("screen.read_text", {"frame_id": own, "rect": [0, 0, 20, 20]})["text"]


def test_unclassified_compare_returns_only_safe_fields(tmp_path: Path) -> None:
    """H4: 한쪽이라도 분류 없는 기록이면 run.diff는 안전 필드만 (환경 값·파일·글자 없음)."""
    rig = RunRig.make(tmp_path)
    for run, value, start_at in (
        ("oldc0002", "other", "2026-11-02T01:00:00.100Z"),
        ("oldc0001", PW, "2026-11-02T01:00:00.300Z"),
    ):
        settings = {"legacy": {"layer": "local", "value": value}}
        plant(
            rig.root,
            run,
            [run_start(), start("s1", "n"), end("s1"), run_end("pass", None)],
            verdict="pass",
            started_at=start_at,
            conditions={**CONDITIONS, "settings": settings},
        )
    with rig.daemon() as d, d.client(AGENT) as agent, d.client() as ui:
        result = agent.call("run.diff", {"run_id": "oldc0001", "baseline": "oldc0002"})
        assert result["classified"] is False
        assert result["baseline"] == "oldc0002" and "env" not in result
        assert PW not in json.dumps(result, ensure_ascii=False)
        assert set(result) <= {"run_id", "baseline", "baseline_picked", "classified", "time",
                               "graph", "screen"}  # fmt: skip
        # 사람은 환경 차이 원문 그대로
        shown = ui.call("run.compare", {"run_id": "oldc0001", "baseline": "oldc0002"})
        assert PW in json.dumps(shown, ensure_ascii=False)

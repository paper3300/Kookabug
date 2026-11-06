"""M2 완료 기준 (구현 계획 v0 1장, M2 계획 3장 "완료 기준 → 테스트 매핑") 인수 테스트, Python 쪽.

1. 아무것도 안 바꾸고 저장하면 바이트가 같음 — 말뭉치 전체를 실제 `kookabug daemon`으로 열고
   저장한다. 저장 요청은 Node의 전송 코덱(`wireStringify`)을 거친 텍스트 그대로다(큰 실수 세 개,
   검수 H1)
2. 편집 후 의미·노드 ID·모르는 노드 설정 보존 — 앱 쪽 `apps/desktop/e2e/acceptance.spec.ts`
3. target 편집기로 만든 대상이 바로 매칭됨 — 저장 파일을 다시 읽어 같은 정지 화면에서 찾음 +
   상자 = 자른 영역 + 그 target을 쓰는 그래프 실행 pass. 사용자가 넣은 PNG는 다시 저장해도
   남는다(2차 검수 N1). 데스크톱이면 실제 창을 찍어 만든 target을 새 캡처에서 다시 찾는다
(M0b 6) 같은 행위가 CLI·daemon·서비스에서 같은 권한 판정 — 실행은 실제 CLI `run`·daemon agent
   연결·`WorkspaceService.authorize` 세 경로, 편집은 CLI에 편집 명령이 없어 daemon·서비스 두 경로
   (검수 M8)
(3장) daemon 수명 — 둘이 동시에 떠도 하나만 이김, UI를 꺼도 실행 유지, 다시 붙으면 적용한 seq부터

daemon은 제품 진입점(`kookabug daemon` 하위 프로세스)으로 띄운다. 권한 판정 비교만 같은 프로세스의
daemon(`ThreadDaemon`, 실제 전송·WebSocket)으로 한다: 허용 판정은 결과에 실리지 않아 daemon이
서비스 `require`에서 받은 판정을 관찰해야 하기 때문이다. 다른 테스트 모듈을 import하지 않는다.
자세한 경우는 각 작업의 테스트에 있다 (`kookabug_daemon/tests/*`, `tests/documents/*`,
`apps/desktop/e2e/*`).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.cli import cli_env, run_cli
from helpers.corpus import CORPUS_DIR, SAMPLE_WORKSPACE, corpus_files, through_js
from helpers.daemon_runs import TEST, EventLog, RunRig
from helpers.daemon_targets import START_BUTTON, Editor, target_workspace
from helpers.graphs import GraphBuilder, target
from helpers.run import tk

from kb_testing.daemon import DaemonProcess, ThreadDaemon, copy_sample_workspace, daemon_env
from kb_testing.proc import Spawned, wait_until
from kb_testing.sample_game import launch_sample_game
from kookabug_core.permissions import Principal
from kookabug_core.record import read_run
from kookabug_core.service import (
    RUN_START_TOOL,
    ApprovalRequired,
    PermissionDenied,
    WorkspaceService,
)
from kookabug_daemon.client import DaemonClient, DaemonError, attach
from kookabug_daemon.session import SessionInfo, read_session
from kookabug_platform.frames import decode_image
from kookabug_platform.vision import FrameMeta, Vision, load_target_file

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

OLD_NS: Final = 1_600_000_000 * 10**9
BIG_FLOATS: Final = ("1e20", "9007199254740992.0", "1.2345678901234567e19")
"""검수 H1: 말뭉치 `numbers.graph.json`에 원문 그대로 들어 있어야 하는 큰 실수."""
TITLE_TEXT: Final = (312, 150, 400, 80)
"""타이틀 화면의 제목 글자 (시작 버튼과 다른 유일한 무늬)."""
AGENT_ID: Final = "agent-m2"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stamp(path: Path) -> int:
    os.utime(path, ns=(OLD_NS, OLD_NS))
    return path.stat().st_mtime_ns


@contextmanager
def product_daemon(
    spawned: Spawned, root: Path, out: Path, *args: str, env: Mapping[str, str]
) -> Iterator[tuple[DaemonProcess, SessionInfo]]:
    """`kookabug daemon --workspace <root> --json` 하위 프로세스. 끝에 `daemon.shutdown`."""
    proc = DaemonProcess.start(spawned, root, out, *args, env=env)
    assert proc.first_line()["status"] == "started", proc.output()
    info = read_session(root)
    assert info is not None and info.pid == proc.pid
    try:
        yield proc, info
    finally:
        if proc.alive():
            with DaemonClient.from_session(info) as client:
                client.call("daemon.shutdown", {"force": True})
            assert proc.wait() == 0, proc.output()


# ---------------------------------------------------------------- 1. 무수정 저장 바이트 동일


def corpus_rel(path: Path) -> str:
    """말뭉치 파일의 워크스페이스 경로 (예제 워크스페이스 파일은 제자리, 나머지 `tests/corpus/`)."""
    if path.is_relative_to(SAMPLE_WORKSPACE):
        return path.relative_to(SAMPLE_WORKSPACE).as_posix()
    return f"tests/corpus/{path.name}"


def test_unmodified_save_bytes_identical_corpus_via_daemon(
    tmp_path: Path, spawned: Spawned
) -> None:
    root = copy_sample_workspace(tmp_path / "ws")
    (root / "tests" / "corpus").mkdir()
    for path in CORPUS_DIR.glob("*.graph.json"):
        (root / "tests" / "corpus" / path.name).write_bytes(path.read_bytes())
    files = {corpus_rel(p): p for p in corpus_files()}
    numbers = (root / "tests/corpus/numbers.graph.json").read_text(encoding="utf-8")
    assert all(token in numbers for token in BIG_FLOATS)
    before = {rel: (root / rel).read_bytes() for rel in files}
    for rel, source in files.items():
        assert before[rel] == source.read_bytes(), rel
        stamp(root / rel)

    with (
        product_daemon(spawned, root, tmp_path / "d", env=daemon_env(tmp_path)) as (_, info),
        DaemonClient.from_session(info) as client,
    ):
        requests: list[str] = []
        for number, rel in enumerate(files, start=1_000_000):
            opened = client.call("graph.open", {"path": rel})
            assert opened["revision"] == sha(before[rel]), rel
            params = {
                "doc_id": opened["doc_id"],
                "value": opened["value"],
                "base_revision": opened["revision"],
            }
            request = {"jsonrpc": "2.0", "id": number, "method": "graph.save", "params": params}
            requests.append(json.dumps(request))
        # 받은 값을 JS 값으로 되돌려 전송 코덱으로 다시 쓴 텍스트 (주 프로세스의 송신과 같다)
        wired = through_js(requests)
        for number, (rel, wire) in enumerate(zip(files, wired, strict=True), start=1_000_000):
            assert "ok" in wire, (rel, wire)
            client.send_text(wire["ok"])
            response = client.next_unmatched(timeout=30)
            assert response["id"] == number, response
            saved = response["result"]
            assert (saved["wrote"], saved["canonicalized"], saved["revision"]) == (
                False,
                False,
                sha(before[rel]),
            ), rel

    for rel in files:
        assert (root / rel).read_bytes() == before[rel], rel
        assert (root / rel).stat().st_mtime_ns == OLD_NS, rel


# ---------------------------------------------------------------- 3. target 바로 매칭


def crop_png(png: Path, rect: tuple[int, int, int, int]) -> bytes:
    x, y, w, h = rect
    pixels = decode_image(png.read_bytes())[y : y + h, x : x + w]
    ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels))
    assert ok
    return data.tobytes()


def found_on_disk(root: Path, rel: str, png: Path) -> tuple[int, int, int, int] | None:
    """저장한 target 파일을 데몬 밖에서 다시 읽어 그 PNG에서 찾은 상자 (runner와 같은 매칭)."""
    spec = load_target_file(root / rel)
    pixels = decode_image(png.read_bytes())
    match = Vision().find(pixels, FrameMeta.of_image(pixels), spec).match
    return None if match is None else match.rect


def saved_target_headless(tmp_path: Path, spawned: Spawned) -> None:
    root = target_workspace(tmp_path)
    title = root / "captures" / "title.png"
    rel = "targets/editor/start.target.json"
    graph = "tests/editor_target.graph.json"
    (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs={"path": "SampleRPG", "window_title": "SampleRPG", "timeout_ms": 5000},
            next={"attached": "n_wait"},
        )
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(rel), "timeout_ms": 5000},
            next={"found": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
        .write(root, graph)
    )
    # 사용자가 넣은 PNG를 쓰는 target (2차 검수 N1)
    user_rel = "targets/user/button.target.json"
    user_png = root / "targets" / "user" / "source.png"
    user_png.parent.mkdir(parents=True)
    user_png.write_bytes(crop_png(title, START_BUTTON))
    (root / user_rel).write_text(
        json.dumps({"format": "kookabug.target/0", "image": "source.png"}), encoding="utf-8"
    )
    platform = ("--platform-fake", str(root / "fake-platform.json"))

    with (
        product_daemon(spawned, root, tmp_path / "d", *platform, env=cli_env(tmp_path)) as (
            _,
            info,
        ),
        DaemonClient.from_session(info) as client,
    ):
        ed = Editor(client)
        frame = ed.load("captures/title.png")
        saved = ed.save(rel, frame, START_BUTTON, {"match": {"threshold": 0.9}})
        # 저장 응답의 미리보기: 같은 정지 화면에서 찾음, 상자 = 자른 영역
        preview = saved["preview"]
        assert preview["found"] is True and preview["threshold"] == 0.9, preview
        assert preview["match"]["rect"] == list(START_BUTTON)
        assert preview["match"]["score"] >= 0.9 and preview["match"]["scale"] == 1.0
        assert saved["warnings"] == []
        # 저장한 파일(디스크 이미지)로 daemon이 다시 찾아도 같다
        opened = ed.open(rel)
        assert opened["revision"] == saved["revision"] and opened["diagnostics"] == []
        again = ed.preview(frame, opened["spec"], image=opened["spec"]["image"], base=rel)
        assert again["found"] is True and again["match"]["rect"] == list(START_BUTTON)
        # 그 target을 쓰는 그래프 실행 (가짜 플랫폼, 예제 게임 장면 표)
        started = client.call("run.start", {"path": graph})
        status = wait_until(
            lambda: (
                (s := client.call("run.status", {"run_id": started["run_id"]}))["state"] == "ended"
                and s
            ),
            timeout=120,
            interval=0.2,
        )
        assert status["outcome"]["verdict"] == "pass", status

        # 사용자 PNG를 쓰던 target을 새 영역으로 다시 저장: 새 이미지로 바뀌고 사용자 PNG는 남는다
        user = ed.open(user_rel)
        resaved = ed.save(user_rel, frame, TITLE_TEXT, user["spec"], user["revision"])
        assert resaved["preview"]["found"] is True, resaved
        assert resaved["preview"]["match"]["rect"] == list(TITLE_TEXT)
        assert resaved["image"] != "targets/user/source.png"

    # 데몬 밖: 저장 파일을 다시 읽어 같은 화면에서 찾는다
    assert found_on_disk(root, rel, title) == START_BUTTON
    assert found_on_disk(root, user_rel, title) == TITLE_TEXT
    assert (root / "targets/editor/start.png").read_bytes() == crop_png(title, START_BUTTON)
    assert user_png.read_bytes() == crop_png(title, START_BUTTON)


def saved_target_desktop(tmp_path: Path, spawned: Spawned) -> None:
    root = target_workspace(tmp_path / "ws")
    rel = "targets/live/start.target.json"
    title = f"KBM2 {uuid.uuid4().hex[:8]}"
    with (
        launch_sample_game(("--title", title), workdir=tmp_path / "game") as game,
        product_daemon(spawned, root, tmp_path / "d", env=daemon_env(tmp_path)) as (_, info),
        DaemonClient.from_session(info) as client,
    ):
        windows = client.call("windows.list", {})["windows"]
        assert [w["title"] for w in windows if w["handle"] == game.hwnd] == [title], windows
        ed = Editor(client)
        frame = client.call("target.capture", {"window": game.hwnd})
        cw, ch = frame["client_size"]
        # 예제 게임은 1024x640 기준으로 그린다: 화면 배율만큼 커진 시작 버튼 안쪽
        scale = ch / 640
        x, y, w, h = (round(v * scale) for v in START_BUTTON)
        crop = (x + 4, y + 4, w - 8, h - 8)
        saved = ed.save(rel, frame, crop)
        assert saved["preview"]["found"] is True, saved
        assert saved["preview"]["match"]["rect"] == list(crop)
        opened = ed.open(rel)
        assert opened["spec"]["recorded"] == {"client_size": [cw, ch], "dpi": frame["dpi"]}
        # 새로 찍은 화면에서 저장한 파일 그대로 찾는다
        live = client.call("target.capture", {"window": game.hwnd})
        result = ed.preview(live, opened["spec"], image=opened["spec"]["image"], base=rel)
        assert result["found"] is True, result
        mx, my, _, _ = result["match"]["rect"]
        assert abs(mx - crop[0]) <= 2 and abs(my - crop[1]) <= 2


@pytest.mark.parametrize("mode", ["headless", pytest.param("desktop", marks=pytest.mark.desktop)])
def test_saved_target_matches_same_frame(tmp_path: Path, spawned: Spawned, mode: str) -> None:
    if mode == "headless":
        saved_target_headless(tmp_path, spawned)
    else:
        saved_target_desktop(tmp_path, spawned)


# ---------------------------------------------------------------- (M0b 6) 권한: 같은 판정


def agent(*, attended: bool = False) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": AGENT_ID, "attended": attended}


def write_local(rig: RunRig, permissions: Mapping[str, Any] | None) -> None:
    path = rig.root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body: dict[str, Any] = {"format": "kookabug.local/0"}
    if permissions is not None:
        body["permissions"] = dict(permissions)
    path.write_text(json.dumps(body), encoding="utf-8")


def write_team(rig: RunRig, permissions: Mapping[str, Any]) -> None:
    path = rig.root / "kookabug.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["permissions"] = dict(permissions)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_user(rig: RunRig, permissions: Mapping[str, Any] | None) -> None:
    folder = Path(rig.env["KOOKABUG_USER_CONFIG_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {"format": "kookabug.user-settings/0"}
    if permissions is not None:
        body["permissions"] = dict(permissions)
    (folder / "settings.json").write_text(json.dumps(body), encoding="utf-8")


def run_folders(root: Path) -> list[Path]:
    runs = root / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


RUN_POLICIES: Final[list[Any]] = [
    # (사용자 설정, 팀 kookabug.json, 프로젝트 local.json) → (verdict, final, reason)
    pytest.param(
        (None, None, {"toolsets": {"run": "allow"}}), ("allow", "allow", "toolset"), id="allow"
    ),
    pytest.param((None, None, None), ("deny", "deny", "preset"), id="deny"),
    pytest.param(
        (None, None, {"toolsets": {"run": "ask"}}),
        ("ask", "deny", "unattended_ask"),
        id="unattended_ask",
    ),
    pytest.param(
        ({"preset": "full"}, {"preset": "read_only"}, None),
        ("deny", "deny", "team_ceiling"),
        id="team_ceiling",
    ),
]


@pytest.mark.parametrize(("policy", "expected"), RUN_POLICIES)
def test_run_start_same_decision_real_cli_daemon_service(
    tmp_path: Path, policy: tuple[Any, Any, Any], expected: tuple[str, str, str]
) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    user, team, local = policy
    write_user(rig, user)
    if team is not None:
        write_team(rig, team)
    write_local(rig, local)

    # ③ 서비스
    principal = Principal("agent", AGENT_ID, attended=False)
    decision = (
        WorkspaceService(rig.root, environ=rig.env)
        .authorize(principal, RUN_START_TOOL, TEST)
        .to_dict()
    )
    assert (decision["verdict"], decision["final"], decision["reason"]) == expected

    # ① 실제 CLI 하위 프로세스 (사람 없는 에이전트)
    done = run_cli(
        ["run", TEST, "--json"], cwd=rig.root, env={**rig.env, "KOOKABUG_AGENT": AGENT_ID}
    )
    cli = json.loads(done.stdout)
    assert cli["principal"] == {"kind": "agent", "id": AGENT_ID, "attended": False}
    assert cli["decision"] == decision
    cli_folders = run_folders(rig.root)

    # ② daemon agent 연결. daemon이 집행한 판정은 서비스 `require`가 돌려준(또는 예외에 실은) 값이다
    observed: list[dict[str, Any]] = []
    # 에이전트 실행: 개발 모듈 없는 daemon (개발 모듈 daemon의 에이전트 실행은 거부, M6 3.7)
    with rig.daemon(modules=()) as d, d.client(agent()) as client:
        original = d.daemon.service.require

        def observe(who: Principal, tool: str, arg: str = "", **kwargs: Any) -> Any:
            if tool != RUN_START_TOOL:
                return original(who, tool, arg, **kwargs)
            assert (who, arg) == (principal, TEST)
            try:
                result = original(who, tool, arg, **kwargs)
            except (PermissionDenied, ApprovalRequired) as exc:
                observed.append(exc.decision.to_dict())
                raise
            observed.append(result.to_dict())
            return result

        d.daemon.service.require = observe  # type: ignore[method-assign]
        if decision["final"] == "allow":
            started = client.call("run.start", {"path": TEST})
            wait_until(
                lambda: (
                    client.call("run.status", {"run_id": started["run_id"]})["state"] == "ended"
                ),
                interval=0.1,
            )
        else:
            with pytest.raises(DaemonError) as caught:
                client.call("run.start", {"path": TEST})
            assert caught.value.kind == "permission_denied"
            assert caught.value.data["decision"] == decision
    assert observed == [decision]

    # 집행도 같다: 허용이면 둘 다 실행, 거부면 CLI 종료 코드 5·daemon 거부, 실행 폴더 없음
    if decision["final"] == "allow":
        assert done.returncode == 0 and cli["verdict"] == "pass", done.stderr
        assert len(cli_folders) == 1 and len(run_folders(rig.root)) == 2
    else:
        assert done.returncode == 5 and cli["run_dir"] is None, done.stderr
        assert cli_folders == [] and run_folders(rig.root) == []


NEW_GRAPH: Final = "tests/agent_new.graph.json"
NEW_TARGET: Final = "targets/agent_new.target.json"
EDIT_ARGS: Final = {
    "kb_graph_patch": TEST,
    "kb_graph_create": NEW_GRAPH,
    "kb_target_create": NEW_TARGET,
}
EDIT_POLICIES: Final[dict[str, tuple[Callable[[RunRig], None], bool, str]]] = {
    # 이름 → (정책 쓰기, 사람 있는 에이전트, daemon 오류 종류)
    "deny": (lambda rig: write_team(rig, {"preset": "read_only"}), False, "permission_denied"),
    "ask": (
        lambda rig: write_local(rig, {"toolsets": {"graph_edit": "ask"}}),
        True,
        "approval_required",
    ),
    "unattended_ask": (
        lambda rig: write_local(rig, {"toolsets": {"graph_edit": "ask"}}),
        False,
        "permission_denied",
    ),
}


def edit(client: DaemonClient, tool: str) -> Any:
    """그 도구에 대응하는 daemon 메서드 (`graph.save`·`graph.create`·`target.save`)."""
    if tool == "kb_graph_patch":
        opened = client.call("graph.open", {"path": TEST})
        value = opened["value"]
        value["meta"] = {"title": "편집함"}
        params = {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]}
        return client.call("graph.save", params)
    if tool == "kb_graph_create":
        return client.call("graph.create", {"path": NEW_GRAPH, "kind": "test"})
    crop = {"frame_id": "f1", "rect": [0, 0, 4, 4]}
    params = {"path": NEW_TARGET, "spec": {}, "crop": crop, "base_revision": None}
    return client.call("target.save", params)


@pytest.mark.parametrize("policy", list(EDIT_POLICIES))
@pytest.mark.parametrize("tool", list(EDIT_ARGS))
def test_graph_edit_same_decision_daemon_service(tmp_path: Path, tool: str, policy: str) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    write_policy, attended, kind = EDIT_POLICIES[policy]
    write_policy(rig)
    graph = rig.root / TEST
    stamp(graph)
    before = graph.read_bytes()

    # ③ 서비스
    principal = Principal("agent", AGENT_ID, attended=attended)
    expected = (
        WorkspaceService(rig.root, environ=rig.env)
        .authorize(principal, tool, EDIT_ARGS[tool])
        .to_dict()
    )
    assert expected["final"] != "allow"

    # ② daemon agent 연결: 같은 판정, 집행은 아무것도 쓰지 않음
    with ThreadDaemon(rig.root, service=rig.service()) as d:
        with d.client(agent(attended=attended)) as client, pytest.raises(DaemonError) as caught:
            edit(client, tool)
        assert caught.value.kind == kind, caught.value
        assert caught.value.data["decision"] == expected
        assert tool in caught.value.message
        assert graph.read_bytes() == before and graph.stat().st_mtime_ns == OLD_NS
        assert not (rig.root / NEW_GRAPH).exists()
        assert not (rig.root / NEW_TARGET).exists()
        # 같은 정책에서 UI 연결은 판정받지 않는다 (graph.save·graph.create는 실제로 쓴다)
        if tool != "kb_target_create":
            with d.client() as ui:
                edit(ui, tool)
            changed = graph.read_bytes() != before or (rig.root / NEW_GRAPH).exists()
            assert changed


# ---------------------------------------------------------------- (3장) daemon 수명


def gate_graph(signal: Path) -> GraphBuilder:
    return (
        tk()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "앞"}, next={"done": "n_gate"})
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_after"})
        .node("n_after", "core.log.message", inputs={"text": "뒤"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def gate_logged(event: Mapping[str, Any]) -> bool:
    return event.get("event") == "log" and event.get("message") == "gate"


def test_single_daemon_and_run_survives_ui_and_resume_seq(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    # 둘이 동시에 떠도 하나만 이긴다. 진 쪽은 이긴 쪽 세션을 내고 0으로 끝난다
    procs = [
        DaemonProcess.start(spawned, rig.root, tmp_path / f"d{i}", *rig.daemon_args(), env=rig.env)
        for i in range(2)
    ]
    lines = [p.first_line() for p in procs]
    assert sorted(line["status"] for line in lines) == ["already_running", "started"], [
        p.output() for p in procs
    ]
    winner = next(p for p, line in zip(procs, lines, strict=True) if line["status"] == "started")
    loser = next(p for p in procs if p is not winner)
    assert loser.wait() == 0
    info = read_session(rig.root)
    assert info is not None and info.pid == winner.pid
    assert {line["session"]["start_id"] for line in lines} == {info.start_id}

    # UI가 실행을 시작하고 구독해 게이트까지 적용한 뒤 끊긴다 (UI 끔)
    with DaemonClient.from_session(info) as first:
        started = first.call("run.start", {"path": TEST})
        first.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
        log1 = EventLog(first, started["run_id"])
        log1.until_event(gate_logged)
    applied = log1.last
    run_dir = Path(started["run_dir"])

    # 실행은 그대로다: daemon 살아 있음, run.end 없음
    assert winner.alive(), winner.output()
    assert read_run(run_dir).run_end is None

    # 다시 붙기: 새 daemon을 띄우지 않고 같은 세션에 붙는다
    def no_spawn(root: Path) -> Any:
        raise AssertionError(f"살아 있는 daemon이 있는데 새로 띄우려 했다: {root}")

    again = attach(rig.root, spawn=no_spawn)
    assert again is not None and (again.start_id, again.pid) == (info.start_id, winner.pid)
    with DaemonClient.from_session(again) as second:
        assert second.call("run.status", {"run_id": started["run_id"]})["state"] == "running"
        # 적용한 마지막 seq부터 다시 구독한다. 빈틈·중복이 없다 (EventLog strict)
        second.call("run.subscribe", {"run_id": started["run_id"], "after_seq": applied})
        log2 = EventLog(second, started["run_id"], base=applied)
        signal.touch()
        log2.until_ended(timeout=90)
        events = read_run(run_dir).events
        assert (
            log1.seqs + log2.seqs == [e["seq"] for e in events] == list(range(1, len(events) + 1))
        )
        assert log2.ended is not None and log2.ended["outcome"]["verdict"] == "pass"
        second.call("daemon.shutdown", {})
    assert winner.wait() == 0, winner.output()

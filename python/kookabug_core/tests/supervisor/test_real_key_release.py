"""누른 채 강제 종료된 runner의 **실제** 입력을 감독자가 SendInput으로 뗀다 (구현 계획 M1 2.4, 완료
기준 6, 계획 검수 10).

- 게임(예제 게임)은 **테스트 하네스의 세션 Job**에서 띄운다 — runner 실행 Job 밖이라 Job 정리와
  경합하지 않는다. 제품의 복구 순서(키 해제 → `run.end` → `run.json` → Job 정리)는 그대로다
- 그래프는 `procs/input_runner.py`의 `testkit.input.press_window`로 그 창에 원시 누르기를 한다
  (앱·창 노드 전 단계). 장벽은 **마지막 누르기의 `after_down`에만** 건다(`wait:`)
- 해제 확인은 둘 다: 게임의 수신 기록(`key_up`·`mouse_up`)과 `GetAsyncKeyState`
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.supervisor import SupervisorHost, events, runner_stderr, start_run

from kb_testing import keys
from kb_testing.proc import (
    PROCS_DIR,
    Barrier,
    Spawned,
    barrier,
    python_cmd,
    read_fake_input_log,
    wait_until,
)
from kb_testing.sample_game import SampleGame, launch_sample_game
from kookabug_core.inputs import recover_run
from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV
from kookabug_core.record import read_run
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.supervisor import RunHandle
from kookabug_platform.sendinput import SendInputBackend
from kookabug_platform.windows import activate

pytestmark = [pytest.mark.desktop_input, pytest.mark.process]

INPUT_RUNNER_CMD: Final = python_cmd(PROCS_DIR / "input_runner.py")
CLICK_AT: Final = (600, 520)
"""마우스를 누르는 클라이언트 점 (타이틀 화면의 빈 자리)."""
ACK_TIMEOUT_S: Final = 10.0

# 입력 이름 → (게임 수신 기록에서 찾을 것, GetAsyncKeyState 이름)
ACK: Final = {
    "shift": (("key", "lshift"), "shift"),
    "a": (("key", "a"), "a"),
    "rctrl": (("key", "rctrl"), "rctrl"),
    "mouse:left": (("button", "left"), "mouse:left"),
    "mouse:right": (("button", "right"), "mouse:right"),
}


@pytest.fixture(autouse=True)
def clean_keys() -> Iterator[None]:
    keys.assert_no_keys_held()
    try:
        yield
    finally:
        keys.release_all_for_test()


@pytest.fixture
def game(tmp_path: Path) -> Iterator[SampleGame]:
    title = f"KBT5R {uuid.uuid4().hex[:8]}"
    with launch_sample_game(("--title", title), workdir=tmp_path / "game") as g:
        bring_front(g.hwnd)
        yield g


def bring_front(hwnd: int) -> None:
    wait_until(lambda: activate(hwnd), timeout=5, message=lambda: f"{hwnd:#x}를 앞으로 못 가져옴")


def press_graph(game: SampleGame, inputs: Sequence[str]) -> GraphBuilder:
    x, y = CLICK_AT
    return (
        tk()
        .entry("n_press")
        .node(
            "n_press",
            "testkit.input.press_window",
            inputs={"title": game.ready["title"], "inputs": list(inputs), "x": x, "y": y},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def windows_platform(hooks: dict[str, dict[str, str]] | None = None) -> PlatformSpec:
    return PlatformSpec("windows", hooks=hooks or {})


def is_event(record: dict[str, Any], kind: str, name: str) -> bool:
    (field, value), _ = ACK[name]
    device_event = f"{'mouse' if name.startswith('mouse:') else 'key'}_{kind}"
    return record["event"] == device_event and record.get(field) == value


def wait_ack(game: SampleGame, name: str, kind: str, *, after: int) -> dict[str, Any]:
    return game.wait_event(
        where=lambda r: is_event(r, kind, name), after=after, timeout=ACK_TIMEOUT_S
    )


def acks(game: SampleGame, kind: str, names: Sequence[str], after: int) -> list[str]:
    """`after` 뒤 기록에서 `names`의 `kind`(down·up)가 나온 차례."""
    found: list[str] = []
    for record in game.events():
        if record["seq"] <= after:
            continue
        for name in names:
            if is_event(record, kind, name):
                found.append(name)
    return found


def async_name(name: str) -> str:
    return ACK[name][1]


def wait_barrier(wall: Barrier, handle: RunHandle) -> None:
    """장벽에 닿기를 기다린다. 실행이 먼저 끝나면 그 기록을 붙여 바로 실패."""

    def reached() -> bool:
        if wall.is_ready():
            return True
        if handle.runner is not None and handle.runner.wait(0) is not None:
            view = read_run(handle.run_dir)
            raise AssertionError(f"장벽 전에 실행이 끝났다: {view.events}\n{runner_stderr(handle)}")
        return False

    wait_until(reached, timeout=30, message=lambda: runner_stderr(handle))


def kill_runner(handle: RunHandle) -> None:
    assert handle.runner is not None
    handle.runner.terminate(1)
    assert handle.wait_exit(10) == 1


def held_and_acked(game: SampleGame, names: Sequence[str], mark: int) -> None:
    """장벽에 닿은 뒤: 모두 게임이 눌림으로 받았고, OS에서도 눌려 있다."""
    for name in names:
        wait_ack(game, name, "down", after=mark)
    assert [n for n in names if not keys.is_down(async_name(n))] == []


def assert_supervisor_released(
    handle: RunHandle, game: SampleGame, names: Sequence[str], mark: int
) -> None:
    outcome = handle.wait(30)
    assert outcome.run_end is not None, runner_stderr(handle)
    assert outcome.run_end["code"] == "runner_died"
    assert outcome.run_end["input_recovery"] == "recovered"
    # 게임 ACK와 비동기 키 상태를 각각 (둘 중 하나만 맞아도 실패)
    for name in names:
        wait_ack(game, name, "up", after=mark)
    wait_until(
        lambda: not [n for n in names if keys.is_down(async_name(n))],
        timeout=ACK_TIMEOUT_S,
        message=lambda: f"OS에서 아직 눌림: {[n for n in names if keys.is_down(async_name(n))]}",
    )
    marker = json.loads((handle.run_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
    assert marker["recovered_by"]["kind"] == "supervisor"
    (recovered,) = [e for e in events(handle) if e["event"] == "input.recovered"]
    assert recovered["by"]["kind"] == "supervisor"
    assert len(recovered["inputs"]) == len(names)


@pytest.mark.parametrize(
    "name",
    [
        "shift",
        "a",
        pytest.param("rctrl", id="right_ctrl"),
        pytest.param("mouse:left", id="mouse_left"),
        pytest.param("mouse:right", id="mouse_right"),
    ],
)
def test_runner_killed_with_real_input_down_supervisor_releases(
    tmp_path: Path, spawned: Spawned, game: SampleGame, name: str
) -> None:
    wall = barrier(tmp_path / "barriers" / "down")
    mark = game.last_seq()
    # 훅 이름: 키는 정식 이름, 마우스는 mouse:<버튼>
    handle = start_run(
        tmp_path,
        spawned,
        press_graph(game, [name]),
        runner_cmd=INPUT_RUNNER_CMD,
        platform=windows_platform({"after_down": {name: f"wait:{wall.path}"}}),
        plugin_modules=(),
    )
    wait_barrier(wall, handle)
    held_and_acked(game, [name], mark)
    kill_runner(handle)
    assert_supervisor_released(handle, game, [name], mark)


def test_runner_killed_with_composite_held_supervisor_releases(
    tmp_path: Path, spawned: Spawned, game: SampleGame
) -> None:
    names = ["shift", "a", "mouse:left"]
    wall = barrier(tmp_path / "barriers" / "last")
    mark = game.last_seq()
    handle = start_run(
        tmp_path,
        spawned,
        press_graph(game, names),
        runner_cmd=INPUT_RUNNER_CMD,
        platform=windows_platform({"after_down": {"mouse:left": f"wait:{wall.path}"}}),
        plugin_modules=(),
    )
    wait_barrier(wall, handle)
    held_and_acked(game, names, mark)
    assert acks(game, "down", names, mark) == names
    kill_runner(handle)
    assert_supervisor_released(handle, game, names, mark)
    # 누른 차례의 거꾸로 뗐다
    assert acks(game, "up", names, mark) == list(reversed(names))


def die_holding_without_supervisor(
    tmp_path: Path, spawned: Spawned, game: SampleGame, names: Sequence[str]
) -> tuple[SupervisorHost, Path]:
    """실행 A(`windows`)가 `names`를 누른 채 runner kill → 감독자도 마무리(키 복구) 직전에 kill
    (이중 고장). 그 자리에서 뗀 주체가 없음을 확인하고 (감독자 호스트, A 실행 폴더)."""
    wall = barrier(tmp_path / "barriers" / "last")
    finalize = barrier(tmp_path / "barriers" / "before_finalize")
    host = SupervisorHost.make(
        tmp_path,
        press_graph(game, names),
        faults=[
            {"point": "recovery.before_finalize", "role": "supervisor", "action": finalize.action}
        ],
        runner_cmd=INPUT_RUNNER_CMD,
        platform=windows_platform({"after_down": {names[-1]: f"wait:{wall.path}"}}),
        plugin_modules=(),
    )
    mark = game.last_seq()
    host.start(spawned)

    def reached() -> bool:
        if wall.is_ready():
            return True
        # 감독자는 복구 직전 장벽(before_finalize)에서 멈추므로 done.json이 아니라 run.end로 본다
        if (host.out / "started.json").exists() and host.view().run_end is not None:
            raise AssertionError(f"장벽 전에 실행이 끝났다: {host.view().events}\n{host.stderr()}")
        return False

    wait_until(reached, timeout=30, message=host.stderr)
    held_and_acked(game, names, mark)
    a_dir = host.run_dir
    host.kill_runner()
    finalize.wait_ready()
    host.kill()
    time.sleep(1.0)
    assert acks(game, "up", names, mark) == []
    assert [n for n in names if not keys.is_down(async_name(n))] == []
    assert not (a_dir / INPUT_RECOVERY_FILE).exists()
    lease = host.lease_file()
    assert lease is not None and lease["clean"] is False
    assert lease["owner"]["device"] == {"kind": "windows"}
    return host, a_dir


def test_double_fault_next_owner_releases_real_inputs_before_its_input(
    tmp_path: Path, spawned: Spawned, game: SampleGame
) -> None:
    names = ["shift", "a", "mouse:left"]
    host, a_dir = die_holding_without_supervisor(tmp_path, spawned, game, names)

    # 실행 B: 같은 임대권·같은 장치. 임대권을 얻으면 자기 입력(b) 전에 A의 입력을 뗀다
    env = {k: v for k, v in host.env.items() if k != "KOOKABUG_FAULTS"}
    bring_front(game.hwnd)
    b_mark = game.last_seq()
    handle = start_run(
        tmp_path,
        spawned,
        press_graph(game, ["b"]),
        env=env,
        runner_cmd=INPUT_RUNNER_CMD,
        platform=windows_platform(),
        plugin_modules=(),
    )
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and outcome.verdict == "pass", runner_stderr(handle)
    first_b = game.wait_event("key_down", key="b", after=b_mark, timeout=ACK_TIMEOUT_S)
    releases = [wait_ack(game, n, "up", after=b_mark) for n in names]
    assert all(r["seq"] < first_b["seq"] for r in releases), (releases, first_b)
    assert acks(game, "up", names, b_mark) == list(reversed(names))
    game.wait_event("key_up", key="b", after=first_b["seq"], timeout=ACK_TIMEOUT_S)
    wait_until(lambda: not keys.held([*map(async_name, names), "b"]), timeout=ACK_TIMEOUT_S)
    marker = json.loads((a_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
    assert marker["recovered_by"] == {"kind": "runner", "run_id": handle.run_id}
    (recovered,) = [e for e in events(handle) if e["event"] == "input.recovered"]
    assert recovered["inputs"] == [
        {"device": "keyboard", "key": "shift"},
        {"device": "keyboard", "key": "a"},
        {"device": "mouse", "button": "left"},
    ]
    assert read_run(a_dir).status == "interrupted"


def test_fake_next_owner_releases_real_inputs_of_windows_run(
    tmp_path: Path, spawned: Spawned, game: SampleGame
) -> None:
    # 다음 획득자가 다른 장치(가짜 플랫폼)여도 앞 실행의 장치(SendInput)로 실제 키를 뗀 뒤에만
    # 복구 표시를 남긴다 (M1 T5 검수 1). 늦게 온 감독자 복구는 이미 복구됨으로 건너뛴다
    names = ["shift", "a"]
    host, a_dir = die_holding_without_supervisor(tmp_path, spawned, game, names)
    env = {k: v for k, v in host.env.items() if k != "KOOKABUG_FAULTS"}
    b_mark = game.last_seq()
    graph = (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": "x"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    handle = start_run(tmp_path, spawned, graph, env=env)  # 가짜 플랫폼 (워커 testkit)
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and outcome.verdict == "pass", runner_stderr(handle)
    for name in names:
        wait_ack(game, name, "up", after=b_mark)
    assert acks(game, "up", names, b_mark) == list(reversed(names))
    wait_until(lambda: not keys.held([async_name(n) for n in names]), timeout=ACK_TIMEOUT_S)
    # 가짜 실행의 x는 가짜 기록에만 (실제로 x를 보내지 않았다)
    assert not [e for e in game.events() if e["seq"] > b_mark and e.get("key") == "x"]
    fake_lines = read_fake_input_log(tmp_path / "input.jsonl")
    assert [(ln["op"], ln.get("key")) for ln in fake_lines] == [("down", "x"), ("up", "x")]
    marker = json.loads((a_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
    assert marker["recovered_by"] == {"kind": "runner", "run_id": handle.run_id}
    late = recover_run(
        a_dir, backend=SendInputBackend(), name=env[LEASE_NAME_ENV], directory=env[STATE_DIR_ENV]
    )
    assert late.status == "already_recovered"

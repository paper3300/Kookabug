"""실행 시작 스냅샷: 고정점 복사, 원본 변경 감지, 자원 한도, 스냅샷 경로 (M0b 2.8).

실제 M0a 로더·검증·실행기를 쓴다.
"""

import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
from helpers.graphs import (
    GraphBuilder,
    make_workspace,
    secret,
    setting,
    subgraph_interface,
    target,
    write_json,
    write_target,
)

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, RunResult
from kookabug_core.loader import MAX_CALL_DEPTH, Program, load_program
from kookabug_core.record import (
    Snapshot,
    SnapshotError,
    SnapshotLimits,
    create_run_folder,
    take_snapshot,
)
from kookabug_core.record.snapshot import GRAPH_PREFIX
from kookabug_core.validate import validate
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE, MemorySecrets, Workspace

TEST = "tests/t.graph.json"
SECRET_VALUE = "pw-7f3a-do-not-record"


def sub(*body: tuple[str, str, dict[str, object]]) -> GraphBuilder:
    """서브그래프: entry → body 노드들을 차례로 → exit(done). body는 (id, type, inputs)."""
    g = GraphBuilder("subgraph", interface=subgraph_interface())
    ids = [b[0] for b in body]
    g.entry(ids[0] if ids else "n_exit")
    for i, (node, node_type, inputs) in enumerate(body):
        nxt = ids[i + 1] if i + 1 < len(ids) else "n_exit"
        if node_type == "core.graph.call":
            g.call(node, str(inputs["graph"]), next={"done": nxt})
        else:
            g.node(node, node_type, inputs=inputs, next={"done": nxt})
    return g.exit("n_exit", "done")


def call(graph: str, node: str = "n_call") -> tuple[str, str, dict[str, object]]:
    return (node, "core.graph.call", {"graph": graph})


def use(*targets: str, node: str = "n_use") -> tuple[str, str, dict[str, object]]:
    return (node, "core.var.set", {"name": "v", "value": [target(t) for t in targets]})


def main(*body: tuple[str, str, dict[str, object]]) -> GraphBuilder:
    """테스트 그래프: entry → body → core.test.pass."""
    g = GraphBuilder()
    ids = [b[0] for b in body]
    g.entry(ids[0] if ids else "n_pass")
    for i, (node, node_type, inputs) in enumerate(body):
        nxt = ids[i + 1] if i + 1 < len(ids) else "n_pass"
        if node_type == "core.graph.call":
            g.call(node, str(inputs["graph"]), next={"done": nxt})
        else:
            g.node(node, node_type, inputs=inputs, next={"done": nxt})
    return g.node("n_pass", "core.test.pass")


def snapshot(
    ws: Workspace,
    dest: Path,
    *,
    limits: SnapshotLimits | None = None,
    on_copy: Callable[[str, int], None] | None = None,
) -> Snapshot:
    return take_snapshot(
        ws,
        TEST,
        dest,
        secrets=MemorySecrets({"pw": SECRET_VALUE}),
        limits=limits or SnapshotLimits(),
        on_copy=on_copy,
    )


def errors(program: Program) -> list[Diagnostic]:
    return [d for d in validate(program) if d.severity == "error"]


def run(program: Program, prefix: str = GRAPH_PREFIX) -> RunResult:
    executor = Executor(platform=FakePlatform(), clock=FakeClock())
    return executor.run(program, ExecOptions(run_id="r1", graph_prefix=prefix))


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def basic_workspace(root: Path) -> Workspace:
    """테스트 → s1 → s2(target a) , 테스트도 target b. 관계없는 그래프·target도 둔다."""
    ws = make_workspace(root)
    write_target(ws, "targets/a.target.json")
    write_target(ws, "targets/b.target.json", image="../img/b.png")
    write_target(ws, "targets/unused.target.json")
    sub(use("targets/a.target.json")).write(ws, "subgraphs/s2.graph.json")
    sub(call("subgraphs/s2.graph.json")).write(ws, "subgraphs/s1.graph.json")
    sub().write(ws, "subgraphs/unused.graph.json")
    main(use("targets/b.target.json"), call("subgraphs/s1.graph.json")).write(ws, TEST)
    return ws


CLOSURE = {
    WORKSPACE_FILE,
    TEST,
    "subgraphs/s1.graph.json",
    "subgraphs/s2.graph.json",
    "targets/a.target.json",
    "targets/a.png",
    "targets/b.target.json",
    "img/b.png",
}


def test_snapshot_copies_closure_bytes(tmp_path: Path) -> None:
    ws = basic_workspace(tmp_path / "ws")
    snap = snapshot(ws, tmp_path / "snap")
    assert files_under(snap.root) == CLOSURE
    for rel in CLOSURE:
        original = (tmp_path / "ws" / rel).read_bytes()
        assert (snap.root / rel).read_bytes() == original
        assert snap.files[rel] == len(original)
    assert snap.absent == set()
    assert snap.attempts == 1
    assert errors(snap.program) == []


def test_snapshot_has_workspace_json_not_local_json_or_secrets(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = make_workspace(root, settings={"user": None}, local={"user": "local-user-9"})
    main(
        ("n_user", "core.var.set", {"name": "u", "value": setting("user")}),
        ("n_pw", "core.var.set", {"name": "p", "value": secret("pw")}),
    ).write(ws, TEST)
    snap = snapshot(ws, tmp_path / "snap")
    assert files_under(snap.root) == {WORKSPACE_FILE, TEST}
    assert (snap.root / WORKSPACE_FILE).read_bytes() == (root / WORKSPACE_FILE).read_bytes()
    assert not (snap.root / LOCAL_FILE).exists()
    for path in snap.root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert SECRET_VALUE.encode() not in data
            assert b"local-user-9" not in data
    # local 설정·비밀값은 스냅샷 파일이 아니라 원래 워크스페이스에서 해석된다
    assert errors(snap.program) == []
    assert snap.program.graphs[TEST].nodes["n_user"].inputs["value"] == "local-user-9"
    assert run(snap.program).verdict == "pass"


def test_program_loaded_from_snapshot_only(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = basic_workspace(root)
    snap = snapshot(ws, tmp_path / "snap")
    assert snap.workspace.root == snap.root
    assert snap.program.workspace is snap.workspace
    # 원본을 지우고 바꿔도 스냅샷 프로그램은 그대로 돈다
    (root / "subgraphs" / "s2.graph.json").unlink()
    (root / "targets" / "a.target.json").unlink()
    main().write(ws, TEST)
    graph_files = {g.path for g in snap.program.graphs.values()}
    assert graph_files == {TEST, "subgraphs/s1.graph.json", "subgraphs/s2.graph.json"}
    node = snap.program.graphs["subgraphs/s2.graph.json"].nodes["n_use"]
    (found,) = node.inputs["value"]
    assert found.path.is_relative_to(snap.root)
    assert run(snap.program).verdict == "pass"


def test_new_subgraph_reference_after_first_copy_copied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = make_workspace(root)
    sub().write(ws, "subgraphs/a.graph.json")
    main(call("subgraphs/a.graph.json")).write(ws, TEST)
    before = load_program(ws, TEST, secrets=MemorySecrets())
    assert "subgraphs/b.graph.json" not in before.references.discovered
    # 원본이 A→B로 바뀐 뒤 스냅샷: 앞서 읽은 참조 목록이 아니라 지금 상태를 따라간다
    sub().write(ws, "subgraphs/b.graph.json")
    sub(call("subgraphs/b.graph.json")).write(ws, "subgraphs/a.graph.json")
    snap = snapshot(ws, tmp_path / "snap")
    assert files_under(snap.root) == {
        WORKSPACE_FILE,
        TEST,
        "subgraphs/a.graph.json",
        "subgraphs/b.graph.json",
    }
    assert errors(snap.program) == []
    assert run(snap.program).verdict == "pass"


def test_new_target_reference_copied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = make_workspace(root)
    sub().write(ws, "subgraphs/a.graph.json")
    main(call("subgraphs/a.graph.json")).write(ws, TEST)
    write_target(ws, "targets/new.target.json")
    sub(use("targets/new.target.json")).write(ws, "subgraphs/a.graph.json")
    snap = snapshot(ws, tmp_path / "snap")
    assert {"targets/new.target.json", "targets/new.png"} <= files_under(snap.root)
    assert errors(snap.program) == []


def test_new_image_reference_copied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = make_workspace(root)
    write_target(ws, "targets/t.target.json")
    sub(use("targets/t.target.json")).write(ws, "subgraphs/a.graph.json")
    main(call("subgraphs/a.graph.json")).write(ws, TEST)
    # target이 새 이미지를 가리키도록 바뀜 (그래프 두 단계 아래 target의 이미지)
    write_json(ws, "targets/t.target.json", {"format": "kookabug.target/0", "image": "v2.png"})
    (root / "targets" / "v2.png").write_bytes(b"\x89PNG-v2")
    snap = snapshot(ws, tmp_path / "snap")
    assert "targets/v2.png" in files_under(snap.root)
    assert "targets/t.png" not in files_under(snap.root)
    assert errors(snap.program) == []


def test_reference_missing_in_original_is_validation_error_not_unstable(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = make_workspace(root)
    write_target(ws, "targets/noimg.target.json", create_image=False)
    sub(use("targets/none.target.json", "targets/noimg.target.json")).write(
        ws, "subgraphs/a.graph.json"
    )
    main(call("subgraphs/a.graph.json"), call("subgraphs/none.graph.json", "n_call2")).write(
        ws, TEST
    )
    snap = snapshot(ws, tmp_path / "snap")
    assert snap.attempts == 1
    assert snap.absent == {
        "subgraphs/none.graph.json",
        "targets/none.target.json",
        "targets/noimg.png",
    }
    codes = sorted(d.code for d in errors(snap.program))
    assert codes == ["call_target_missing", "target_invalid", "target_missing"]


def chain(ws: Workspace, depth: int) -> set[str]:
    """테스트 → c1 → … → c<depth>, 끝 서브그래프가 target(과 그 이미지)을 쓴다. 만든 파일."""
    write_target(ws, "targets/end.target.json")
    sub(use("targets/end.target.json")).write(ws, f"subgraphs/c{depth}.graph.json")
    for i in range(1, depth):
        sub(call(f"subgraphs/c{i + 1}.graph.json")).write(ws, f"subgraphs/c{i}.graph.json")
    main(call("subgraphs/c1.graph.json")).write(ws, TEST)
    return {
        WORKSPACE_FILE,
        TEST,
        "targets/end.target.json",
        "targets/end.png",
        *(f"subgraphs/c{i}.graph.json" for i in range(1, depth + 1)),
    }


@pytest.mark.parametrize("depth", [1, 8, 9, MAX_CALL_DEPTH])
def test_static_call_chain_depth(tmp_path: Path, depth: int) -> None:
    ws = make_workspace(tmp_path / "ws")
    expected = chain(ws, depth)
    snap = snapshot(ws, tmp_path / "snap")
    assert files_under(snap.root) == expected
    assert snap.attempts == 1 and snap.absent == set()
    assert errors(snap.program) == []
    result = run(snap.program)
    assert result.verdict == "pass"
    # 사슬 끝 스텝의 target도 스냅샷에서 읽은 것
    end = snap.program.graphs[f"subgraphs/c{depth}.graph.json"].nodes["n_use"]
    assert end.inputs["value"][0].path.is_relative_to(snap.root)


def test_call_chain_depth_17_is_call_depth_not_snapshot_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path / "ws")
    chain(ws, MAX_CALL_DEPTH + 1)
    snap = snapshot(ws, tmp_path / "snap")
    assert snap.attempts == 1
    assert [d.code for d in errors(snap.program)] == ["call_depth"]


def test_each_file_copied_once(tmp_path: Path) -> None:
    # 같은 서브그래프·target을 여러 곳에서 참조해도 파일마다 한 번만 복사한다
    ws = make_workspace(tmp_path / "ws")
    write_target(ws, "targets/t.target.json")
    sub(use("targets/t.target.json")).write(ws, "subgraphs/leaf.graph.json")
    for name in ("a", "b"):
        sub(call("subgraphs/leaf.graph.json"), use("targets/t.target.json", node="n_t")).write(
            ws, f"subgraphs/{name}.graph.json"
        )
    main(
        call("subgraphs/a.graph.json"),
        call("subgraphs/b.graph.json", "n_call2"),
        call("subgraphs/leaf.graph.json", "n_call3"),
        use("targets/t.target.json"),
    ).write(ws, TEST)
    copies: Counter[str] = Counter()
    snap = snapshot(ws, tmp_path / "snap", on_copy=lambda rel, _attempt: copies.update([rel]))
    assert set(copies) == files_under(snap.root)
    assert all(n == 1 for n in copies.values()), copies
    assert run(snap.program).verdict == "pass"


def test_original_changed_during_copy_restarts(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = basic_workspace(root)
    changed = root / "subgraphs" / "s1.graph.json"
    new_bytes = changed.read_bytes() + b"\n\n"
    attempts: list[int] = []

    def touch(rel: str, attempt: int) -> None:
        attempts.append(attempt)
        if rel == "subgraphs/s1.graph.json" and attempt == 1:
            changed.write_bytes(new_bytes)  # 복사한 직후 원본이 바뀜

    snap = snapshot(ws, tmp_path / "snap", on_copy=touch)
    assert snap.attempts == 2
    assert set(attempts) == {1, 2}
    assert (snap.root / "subgraphs" / "s1.graph.json").read_bytes() == new_bytes
    assert files_under(snap.root) == CLOSURE


def test_original_keeps_changing_gives_snapshot_unstable(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = basic_workspace(root)
    changed = root / "subgraphs" / "s2.graph.json"
    attempts: list[int] = []

    def touch(rel: str, attempt: int) -> None:
        if rel == "subgraphs/s2.graph.json":
            attempts.append(attempt)
            changed.write_bytes(changed.read_bytes() + b" ")

    with pytest.raises(SnapshotError) as info:
        snapshot(ws, tmp_path / "snap", on_copy=touch)
    assert info.value.code == "snapshot_unstable"
    # 처음 한 번 + 재시도 3번
    assert attempts == [1, 2, 3, 4]


def test_unstable_retry_limit_is_configurable(tmp_path: Path) -> None:
    ws = basic_workspace(tmp_path / "ws")
    changed = tmp_path / "ws" / TEST

    def touch(rel: str, attempt: int) -> None:
        if rel == TEST:
            changed.write_bytes(changed.read_bytes() + b" ")

    with pytest.raises(SnapshotError) as info:
        snapshot(ws, tmp_path / "snap", on_copy=touch, limits=SnapshotLimits(max_retries=0))
    assert info.value.code == "snapshot_unstable"


def test_resource_limit_gives_snapshot_too_large(tmp_path: Path) -> None:
    ws = basic_workspace(tmp_path / "ws")
    with pytest.raises(SnapshotError) as info:
        snapshot(ws, tmp_path / "snap1", limits=SnapshotLimits(max_files=len(CLOSURE) - 1))
    assert info.value.code == "snapshot_too_large"
    total = sum((tmp_path / "ws" / rel).stat().st_size for rel in CLOSURE)
    with pytest.raises(SnapshotError) as info:
        snapshot(ws, tmp_path / "snap2", limits=SnapshotLimits(max_bytes=total - 1))
    assert info.value.code == "snapshot_too_large"
    # 한도와 딱 맞으면 통과
    snap = snapshot(
        ws, tmp_path / "snap3", limits=SnapshotLimits(max_files=len(CLOSURE), max_bytes=total)
    )
    assert files_under(snap.root) == CLOSURE


PRIVATE_MARKER = b"LOCAL-PRIVATE-MARKER"


def private_workspace(root: Path) -> Workspace:
    """local.json에 개인 값이 있는 워크스페이스 (.kookabug/에 캐시 파일도 하나)."""
    ws = make_workspace(root, local={"private_value": PRIVATE_MARKER.decode()})
    (root / ".kookabug" / "cache.bin").write_bytes(PRIVATE_MARKER)
    return ws


def assert_private_not_copied(dest: Path) -> None:
    assert not (dest / LOCAL_FILE).exists()
    for path in dest.rglob("*"):
        if path.is_file():
            assert PRIVATE_MARKER not in path.read_bytes(), path


def image_pointing_at(ws: Workspace, image: str) -> None:
    write_json(ws, "targets/t.target.json", {"format": "kookabug.target/0", "image": image})
    main(use("targets/t.target.json")).write(ws, TEST)


def make_junction(link: Path, target: Path) -> None:
    import _winapi  # Windows 전용 (관리자 권한 없이 폴더 별칭)

    _winapi.CreateJunction(str(target), str(link))


@pytest.mark.parametrize(
    ("case", "image"),
    [
        ("image", "../.kookabug/local.json"),
        ("upper_case", "../.KOOKABUG/LOCAL.JSON"),
        ("cache_file", "../.kookabug/cache.bin"),
        ("junction", "priv/local.json"),
    ],
)
def test_private_file_referenced_by_target_image_not_copied(
    tmp_path: Path, case: str, image: str
) -> None:
    root = tmp_path / "ws"
    ws = private_workspace(root)
    if case == "junction":
        if sys.platform != "win32":
            pytest.skip("Windows junction")
        (root / "targets").mkdir()
        make_junction(root / "targets" / "priv", root / ".kookabug")
    image_pointing_at(ws, image)
    dest = tmp_path / "snap"
    with pytest.raises(SnapshotError) as info:
        snapshot(ws, dest)
    assert info.value.code == "snapshot_private_file"
    assert_private_not_copied(dest)


@pytest.mark.parametrize("private", [LOCAL_FILE, ".kookabug/cache.bin"])
def test_hard_link_to_private_file_is_not_blocked_by_design(tmp_path: Path, private: str) -> None:
    # 한계(설계 문서 5장): 차단은 경로 기준이다. 개인 폴더 파일의 하드 링크는 다른 경로의 일반
    # 파일로 보고 복사한다. 사용자가 일부러 만드는 것이고 보안 경계가 아니다
    root = tmp_path / "ws"
    ws = private_workspace(root)
    (root / "targets").mkdir()
    os.link(root / private, root / "targets" / "alias.png")
    image_pointing_at(ws, "alias.png")
    snap = snapshot(ws, tmp_path / "snap")
    assert errors(snap.program) == []
    assert (snap.root / "targets" / "alias.png").read_bytes() == (root / private).read_bytes()
    assert not (snap.root / LOCAL_FILE).exists()


@pytest.mark.parametrize("path", [LOCAL_FILE, ".KooKaBug/Local.json"])
def test_private_file_referenced_as_subgraph_not_copied(tmp_path: Path, path: str) -> None:
    ws = private_workspace(tmp_path / "ws")
    main(call(path)).write(ws, TEST)
    dest = tmp_path / "snap"
    with pytest.raises(SnapshotError) as info:
        snapshot(ws, dest)
    assert info.value.code == "snapshot_private_file"
    assert_private_not_copied(dest)


def test_settings_come_from_copied_workspace_json(tmp_path: Path) -> None:
    # 워크스페이스를 연 뒤 kookabug.json이 바뀌면 스냅샷 파일과 실행 설정 둘 다 새 값이다
    root = tmp_path / "ws"
    ws = make_workspace(root, settings={"v": "before"})
    main(("n_use", "core.var.set", {"name": "v", "value": setting("v")})).write(ws, TEST)
    write_json(ws, WORKSPACE_FILE, {"format": "kookabug.workspace/0", "settings": {"v": "after"}})
    snap = snapshot(ws, tmp_path / "snap")
    copied = json.loads((snap.root / WORKSPACE_FILE).read_text("utf-8"))
    assert copied["settings"]["v"] == "after"
    assert snap.program.graphs[TEST].nodes["n_use"].inputs["value"] == "after"
    assert snap.workspace.config == copied


def test_workspace_json_changed_during_copy_program_uses_copied_settings(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = make_workspace(root, settings={"v": "before"}, local={"w": "local-w"})
    main(
        ("n_use", "core.var.set", {"name": "v", "value": setting("v")}),
        ("n_w", "core.var.set", {"name": "w", "value": setting("w")}),
    ).write(ws, TEST)

    def change(rel: str, attempt: int) -> None:
        if rel == WORKSPACE_FILE and attempt == 1:
            write_json(
                ws,
                WORKSPACE_FILE,
                {"format": "kookabug.workspace/0", "settings": {"v": "changed-after-copy"}},
            )

    snap = snapshot(ws, tmp_path / "snap", on_copy=change)
    assert snap.attempts == 2
    copied = json.loads((snap.root / WORKSPACE_FILE).read_text("utf-8"))
    nodes = snap.program.graphs[TEST].nodes
    assert nodes["n_use"].inputs["value"] == copied["settings"]["v"] == "changed-after-copy"
    # local.json은 복사하지 않고 원래 워크스페이스에서 읽은 값을 쓴다
    assert nodes["n_w"].inputs["value"] == "local-w"
    assert not (snap.root / LOCAL_FILE).exists()


def test_previous_contents_of_destination_removed(tmp_path: Path) -> None:
    # 남아 있던 파일을 스냅샷에서 읽으면 원본에 없는 참조가 살아난다
    ws = make_workspace(tmp_path / "ws")
    main(call("subgraphs/gone.graph.json")).write(ws, TEST)
    dest = tmp_path / "snap"
    sub().write(dest, "subgraphs/gone.graph.json")
    snap = snapshot(ws, dest)
    assert files_under(snap.root) == {WORKSPACE_FILE, TEST}
    assert [d.code for d in errors(snap.program)] == ["call_target_missing"]


def test_step_end_graph_path_points_into_snapshot(tmp_path: Path) -> None:
    ws = basic_workspace(tmp_path / "ws")
    folder = create_run_folder(tmp_path / "runs", TEST)
    snap = snapshot(ws, folder.snapshot)
    result = run(snap.program)
    graphs = [e["graph"] for e in result.events if e["event"] == "step.end" and "graph" in e]
    assert graphs == ["snapshot/subgraphs/s2.graph.json", "snapshot/subgraphs/s1.graph.json"]
    for graph in graphs:
        assert (folder.path / graph).is_file()
    # 접두를 주지 않으면 M0a와 같은 워크스페이스 기준 경로
    plain = run(snap.program, prefix="")
    assert [e["graph"] for e in plain.events if "graph" in e and e["event"] == "step.end"] == [
        "subgraphs/s2.graph.json",
        "subgraphs/s1.graph.json",
    ]

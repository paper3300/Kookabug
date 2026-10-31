"""그래프 메서드 (M2 계획 2.4·2.6·2.7, T4): 열기·검증·저장·만들기·닫기, 외부 변경, 경로 검사."""

from __future__ import annotations

import _winapi
import hashlib
import json
import os
import queue
import shutil
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from helpers.corpus import CORPUS_DIR, SAMPLE_WORKSPACE, corpus_files, corpus_id, through_js

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_core import documents
from kookabug_core.canonical import canonical_dumps, is_canonical, json_equal, loads_strict
from kookabug_core.validate import check_graph, check_graph_value
from kookabug_core.workspace import Workspace
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.documents import read_graph
from kookabug_daemon.protocol import INVALID_PARAMS, PARSE_ERROR

pytestmark = pytest.mark.process

FILES = corpus_files()
INVENTORY = "tests/inventory_open.graph.json"
ENTER_WORLD = "subgraphs/enter_world.graph.json"
NUMBERS = "tests/corpus/numbers.graph.json"
OLD_NS = 1_600_000_000 * 10**9


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corpus_rel(path: Path) -> str:
    """말뭉치 파일의 워크스페이스 경로 (예제 워크스페이스 파일은 제자리, 나머지 `tests/corpus/`)."""
    if path.is_relative_to(SAMPLE_WORKSPACE):
        return path.relative_to(SAMPLE_WORKSPACE).as_posix()
    return f"tests/corpus/{path.name}"


def make_ws(dest: Path) -> Path:
    root = copy_sample_workspace(dest)
    (root / "tests" / "corpus").mkdir()
    for path in CORPUS_DIR.glob("*.graph.json"):
        shutil.copyfile(path, root / "tests" / "corpus" / path.name)
    return root


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return make_ws(tmp_path / "ws")


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def failure(exc: pytest.ExceptionInfo[DaemonError]) -> dict[str, Any]:
    assert exc.value.kind is not None, exc.value
    return exc.value.data


def stamp(path: Path) -> int:
    os.utime(path, ns=(OLD_NS, OLD_NS))
    return path.stat().st_mtime_ns


def wait_notification(
    client: DaemonClient, method: str, match: Any = None, timeout: float = 5.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"{timeout}초 안에 {method} 알림이 오지 않았다")
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            continue
        if message["method"] == method and (match is None or match(message["params"])):
            return message["params"]


def drain(client: DaemonClient, method: str, seconds: float) -> list[dict[str, Any]]:
    """`seconds` 동안 받은 그 알림 전부."""
    found: list[dict[str, Any]] = []
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message["method"] == method:
            found.append(message["params"])
    return found


# ---------------------------------------------------------------- 열기


def test_open_returns_value_revision_shapes_diagnostics(ws: Path, daemon: ThreadDaemon) -> None:
    data = (ws / INVENTORY).read_bytes()
    text = data.decode("utf-8")
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": INVENTORY})
    assert opened["doc_id"]
    assert opened["revision"] == sha(data)
    assert json_equal(opened["value"], loads_strict(text))
    assert opened["canonical"] is is_canonical(text)
    _, expected = check_graph(Workspace.open(ws), INVENTORY)
    assert opened["diagnostics"] == [d.to_dict() for d in expected]
    shapes = opened["shapes"]
    assert set(shapes) == set(loads_strict(text)["nodes"])
    call_exits = [e["name"] for e in shapes["n_enter_world"]["exits"]]
    assert set(call_exits) == {"success", "maintenance", "login_failed"}  # FromInterface
    assert all(s["unknown"] is False for s in shapes.values())
    assert (ws / INVENTORY).read_bytes() == data  # 열기는 쓰지 않는다


def test_open_invalid_json_error_with_position(ws: Path, daemon: ThreadDaemon) -> None:
    (ws / "tests" / "bad.graph.json").write_bytes(
        b'{\n  "format": "kookabug.graph/0",\n  "kind": test\n}\n'
    )
    (ws / "tests" / "bom.graph.json").write_bytes(b"\xef\xbb\xbf{}")
    (ws / "tests" / "array.graph.json").write_bytes(b"[]\n")
    with daemon.client() as client:
        with pytest.raises(DaemonError) as exc:
            client.call("graph.open", {"path": "tests/array.graph.json"})
        assert failure(exc) | {"message": ""} == {
            "code": "invalid_json",
            "message": "",
            "line": None,
            "column": None,
        }
        with pytest.raises(DaemonError) as exc:
            client.call("graph.open", {"path": "tests/bad.graph.json"})
        data = failure(exc)
        assert data["code"] == "invalid_json"
        assert (data["line"], data["column"]) == (3, 11)
        assert data["message"]
        with pytest.raises(DaemonError) as exc:
            client.call("graph.open", {"path": "tests/bom.graph.json"})
        assert failure(exc) | {"message": ""} == {
            "code": "invalid_json",
            "message": "",
            "line": 1,
            "column": 1,
        }
        with pytest.raises(DaemonError) as exc:
            client.call("graph.open", {"path": "tests/none.graph.json"})
        assert failure(exc) == {"code": "not_found", "path": "tests/none.graph.json"}
    assert len(daemon.daemon.documents) == 0  # 실패한 열기는 문서를 남기지 않는다


# ---------------------------------------------------------------- 저장


@pytest.fixture(scope="module")
def corpus_daemon(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ThreadDaemon]:
    root = make_ws(tmp_path_factory.mktemp("corpus") / "ws")
    with ThreadDaemon(root) as d:
        yield d


@pytest.mark.parametrize("path", FILES, ids=[corpus_id(p) for p in FILES])
def test_unmodified_save_bytes_identical_via_daemon(
    path: Path, corpus_daemon: ThreadDaemon
) -> None:
    rel = corpus_rel(path)
    target = corpus_daemon.root / rel
    before = target.read_bytes()
    assert before == path.read_bytes()
    mtime = stamp(target)
    with corpus_daemon.client() as client:
        opened = client.call("graph.open", {"path": rel})
        assert opened["revision"] == sha(before)
        saved = client.call(
            "graph.save",
            {
                "doc_id": opened["doc_id"],
                "value": opened["value"],
                "base_revision": opened["revision"],
            },
        )
        client.call("graph.close", {"doc_id": opened["doc_id"]})
    assert (saved["wrote"], saved["canonicalized"], saved["revision"]) == (
        False,
        False,
        sha(before),
    )
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == mtime


def test_unmodified_save_mtime_unchanged_via_daemon(ws: Path, daemon: ThreadDaemon) -> None:
    target = ws / "tests" / "corpus" / "crlf.graph.json"
    before = target.read_bytes()
    assert b"\r\n" in before
    mtime = stamp(target)
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": "tests/corpus/crlf.graph.json"})
        for _ in range(2):
            saved = client.call(
                "graph.save",
                {
                    "doc_id": opened["doc_id"],
                    "value": opened["value"],
                    "base_revision": opened["revision"],
                },
            )
            assert saved["wrote"] is False
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == mtime


def test_save_after_edit_semantics_preserved(ws: Path, daemon: ThreadDaemon) -> None:
    for rel in ("tests/corpus/unknown-node.graph.json", "tests/corpus/unknown-keys.graph.json"):
        original = loads_strict((ws / rel).read_text(encoding="utf-8"))
        with daemon.client() as client:
            opened = client.call("graph.open", {"path": rel})
            value = opened["value"]
            first = sorted(value["nodes"])[0]
            value["nodes"][first]["title"] = "편집한 제목"
            saved = client.call(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
            assert saved["wrote"] is True
            assert saved["revision"] == sha((ws / rel).read_bytes())
            reopened = client.call("graph.open", {"path": rel})
            assert reopened["doc_id"] == opened["doc_id"]  # 경로당 문서 하나
            assert reopened["revision"] == saved["revision"]
        back = loads_strict((ws / rel).read_text(encoding="utf-8"))
        assert back["nodes"][first]["title"] == "편집한 제목"
        assert set(back["nodes"]) == set(original["nodes"])  # 노드 ID 그대로
        expected = json.loads(json.dumps(original))
        expected["nodes"][first]["title"] = "편집한 제목"
        assert json_equal(back, expected)  # 모르는 노드 설정·모르는 키 보존
        for node_id, node in original["nodes"].items():
            if node_id != first:
                assert json_equal(back["nodes"][node_id], node)


def test_save_conflict_after_external_edit(ws: Path, daemon: ThreadDaemon) -> None:
    target = ws / INVENTORY
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": INVENTORY})
        changed = target.read_bytes().replace(b"\n", b"\r\n")
        target.write_bytes(changed)
        value = opened["value"]
        value["meta"] = {"title": "내 편집"}
        with pytest.raises(DaemonError) as exc:
            client.call(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
    assert failure(exc) == {"code": "revision_conflict", "revision": sha(changed)}
    assert target.read_bytes() == changed


def test_graph_changed_notification_on_external_edit(ws: Path, daemon: ThreadDaemon) -> None:
    target = ws / INVENTORY
    with daemon.client() as client, daemon.client() as other:
        opened = client.call("graph.open", {"path": INVENTORY})
        doc_id = opened["doc_id"]
        changed = target.read_bytes() + b"\n"
        target.write_bytes(changed)
        params = wait_notification(client, "graph.changed", lambda p: p["doc_id"] == doc_id)
        assert params == {"doc_id": doc_id, "revision": sha(changed)}
        # 같은 revision은 한 번만, 문서를 열지 않은 연결에는 보내지 않는다
        assert drain(client, "graph.changed", 2.5) == []
        assert drain(other, "graph.changed", 0.1) == []

        # 다시 열면(조용한 다시 열기) 문서가 디스크 revision이 된다. 자기 저장은 알리지 않는다
        reopened = client.call("graph.open", {"path": INVENTORY})
        value = reopened["value"]
        value["meta"] = {"title": "daemon 저장"}
        saved = client.call(
            "graph.save", {"doc_id": doc_id, "value": value, "base_revision": reopened["revision"]}
        )
        assert saved["wrote"] is True
        assert drain(client, "graph.changed", 2.5) == []

        target.unlink()
        params = wait_notification(client, "graph.changed", lambda p: p["doc_id"] == doc_id)
        assert params == {"doc_id": doc_id, "revision": None}


def test_force_reverted_buffer_writes_via_daemon(ws: Path, daemon: ThreadDaemon) -> None:
    # 검수 M1: A를 연 뒤 디스크가 B, 버퍼를 A로 되돌려 force → 디스크가 A 바이트
    target = ws / INVENTORY
    a = target.read_bytes()
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": INVENTORY})
        b = canonical_dumps({**loads_strict(a.decode("utf-8")), "meta": {"title": "B"}})
        target.write_bytes(b.encode("utf-8"))
        saved = client.call(
            "graph.save",
            {
                "doc_id": opened["doc_id"],
                "value": opened["value"],
                "base_revision": opened["revision"],
                "force": True,
            },
        )
    assert saved["wrote"] is True
    assert saved["revision"] == sha(a)
    assert target.read_bytes() == a


def test_concurrent_saves_same_doc_serialized(ws: Path, daemon: ThreadDaemon) -> None:
    # 같은 문서 저장 직렬화: 같은 기준 revision으로 동시에 저장하면 하나만 쓰고 하나는 충돌
    target = ws / INVENTORY
    with daemon.client() as first, daemon.client() as second:
        opened = first.call("graph.open", {"path": INVENTORY})
        futures: list[Future[Any]] = []
        for client, title in ((first, "첫째"), (second, "둘째")):
            value = json.loads(json.dumps(opened["value"]))
            value["meta"] = {"title": title}
            futures.append(
                client.request(
                    "graph.save",
                    {
                        "doc_id": opened["doc_id"],
                        "value": value,
                        "base_revision": opened["revision"],
                    },
                )
            )
        outcomes: list[Any] = []
        for future in futures:
            try:
                outcomes.append(future.result(30))
            except DaemonError as exc:
                outcomes.append(exc.kind)
    saved = [o for o in outcomes if isinstance(o, dict)]
    assert len(saved) == 1 and outcomes.count("revision_conflict") == 1
    assert saved[0]["revision"] == sha(target.read_bytes())


def test_big_floats_via_wire_codec_save(ws: Path, daemon: ThreadDaemon) -> None:
    # 검수 H1: Node 전송 코덱(wireStringify)으로 만든 요청 텍스트를 WebSocket으로 그대로 보낸다
    target = ws / NUMBERS
    before = target.read_bytes()
    mtime = stamp(target)

    def send(client: DaemonClient, request_id: int, method: str, params: Any) -> dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        [wire] = through_js([json.dumps(request)])
        client.send_text(wire["ok"])
        response = client.next_unmatched(timeout=30)
        assert response["id"] == request_id, response
        return response

    with daemon.client() as client:
        opened = client.call("graph.open", {"path": NUMBERS})
        doc_id, revision = opened["doc_id"], opened["revision"]
        response = send(
            client,
            1_000_001,
            "graph.save",
            {"doc_id": doc_id, "value": opened["value"], "base_revision": revision},
        )
        assert response["result"]["wrote"] is False
        assert target.read_bytes() == before
        assert target.stat().st_mtime_ns == mtime

        value = opened["value"]
        value["nodes"]["n_sink"]["title"] = "옆 필드만 고침"
        response = send(
            client,
            1_000_002,
            "graph.save",
            {"doc_id": doc_id, "value": value, "base_revision": revision},
        )
        assert response["result"]["wrote"] is True
    text = target.read_text(encoding="utf-8")
    for token in (
        '"big": 1e+20',
        '"two_53_float": 9.007199254740992e+15',
        "1.2345678901234567e+19",
    ):
        assert token in text
    sink = loads_strict(text)["nodes"]["n_sink"]["in"]
    for name in ("big", "big_plus", "big_upper", "two_53_float", "big_digits"):
        assert isinstance(sink[name], float), name

    # 코덱 없이 JSON.stringify로 보내면 범위 밖 정수 토큰이라 읽지 않는다 (parse_error 뒤 닫음)
    saved = target.read_bytes()
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": NUMBERS})
        request = {
            "jsonrpc": "2.0",
            "id": 1_000_003,
            "method": "graph.save",
            "params": {
                "doc_id": opened["doc_id"],
                "value": opened["value"],
                "base_revision": opened["revision"],
            },
        }
        [plain] = through_js([json.dumps(request)], mode="json")
        client.send_text(plain["ok"])
        response = client.next_unmatched(timeout=30)
        assert response["error"]["code"] == PARSE_ERROR
        assert client.wait_closed() == 1007
    assert target.read_bytes() == saved


def test_real_out_of_range_int_rejected_no_write(ws: Path, daemon: ThreadDaemon) -> None:
    # 실제 범위 밖 정수(Python int)는 봉투 값 검사에서 거부된다. 저장까지 가지 않고 파일은 그대로
    target = ws / INVENTORY
    before = target.read_bytes()
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": INVENTORY})
        request = {
            "jsonrpc": "2.0",
            "id": 1_000_010,
            "method": "graph.save",
            "params": {
                "doc_id": opened["doc_id"],
                "value": {**opened["value"], "meta": {"n": 2**53}},
                "base_revision": opened["revision"],
            },
        }
        client.send_text(json.dumps(request))
        assert client.next_unmatched(timeout=30)["error"]["code"] == PARSE_ERROR
    assert target.read_bytes() == before


# ---------------------------------------------------------------- daemon 교체


def test_reopen_after_daemon_restart_same_path_new_doc_id(ws: Path) -> None:
    # 검수 M4: 새 daemon에 graph.open → 새 doc_id, 옛 doc_id는 doc_not_open,
    # 옛 revision으로 저장하면 디스크가 같을 때 성공
    with ThreadDaemon(ws) as first, first.client() as client:
        old = client.call("graph.open", {"path": INVENTORY})
        start_id = first.session.start_id
    with ThreadDaemon(ws) as second, second.client() as client:
        assert second.session.start_id != start_id
        with pytest.raises(DaemonError) as exc:
            client.call(
                "graph.save",
                {"doc_id": old["doc_id"], "value": old["value"], "base_revision": old["revision"]},
            )
        assert failure(exc) == {"code": "doc_not_open", "revision": None}
        new = client.call("graph.open", {"path": INVENTORY})
        assert new["doc_id"] != old["doc_id"]
        assert new["revision"] == old["revision"]
        value = old["value"]
        value["meta"] = {"title": "dirty 버퍼"}
        saved = client.call(
            "graph.save",
            {"doc_id": new["doc_id"], "value": value, "base_revision": old["revision"]},
        )
        assert saved["wrote"] is True


# ---------------------------------------------------------------- 검증


def test_validate_uses_buffer_and_seq_echo(ws: Path, daemon: ThreadDaemon) -> None:
    before = (ws / INVENTORY).read_bytes()
    with daemon.client() as client:
        opened = client.call("graph.open", {"path": INVENTORY})
        value = opened["value"]
        del value["nodes"]["n_check_inventory"]
        checked = client.call(
            "graph.validate", {"doc_id": opened["doc_id"], "value": value, "seq": 7}
        )
        assert checked["seq"] == 7
        _, expected = check_graph_value(Workspace.open(ws), INVENTORY, value)
        assert checked["diagnostics"] == [d.to_dict() for d in expected]
        assert checked["diagnostics"] != opened["diagnostics"]
        assert any(d["node"] == "n_press_i" for d in checked["diagnostics"])
        assert "n_check_inventory" not in checked["shapes"]

        # 정수값 실수 seq(Python 클라이언트)도 정수로 돌려준다
        again = client.call(
            "graph.validate", {"doc_id": opened["doc_id"], "value": opened["value"], "seq": 8.0}
        )
        assert again["seq"] == 8 and type(again["seq"]) is int
    assert (ws / INVENTORY).read_bytes() == before


def test_validate_after_subgraph_save_changes_call_exits(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client() as client:
        test_doc = client.call("graph.open", {"path": INVENTORY})
        sub = client.call("graph.open", {"path": ENTER_WORLD})

        def call_exits(seq: int) -> set[str]:
            checked = client.call(
                "graph.validate",
                {"doc_id": test_doc["doc_id"], "value": test_doc["value"], "seq": seq},
            )
            return {e["name"] for e in checked["shapes"]["n_enter_world"]["exits"]}

        assert "timeout" not in call_exits(1)
        value = sub["value"]
        value["interface"]["exits"]["timeout"] = {"kind": "fail"}
        client.call(
            "graph.save",
            {"doc_id": sub["doc_id"], "value": value, "base_revision": sub["revision"]},
        )
        assert "timeout" in call_exits(2)


# ---------------------------------------------------------------- 만들기·닫기


def test_create_exists_refused(ws: Path, daemon: ThreadDaemon) -> None:
    rel = "tests/flows/new_flow.graph.json"
    with daemon.client() as client:
        created = client.call("graph.create", {"path": rel, "kind": "test", "title": "새 흐름"})
        data = (ws / rel).read_bytes()
        assert data.decode("utf-8") == canonical_dumps(documents.template("test", "새 흐름"))
        assert created["revision"] == sha(data)
        assert created["canonical"] is True
        assert not [d for d in created["diagnostics"] if d["severity"] == "error"]
        assert set(created["shapes"]) == {"n_entry"}

        sub = client.call(
            "graph.create", {"path": "subgraphs/new_sub.graph.json", "kind": "subgraph"}
        )
        assert {e["name"] for e in sub["shapes"]["n_exit"]["exits"]} == set()
        assert "interface" in sub["value"]

        stamp(ws / rel)
        mtime = (ws / rel).stat().st_mtime_ns
        with pytest.raises(DaemonError) as exc:
            client.call("graph.create", {"path": rel, "kind": "subgraph"})
        assert failure(exc) == {"code": "exists", "revision": sha(data)}
        with pytest.raises(DaemonError) as exc:
            client.call("graph.create", {"path": INVENTORY, "kind": "test"})
        assert failure(exc)["code"] == "exists"
    assert (ws / rel).read_bytes() == data
    assert (ws / rel).stat().st_mtime_ns == mtime


def test_close_and_disconnect_release_documents(ws: Path, daemon: ThreadDaemon) -> None:
    table = daemon.daemon.documents
    with daemon.client() as first:
        with daemon.client() as second:
            a = first.call("graph.open", {"path": INVENTORY})
            b = second.call("graph.open", {"path": INVENTORY})
            assert a["doc_id"] == b["doc_id"]  # 연결과 무관하게 경로당 문서 하나
            first.call("graph.open", {"path": ENTER_WORLD})
            assert len(table) == 2
            first.call("graph.close", {"doc_id": a["doc_id"]})
            with pytest.raises(DaemonError) as exc:
                first.call("graph.close", {"doc_id": a["doc_id"]})  # 이 연결은 더 쥐지 않음
            assert failure(exc)["code"] == "doc_not_open"
            assert len(table) == 2  # 두 번째 연결이 아직 연다
            second.call("graph.validate", {"doc_id": a["doc_id"], "value": a["value"], "seq": 0})
        deadline = time.monotonic() + 5
        while len(table) != 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(table) == 1  # 끊긴 연결의 참조가 풀렸다
    deadline = time.monotonic() + 5
    while len(table) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(table) == 0


# ---------------------------------------------------------------- 경로


def junction(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def test_path_outside_and_private_refused(ws: Path, tmp_path: Path, daemon: ThreadDaemon) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.graph.json").write_bytes((ws / INVENTORY).read_bytes())
    (ws / ".kookabug").mkdir(exist_ok=True)
    (ws / ".kookabug" / "x.graph.json").write_bytes((ws / INVENTORY).read_bytes())
    junction(ws / "tests" / "out", outside)
    junction(ws / "tests" / "priv", ws / ".kookabug")
    before = {p: p.read_bytes() for p in (outside / "x.graph.json", ws / "kookabug.json")}

    refused = {
        "../outside/x.graph.json": "path_outside_workspace",
        "tests/../../outside/x.graph.json": "path_outside_workspace",
        f"{outside.as_posix()}/x.graph.json": "path_outside_workspace",
        "/tests/inventory_open.graph.json": "path_outside_workspace",
        "tests\\inventory_open.graph.json": "path_outside_workspace",
        "tests//inventory_open.graph.json": "path_outside_workspace",
        "./tests/inventory_open.graph.json": "path_outside_workspace",
        "tests/out/x.graph.json": "path_outside_workspace",
        ".kookabug/x.graph.json": "private_path",
        ".KOOKABUG/x.graph.json": "private_path",
        "tests/priv/x.graph.json": "private_path",
    }
    with daemon.client() as client:
        for path, code in refused.items():
            for method, params in (
                ("graph.open", {"path": path}),
                ("graph.create", {"path": path, "kind": "test"}),
            ):
                with pytest.raises(DaemonError) as exc:
                    client.call(method, params)
                assert failure(exc) == {"code": code, "path": path}, (method, path)
        # 그래프가 아닌 파일(팀 정책 kookabug.json 등)은 그래프 메서드로 열거나 만들 수 없다
        for path in ("kookabug.json", "tests/notes.txt"):
            with pytest.raises(DaemonError) as exc:
                client.call("graph.open", {"path": path})
            assert exc.value.code == INVALID_PARAMS
            with pytest.raises(DaemonError) as exc:
                client.call("graph.create", {"path": path, "kind": "test"})
            assert exc.value.code == INVALID_PARAMS
        # 그래프 이름의 링크가 그래프가 아닌 파일을 가리켜도 거부 (심볼릭 링크 권한이 있을 때)
        try:
            os.symlink(ws / "kookabug.json", ws / "tests" / "team.graph.json")
        except OSError:
            pass
        else:
            with pytest.raises(DaemonError) as exc:
                client.call("graph.open", {"path": "tests/team.graph.json"})
            assert exc.value.code == INVALID_PARAMS
    assert {p: p.read_bytes() for p in before} == before
    assert not (ws / "tests" / "notes.txt").exists()
    assert sorted(p.name for p in outside.iterdir()) == ["x.graph.json"]
    assert len(daemon.daemon.documents) == 0


def test_mapping_error_fields_match_contract() -> None:
    # 코어 문서 오류 → daemon 오류 data (종류별 필드)
    from kookabug_daemon.documents import document_failed

    err = documents.DocumentError("io_error", "쓸 수 없다")
    assert document_failed(err, "tests/a.graph.json").error()["data"] == {
        "code": "io_error",
        "message": "쓸 수 없다",
    }
    err = documents.DocumentError("exists", "있다", revision=None)
    assert document_failed(err, "x").error()["data"] == {"code": "exists", "revision": None}


# ---------------------------------------------------------------- 여러 연결·수명 (검수 T4_1)


def wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("조건 대기 시간 초과")
        time.sleep(0.01)


def test_other_open_does_not_replace_force_original(ws: Path, daemon: ThreadDaemon) -> None:
    # 다른 연결이 디스크(같은 값·다른 들여쓰기 B)를 읽어도 첫 연결의 force 저장은 그 연결이 본 A로
    target = ws / INVENTORY
    a = target.read_bytes()
    with daemon.client() as first, daemon.client() as second:
        opened = first.call("graph.open", {"path": INVENTORY})
        b = json.dumps(opened["value"], indent=4, ensure_ascii=False).encode("utf-8")
        assert b != a
        target.write_bytes(b)
        other = second.call("graph.open", {"path": INVENTORY})
        assert other["doc_id"] == opened["doc_id"] and other["revision"] == sha(b)
        saved = first.call(
            "graph.save",
            {
                "doc_id": opened["doc_id"],
                "value": opened["value"],
                "base_revision": opened["revision"],
                "force": True,
            },
        )
        assert (saved["wrote"], saved["revision"]) == (True, sha(a))
        assert target.read_bytes() == a
        # 둘째 연결의 기준은 B다: 같은 값을 force로 저장하면 B 바이트로 돌아간다
        saved = second.call(
            "graph.save",
            {
                "doc_id": other["doc_id"],
                "value": other["value"],
                "base_revision": other["revision"],
                "force": True,
            },
        )
        assert saved["wrote"] is True
    assert target.read_bytes() == b


def test_other_holder_receives_daemon_save_change(ws: Path) -> None:
    # 두 연결이 같은 문서를 연 채 첫 연결이 저장 → 둘째 연결만 graph.changed를 받는다
    with ThreadDaemon(ws, watch_interval_s=0.05) as d, d.client() as first, d.client() as second:
        opened = first.call("graph.open", {"path": INVENTORY})
        second.call("graph.open", {"path": INVENTORY})
        time.sleep(0.2)
        value = opened["value"]
        value["meta"] = {"title": "첫 연결 저장"}
        saved = first.call(
            "graph.save",
            {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
        )
        params = wait_notification(second, "graph.changed", timeout=3.0)
        assert params == {"doc_id": opened["doc_id"], "revision": saved["revision"]}
        assert drain(first, "graph.changed", 0.5) == []  # 자기 저장은 알리지 않는다
        assert drain(second, "graph.changed", 0.5) == []  # 같은 revision은 한 번만


def test_save_rechecks_replaced_parent_junction(ws: Path, tmp_path: Path) -> None:
    # 연 뒤에 부모 폴더가 루트 밖을 가리키는 정션으로 바뀌면 검증·저장을 쓰기 전에 거부한다
    folder = ws / "tests" / "movable"
    folder.mkdir()
    initial = (ws / INVENTORY).read_bytes()
    (folder / "a.graph.json").write_bytes(initial)
    outside = tmp_path / "outside"
    outside.mkdir()
    foreign = outside / "a.graph.json"
    foreign.write_bytes(initial)
    rel = "tests/movable/a.graph.json"
    with ThreadDaemon(ws, watch_interval_s=0.05) as d, d.client() as client:
        opened = client.call("graph.open", {"path": rel})
        folder.rename(ws / "tests" / "moved")
        _winapi.CreateJunction(str(outside), str(folder))
        value = opened["value"]
        value["meta"] = {"title": "루트 밖 쓰기"}
        for method, params in (
            ("graph.save", {"base_revision": opened["revision"]}),
            ("graph.save", {"base_revision": opened["revision"], "force": True}),
            ("graph.validate", {"seq": 1}),
        ):
            with pytest.raises(DaemonError) as exc:
                client.call(method, {"doc_id": opened["doc_id"], "value": value, **params})
            assert failure(exc) == {"code": "path_outside_workspace", "path": rel}
        # 감시는 그 문서가 없어진 것으로 알린다 (밖의 파일 revision을 내지 않는다)
        changed = wait_notification(client, "graph.changed", timeout=3.0)
        assert changed == {"doc_id": opened["doc_id"], "revision": None}

        # 루트 안의 다른 파일로 바뀌어도 그 문서로는 쓰지 않는다
        os.rmdir(folder)  # 정션만 지운다
        other = ws / "tests" / "other"
        other.mkdir()
        (other / "a.graph.json").write_bytes(initial)
        _winapi.CreateJunction(str(other), str(folder))
        with pytest.raises(DaemonError) as exc:
            client.call(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
        assert failure(exc)["code"] == "not_found"
    assert foreign.read_bytes() == initial
    assert (other / "a.graph.json").read_bytes() == initial
    assert (ws / "tests" / "moved" / "a.graph.json").read_bytes() == initial


def test_disconnect_while_open_does_not_register(
    ws: Path, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 연결이 끊긴 뒤에 끝난 열기는 그 연결의 참조를 남기지 않는다
    table = daemon.daemon.documents
    started, release, done = threading.Event(), threading.Event(), threading.Event()
    real_open = table.open

    def delayed_open(*args: Any, **kwargs: Any) -> Any:
        started.set()
        try:
            assert release.wait(10)
            return real_open(*args, **kwargs)
        finally:
            done.set()

    monkeypatch.setattr(table, "open", delayed_open)
    client = daemon.client()
    try:
        client.request("graph.open", {"path": INVENTORY})
        assert started.wait(5)
        client.close()
        wait_for(lambda: daemon.call_in_loop(daemon.daemon.transport.count) == 0)
    finally:
        release.set()
    assert done.wait(5)
    assert len(table) == 0


def test_disconnect_mid_save_keeps_path_serialized(
    ws: Path, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 끊긴 연결의 저장이 쓰기 도중이면, 새 연결의 열기·저장은 그 쓰기가 끝날 때까지 기다린다.
    # 그래서 성공으로 답한 저장이 뒤에 끝난 옛 쓰기에 덮이지 않는다
    target = ws / INVENTORY
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    real_write = documents.write_atomic

    def delayed_write(path: Path, data: bytes) -> None:
        if b'"title": "first-save"' not in data:
            return real_write(path, data)
        entered.set()
        try:
            assert release.wait(10)
            return real_write(path, data)
        finally:
            done.set()

    monkeypatch.setattr(documents, "write_atomic", delayed_write)
    first = daemon.client()
    try:
        opened = first.call("graph.open", {"path": INVENTORY})
        original = opened["revision"]
        opened["value"]["meta"] = {"title": "first-save"}
        first.request(
            "graph.save",
            {"doc_id": opened["doc_id"], "value": opened["value"], "base_revision": original},
        )
        assert entered.wait(5)
        first.close()
        wait_for(lambda: daemon.call_in_loop(daemon.daemon.transport.count) == 0)
        assert len(daemon.daemon.documents) == 0  # 항목은 풀렸지만 경로 잠금은 쓰기가 쥐고 있다
        with daemon.client() as second:
            value = json.loads(json.dumps(opened["value"]))
            value["meta"] = {"title": "second-save"}
            pending_open = second.request("graph.open", {"path": INVENTORY})
            time.sleep(0.5)
            assert not pending_open.done()  # 옛 쓰기가 끝나기 전에는 읽지 않는다
            release.set()
            assert done.wait(5)
            reopened = pending_open.result(30)
            assert reopened["doc_id"] != opened["doc_id"]
            first_saved = target.read_bytes()
            assert reopened["revision"] == sha(first_saved) != original
            # 옛 revision 기준 저장은 충돌, 새 기준이면 쓴다. 답한 저장이 마지막 바이트다
            with pytest.raises(DaemonError) as exc:
                second.call(
                    "graph.save",
                    {"doc_id": reopened["doc_id"], "value": value, "base_revision": original},
                )
            assert failure(exc) == {"code": "revision_conflict", "revision": sha(first_saved)}
            saved = second.call(
                "graph.save",
                {
                    "doc_id": reopened["doc_id"],
                    "value": value,
                    "base_revision": reopened["revision"],
                },
            )
            assert saved["wrote"] is True
            assert saved["revision"] == sha(target.read_bytes())
    finally:
        release.set()
        first.close()
    assert loads_strict(target.read_text(encoding="utf-8"))["meta"]["title"] == "second-save"


def test_save_waits_for_in_flight_write_of_closed_connection(
    ws: Path, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 반례와 같은 순서(같은 기준 revision으로 새 연결이 저장)는 옛 쓰기가 끝난 뒤 충돌이 된다
    target = ws / INVENTORY
    entered, release = threading.Event(), threading.Event()
    real_write = documents.write_atomic

    def delayed_write(path: Path, data: bytes) -> None:
        if b'"title": "first-save"' in data:
            entered.set()
            assert release.wait(10)
        return real_write(path, data)

    monkeypatch.setattr(documents, "write_atomic", delayed_write)
    with daemon.client() as second:
        new = second.call("graph.open", {"path": INVENTORY})
        first = daemon.client()
        try:
            opened = first.call("graph.open", {"path": INVENTORY})
            value = opened["value"]
            value["meta"] = {"title": "first-save"}
            first.request(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
            assert entered.wait(5)
            first.close()
            mine = json.loads(json.dumps(new["value"]))
            mine["meta"] = {"title": "second-save"}
            pending = second.request(
                "graph.save",
                {"doc_id": new["doc_id"], "value": mine, "base_revision": new["revision"]},
            )
            time.sleep(0.5)
            assert not pending.done()  # 같은 경로 잠금을 기다린다
            release.set()
            with pytest.raises(DaemonError) as exc:
                pending.result(30)
            assert exc.value.kind == "revision_conflict"
        finally:
            release.set()
            first.close()
    assert loads_strict(target.read_text(encoding="utf-8"))["meta"]["title"] == "first-save"


# ---------------------------------------------------------------- 잠금 뒤 경로 재검사 (검수 T4_2)


def movable_with_outside(ws: Path, tmp_path: Path) -> tuple[Path, Path]:
    """`tests/movable/a.graph.json`과 같은 이름의 루트 밖 파일(제목 `outside-only-marker`)."""
    folder = ws / "tests" / "movable"
    folder.mkdir()
    (folder / "a.graph.json").write_bytes((ws / INVENTORY).read_bytes())
    outside = tmp_path / "outside"
    outside.mkdir()
    external = loads_strict((ws / INVENTORY).read_text(encoding="utf-8"))
    external["meta"] = {"title": "outside-only-marker"}
    (outside / "a.graph.json").write_text(json.dumps(external), encoding="utf-8")
    return folder, outside


def swap_to_junction(ws: Path, folder: Path, outside: Path) -> None:
    folder.rename(ws / "tests" / "moved")
    _winapi.CreateJunction(str(outside), str(folder))


def test_open_revalidates_after_waiting_for_path_lock(
    ws: Path, tmp_path: Path, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 앞선 열기가 경로 잠금을 쥔 동안 기다린 열기는, 그 사이 정션으로 바뀐 경로를 따라 읽지 않는다
    folder, outside = movable_with_outside(ws, tmp_path)
    rel = "tests/movable/a.graph.json"
    entered, queued, release = threading.Event(), threading.Event(), threading.Event()
    table = daemon.daemon.documents
    real_open = table.open
    with daemon.client() as first, daemon.client() as second:
        holder: list[int] = []

        def observe_open(where: Any, connection: int, reader: Any = read_graph) -> Any:
            if not holder:
                holder.append(connection)

                def delayed_reader(path: Path) -> Any:
                    doc = read_graph(path)
                    entered.set()
                    assert release.wait(10)
                    return doc

                return real_open(where, connection, delayed_reader)
            queued.set()
            return real_open(where, connection, reader)

        monkeypatch.setattr(table, "open", observe_open)
        try:
            first_pending = first.request("graph.open", {"path": rel})
            assert entered.wait(5)
            pending = second.request("graph.open", {"path": rel})
            assert queued.wait(5)
            time.sleep(0.2)
            assert not pending.done()  # 경로 잠금을 기다린다
            swap_to_junction(ws, folder, outside)
        finally:
            release.set()
        first_pending.result(10)
        with pytest.raises(DaemonError) as exc:
            pending.result(10)
        assert failure(exc) == {"code": "path_outside_workspace", "path": rel}


def test_create_revalidates_after_waiting_for_path_lock(
    ws: Path, tmp_path: Path, daemon: ThreadDaemon
) -> None:
    # 만들기도 경로 잠금을 잡은 뒤 만들기 직전에 다시 검사한다
    folder, outside = movable_with_outside(ws, tmp_path)
    rel = "tests/movable/new.graph.json"
    lock = daemon.daemon.documents.path_lock(os.path.normcase(str(folder / "new.graph.json")))
    with daemon.client() as client:
        with lock:
            pending = client.request("graph.create", {"path": rel, "kind": "test"})
            time.sleep(0.3)
            assert not pending.done()
            swap_to_junction(ws, folder, outside)
        with pytest.raises(DaemonError) as exc:
            pending.result(10)
        assert failure(exc) == {"code": "path_outside_workspace", "path": rel}
    assert sorted(p.name for p in outside.iterdir()) == ["a.graph.json"]


def test_other_alias_disappearing_does_not_break_direct_holder(
    ws: Path, daemon: ThreadDaemon
) -> None:
    # 연결마다 자기가 연 경로로 다시 검사한다: 다른 연결의 별칭 정션이 사라져도 실제 경로는 된다
    actual = ws / "tests" / "actual"
    actual.mkdir()
    (actual / "a.graph.json").write_bytes((ws / INVENTORY).read_bytes())
    alias = ws / "tests" / "alias"
    _winapi.CreateJunction(str(actual), str(alias))
    direct = "tests/actual/a.graph.json"
    with daemon.client() as second:
        with daemon.client() as first:
            linked = first.call("graph.open", {"path": "tests/alias/a.graph.json"})
            opened = second.call("graph.open", {"path": direct})
            assert linked["doc_id"] == opened["doc_id"]
            os.rmdir(alias)  # 정션만 지운다
            # 별칭으로 연 연결은 자기 경로가 없어졌다
            with pytest.raises(DaemonError) as exc:
                first.call(
                    "graph.validate",
                    {"doc_id": linked["doc_id"], "value": linked["value"], "seq": 0},
                )
            assert failure(exc) == {"code": "not_found", "path": "tests/alias/a.graph.json"}
        wait_for(lambda: daemon.call_in_loop(daemon.daemon.transport.count) == 1)
        checked = second.call(
            "graph.validate", {"doc_id": opened["doc_id"], "value": opened["value"], "seq": 1}
        )
        assert checked["seq"] == 1
        value = opened["value"]
        value["meta"] = {"title": "실제 경로 저장"}
        saved = second.call(
            "graph.save",
            {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
        )
        assert saved["wrote"] is True
        reopened = second.call("graph.open", {"path": direct})
        assert reopened["doc_id"] == opened["doc_id"]
        second.call(
            "graph.validate", {"doc_id": reopened["doc_id"], "value": reopened["value"], "seq": 2}
        )
    assert loads_strict((actual / "a.graph.json").read_text("utf-8"))["meta"]["title"] == (
        "실제 경로 저장"
    )


def test_tree_graph_read_rechecks_path(ws: Path, tmp_path: Path) -> None:
    # 탐색기의 그래프 읽기도 읽기 직전에 경로를 다시 해석한다 (목록 뒤 바뀐 링크로 밖을 읽지 않음)
    from kookabug_daemon.methods.workspace import graph_entry

    folder, outside = movable_with_outside(ws, tmp_path)
    assert graph_entry(ws, "tests/movable/a.graph.json") == {"graph_kind": "test"}
    swap_to_junction(ws, folder, outside)
    entry = graph_entry(ws, "tests/movable/a.graph.json")
    assert "graph_kind" not in entry and "루트 밖" in entry["problem"]


# ---------------------------------------------------------------- 열지 않은 연결의 후보 (검수 T4_3)


ALIAS = "tests/alias.graph.json"


def redirect_realpath(monkeypatch: pytest.MonkeyPatch, targets: dict[Path, Path]) -> None:
    """파일 심볼릭 링크 대역: 그 경로들의 `os.path.realpath`만 정한 대상으로 바꾼다 (심볼릭 링크
    만들기 권한이 없는 PC에서도 daemon의 요청·문서 표·후보 순회·형식 검사를 그대로 돌린다)."""
    real = os.path.realpath

    def fake(path: Any, *args: Any, **kwargs: Any) -> str:
        key = os.path.normcase(os.path.abspath(path))
        # `targets`는 검사 도중 바꾼다 (링크 교체): 매번 지금 표를 본다
        for link, destination in targets.items():
            if os.path.normcase(os.path.abspath(link)) == key:
                return str(destination)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", fake)


def test_invalid_alias_candidate_does_not_hide_valid_target(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 다른 연결의 별칭이 그래프가 아닌 파일을 가리키게 돼도(-32602 후보), 열지 않은 연결은 다음
    # 후보(실제 경로로 연 연결·실제 파일)로 검증·저장한다. 별칭을 연 연결 자신은 계속 거부된다
    target = ws / INVENTORY
    alias = ws / ALIAS
    alias.write_bytes(target.read_bytes())
    links = {alias: target}
    redirect_realpath(monkeypatch, links)
    with ThreadDaemon(ws) as d, d.client() as owner, d.client() as caller, d.client() as direct:
        opened = owner.call("graph.open", {"path": ALIAS})
        actual = direct.call("graph.open", {"path": INVENTORY})
        assert opened["doc_id"] == actual["doc_id"]
        doc_id = opened["doc_id"]
        checks = {"doc_id": doc_id, "value": opened["value"], "seq": 1}
        assert caller.call("graph.validate", checks)["seq"] == 1

        links[alias] = ws / "kookabug.json"  # 별칭만 그래프가 아닌 파일로
        assert direct.call("graph.validate", checks)["seq"] == 1
        assert caller.call("graph.validate", {**checks, "seq": 2})["seq"] == 2
        value = opened["value"]
        value["meta"] = {"title": "열지 않은 연결의 저장"}
        saved = caller.call(
            "graph.save", {"doc_id": doc_id, "value": value, "base_revision": opened["revision"]}
        )
        assert saved["wrote"] is True
        assert loads_strict(target.read_text("utf-8"))["meta"]["title"] == "열지 않은 연결의 저장"
        with pytest.raises(DaemonError) as exc:
            owner.call("graph.validate", checks)  # 연 연결은 자기 경로로만 본다
        assert exc.value.code == INVALID_PARAMS and exc.value.data["path"] == ALIAS

        # 모든 후보가 실패하면 마지막 후보(실제 파일 경로)의 오류다
        direct.call("graph.close", {"doc_id": doc_id})
        links[target] = ws / "kookabug.json"
        with pytest.raises(DaemonError) as exc:
            caller.call("graph.validate", checks)
        assert exc.value.code == INVALID_PARAMS and exc.value.data["path"] == INVENTORY
    assert loads_strict((ws / "kookabug.json").read_text("utf-8"))["format"]  # 그대로


def test_invalid_alias_candidate_native_symlink(ws: Path) -> None:
    # 같은 성질을 실제 파일 심볼릭 링크로 (만들 권한이 있는 PC에서만)
    target = ws / INVENTORY
    alias = ws / ALIAS
    try:
        os.symlink(target, alias)
    except OSError as exc:
        pytest.skip(f"파일 심볼릭 링크를 만들 수 없다: {exc}")
    with ThreadDaemon(ws) as d, d.client() as owner, d.client() as caller, d.client() as direct:
        opened = owner.call("graph.open", {"path": ALIAS})
        direct.call("graph.open", {"path": INVENTORY})
        alias.unlink()
        os.symlink(ws / "kookabug.json", alias)
        checked = caller.call(
            "graph.validate", {"doc_id": opened["doc_id"], "value": opened["value"], "seq": 3}
        )
        assert checked["seq"] == 3

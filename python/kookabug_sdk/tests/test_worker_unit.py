"""워커 호스트의 프로세스 밖 단위 검사: 플러그인 모으기, `ctx.path` 루트, 원격 `ctx`, 오류 응답."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from kookabug_sdk import rpc
from kookabug_sdk.context import Cancelled, ContextViolation
from kookabug_sdk.result import NodeContractError
from kookabug_sdk.schema import FORMAT
from kookabug_sdk.types import Image, Point, Secret
from kookabug_sdk.worker import (
    DEV_VERSION,
    EXIT_LOST,
    RunDeadline,
    WorkerContext,
    WorkerHost,
    collect_plugins,
    error_reply,
    files_path,
)

PLUGIN_MODULE = """
from kookabug_sdk import Context, Exit, Result, node

@node(type="beta.say", version=2, title="말하기", exits=[Exit("done", "ok")])
def say(ctx: Context, text: str = "x") -> Result:
    return Result.ok("done")

@node(type="alpha.one", version=1, title="하나", exits=[Exit("done", "ok")])
def one(ctx: Context) -> Result:
    return Result.ok("done")

ALIAS = one
"""


def test_collect_plugins_groups_by_plugin_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "wk_sample_plugin.py").write_text(PLUGIN_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    plugins = collect_plugins(["wk_sample_plugin"])
    assert [p["id"] for p in plugins] == ["alpha", "beta"]
    alpha, beta = plugins
    assert alpha["version"] == DEV_VERSION
    assert alpha["schema"] == {
        "format": FORMAT,
        "nodes": [alpha["schema"]["nodes"][0]],
        "plugin": {"id": "alpha", "version": DEV_VERSION},
    }
    assert [n["type"] for n in alpha["schema"]["nodes"]] == ["alpha.one"]  # 별칭은 한 번
    assert beta["schema"]["nodes"][0]["version"] == 2


def test_collect_plugins_import_error_propagates() -> None:
    with pytest.raises(ModuleNotFoundError):
        collect_plugins(["kookabug_sdk_no_such_module"])


@pytest.mark.parametrize("rel", ["a.txt", "data/x.txt", "깊은/폴더/파일.json"])
def test_files_path_inside_root(tmp_path: Path, rel: str) -> None:
    assert files_path(tmp_path, rel) == tmp_path.joinpath(*rel.split("/"))


@pytest.mark.parametrize(
    "rel", ["", "../x", "a/../../x", "a/./b", "a//b", "/abs", "C:/x", "a\\b", "..", "."]
)
def test_files_path_outside_root_rejected(tmp_path: Path, rel: str) -> None:
    with pytest.raises(ValueError, match="워크스페이스 기준 경로"):
        files_path(tmp_path, rel)


class FakeRunner:
    """`WorkerContext`가 runner에 보내는 요청을 받는다."""

    def __init__(self, replies: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.replies = replies or {}

    def __call__(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        reply = self.replies.get(method, {})
        if isinstance(reply, BaseException):
            raise reply
        return reply


def make_ctx(
    runner: FakeRunner,
    *,
    cancel: threading.Event | None = None,
    remaining_ms: int = 60_000,
    root: Path = Path("snap"),
    invoke: int = 7,
) -> WorkerContext:
    return WorkerContext(
        request=runner,
        cancel=cancel or threading.Event(),
        files_root=root,
        config={"n": 1},
        window=None,
        deadline_remaining_ms=remaining_ms,
        invoke=invoke,
    )


def test_ctx_requests_and_encoded_values() -> None:
    runner = FakeRunner(
        {
            "ctx.capture": {
                "image": {
                    "$kb": "image",
                    "width": 1,
                    "height": 2,
                    "path": "f.png",
                    "frame": 0,
                    "data": None,
                    "capture_id": 5,
                }
            },
            "ctx.vars.get": {"found": True, "value": {"$kb": "secret", "value": "s"}},
            "ctx.artifacts.save": {"path": None},
            "ctx.setting": {"value": [1, 2]},
        }
    )
    ctx = make_ctx(runner)
    image = ctx.capture()
    assert image == Image(1, 2, path=Path("f.png"), frame=0) and image.capture_id == 5
    secret = ctx.vars.get("pw")
    assert isinstance(secret, Secret) and secret.reveal() == "s"
    assert ctx.artifacts.save(image, "shot") is None
    assert ctx.setting("k") == [1, 2]
    ctx.log.warn(Secret("원문"))
    ctx.input.click(Point(1, 2), button="right")
    ctx.input.type_text(Secret("타자"))
    ctx.vars.set("x", (1, 2))
    calls = dict(runner.calls)
    # 모든 요청에 이 실행의 번호가 실린다
    assert all(params["invoke"] == 7 for _, params in runner.calls)
    assert calls["ctx.log"] == {"invoke": 7, "level": "warn", "message": "***"}
    assert calls["ctx.input.click"] == {
        "invoke": 7,
        "at": {"$kb": "point", "x": 1, "y": 2},
        "button": "right",
    }
    assert calls["ctx.input.type_text"]["text"] == {"$kb": "secret", "value": "타자"}
    assert calls["ctx.vars.set"] == {"invoke": 7, "name": "x", "value": [1, 2]}
    assert calls["ctx.artifacts.save"]["image"]["capture_id"] == 5
    assert ctx.config == {"n": 1}


def test_closed_ctx_refuses_requests() -> None:
    # 실행이 끝난 ctx(노드가 보관한 것, 남긴 스레드의 것)로는 runner에 요청하지 않는다
    runner = FakeRunner()
    ctx = make_ctx(runner)
    ctx.close()
    for call in (
        ctx.capture,
        lambda: ctx.log.info("x"),
        lambda: ctx.vars.get("x", None),
        lambda: ctx.input.key("a"),
        lambda: ctx.setting("k"),
    ):
        with pytest.raises(ContextViolation, match="끝난 노드 실행"):
            call()
    assert runner.calls == []


class _ShutdownPeer:
    """`worker.shutdown` 하나를 주는 가짜 피어. `close()`는 `RpcPeer.close`처럼 incoming에
    `PeerLost`를 넣고, 분배 스레드가 그것을 처리할 시간을 장벽으로 준다(경쟁 순서 고정)."""

    def __init__(self, lost: threading.Event) -> None:
        self.incoming: queue.Queue[rpc.Incoming | rpc.PeerLost] = queue.Queue()
        self.incoming.put(rpc.Incoming("worker.shutdown", {}, 1))
        self.responded: list[Any] = []
        self._lost = lost

    def respond(self, request: rpc.Incoming, result: Any) -> None:
        self.responded.append(result)

    def close(self, flush_timeout: float = 0.0) -> None:
        self.incoming.put(rpc.PeerLost("이쪽에서 닫았다"))
        self._lost.wait(1)  # 분배 스레드가 연결 상실 처리기를 부를 기회


def test_normal_shutdown_does_not_run_loss_handler() -> None:
    # 자기 close가 넣은 PeerLost를 분배 스레드가 연결 상실(os._exit(2))로 처리하지 않는다
    lost = threading.Event()
    peer = _ShutdownPeer(lost)
    code = WorkerHost(peer, on_lost=lost.set).serve()  # pyright: ignore[reportArgumentType]
    assert code == 0
    assert peer.responded == [{}]
    assert not lost.is_set()


def test_external_peer_loss_runs_loss_handler() -> None:
    lost = threading.Event()

    class LostPeer:
        def __init__(self) -> None:
            self.incoming: queue.Queue[rpc.PeerLost] = queue.Queue()
            self.incoming.put(rpc.PeerLost("runner가 끊었다"))

    code = WorkerHost(LostPeer(), on_lost=lost.set).serve()  # pyright: ignore[reportArgumentType]
    assert code == EXIT_LOST
    assert lost.wait(5)


def test_vars_missing_uses_default_or_key_error() -> None:
    ctx = make_ctx(FakeRunner({"ctx.vars.get": {"found": False, "value": None}}))
    assert ctx.vars.get("x", 7) == 7
    assert not ctx.vars.has("x")
    with pytest.raises(KeyError):
        ctx.vars.get("x")


@pytest.mark.parametrize(
    ("code", "data", "expected"),
    [
        (rpc.CANCELLED, None, Cancelled),
        (rpc.CONTEXT_VIOLATION, {"type": "EffectNotDeclared"}, ContextViolation),
        (rpc.NODE_CONTRACT, None, NodeContractError),
        (rpc.NODE_ERROR, {"type": "KeyError"}, KeyError),
        (rpc.NODE_ERROR, {"type": "ValueError"}, ValueError),
        (rpc.NODE_ERROR, {"type": "OSError"}, RuntimeError),
        (rpc.INVALID_PARAMS, None, RuntimeError),
    ],
)
def test_runner_errors_raised_as_same_kind(
    code: int, data: Any, expected: type[BaseException]
) -> None:
    ctx = make_ctx(FakeRunner({"ctx.setting": rpc.RpcError(code, "거부", data)}))
    with pytest.raises(expected):
        ctx.setting("k")


def test_sleep_wakes_on_cancel() -> None:
    cancel = threading.Event()
    ctx = make_ctx(FakeRunner(), cancel=cancel)
    threading.Timer(0.05, cancel.set).start()
    began = time.monotonic()
    with pytest.raises(Cancelled):
        ctx.sleep(10_000)
    assert time.monotonic() - began < 2
    # 취소 뒤에는 runner에 요청하지 않는다
    runner = FakeRunner()
    with pytest.raises(Cancelled):
        make_ctx(runner, cancel=cancel).log.info("x")
    assert runner.calls == []


def test_sleep_stops_at_run_deadline() -> None:
    ctx = make_ctx(FakeRunner(), remaining_ms=50)
    began = time.monotonic()
    with pytest.raises(RunDeadline):
        ctx.sleep(10_000)
    assert time.monotonic() - began < 2
    with pytest.raises(RunDeadline):
        ctx.check_cancel()
    with pytest.raises(ValueError):
        make_ctx(FakeRunner()).sleep(-1)


def test_path_is_files_root_based(tmp_path: Path) -> None:
    ctx = make_ctx(FakeRunner(), root=tmp_path)
    assert ctx.path("a/b.txt") == tmp_path / "a" / "b.txt"
    with pytest.raises(ValueError):
        ctx.path("../x")


def test_error_reply_mapping() -> None:
    cancelled = error_reply(Cancelled())
    assert (cancelled.code, cancelled.data) == (rpc.CANCELLED, {"reason": "cancelled"})
    deadline = error_reply(RunDeadline("기한"))
    assert (deadline.code, deadline.data["reason"]) == (rpc.CANCELLED, "deadline")
    assert error_reply(ContextViolation("막힘")).code == rpc.CONTEXT_VIOLATION
    assert error_reply(NodeContractError("틀림")).code == rpc.NODE_CONTRACT
    try:
        raise RuntimeError("터짐")
    except RuntimeError as exc:
        reply = error_reply(exc)
    assert (reply.code, reply.message) == (rpc.NODE_ERROR, "RuntimeError: 터짐")
    assert reply.data["type"] == "RuntimeError"
    assert "Traceback" in reply.data["traceback"] and "터짐" in reply.data["traceback"]
    assert error_reply(KeyError()).message == "KeyError"

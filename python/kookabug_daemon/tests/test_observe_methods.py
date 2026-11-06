"""관측 도구의 daemon 쪽 (M5 계획 3.3·D7, B2): `kb_screen_capture`(`windows.list`·`target.capture`)·
`kb_image_find`(`target.open`·`target.preview`)·`kb_ocr_read`(`screen.read_text`).

창·캡처는 같은 프로세스 daemon의 함수를 가짜로 바꾼다(예제 게임 로그인 화면 PNG). OCR 엔진도 가짜다.
`screen.read_text`는 녹화 세션 프레임을 받지 않고, `sensitive: true` target이 보이는 영역과 겹치면
`sensitive_region`이다. 지금 화면은 기록이 아니라 가리지 않는다.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.daemon_targets import Editor, target_workspace

from kb_testing.daemon import ThreadDaemon, daemon_env, make_workspace
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kookabug_daemon.client import DaemonError
from kookabug_daemon.frames import EditorFrame, FrameCache

pytestmark = pytest.mark.process

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-1", "attended": True}
LOGIN_BUTTON: Final = (432, 380, 160, 56)
PASSWORD: Final = (400, 285, 320, 50)
"""예제 게임 로그인 화면의 비밀번호 칸 (layout.py)."""
TITLE: Final = "Kookabug Sample Game"


class _FakeEngine:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def read(self, image: Any, *, region: Any = None, deadline: Any = None) -> list[Any]:
        from kookabug_platform.ocr.engine import OcrLine

        self.calls.append(tuple(region))
        return [OcrLine("로그인", tuple(region), 0.9)]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return target_workspace(tmp_path)


def _pixels(root: Path) -> Any:
    data = (root / "captures" / "login.png").read_bytes()
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return np.ascontiguousarray(pixels)


def _sensitive_target(client: Any, root: Path) -> None:
    """비밀번호 칸을 `sensitive: true` target으로 저장한다 (UI)."""
    ed = Editor(client)
    frame = ed.load("captures/login.png")
    rel = "targets/secret/password.target.json"
    ed.save(rel, frame, PASSWORD)
    path = root / rel
    body = json.loads(path.read_text("utf-8"))
    body["sensitive"] = True
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def test_ocr_rejects_recorder_frame(root: Path) -> None:
    with ThreadDaemon(root) as d:
        engine = _FakeEngine()
        d.daemon.targets.ocr_factory = lambda: engine
        pixels = _pixels(root)
        pixels.setflags(write=False)
        size = (int(pixels.shape[1]), int(pixels.shape[0]))
        rec_id = FrameCache.new_id()
        d.daemon.frames.add(EditorFrame(rec_id, pixels, size, 96, "", origin="recorder"))
        with d.client(AGENT) as agent:
            # agent는 자기 연결이 만든 정지 화면만 쓴다 (B2 검수 H2)
            plain = agent.call("target.load_image", {"path": "captures/login.png"})["frame_id"]
            for method, params in (
                ("screen.read_text", {"frame_id": rec_id, "rect": list(LOGIN_BUTTON)}),
                (
                    "target.preview",
                    {
                        "frame_id": rec_id,
                        "spec": {},
                        "template": {"crop": {"frame_id": plain, "rect": list(LOGIN_BUTTON)}},
                        "seq": 1,
                    },
                ),
            ):
                with pytest.raises(DaemonError) as caught:
                    agent.call(method, params)
                assert caught.value.kind == "recorder_frame", method
            assert engine.calls == []  # OCR 전에 거부
            got = agent.call("screen.read_text", {"frame_id": plain, "rect": list(LOGIN_BUTTON)})
            assert got["text"] == "로그인" and engine.calls == [LOGIN_BUTTON]
        with d.client() as ui, pytest.raises(DaemonError) as caught:
            # 사람 연결도 이 메서드로는 녹화 프레임을 읽지 않는다 (사람은 target.read_text)
            ui.call("screen.read_text", {"frame_id": rec_id})
        assert caught.value.kind == "recorder_frame"


def test_capture_find_ocr_fake_platform(
    root: Path, tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kookabug_daemon.methods.target as target_methods
    import kookabug_daemon.methods.windows as window_methods

    pixels = _pixels(root)
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    window = {
        "handle": 4242,
        "title": TITLE,
        "process": "sample_game.exe",
        "pid": 1,
        "client_size": [width, height],
        "dpi": 96,
    }
    monkeypatch.setattr(window_methods, "_windows", lambda: [window])
    captures: list[int] = []

    def capture(hwnd: int) -> Any:
        captures.append(hwnd)
        return SimpleNamespace(
            pixels=pixels.copy(), info=SimpleNamespace(client_size=(width, height), dpi=96)
        )

    monkeypatch.setattr(target_methods, "capture_window", capture)
    local = root / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    local.write_text(
        json.dumps({"format": "kookabug.local/0", "permissions": {"preset": "read_only"}}),
        encoding="utf-8",
    )
    with ThreadDaemon(root, agent_toolsets=("core",)) as d:
        engine = _FakeEngine()
        d.daemon.targets.ocr_factory = lambda: engine
        mcp = McpClient.start(spawned, root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            assert mcp.error("kb_screen_capture")["code"] == "toolset_disabled"
            mcp.data("kb_toolset_enable", {"toolsets": ["observe"]})
            listed = mcp.data("kb_screen_capture")
            assert listed["windows"][0]["title"] == TITLE
            result = mcp.call_tool("kb_screen_capture", {"window": "Sample Game"})
            assert result["isError"] is False, result
            shot = result["structuredContent"]
            assert captures == [4242] and shot["width"] == width
            (image,) = [c for c in result["content"] if c["type"] == "image"]
            data = base64.b64decode(image["data"])
            assert image["mimeType"] == "image/png" and len(data) <= 1024 * 1024
            decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            assert decoded is not None and max(decoded.shape[:2]) <= 1568
            frame_id = shot["frame_id"]

            found = mcp.data(
                "kb_image_find",
                {"frame_id": frame_id, "target": "targets/login/login_button.target.json"},
            )
            assert found["found"] is True
            x, y, _, _ = found["match"]["rect"]
            assert abs(x - LOGIN_BUTTON[0]) <= 8 and abs(y - LOGIN_BUTTON[1]) <= 8

            read = mcp.data("kb_ocr_read", {"frame_id": frame_id, "rect": list(LOGIN_BUTTON)})
            assert read["text"] == "로그인"
            # 비밀번호 칸을 sensitive target으로 만들면, 그것이 보이는 화면은 영역과 상관없이 읽지
            # 않는다 (B2 검수 H3)
            with d.client() as ui:
                _sensitive_target(ui, root)
            calls = len(engine.calls)
            for args in (
                {"frame_id": frame_id, "rect": [380, 270, 200, 40]},  # 겹침
                {"frame_id": frame_id, "rect": list(LOGIN_BUTTON)},  # 안 겹침
                {"frame_id": frame_id},  # 전체
            ):
                error = mcp.error("kb_ocr_read", args)
                assert error["code"] == "sensitive_region", args
                assert error["path"] == "targets/secret/password.target.json"
            assert len(engine.calls) == calls
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)


# ---------------------------------------------------------------- B2 검수 반례 (2라운드)


class _MarkOcr:
    name = "mark"

    def __init__(self) -> None:
        self.calls = 0

    def read(self, image: Any, *, region: Any = None, deadline: Any = None) -> list[Any]:
        from kookabug_platform.ocr.engine import OcrLine

        self.calls += 1
        return [OcrLine("review-secret-42", tuple(region), 0.99)]


def test_sensitive_ocr_duplicate_match_denied(tmp_path: Path) -> None:
    """H3: 같은 민감 target이 두 곳에 보이면 최고 매칭이 아닌 곳의 OCR도 거부한다."""
    root = make_workspace(tmp_path / "ws")
    targets = root / "targets"
    targets.mkdir()
    rng = np.random.default_rng(12)
    pattern = rng.integers(0, 256, (24, 32, 3), dtype=np.uint8)
    pixels = np.zeros((180, 280, 3), dtype=np.uint8)
    boxes = [(20, 20, 32, 24), (180, 100, 32, 24)]
    for x, y, w, h in boxes:
        pixels[y : y + h, x : x + w] = pattern
    cv2.imwrite(str(targets / "private.png"), pattern)
    cv2.imwrite(str(root / "screen.png"), pixels)
    (targets / "private.target.json").write_text(
        json.dumps(
            {
                "format": "kookabug.target/0",
                "image": "private.png",
                "sensitive": True,
                "match": {"threshold": 0.99},
            }
        ),
        encoding="utf-8",
    )
    engine = _MarkOcr()
    with ThreadDaemon(root) as d, d.client(AGENT) as agent:
        d.daemon.targets.ocr_factory = lambda: engine
        frame = agent.call("target.load_image", {"path": "screen.png"})["frame_id"]
        result = agent.call(
            "target.preview",
            {
                "frame_id": frame,
                "spec": {"match": {"threshold": 0.99}},
                "template": {"image": "private.png"},
                "base_path": "targets/private.target.json",
                "seq": 1,
            },
        )
        assert result["found"] and len(result["peaks"]) >= 2, result
        best = result["match"]["rect"]
        other = next(box for box in boxes if abs(box[0] - best[0]) > 50)
        for rect in (list(other), list(best), [100, 150, 20, 20]):
            with pytest.raises(DaemonError) as caught:
                agent.call("screen.read_text", {"frame_id": frame, "rect": rect})
            assert caught.value.kind == "sensitive_region", rect
        assert engine.calls == 0


def test_image_find_threshold_override(
    root: Path, tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: `kb_image_find`의 threshold는 target 사양 `match.threshold`로 (인자 있음·없음 둘 다)."""
    import kookabug_daemon.methods.target as target_methods
    import kookabug_daemon.methods.windows as window_methods

    pixels = _pixels(root)
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    window = {
        "handle": 7,
        "title": TITLE,
        "process": "sample_game.exe",
        "pid": 1,
        "client_size": [width, height],
        "dpi": 96,
    }
    monkeypatch.setattr(window_methods, "_windows", lambda: [window])
    monkeypatch.setattr(
        target_methods,
        "capture_window",
        lambda hwnd: SimpleNamespace(
            pixels=pixels.copy(), info=SimpleNamespace(client_size=(width, height), dpi=96)
        ),
    )
    with ThreadDaemon(root) as d:
        assert d is not None
        mcp = McpClient.start(spawned, root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            # agent는 자기 연결이 만든 정지 화면만 쓴다: MCP로 캡처한다
            frame_id = mcp.data("kb_screen_capture", {"window": TITLE})["frame_id"]
            args = {"frame_id": frame_id, "target": "targets/login/login_button.target.json"}
            plain = mcp.data("kb_image_find", args)
            assert plain["found"] is True
            loose = mcp.data("kb_image_find", {**args, "threshold": 0.8})
            assert loose["found"] is True and loose["threshold"] == 0.8
            strict = mcp.data("kb_image_find", {**args, "threshold": 1.0})
            assert strict["threshold"] == 1.0
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)


# ---------------------------------------------------------------- B2 재검수 H5 (3라운드)


def _private_workspace(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    """민감 target 하나(무늬)가 보이는 `screen.png` 워크스페이스 → (루트, 무늬 PNG, target, 값)."""
    root = make_workspace(tmp_path / "ws")
    targets = root / "targets"
    targets.mkdir()
    pattern = np.random.default_rng(17).integers(0, 256, (32, 64, 3), dtype=np.uint8)
    pixels = np.zeros((100, 180, 3), dtype=np.uint8)
    pixels[20:52, 30:94] = pattern
    image = targets / "private.png"
    cv2.imwrite(str(image), pattern)
    cv2.imwrite(str(root / "screen.png"), pixels)
    target = targets / "private.target.json"
    value: dict[str, Any] = {
        "format": "kookabug.target/0",
        "image": "private.png",
        "sensitive": True,
        "match": {"threshold": 0.99},
    }
    target.write_text(json.dumps(value), encoding="utf-8")
    return root, image, target, value


def _read(agent: Any, args: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        agent.call("screen.read_text", args)
    return caught.value


@pytest.mark.parametrize("damage", ["missing_image", "broken_image", "bad_threshold"])
def test_sensitive_target_detection_error_must_not_enable_ocr(tmp_path: Path, damage: str) -> None:
    """민감 target을 확인하지 못하면(이미지 없음·손상·사양 오류) OCR을 부르지 않고 거부한다
    (fail closed). 거부 메시지로 "보임"과 "확인 못 함"을 가른다."""
    root, image, target, value = _private_workspace(tmp_path)
    engine = _MarkOcr()
    with ThreadDaemon(root) as d, d.client(AGENT) as agent:
        d.daemon.targets.ocr_factory = lambda: engine
        frame = agent.call("target.load_image", {"path": "screen.png"})["frame_id"]
        args = {"frame_id": frame, "rect": [30, 20, 64, 32]}
        before = _read(agent, args)
        assert before.kind == "sensitive_region" and "보이는 화면" in before.message
        if damage == "missing_image":
            image.unlink()
        elif damage == "broken_image":
            image.write_bytes(b"not-png")
        else:
            value["match"]["threshold"] = "broken"
            target.write_text(json.dumps(value), encoding="utf-8")
        after = _read(agent, args)
        assert after.kind == "sensitive_region", damage
        assert "민감 target을 확인하지 못함" in after.message
        assert after.data["path"] == "targets/private.target.json"
        assert "review-secret-42" not in str(after) and engine.calls == 0
        # 영역을 바꿔도(민감 영역 밖) 그대로 거부
        assert _read(agent, {"frame_id": frame, "rect": [120, 60, 40, 30]}).kind == (
            "sensitive_region"
        )
        assert engine.calls == 0


def test_sensitive_target_unreadable_json_must_not_enable_ocr(tmp_path: Path) -> None:
    """`sensitive`인지조차 읽지 못한 target 파일(JSON 깨짐)도 확인 못 함 → 거부. 고치면 다시 보통
    판정(민감 target이 안 보이는 화면이면 읽는다)."""
    root, _, target, value = _private_workspace(tmp_path)
    (root / "blank.png").write_bytes(cv2.imencode(".png", np.zeros((60, 80, 3), np.uint8))[1])
    engine = _MarkOcr()
    with ThreadDaemon(root) as d, d.client(AGENT) as agent:
        d.daemon.targets.ocr_factory = lambda: engine
        frame = agent.call("target.load_image", {"path": "blank.png"})["frame_id"]
        args = {"frame_id": frame, "rect": [0, 0, 20, 20]}
        assert agent.call("screen.read_text", args)["text"] == "review-secret-42"  # 안 보임
        calls = engine.calls
        target.write_text('{"format": "kookabug.target/0", "sensitive": tr', encoding="utf-8")
        error = _read(agent, args)
        assert error.kind == "sensitive_region" and "확인하지 못함" in error.message
        assert error.data["path"] == "targets/private.target.json" and engine.calls == calls
        target.write_text(json.dumps(value), encoding="utf-8")
        assert agent.call("screen.read_text", args)["text"] == "review-secret-42"


@pytest.mark.parametrize(
    "damage",
    [
        "json_broken",
        "json_array",
        "read_error",
        "folder_error",
        "runtime_error",
        "value_error",
        "invalid_match_type",
        "threshold_range",
        "search_range",
        "sensitive_type",
    ],
)
def test_every_detection_failure_blocks_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    """민감 target 판정 실패는 모두 거부 (B2 재검수 3라운드 H5 잔여): 읽기·폴더·매칭 예외, 깨진
    JSON, 그리고 예외 없이 미검출로 끝나는 스키마 오류(범위 밖 임계값·검색 범위, `sensitive`
    형식 오류). 오류 원문(표식)은 결과에 나오지 않고 OCR은 불리지 않는다."""
    import kookabug_daemon.targets as targets
    from kookabug_core.schema import check_shape

    mark = "review-secret-42"
    root, _, target, value = _private_workspace(tmp_path)
    engine = _MarkOcr()
    with ThreadDaemon(root) as d, d.client(AGENT) as agent:
        d.daemon.targets.ocr_factory = lambda: engine
        frame = agent.call("target.load_image", {"path": "screen.png"})["frame_id"]
        args = {"frame_id": frame, "rect": [30, 20, 64, 32]}
        assert _read(agent, args).kind == "sensitive_region" and engine.calls == 0
        if damage == "json_broken":
            target.write_text('{"sensitive":tr', encoding="utf-8")
        elif damage == "json_array":
            target.write_text("[]", encoding="utf-8")
        elif damage == "read_error":
            original = Path.read_text

            def read(path: Path, *a: Any, **kw: Any) -> str:
                if path == target:
                    raise PermissionError(mark)
                return original(path, *a, **kw)

            monkeypatch.setattr(Path, "read_text", read)
        elif damage == "folder_error":

            def walk(root: Path, failures: list[str]) -> Any:
                failures.append(mark)
                return iter(())

            monkeypatch.setattr(targets, "_walk_targets", walk)
        elif damage in ("runtime_error", "value_error"):
            error = RuntimeError if damage == "runtime_error" else ValueError

            def find(*a: Any, **kw: Any) -> Any:
                raise error(mark)

            monkeypatch.setattr(targets, "_find", find)
        else:
            if damage == "invalid_match_type":
                value["match"] = 7
            elif damage == "threshold_range":
                value["match"]["threshold"] = 1.1
            elif damage == "search_range":
                value["search"] = {"region": [2, 0, 0.2, 0.2]}
            else:  # sensitive_type
                value["sensitive"] = "true"
            assert check_shape(value, "target"), "유효한 사양은 오류 반례가 아니다"
            target.write_text(json.dumps(value), encoding="utf-8")
        after = _read(agent, args)
        assert after.kind == "sensitive_region", damage
        assert "확인하지 못함" in after.message, after.message
        assert mark not in str(after) and mark not in json.dumps(after.data)
        assert engine.calls == 0

"""기능 점검 `kookabug doctor` (구현 계획 M1 2.11, 계획 검수 8).

검사 항목마다 `{id, profile, ok, detail}`. 프로필은 둘이다.

- `headless`(설치 스모크·헤드리스 CI 필수): Python 위치(설치본인가), 무거운 의존성 import(`numpy`·
  `cv2`·`onnxruntime`·`windows_capture`), 그 DLL을 어디서 읽었나(`msvcp140.dll` 등 — 설치본이면
  설치 폴더여야 함), OCR 모델(찾기·크기·SHA256), DPI 인식(Per-Monitor V2, 진입점이 정한 결과),
  가짜 플랫폼 스모크 그래프(실제 매칭·OCR), 영상 인코더(Media Foundation H.264 열기 시험 — 쓸 수
  없어도 실패가 아니라 "영상 사용 불가"와 이유, M3)
- `desktop`(= headless + 데스크톱 증거): 입력 데스크톱(잠금 화면 아님), 임시 창 WGC 한 프레임,
  정지 화면 재사용(같은 화면의 두 번째 캡처), 포그라운드 가져오기. 입력은 보내지 않는다

스모크 그래프는 `smoke=`로 넘긴다. `kookabug doctor`는 예제 게임 워크스페이스의 헤드리스 스모크
그래프(`example_smoke()`: 설치본 `<설치>/examples/sample-game/workspace`, 개발 레포
`fixtures/sample-game/workspace`)를 쓰고, 그것이 없는 개발 환경(wheel만 설치)에서는 이 모듈이 임시
폴더에 만드는 최소 워크스페이스(그린 화면 한 장에서 표식을 찾고 수를 읽어 비교)를 쓴다. 설치본에서
예제가 없으면 스모크 실패다. 무거운 의존성은 검사 안에서 import한다 — 없으면 그 항목이 실패로
나오게.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib
import json
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from kookabug_core.engine import RunResult

__all__ = [
    "DLLS",
    "MODULES",
    "PROFILES",
    "Check",
    "Profile",
    "SmokeGraph",
    "example_smoke",
    "loaded_dll",
    "run_checks",
    "smoke_workspace",
]

type Profile = Literal["headless", "desktop"]
PROFILES: Final[tuple[Profile, ...]] = ("headless", "desktop")
MODULES: Final = ("numpy", "cv2", "onnxruntime", "windows_capture")
DLLS: Final = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "onnxruntime.dll")
"""어디서 읽었는지 보고하는 DLL. 설치본이면 `msvcp140.dll`은 설치 폴더여야 한다 (2.12)."""
SMOKE_NUMBER: Final = 12345
WINDOW_TITLE: Final = "Kookabug doctor"
EXAMPLE_SMOKE: Final = "tests/smoke_headless.graph.json"
EXAMPLE_PLATFORM: Final = "fake-platform.json"
"""예제 워크스페이스의 헤드리스 스모크 그래프와 가짜 플랫폼 사양(`scenario` = 장면 표, 사양 파일
기준)."""


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    profile: Profile
    ok: bool
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"detail": self.detail, "id": self.id, "ok": self.ok, "profile": self.profile}


@dataclass(frozen=True, slots=True)
class SmokeGraph:
    """가짜 플랫폼으로 돌릴 스모크 그래프: 워크스페이스, 그래프(워크스페이스 기준), 화면(프레임
    PNG들 또는 장면 표 `scenario`)."""

    workspace: Path
    graph: str
    frames: tuple[Path, ...] = ()
    scenario: Path | None = None


# ---------------------------------------------------------------- 공용


def _install_root() -> Path:
    """설치본 루트 후보: 동봉 Python 폴더(`<설치>/python`)의 부모."""
    return Path(sys.base_prefix).resolve().parent


def installed() -> bool:
    """설치본의 Python으로 돌고 있는가 (`<설치>/python` + `<설치>/bin`, 구현 계획 M1 2.12)."""
    base = Path(sys.base_prefix).resolve()
    return base.name.casefold() == "python" and (base.parent / "bin").is_dir()


def _guard(check_id: str, profile: Profile, body: Callable[[], tuple[bool, str]]) -> Check:
    try:
        ok, detail = body()
    except Exception as exc:
        code = getattr(exc, "code", None)
        prefix = f"{code}: " if isinstance(code, str) else f"{type(exc).__name__}: "
        return Check(check_id, profile, False, prefix + str(exc))
    return Check(check_id, profile, ok, detail)


# ---------------------------------------------------------------- headless


def _python() -> tuple[bool, str]:
    where = "설치본" if installed() else "설치본 아님 (개발 환경)"
    return True, f"{sys.executable} (Python {sys.version.split()[0]}, {where})"


def _import(name: str) -> Callable[[], tuple[bool, str]]:
    def body() -> tuple[bool, str]:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "?")
        return True, f"{version} ({getattr(module, '__file__', '?')})"

    return body


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleFileNameW.restype = wintypes.DWORD
_kernel32.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)


def loaded_dll(name: str) -> Path | None:
    """이 프로세스가 읽은 그 DLL의 경로 (읽지 않았으면 None)."""
    handle = _kernel32.GetModuleHandleW(name)
    if not handle:
        return None
    buf = ctypes.create_unicode_buffer(32768)
    size = _kernel32.GetModuleFileNameW(handle, buf, len(buf))
    return Path(buf.value[:size]) if size else None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _dlls() -> tuple[bool, str]:
    for name in ("cv2", "onnxruntime"):  # 무거운 의존성이 읽는 DLL을 보려면 먼저 읽는다
        with contextlib.suppress(ImportError):
            importlib.import_module(name)
    root = _install_root()
    check_local = installed()
    parts: list[str] = []
    ok = True
    for name in DLLS:
        path = loaded_dll(name)
        parts.append(f"{name}={path if path is not None else '(읽지 않음)'}")
        if name == "msvcp140.dll" and check_local and (path is None or not _inside(path, root)):
            ok = False
            parts[-1] += " — 설치 폴더 밖 (앱 로컬 VC++ 런타임이 아님)"
    return ok, "; ".join(parts)


def _models() -> tuple[bool, str]:
    from kookabug_platform.ocr.models import find_models

    models = find_models()
    return True, f"{models.folder} (det {models.det.name}, rec {models.rec.name}, 해시 일치)"


def _dpi() -> tuple[bool, str]:
    from kookabug_core.win import dpi

    reason = dpi.startup_error()
    if reason is not None:
        return False, f"dpi_awareness_unavailable: {reason}"
    return True, "Per-Monitor V2"


# ---------------------------------------------------------------- 스모크 그래프


def _smoke_image() -> Any:
    """그린 화면 한 장 (640x360): 왼쪽 위 표식(주황 사각형 + 흰 원), 가운데 "SCORE 12345"."""
    import cv2
    import numpy as np

    image = np.full((360, 640, 3), (48, 40, 32), dtype=np.uint8)
    cv2.rectangle(image, (40, 40), (159, 119), (0, 140, 255), thickness=-1)
    cv2.circle(image, (100, 80), 24, (255, 255, 255), thickness=-1)
    cv2.rectangle(image, (52, 52), (70, 70), (60, 20, 120), thickness=-1)
    cv2.putText(
        image,
        f"SCORE {SMOKE_NUMBER}",
        (190, 225),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.6,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    return image


def smoke_workspace(root: Path) -> SmokeGraph:
    """최소 스모크 워크스페이스를 `root`에 쓴다: 화면 PNG, 표식 target, 그래프(표식 대기 → 수 읽기
    → 비교)."""
    import cv2

    image = _smoke_image()
    (root / "targets").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "kookabug.json").write_text(
        json.dumps({"format": "kookabug.workspace/0"}), encoding="utf-8"
    )
    screen = root / "screen.png"
    screen.write_bytes(cv2.imencode(".png", image)[1].tobytes())
    marker = image[40:120, 40:160]
    (root / "targets" / "marker.png").write_bytes(cv2.imencode(".png", marker)[1].tobytes())
    target = {
        "format": "kookabug.target/0",
        "image": "marker.png",
        "recorded": {"client_size": [640, 360], "dpi": 96},
    }
    (root / "targets" / "marker.target.json").write_text(json.dumps(target), encoding="utf-8")
    graph = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_entry": {"next": {"start": "n_wait"}, "type": "core.graph.entry", "version": 1},
            "n_wait": {
                "in": {
                    "target": {"$target": "targets/marker.target.json"},
                    "timeout_ms": 5000,
                },
                "next": {"found": "n_read"},
                "type": "core.image.wait",
                "version": 1,
            },
            "n_read": {
                "in": {"parse": "number", "region": [170, 170, 440, 80]},
                "next": {"done": "n_check"},
                "type": "core.ocr.read",
                "version": 1,
            },
            "n_check": {
                "in": {"a": {"$link": "n_read.number"}, "b": SMOKE_NUMBER, "op": "=="},
                "type": "core.assert.compare",
                "version": 1,
            },
        },
        "plugins": {"core": "0.1.0"},
    }
    (root / "tests" / "smoke.graph.json").write_text(json.dumps(graph), encoding="utf-8")
    return SmokeGraph(root, "tests/smoke.graph.json", frames=(screen,))


def _example_workspace() -> Path | None:
    """예제 게임 워크스페이스: 설치본이면 `<설치>/examples/sample-game/workspace`(없어도 그 경로 —
    스모크가 실패로 알린다), 아니면 개발 레포의 `fixtures/sample-game/workspace`(없으면 None)."""
    if installed():
        return _install_root() / "examples" / "sample-game" / "workspace"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / "sample-game" / "workspace"
        if (candidate / "kookabug.json").is_file():
            return candidate
    return None


def example_smoke(workspace: Path | None = None) -> SmokeGraph | None:
    """예제 워크스페이스의 헤드리스 스모크 그래프 (장면 표는 `fake-platform.json`의 `scenario`).
    `workspace`를 안 주면 `_example_workspace()`. 찾을 곳이 없으면 None(최소 스모크를 쓴다)."""
    root = _example_workspace() if workspace is None else workspace
    if root is None:
        return None
    scenario: Path | None = None
    with contextlib.suppress(OSError, ValueError):
        spec = json.loads((root / EXAMPLE_PLATFORM).read_text(encoding="utf-8"))
        if isinstance(spec, dict) and isinstance(spec.get("scenario"), str):
            scenario = (root / spec["scenario"]).resolve()
    return SmokeGraph(root, EXAMPLE_SMOKE, scenario=scenario)


def run_smoke(smoke: SmokeGraph) -> RunResult:
    """스모크 그래프를 가짜 플랫폼(프레임 PNG 또는 장면 표) + 실제 매칭·OCR + 프레임 저장소로
    실행한다."""
    from kookabug_core.engine import ExecOptions, Executor
    from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
    from kookabug_core.loader import load_program
    from kookabug_core.workspace import Workspace
    from kookabug_platform.engines import RunEngines
    from kookabug_platform.frames import FrameStore, decode_image

    store = FrameStore()
    engines = RunEngines(store)
    platform: Any
    if smoke.scenario is not None:
        platform = ScenarioPlatform(
            FakeScenario.load(smoke.scenario), decode=decode_image, engines=engines
        )
    else:
        platform = _FramePlatform(smoke.frames, engines)
    program = load_program(Workspace.open(smoke.workspace), smoke.graph)
    executor = Executor(platform=platform, frames=store)
    return executor.run(program, ExecOptions(run_id="doctor"))


class _FramePlatform:
    """프레임 PNG를 차례로 주는 가짜 플랫폼 + 찾기·비교·OCR."""

    def __init__(self, frames: Sequence[Path], engines: Any) -> None:
        from kookabug_core.engine import FakePlatform
        from kookabug_platform.frames import decode_image

        self._frames = FakePlatform(frames, decode=decode_image)
        self._engines = engines

    @property
    def input(self) -> Any:
        return self._frames.input

    def capture(self, window: Any, region: Any) -> Any:
        return self._frames.capture(window, region)

    def capture_staged(self, window: Any, region: Any, limits: Any) -> Any:
        return self._frames.capture_staged(window, region, limits)

    def find(self, image: Any, target: Any, *, region: Any, limits: Any) -> Any:
        return self._engines.find(image, target, region=region, limits=limits)

    def diff(self, a: Any, b: Any, *, region: Any) -> float:
        return self._engines.diff(a, b, region=region)

    def read_text(self, image: Any, *, region: Any, sensitive: bool, limits: Any) -> Any:
        return self._engines.read_text(image, region=region, sensitive=sensitive, limits=limits)


def _smoke(smoke: SmokeGraph | None) -> Callable[[], tuple[bool, str]]:
    def body() -> tuple[bool, str]:
        with tempfile.TemporaryDirectory(prefix="kookabug-doctor-") as tmp:
            graph = smoke if smoke is not None else smoke_workspace(Path(tmp))
            started = time.perf_counter()
            result = run_smoke(graph)
            elapsed = int((time.perf_counter() - started) * 1000)
        text = _last_text(result)
        seen = f", OCR {text!r}" if text is not None else ""
        where = graph.workspace / graph.graph if smoke is not None else f"{graph.graph} (내장)"
        detail = f"{where}: {result.verdict} ({elapsed} ms{seen})"
        if result.verdict != "pass":
            detail += f" — {result.code}: {result.reason}"
        return result.verdict == "pass", detail

    return body


def _last_text(result: RunResult) -> str | None:
    """마지막으로 글자를 내보낸 스텝의 `text` 출력 (OCR 노드·문구 검증). 없으면 None."""
    for event in reversed(result.events):
        if event["event"] == "step.end":
            text = event.get("outputs", {}).get("text")
            if isinstance(text, str):
                return text
    return None


# ---------------------------------------------------------------- desktop


class _ProbeWindow:
    """점검용 임시 창 (tkinter, 자기 스레드). 입력은 받지 않는다."""

    def __init__(self) -> None:
        self.hwnd = 0
        self.error: BaseException | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="doctor-window", daemon=True)

    def _run(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title(WINDOW_TITLE)
            root.geometry("360x200+120+120")
            canvas = tk.Canvas(root, width=360, height=200, bg="#20406a", highlightthickness=0)
            canvas.pack()
            canvas.create_rectangle(30, 30, 150, 110, fill="#ff8c00", outline="")
            canvas.create_text(240, 150, text="Kookabug", fill="white")
            root.update()
            self.hwnd = int(root.wm_frame(), 16)
        except BaseException as exc:
            self.error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            while not self._stop.is_set():
                root.update()
                time.sleep(0.02)
        finally:
            root.destroy()

    def __enter__(self) -> _ProbeWindow:
        self._thread.start()
        if not self._ready.wait(10):
            raise TimeoutError("점검용 창이 10초 안에 뜨지 않았다")
        if self.error is not None:
            raise self.error
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(5)


def _desktop_checks() -> list[Check]:
    from kookabug_platform.capture import CaptureService
    from kookabug_platform.deadline import ObservationDeadline
    from kookabug_platform.tracker import WindowTracker
    from kookabug_platform.windows import activate, check_input_desktop

    def input_desktop() -> tuple[bool, str]:
        check_input_desktop()
        return True, "입력 데스크톱 Default, 잠금 화면 아님"

    checks = [_guard("desktop.input_desktop", "desktop", input_desktop)]
    state: dict[str, Any] = {}
    try:
        with _ProbeWindow() as window, WindowTracker() as tracker:
            service = CaptureService(tracker)
            try:
                binding = tracker.bind(window.hwnd)

                def first() -> tuple[bool, str]:
                    frame = service.capture(binding, deadline=ObservationDeadline(5000))
                    state["first"] = frame
                    w, h = frame.size
                    return True, f"WGC 프레임 {w}x{h} (hwnd {window.hwnd:#x})"

                def reuse() -> tuple[bool, str]:
                    if "first" not in state:
                        return False, "첫 프레임이 없어 볼 수 없다"
                    time.sleep(0.2)
                    frame = service.capture(binding, deadline=ObservationDeadline(5000))
                    same = frame.info.pixels_at == state["first"].info.pixels_at
                    ok = frame.info.reused or same
                    return ok, (
                        f"정지 화면 두 번째 캡처: reused={frame.info.reused}, 같은 픽셀 시각={same}"
                    )

                def foreground() -> tuple[bool, str]:
                    if activate(window.hwnd):
                        return True, "임시 창을 포그라운드로 가져왔다"
                    return False, "포그라운드를 가져오지 못했다 (포그라운드 잠금·비대화형)"

                checks.append(_guard("desktop.capture", "desktop", first))
                checks.append(_guard("desktop.static_reuse", "desktop", reuse))
                checks.append(_guard("desktop.foreground", "desktop", foreground))
            finally:
                service.close_all()
    except Exception as exc:
        done = {c.id for c in checks}
        for check_id in ("desktop.capture", "desktop.static_reuse", "desktop.foreground"):
            if check_id not in done:
                checks.append(Check(check_id, "desktop", False, f"{type(exc).__name__}: {exc}"))
    return checks


def _video_encoder() -> tuple[bool, str]:
    """영상 인코더 (M3 2.5): runner와 같은 공장으로 임시 폴더에서 열기 시험. 쓸 수 없어도 실행은
    영상 없이 돌므로 실패로 보지 않고 이유를 적는다 (N·KN 판 등)."""
    from kookabug_core.record.video import EncoderUnavailable, encoder_factory_from_env

    factory, unavailable = encoder_factory_from_env()
    try:
        if unavailable is not None:
            raise unavailable
        assert factory is not None
        with tempfile.TemporaryDirectory(prefix="kookabug-doctor-video-") as folder:
            factory.probe(Path(folder))
    except EncoderUnavailable as exc:
        return True, f"영상 사용 불가 ({exc.reason}): {exc.detail} — 실행은 영상 없이 돈다"
    return True, "영상 사용 가능: Media Foundation H.264 (OS 구성요소)"


# ---------------------------------------------------------------- 실행


def run_checks(profile: Profile = "desktop", *, smoke: SmokeGraph | None = None) -> list[Check]:
    """그 프로필의 검사 전부 (`desktop`은 `headless`를 포함한다)."""
    if profile not in PROFILES:
        raise ValueError(f"프로필은 {', '.join(PROFILES)} 중 하나다: {profile!r}")
    checks = [_guard("python", "headless", _python)]
    checks += [_guard(f"import.{name}", "headless", _import(name)) for name in MODULES]
    checks.append(_guard("dll.origin", "headless", _dlls))
    checks.append(_guard("ocr.models", "headless", _models))
    checks.append(_guard("dpi", "headless", _dpi))
    checks.append(_guard("smoke.fake", "headless", _smoke(smoke)))
    checks.append(_guard("video.encoder", "headless", _video_encoder))
    if profile == "desktop":
        checks += _desktop_checks()
    return checks

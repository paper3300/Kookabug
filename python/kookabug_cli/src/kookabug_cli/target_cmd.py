"""`kookabug target test` (구현 계획 M1 2.11).

    kookabug target test <target.json> (--window 제목 | --hwnd N | --image PNG)
                         [--out PNG] [--json] [--all-scales]

target 하나를 창(지금 화면 한 장) 또는 이미지 파일에서 찾고 미리보기 PNG를 쓴다. 종료 코드 `0`
찾음, `1` 못 찾음, `6` 사용법·환경 오류(창 없음·캡처 실패·target 이미지 오류 포함). `--json`이면
결과 객체 하나만 출력한다. target 파일은 워크스페이스 밖에 있어도 된다(`image`는 그 파일 기준).

창을 쓰면 먼저 프로세스 DPI 인식을 Per-Monitor V2로 정한다(좌표가 물리 픽셀이어야 한다). 이
모듈과 `kookabug_platform`(opencv)은 이 명령을 쓸 때만 불러온다 — `kookabug run`의 시작을
무겁게 하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

from kookabug_platform.errors import PlatformError
from kookabug_platform.frames import decode_image, encode_png
from kookabug_platform.preview import render_preview
from kookabug_platform.vision import (
    Candidate,
    FindResult,
    FrameMeta,
    Pixels,
    TargetFileError,
    Vision,
    load_target_file,
)

__all__ = [
    "CAPTURE_TIMEOUT_MS",
    "EXIT_FOUND",
    "EXIT_NOT_FOUND",
    "EXIT_USAGE",
    "Frame",
    "SourceError",
    "candidate_json",
    "load_frame",
    "result_json",
    "run",
]

EXIT_FOUND: Final = 0
EXIT_NOT_FOUND: Final = 1
EXIT_USAGE: Final = 6
CAPTURE_TIMEOUT_MS: Final = 2000
"""창 한 장을 기다리는 시간 (`run.capture_timeout_ms` 기본값과 같다)."""


class SourceError(Exception):
    """프레임을 얻을 수 없다 (창 없음·캡처 실패·이미지 파일 오류). 종료 코드 6. `code`는
    플랫폼 오류 코드가 있으면 그것."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Frame:
    pixels: Pixels
    meta: FrameMeta
    source: dict[str, Any]
    """JSON에 남기는 출처 (`kind`: `image`·`window`)."""


def _hwnd(text: str) -> int:
    try:
        value = int(text, 0)
    except ValueError:
        value = 0
    if value <= 0:
        raise SourceError(f"--hwnd {text!r}는 양의 정수가 아니다")
    return value


def load_frame(args: argparse.Namespace) -> Frame:
    """`--image`·`--window`·`--hwnd` 중 하나로 프레임 한 장."""
    if args.image is not None:
        path = Path(args.image)
        try:
            pixels = decode_image(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise SourceError(f"이미지 {path}을(를) 읽을 수 없다: {exc}") from exc
        return Frame(pixels, FrameMeta.of_image(pixels), {"kind": "image", "path": str(path)})
    return _capture_window(args.window, None if args.hwnd is None else _hwnd(args.hwnd))


def _capture_window(title: str | None, hwnd: int | None) -> Frame:
    from kookabug_core.win import dpi
    from kookabug_platform.capture import CaptureService
    from kookabug_platform.deadline import ObservationDeadline
    from kookabug_platform.tracker import WindowTracker
    from kookabug_platform.windows import find_window, window_info

    reason = dpi.enable_at_startup()
    if reason is not None:
        raise SourceError(reason, dpi.CODE)
    if hwnd is None:
        assert title is not None
        try:
            hwnd = find_window(title=title)
        except Exception as exc:  # 잘못된 /정규식/
            raise SourceError(f"--window {title!r}: {exc}") from exc
        if hwnd is None:
            raise SourceError(f"제목이 {title!r}에 맞는 창이 없다")
    tracker = WindowTracker()
    try:
        tracker.start()
        service = CaptureService(tracker)
        try:
            binding = tracker.bind(hwnd)
            captured = service.capture(binding, deadline=ObservationDeadline(CAPTURE_TIMEOUT_MS))
        finally:
            service.close_all()
        title_now = window_info(hwnd).title
    except PlatformError as exc:
        raise SourceError(str(exc), exc.code) from exc
    except OSError as exc:
        raise SourceError(f"창 {hwnd:#x}을(를) 캡처할 수 없다: {exc}") from exc
    finally:
        tracker.stop()
    meta = FrameMeta.of_capture(captured)
    source = {
        "kind": "window",
        "hwnd": hwnd,
        "title": title_now,
        "client_size": list(captured.info.client_size),
        "dpi": captured.info.dpi,
    }
    return Frame(captured.pixels, meta, source)


def candidate_json(candidate: Candidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "method": candidate.method,
        "scale": round(candidate.scale, 4),
        "rect": list(candidate.rect),
        "score": round(candidate.score, 4),
        "color_diff": None if candidate.color_diff is None else round(candidate.color_diff, 2),
        "accepted": candidate.accepted,
        "reason": candidate.reason or None,
    }


def result_json(result: FindResult) -> dict[str, Any]:
    match = result.match
    return {
        "found": result.found,
        "match": None
        if match is None
        else {
            "rect": list(match.rect),
            "score": round(match.score, 4),
            "scale": round(match.scale, 4),
            "method": match.method,
            "click": list(match.click),
        },
        "best": candidate_json(result.best),
        "threshold": result.threshold,
        "expected_scale": round(result.expected_scale, 4),
        "search": list(result.search),
        "candidates": [candidate_json(c) for c in result.candidates],
        "elapsed_ms": round(result.elapsed_ms, 1),
    }


def _default_out(target: Path) -> Path:
    # 워크스페이스에 파일을 늘리지 않게 임시 폴더에 쓴다
    stem = target.name.removesuffix(".json").removesuffix(".target")
    return Path(tempfile.gettempdir()) / "kookabug" / "target-test" / f"{stem}.png"


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    report: dict[str, Any] = {"command": "target test", "target": args.target}

    def finish(code: int, error: str | None = None, error_code: str | None = None) -> int:
        report.update(exit_code=code, error=error, error_code=error_code)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        elif error is not None:
            print(f"오류: {error}", file=err)
        return code

    target_path = Path(args.target)
    try:
        target = load_target_file(target_path)
        frame = load_frame(args)
        report["source"] = frame.source
        result = Vision().find(frame.pixels, frame.meta, target, exhaustive=args.all_scales)
    except TargetFileError as exc:
        return finish(EXIT_USAGE, str(exc))
    except SourceError as exc:
        return finish(EXIT_USAGE, str(exc), exc.code)
    except PlatformError as exc:
        return finish(EXIT_USAGE, str(exc), exc.code)
    report.update(result_json(result))

    preview = Path(args.out) if args.out is not None else _default_out(target_path)
    image = render_preview(frame.pixels, frame.meta, result, show_all=args.all_scales)
    try:
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(encode_png(image))
    except OSError as exc:
        return finish(EXIT_USAGE, f"미리보기 {preview}을(를) 쓸 수 없다: {exc}")
    report["preview"] = str(preview)

    code = EXIT_FOUND if result.found else EXIT_NOT_FOUND
    if not args.json:
        _print_human(result, preview, out)
    return finish(code)


def _print_human(result: FindResult, preview: Path, out: TextIO) -> None:
    best = result.best
    if result.match is not None:
        m = result.match
        print(
            f"찾음: 점수 {m.score:.3f} (임계값 {result.threshold:.2f}), 배율 {m.scale:.2f}, "
            f"방법 {m.method}, 상자 {list(m.rect)}, 클릭 {list(m.click)}",
            file=out,
        )
    elif best is not None:
        why = {"threshold": "점수 미달", "color": "색 확인 실패"}.get(best.reason, best.reason)
        print(
            f"못 찾음 ({why}): 최고 점수 {best.score:.3f} (임계값 {result.threshold:.2f}), "
            f"배율 {best.scale:.2f}, 방법 {best.method}, 상자 {list(best.rect)}",
            file=out,
        )
    else:
        print("못 찾음: 검색 범위가 이미지보다 작다", file=out)
    print(f"미리보기: {preview}", file=out, flush=True)

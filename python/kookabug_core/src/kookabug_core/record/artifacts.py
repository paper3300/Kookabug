"""스텝 artifacts 저장과 기록 정책 집행 (`Recorder`).

모든 저장은 `Recorder`를 거친다: `ctx.artifacts.save`, 예외 스크린샷, (M1) 캡처 노드.

- 스크린샷은 스텝의 실효 정책(구간 끄기·비밀값 입력)과 **획득 당시 표시**를 둘 다 통과해야 남긴다.
  막히면 저장하지 않고 `step.end.omitted`에 `{kind, name, reason, source}`를 남긴다. 판정은 바꾸지
  않는다
- 캡처 표시: 런타임이 캡처할 때마다 이미지에 실행 안 번호(`Image.capture_id`)를 붙이고, 얻은
  스텝에서 스크린샷이 막혔으면 그 번호에 이유를 남긴다. 번호는 복사·출력·워커 경계를 넘어도
  이미지에 남으므로, 꺼 둔 구간이나 비밀값 스텝에서 얻은 프레임은 나중에 켜진 스텝이 저장하려 해도
  막힌다 (`capture_policy`). 바이트만 있는 이미지도 같다. 같은 화면을 켜진 스텝이 새로 얻으면 새
  캡처다
- 예외 스크린샷: 노드가 `error`로 끝나면 **그 스텝 안에서 얻은 마지막 캡처**만 후보다. 그 스텝에서
  캡처가 없으면 남기지 않는다
- 실패 증거(M1 2.15): 처리되지 않은 fail이 확정된 스텝은 **그 스텝 아래(자기와 안쪽 스텝)에서
  얻은 마지막 캡처**를 `steps/<스텝>_fail`로 남긴다. 안쪽 스텝이 닫힐 때 그 마지막 캡처를 부른
  스텝으로 올린다(부른 스텝의 것보다 나중일 때만). 그 아래에서 캡처가 없으면 남기지 않는다
- 서브그래프 호출 스텝의 실패·예외 증거는 호출 노드의 비밀값 입력으로 막지 않는다(구간 끄기와 획득
  당시 표시는 본다). 그 프레임은 안쪽 스텝이 얻은 것이고, 비밀값을 받은 안쪽 스텝의 프레임은 획득
  당시 표시로 막히므로 안쪽 스텝 각각이 남길 수 있는 것보다 넓게 남기지 않는다 (M1 T12)
- OCR 글자: 스텝 안에서 마지막으로 읽은 글자를 스텝을 닫을 때 `steps/<스텝>_ocr.txt`로 남긴다.
  `sensitive` target으로 읽은 적이 있으면 남기지 않고 `sensitive_target`, 그 밖에는 스크린샷과
  같은 정책(구간 끄기·비밀값 입력·획득 당시 표시)을 따른다 — 화면에서 읽은 글자도 화면이다
- 경로는 실행 폴더 기준 `steps/<스텝>_<이름>`. 이미지 파일을 복사할 때는 확장자를 붙인다
- 프레임 저장소(M1 2.7, `FrameRegistry`)가 있으면 캡처 픽셀은 저장소에 있고 노드는 픽셀 없는
  **참조 이미지**(`capture_id`만)를 받는다. 참조 이미지를 남길 때는 저장소 픽셀을 PNG로 인코딩해
  `.png`로 둔다. 기록 정책 판정은 인코딩 전에 `capture_id`로 한다(막힌 프레임은 인코딩도 안 함)
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Protocol, cast

from kookabug_core.record.policy import OmitReason, RecordPolicy, StepPolicy, VideoMode, find_secret
from kookabug_sdk import Secret
from kookabug_sdk.types import Image, Match, WindowRef

__all__ = [
    "ERROR_SCREENSHOT",
    "FAIL_SCREENSHOT",
    "OCR_TEXT",
    "STEPS_DIR",
    "ArtifactStore",
    "CaptureMeta",
    "FileArtifacts",
    "FrameRegistry",
    "Recorder",
    "StagedFrame",
    "artifact_path",
    "image_artifact_path",
    "is_reference_image",
]

STEPS_DIR: Final = "steps"
ERROR_SCREENSHOT: Final = "error"
"""예외 스크린샷의 이름 (`steps/<스텝>_error.png`)."""
FAIL_SCREENSHOT: Final = "fail"
"""실패 증거의 이름 (`steps/<스텝>_fail.png`, M1 2.15)."""
OCR_TEXT: Final = "ocr.txt"
"""스텝의 마지막 OCR 글자 (`steps/<스텝>_ocr.txt`)."""

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactStore(Protocol):
    """artifacts를 실제로 두는 곳. 정책은 보지 않는다 (`Recorder`가 본다)."""

    def save(self, step: str, image: Image, name: str) -> str:
        """저장하고 실행 폴더 기준 경로를 돌려준다."""
        ...

    def save_text(self, step: str, name: str, text: str) -> str: ...


@dataclass(frozen=True, slots=True)
class CaptureMeta:
    """캡처 하나의 관측 조건 (찾기·OCR·재검증용, M1 2.5).

    `client_size`·`dpi`는 캡처 순간 대상 창의 것, `origin`은 픽셀 (0, 0)의 클라이언트 좌표(영역
    캡처면 영역 왼쪽 위), `backend`는 캡처 방식(`wgc`·`fake`), `window`는 캡처한 창(SDK 참조),
    `observed_at`은 관측 시각(벽시계 초), `frame`은 프레임 번호.
    """

    client_size: tuple[int, int]
    dpi: int = 96
    origin: tuple[int, int] = (0, 0)
    backend: str = "image"
    window: WindowRef | None = None
    observed_at: float | None = None
    frame: int | None = None


@dataclass(frozen=True, slots=True)
class StagedFrame:
    """플랫폼이 캡처한 픽셀과 그 동일성 키 — 저장소에 등록하기 전 (M1 2.7).

    `key`가 같으면 같은 픽셀이다(같은 프레임·같은 자르기). 코어는 `pixels`를 열지 않는다.
    `meta`는 그 캡처의 관측 조건이다 (저장소가 캡처 번호와 함께 둔다).
    """

    key: Hashable
    pixels: Any = field(repr=False)
    meta: CaptureMeta | None = field(default=None, repr=False, compare=False)


class FrameRegistry(Protocol):
    """실행의 프레임 저장소 (`kookabug_platform.frames.FrameStore`). 코어는 이 모양만 안다."""

    def register(self, capture_id: int, staged: StagedFrame, step: str) -> None:
        """캡처 하나를 그 스텝의 프레임으로 등록한다."""
        ...

    def close_step(self, step: str, *, parent: str | None = None) -> None:
        """스텝이 닫혔다: 그 스텝 증거 등급을 푼다. `parent`(부른 스텝)를 주면 마지막 캡처를 그
        스텝의 증거로 넘긴다 (실패 증거, M1 2.15)."""
        ...

    def mark_output(self, capture_id: int) -> None:
        """스텝 출력(이미지 핀·`Match`)으로 나간 캡처 (출력 참조 등급)."""
        ...

    def encode_png(self, capture_id: int) -> bytes:
        """그 캡처의 픽셀을 PNG로. 버린 프레임이면 `frame_expired`."""
        ...


def is_reference_image(image: Image) -> bool:
    """픽셀 없는 참조 이미지인가 (`data`·`path` 없이 `capture_id`만)."""
    return image.data is None and image.path is None and image.capture_id is not None


def artifact_path(step: str, name: str, suffix: str, taken: Callable[[str], bool]) -> str:
    """`steps/<스텝>_<이름><확장자>`. 이름의 경로 문자는 `_`로 바꾸고, 이미 쓴 경로면 `-2`, `-3`….

    `suffix`(`.png` 등)는 이름이 그것으로 끝나지 않을 때만 붙인다.
    """
    safe = _UNSAFE.sub("_", name).strip("._") or "artifact"
    if suffix and not safe.lower().endswith(suffix.lower()):
        safe += suffix
    stem, dot, ext = safe.rpartition(".")
    if not dot or not stem:
        stem, ext = safe, ""
    path = f"{STEPS_DIR}/{step}_{safe}"
    n = 2
    while taken(path):
        path = f"{STEPS_DIR}/{step}_{stem}-{n}{'.' + ext if ext else ''}"
        n += 1
    return path


def image_artifact_path(step: str, image: Image, name: str, taken: Callable[[str], bool]) -> str:
    """이미지 artifact 경로. 바이트(`data`)가 우선이고, 파일(`path`)을 복사할 때만 확장자를
    붙인다."""
    suffix = image.path.suffix if image.data is None and image.path is not None else ""
    return artifact_path(step, name, suffix, taken)


class FileArtifacts:
    """실행 폴더(`folder`)의 `steps/`에 파일로 둔다. `Image.data`면 바이트, `Image.path`면 복사."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _taken(self, rel: str) -> bool:
        return (self.folder / rel).exists()

    def _target(self, rel: str) -> Path:
        path = self.folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, step: str, image: Image, name: str) -> str:
        if image.data is None and image.path is None:
            raise ValueError(f"저장할 이미지 내용이 없다 (path·data 둘 다 없음): '{name}'")
        rel = image_artifact_path(step, image, name, self._taken)
        if image.data is not None:
            self._target(rel).write_bytes(image.data)
        else:
            assert image.path is not None
            shutil.copyfile(image.path, self._target(rel))
        return rel

    def save_text(self, step: str, name: str, text: str) -> str:
        rel = artifact_path(step, name, "", self._taken)
        self._target(rel).write_text(text, encoding="utf-8", newline="\n")
        return rel


@dataclass(frozen=True, slots=True)
class _CaptureMark:
    step: str
    block: tuple[OmitReason, str | None]
    """획득한 스텝에서 스크린샷을 막은 이유와 위치."""


@dataclass(frozen=True, slots=True)
class _OcrRead:
    text: str
    image: Image
    sensitive: bool


@dataclass(eq=False)
class _StepRecord:
    policy: StepPolicy
    artifacts: list[str] = field(default_factory=list[str])
    omitted: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    last_capture: Image | None = None
    """이 스텝이 직접 얻은 마지막 캡처 (예외 스크린샷)."""
    last_under: Image | None = None
    """이 스텝과 안쪽 스텝이 얻은 마지막 캡처 (실패 증거)."""
    ocr: _OcrRead | None = None
    """마지막으로 읽은 OCR 글자."""
    ocr_sensitive: bool = False
    """`sensitive` target으로 읽은 적이 있다."""
    call: bool = False
    """서브그래프 호출 스텝 (실패·예외 증거는 비밀값 입력으로 막지 않는다)."""


class Recorder:
    """한 실행의 기록 정책 집행. 실행기가 스텝마다 `open_step` → … → `close_step`을 부른다."""

    def __init__(self, store: ArtifactStore, frames: FrameRegistry | None = None) -> None:
        self.store = store
        self.frames = frames
        """프레임 저장소 (없으면 캡처 이미지가 바이트·파일을 그대로 든다 — M0b)."""
        self._open: dict[str, _StepRecord] = {}
        self._policies: dict[str, StepPolicy] = {}
        self._captures = 0
        self._blocked: dict[int, _CaptureMark] = {}
        """막힌 캡처만 (`capture_id` → 표시). 없으면 얻을 때 허용된 것이다."""

    # ------------------------------------------------------------ 스텝 수명

    def open_step(self, step: str, policy: RecordPolicy, *, call: bool = False) -> None:
        """`call`이면 서브그래프 호출 스텝이다: 그 스텝의 실패·예외 증거(안쪽 스텝이 얻은 프레임)는
        호출 노드의 비밀값 입력으로 막지 않는다. 비밀값을 받은 안쪽 스텝의 프레임은 획득 당시
        표시가 막으므로, 남는 것은 안쪽 스텝이 스스로 남길 수 있던 프레임뿐이다."""
        record = _StepRecord(StepPolicy(policy), call=call)
        self._open[step] = record
        self._policies[step] = record.policy

    def note_inputs(self, step: str, inputs: Mapping[str, Any], where: str) -> None:
        """스텝 시작 때 계산한 입력. 비밀값이 있으면 그 스텝의 스크린샷을 막는다.

        `where`는 노드 입력의 위치(`<그래프>#/nodes/<노드>/in`)로, 생략 이유의 `source` 앞에 붙는다.
        """
        found = find_secret(inputs)
        if found is None:
            return
        record = self._open[step]
        record.policy = StepPolicy(record.policy.policy, where + found)
        self._policies[step] = record.policy

    def close_step(
        self, step: str, *, parent: str | None = None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """스텝을 닫고 `(artifacts, omitted)`를 돌려준다. 스텝의 마지막 캡처는 놓는다 — `parent`
        (부른 스텝)를 주면 그 스텝 아래의 마지막 캡처로 올린다(프레임 저장소에서도 그 스텝의 증거로
        넘긴다). OCR 글자는 그 전에 `ocr_artifact`로 남긴다."""
        record = self._open.pop(step, None)
        above = self._open.get(parent) if parent is not None else None
        if self.frames is not None:
            self.frames.close_step(step, parent=parent if above is not None else None)
        if record is None:
            return [], []
        last = record.last_under
        if above is not None and last is not None and _later(last, above.last_under):
            above.last_under = last
        return record.artifacts, record.omitted

    def note_outputs(self, outputs: Mapping[str, Any]) -> None:
        """스텝 출력에 든 캡처(이미지·`Match`의 `capture_id`)를 출력 참조로 표시한다. 이미 버린
        캡처는 건너뛴다(출력은 그대로 남고, 나중에 쓰면 `frame_expired`)."""
        if self.frames is None:
            return
        # engine 패키지가 이 모듈을 import한다 (_masked_text와 같은 이유로 늦게)
        from kookabug_core.engine.errors import EngineError

        for capture_id in _capture_ids(outputs):
            try:
                self.frames.mark_output(capture_id)
            except EngineError:
                continue

    def policy(self, step: str) -> StepPolicy:
        return self._policies[step]

    # ------------------------------------------------------------ 캡처·저장

    def captured(self, step: str, image: Image, staged: StagedFrame | None = None) -> Image:
        """캡처 표시: 실행 안 새 `capture_id`를 붙인 이미지를 돌려주고, 얻은 스텝에서 스크린샷이
        막혔으면 그 이유를 그 번호에 남긴다. 노드에는 돌려준 이미지를 준다.

        플랫폼이 주는 이미지의 `frame`·`path`·바이트와 상관없이 캡처마다 번호가 하나씩이다.
        `staged`(저장소에 둘 픽셀)를 주면 그 번호로 프레임 저장소에 등록한다.
        """
        record = self._open.get(step)
        if record is None:
            return image
        self._captures += 1
        tagged = replace(image, capture_id=self._captures)
        if staged is not None:
            if self.frames is None:
                raise RuntimeError("프레임 저장소 없이 저장소용 픽셀을 받았다")
            self.frames.register(self._captures, staged, step)
        record.last_capture = record.last_under = tagged
        block = record.policy.screenshot_block()
        if block is not None:
            self._blocked[self._captures] = _CaptureMark(step, block)
        return tagged

    def screenshot(
        self, step: str, image: Image, name: str, *, evidence: bool = False
    ) -> str | None:
        """정책을 통과하면 저장하고 경로를, 막히면 `omitted`에 남기고 None을 준다. `evidence`는
        실행기가 남기는 실패·예외 증거다(호출 스텝이면 비밀값 입력을 보지 않는다)."""
        record = self._open[step]
        block = self._block(record, image, secret=not (evidence and record.call))
        if block is not None:
            reason, source = block
            entry: dict[str, Any] = {"kind": "screenshot", "name": name, "reason": reason}
            if source is not None:
                entry["source"] = source
            record.omitted.append(entry)
            return None
        if is_reference_image(image) and self.frames is not None:
            assert image.capture_id is not None
            image = replace(image, data=self.frames.encode_png(image.capture_id))
            if not name.lower().endswith(".png"):
                name += ".png"
        path = self.store.save(step, image, name)
        record.artifacts.append(path)
        return path

    def error_screenshot(self, step: str) -> str | None:
        """노드가 `error`로 끝났을 때: 그 스텝의 마지막 캡처를 (정책이 허용하면) 남긴다."""
        record = self._open.get(step)
        if record is None or record.last_capture is None:
            return None
        return self.screenshot(step, record.last_capture, ERROR_SCREENSHOT, evidence=True)

    def fail_screenshot(self, step: str) -> str | None:
        """처리되지 않은 fail이 그 스텝에서 확정됐을 때: 그 스텝 아래(자기와 안쪽 스텝)의 마지막
        캡처를 (정책이 허용하면) 남긴다 (M1 2.15)."""
        record = self._open.get(step)
        if record is None or record.last_under is None:
            return None
        return self.screenshot(step, record.last_under, FAIL_SCREENSHOT, evidence=True)

    def ocr_read(self, step: str, image: Image, text: str, *, sensitive: bool) -> None:
        """그 스텝에서 읽은 OCR 글자 (스텝을 닫을 때 마지막 것을 남긴다)."""
        record = self._open.get(step)
        if record is None:
            return
        record.ocr = _OcrRead(text, image, sensitive)
        record.ocr_sensitive = record.ocr_sensitive or sensitive

    def ocr_artifact(self, step: str) -> None:
        """스텝을 닫기 전에: 그 스텝에서 마지막으로 읽은 OCR 글자를 남긴다 (또는 생략 이유)."""
        record = self._open.get(step)
        if record is None or record.ocr is None:
            return
        read = record.ocr
        record.ocr = None
        block: tuple[OmitReason, str | None] | None = (
            ("sensitive_target", None) if record.ocr_sensitive else self._block(record, read.image)
        )
        if block is None:
            record.artifacts.append(self.store.save_text(step, OCR_TEXT, read.text))
            return
        entry: dict[str, Any] = {"kind": "text", "name": "ocr", "reason": block[0]}
        if block[1] is not None:
            entry["source"] = block[1]
        record.omitted.append(entry)

    def text(self, step: str, name: str, value: Any) -> str:
        """텍스트 artifact. 비밀값은 가린다 (M0b는 텍스트 구간 끄기가 없다)."""
        record = self._open[step]
        path = self.store.save_text(step, name, _masked_text(value))
        record.artifacts.append(path)
        return path

    def _block(
        self, record: _StepRecord, image: Image, *, secret: bool = True
    ) -> tuple[OmitReason, str | None] | None:
        # 저장하는 스텝의 정책이 먼저 (더 구체적인 이유), 그다음 획득 당시 표시
        block = record.policy.screenshot_block(secret=secret)
        if block is not None:
            return block
        mark = self._blocked.get(image.capture_id) if image.capture_id is not None else None
        if mark is not None:
            return "capture_policy", mark.block[1]
        return None

    # ------------------------------------------------------------ 영상 (M3)

    def video_policy(self, step: str) -> VideoMode:
        return self._policies[step].video

    def video_allowed(self, step: str, *, run_failed: bool) -> bool:
        """이 스텝 구간의 영상을 남겨도 되는가 (`failed_only`는 실행이 실패했을 때만)."""
        mode = self.video_policy(step)
        return mode == "on" or (mode == "failed_only" and run_failed)


def _later(image: Image, than: Image | None) -> bool:
    """`image`가 `than`보다 나중에 얻은 캡처인가 (캡처 번호는 실행 안에서 늘어난다)."""
    if than is None:
        return True
    return (image.capture_id or 0) > (than.capture_id or 0)


def _capture_ids(value: Any) -> list[int]:
    found: list[int] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Image):
            if item.capture_id is not None:
                found.append(item.capture_id)
        elif isinstance(item, Match):
            if item.frame_info is not None and item.frame_info.capture_id is not None:
                found.append(item.frame_info.capture_id)
        elif isinstance(item, Mapping):
            stack.extend(cast(Mapping[Any, Any], item).values())
        elif isinstance(item, list | tuple):
            stack.extend(cast(Sequence[Any], item))
    return found


def _masked_text(value: Any) -> str:
    # engine 패키지가 이 모듈을 import한다 (engine/__init__ → context → Recorder). 순환을 피한다
    from kookabug_core.engine.events import event_value

    if isinstance(value, str):
        return value
    if isinstance(value, Secret):
        return Secret.MASK
    return json.dumps(event_value(value), ensure_ascii=False, sort_keys=True, indent=2)

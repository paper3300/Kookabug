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
- 경로는 실행 폴더 기준 `steps/<스텝>_<이름>`. 이미지 파일을 복사할 때는 확장자를 붙인다
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Protocol

from kookabug_core.record.policy import OmitReason, RecordPolicy, StepPolicy, VideoMode, find_secret
from kookabug_sdk import Secret
from kookabug_sdk.types import Image

__all__ = [
    "ERROR_SCREENSHOT",
    "STEPS_DIR",
    "ArtifactStore",
    "FileArtifacts",
    "Recorder",
    "artifact_path",
    "image_artifact_path",
]

STEPS_DIR: Final = "steps"
ERROR_SCREENSHOT: Final = "error"
"""예외 스크린샷의 이름 (`steps/<스텝>_error.png`)."""

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactStore(Protocol):
    """artifacts를 실제로 두는 곳. 정책은 보지 않는다 (`Recorder`가 본다)."""

    def save(self, step: str, image: Image, name: str) -> str:
        """저장하고 실행 폴더 기준 경로를 돌려준다."""
        ...

    def save_text(self, step: str, name: str, text: str) -> str: ...


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


@dataclass(eq=False)
class _StepRecord:
    policy: StepPolicy
    artifacts: list[str] = field(default_factory=list[str])
    omitted: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    last_capture: Image | None = None


class Recorder:
    """한 실행의 기록 정책 집행. 실행기가 스텝마다 `open_step` → … → `close_step`을 부른다."""

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store
        self._open: dict[str, _StepRecord] = {}
        self._policies: dict[str, StepPolicy] = {}
        self._captures = 0
        self._blocked: dict[int, _CaptureMark] = {}
        """막힌 캡처만 (`capture_id` → 표시). 없으면 얻을 때 허용된 것이다."""

    # ------------------------------------------------------------ 스텝 수명

    def open_step(self, step: str, policy: RecordPolicy) -> None:
        record = _StepRecord(StepPolicy(policy))
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

    def close_step(self, step: str) -> tuple[list[str], list[dict[str, Any]]]:
        """스텝을 닫고 `(artifacts, omitted)`를 돌려준다. 스텝의 마지막 캡처는 놓는다."""
        record = self._open.pop(step, None)
        if record is None:
            return [], []
        return record.artifacts, record.omitted

    def policy(self, step: str) -> StepPolicy:
        return self._policies[step]

    # ------------------------------------------------------------ 캡처·저장

    def captured(self, step: str, image: Image) -> Image:
        """캡처 표시: 실행 안 새 `capture_id`를 붙인 이미지를 돌려주고, 얻은 스텝에서 스크린샷이
        막혔으면 그 이유를 그 번호에 남긴다. 노드에는 돌려준 이미지를 준다.

        플랫폼이 주는 이미지의 `frame`·`path`·바이트와 상관없이 캡처마다 번호가 하나씩이다.
        """
        record = self._open.get(step)
        if record is None:
            return image
        self._captures += 1
        tagged = replace(image, capture_id=self._captures)
        record.last_capture = tagged
        block = record.policy.screenshot_block()
        if block is not None:
            self._blocked[self._captures] = _CaptureMark(step, block)
        return tagged

    def screenshot(self, step: str, image: Image, name: str) -> str | None:
        """정책을 통과하면 저장하고 경로를, 막히면 `omitted`에 남기고 None을 준다."""
        record = self._open[step]
        block = self._block(record, image)
        if block is not None:
            reason, source = block
            entry: dict[str, Any] = {"kind": "screenshot", "name": name, "reason": reason}
            if source is not None:
                entry["source"] = source
            record.omitted.append(entry)
            return None
        path = self.store.save(step, image, name)
        record.artifacts.append(path)
        return path

    def error_screenshot(self, step: str) -> str | None:
        """노드가 `error`로 끝났을 때: 그 스텝의 마지막 캡처를 (정책이 허용하면) 남긴다."""
        record = self._open.get(step)
        if record is None or record.last_capture is None:
            return None
        return self.screenshot(step, record.last_capture, ERROR_SCREENSHOT)

    def text(self, step: str, name: str, value: Any) -> str:
        """텍스트 artifact. 비밀값은 가린다 (M0b는 텍스트 구간 끄기가 없다)."""
        record = self._open[step]
        path = self.store.save_text(step, name, _masked_text(value))
        record.artifacts.append(path)
        return path

    def _block(self, record: _StepRecord, image: Image) -> tuple[OmitReason, str | None] | None:
        # 저장하는 스텝의 정책이 먼저 (더 구체적인 이유), 그다음 획득 당시 표시
        block = record.policy.screenshot_block()
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


def _masked_text(value: Any) -> str:
    # engine 패키지가 이 모듈을 import한다 (engine/__init__ → context → Recorder). 순환을 피한다
    from kookabug_core.engine.events import event_value

    if isinstance(value, str):
        return value
    if isinstance(value, Secret):
        return Secret.MASK
    return json.dumps(event_value(value), ensure_ascii=False, sort_keys=True, indent=2)

"""기록 정책 (스키마 v0 6장 "화면에 찍힌 비밀값").

- 실효 정책 = 워크스페이스 → 테스트 그래프 → (호출 노드 → 서브그래프)를 호출 깊이만큼 → 노드.
  항목마다 한 번이라도 `off`면 `off`이고 아래에서 다시 켤 수 없다. `video`는
  `on` < `failed_only` < `off`로 센 쪽이 이긴다
- 정책을 끈 곳(`source`)은 그 항목을 처음 가장 세게 만든 층이다 (위가 아래를 이긴다)
- 스텝의 입력(재귀)에 비밀값이 있으면 그 스텝의 스크린샷·영상을 남기지 않는다 (`secret_input`)

    policy = RecordPolicy().layer(ws.config.get("record"), "kookabug.json#/record")
    policy.screenshots  # "on" | "off"
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from kookabug_core.diagnostics import json_pointer
from kookabug_sdk import Secret

__all__ = [
    "OmitReason",
    "RecordPolicy",
    "ScreenshotMode",
    "StepPolicy",
    "VideoMode",
    "find_secret",
    "graph_source",
    "node_inputs_source",
    "node_source",
]

type ScreenshotMode = Literal["on", "off"]
type VideoMode = Literal["on", "failed_only", "off"]
type OmitReason = Literal["secret_input", "policy_off", "capture_policy"]

_VIDEO_STRENGTH: Final[dict[str, int]] = {"on": 0, "failed_only": 1, "off": 2}
_VIDEO_MODES: Final[dict[Any, VideoMode]] = {"on": "on", "failed_only": "failed_only", "off": "off"}


def graph_source(graph: str) -> str:
    """그래프(또는 `kookabug.json`) 최상위 `record`의 위치."""
    return f"{graph}#/record"


def node_source(graph: str, node: str) -> str:
    return f"{graph}#{json_pointer('nodes', node, 'record')}"


def node_inputs_source(graph: str, node: str) -> str:
    """노드 입력(`in`)의 위치. 비밀값 위치는 이 뒤에 값 안의 pointer를 붙인다."""
    return f"{graph}#{json_pointer('nodes', node, 'in')}"


@dataclass(frozen=True, slots=True)
class RecordPolicy:
    """실효 기록 정책. `sources`는 항목(`screenshots`·`video`) → 그 값을 정한 층."""

    screenshots: ScreenshotMode = "on"
    video: VideoMode = "on"
    sources: Mapping[str, str] = field(default_factory=dict[str, str])

    def layer(self, record: Mapping[str, Any] | None, source: str) -> RecordPolicy:
        """한 층(`record` 객체, 없으면 그대로)을 더한다. 더 엄격한 값만 받아들인다."""
        if not record:
            return self
        sources = dict(self.sources)
        screenshots = self.screenshots
        video = self.video
        if record.get("screenshots") == "off" and screenshots != "off":
            screenshots = "off"
            sources["screenshots"] = source
        wanted = _VIDEO_MODES.get(record.get("video"))
        if wanted is not None and _VIDEO_STRENGTH[wanted] > _VIDEO_STRENGTH[video]:
            video = wanted
            sources["video"] = source
        if screenshots == self.screenshots and video == self.video:
            return self
        return replace(self, screenshots=screenshots, video=video, sources=sources)


@dataclass(frozen=True, slots=True)
class StepPolicy:
    """스텝 하나의 기록 판단. `secret`은 입력 안 첫 비밀값의 위치 (없으면 None)."""

    policy: RecordPolicy
    secret: str | None = None

    def screenshot_block(self) -> tuple[OmitReason, str | None] | None:
        """스크린샷을 막는 이유와 그 위치. 남겨도 되면 None."""
        if self.policy.screenshots == "off":
            return "policy_off", self.policy.sources.get("screenshots")
        if self.secret is not None:
            return "secret_input", self.secret
        return None

    @property
    def video(self) -> VideoMode:
        """이 스텝 구간의 영상 정책. 비밀값 입력 스텝은 영상도 남기지 않는다."""
        return "off" if self.secret is not None else self.policy.video


def find_secret(value: Any, pointer: str = "") -> str | None:
    """값 트리(list·tuple·dict 재귀)에서 첫 비밀값의 JSON pointer. 없으면 None."""
    if isinstance(value, Secret):
        return pointer
    if isinstance(value, Mapping):
        items: Mapping[Any, Any] = value
        for key, inner in items.items():
            found = find_secret(inner, pointer + json_pointer(str(key)))
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        seq: list[Any] | tuple[Any, ...] = value
        for i, inner in enumerate(seq):
            found = find_secret(inner, pointer + json_pointer(i))
            if found is not None:
                return found
    return None

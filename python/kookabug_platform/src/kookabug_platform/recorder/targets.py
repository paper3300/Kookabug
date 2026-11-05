"""녹화 target 초안·재사용·이름 (M4 계획 2.6 "재사용"·"이름"·"세션 안 중복 정리", 검수 M1, T6).

**재사용**은 "같은 그림"이 아니라 **재생했을 때 같은 점을 누르는가**로 정한다. 후보(이 세션의 초안,
워크스페이스 `targets/` 중 녹화 비율이 같은 것)마다 재생과 같은 규칙(`Vision.find` — 그 target의
검색 범위·방법·임계값·색 허용치, 클릭 직전 프레임 전체)으로 찾고, 찾은 **클릭 점**
(`anchor + offset x 배율`)이 녹화 클릭과 같은 요소 안이면(경계 추정 상자가 있으면 그 상자 안,
고정 크기 대비면 4 px 이내) 그 target을 쓴다. 여럿이면 점수가 높은 것.

**이름**: 상자 안 OCR 글자(파일 이름에 쓸 수 있게, 20자), 없으면 `click_<순번>`. 상자가 보호
영역과 겹치면 OCR하지 않고, 결과가 세션의 보호 대상 원문을 포함하면 버린다(`safe_name`).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.protect import Box, ProtectionSet, safe_name
from kookabug_platform.recorder.crop import ClickCrop, target_spec
from kookabug_platform.vision import (
    FrameMeta,
    Pixels,
    TargetImage,
    TargetSpec,
    Vision,
    load_target_file,
)

__all__ = [
    "MAX_WORKSPACE_CANDIDATES",
    "Candidate",
    "SessionTargets",
    "TargetDraft",
    "find_reuse",
    "name_for_box",
    "workspace_candidates",
]

MAX_WORKSPACE_CANDIDATES: Final = 200
POINT_SLACK: Final = 4
"""고정 크기 대비 상자면 재생 클릭 점이 녹화 점에서 이만큼 안이어야 같은 요소."""

type ReadText = Callable[[Pixels, Box], str | None]
"""이름용 OCR: 클라이언트 그림·상자 → 글자 (못 읽으면 None)."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """재사용 후보. `key`는 워크스페이스 기준 target 경로 또는 세션 초안 ID."""

    key: str
    spec: TargetSpec
    source: str  # "workspace" | "session"


@dataclass
class TargetDraft:
    """이 세션이 만든 target 초안 (아직 파일이 아님). 픽셀은 보호 영역 검사를 거친 상자다."""

    draft_id: str
    name: str
    pixels: Pixels
    spec: dict[str, object]
    box: Box
    frame_t_ns: int | None
    uses: int = 1

    @property
    def image_path(self) -> Path:
        """`Vision` 캐시 이름 (파일이 아니다)."""
        return Path(f"<draft>/{self.draft_id}.png")

    def as_spec(self) -> TargetSpec:
        click = self.spec.get("click") or {}
        recorded = self.spec.get("recorded") or {}
        search = self.spec.get("search") or {}
        assert isinstance(click, dict) and isinstance(recorded, dict) and isinstance(search, dict)
        offset = click.get("offset", [0, 0])
        size = recorded.get("client_size")
        region = search.get("region")
        return TargetSpec(
            name=self.name,
            image_path=self.image_path,
            offset=(float(offset[0]), float(offset[1])),
            recorded_size=None if size is None else (int(size[0]), int(size[1])),
            recorded_dpi=recorded.get("dpi"),
            search_region=None if region is None else tuple(region),  # pyright: ignore[reportArgumentType]
        )


def _same_element(click: tuple[int, int], crop: ClickCrop) -> bool:
    if crop.element is not None:
        x, y, w, h = crop.element
        return x <= click[0] < x + w and y <= click[1] < y + h
    px, py = crop.point
    return abs(click[0] - px) <= POINT_SLACK and abs(click[1] - py) <= POINT_SLACK


def find_reuse(
    vision: Vision,
    image: Pixels,
    meta: FrameMeta,
    crop: ClickCrop,
    candidates: Iterable[Candidate],
) -> Candidate | None:
    """재생 규칙으로 찾은 클릭 점이 녹화 클릭과 같은 요소인 후보 (점수가 가장 높은 것)."""
    best: tuple[float, Candidate] | None = None
    for candidate in candidates:
        try:
            result = vision.find(image, meta, candidate.spec)
        except Exception:  # 깨진 target 파일·이미지는 후보에서 뺀다
            continue
        match = result.match
        if match is None or not _same_element(match.click, crop):
            continue
        if best is None or match.score > best[0]:
            best = (match.score, candidate)
    return None if best is None else best[1]


def _same_ratio(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return abs(a[0] * b[1] - a[1] * b[0]) <= 0.01 * a[0] * b[1]


def workspace_candidates(
    root: Path,
    client_size: tuple[int, int],
    *,
    folders: Sequence[str] = (),
) -> list[Candidate]:
    """워크스페이스 `targets/` 아래 녹화 비율이 같은 target. 200개를 넘으면 `folders`(세션
    그래프가 이미 쓴 target 폴더)만."""
    base = root / "targets"
    if not base.is_dir():
        return []
    paths = sorted(base.rglob("*.target.json"))
    if len(paths) > MAX_WORKSPACE_CANDIDATES:
        wanted = {f.rstrip("/") for f in folders}
        paths = [p for p in paths if p.parent.relative_to(root).as_posix() in wanted]
    found: list[Candidate] = []
    for path in paths:
        try:
            spec = TargetSpec.of(load_target_file(path))
        except Exception:
            continue
        if spec.recorded_size is None or not _same_ratio(spec.recorded_size, client_size):
            continue
        found.append(Candidate(path.relative_to(root).as_posix(), spec, "workspace"))
    return found


def name_for_box(
    image: Pixels,
    box: Box,
    *,
    read_text: ReadText | None,
    protect: ProtectionSet | None,
    t_ns: int | None,
    raw_texts: Iterable[SecretText],
    fallback: str,
) -> str:
    """이름용 OCR (보호 영역과 겹치면 하지 않음) → `safe_name`."""
    if read_text is None or (protect is not None and protect.overlaps(box, t_ns, image)):
        return fallback
    try:
        text = read_text(image, box)
    except Exception:
        text = None
    return safe_name(text, raw_texts, fallback)


@dataclass
class SessionTargets:
    """세션의 target 초안과 재사용 후보. 같은 단추를 두 번 누르면 초안 하나를 같이 쓴다."""

    vision: Vision
    workspace: list[Candidate] = field(default_factory=list[Candidate])
    drafts: dict[str, TargetDraft] = field(default_factory=dict[str, TargetDraft])
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def candidates(self) -> list[Candidate]:
        session = [Candidate(d.draft_id, d.as_spec(), "session") for d in self.drafts.values()]
        return [*session, *self.workspace]

    def resolve(
        self,
        image: Pixels,
        meta: FrameMeta,
        crop: ClickCrop,
        *,
        name: Callable[[int], str],
        frame_t_ns: int | None,
    ) -> tuple[str, str]:
        """클릭 하나의 target: 재사용이면 (`reuse`, 경로·초안 ID), 아니면 새 초안 (`draft`, ID).
        `name(순번)`은 새 초안 이름을 짓는다 (보호 규칙은 부르는 쪽, `name_for_box`)."""
        if crop.box is None:
            raise ValueError("target을 못 만든 클릭이다")
        reused = find_reuse(self.vision, image, meta, crop, self.candidates())
        if reused is not None:
            if reused.source == "session":
                self.drafts[reused.key].uses += 1
                return "draft", reused.key
            return "reuse", reused.key
        number = next(self._ids)
        draft_id = f"d{number}"
        x, y, w, h = crop.box
        pixels = image[y : y + h, x : x + w].copy()
        spec = target_spec(
            f"{number:02d}_{draft_id}.png",
            client_size=meta.client_size,
            dpi=meta.dpi,
            offset=crop.offset,
            search_region=crop.search_region,
        )
        draft = TargetDraft(draft_id, name(number), pixels, spec, crop.box, frame_t_ns)
        self.drafts[draft_id] = draft
        self.vision.put_image(TargetImage.of_pixels(pixels, draft.image_path))
        return "draft", draft_id

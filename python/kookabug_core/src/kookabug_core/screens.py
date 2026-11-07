"""화면 판정 파일 `*.screen.json` (구현 계획 M1 2.10, M7 계획 3.1, 스키마 v0 4장 "화면 판정 파일").

- 화면 ID = 파일 이름 줄기(`screens/lobby/server_list.screen.json` → `server_list`). `screens/`
  아래 어디에 둬도 되고, `screens/_explored/`(Agent 탐색 결과, 사람 확인 전)는 보지 않는다
- 같은 ID의 파일이 둘 이상이면 그 ID는 모호하다(`screen_ambiguous`)
- `detect.all`(전부 보임)·`detect.none`(하나도 안 보임)
- 형식 `kookabug.screen/0`(M1: 조건은 `$target`만)과 `/1`(M7 화면 지도: OCR 조건·설명·종류·UI 요소·
  이동·대표 스크린샷·출처, 후보 전용 `of`). 둘 다 읽는다
- 후보(`screens/_explored/<세션>/<키>.screen.json`)는 `detect`가 없어도 되고(`incomplete` —
  승격 불가) `of`를 쓸 수 있다. 확정 화면(`screens/`의 나머지)은 `detect`가 있어야 하고 `of`를
  쓰지 않는다

여기는 파일 찾기·형식만 다룬다. 판정(이미지 매칭·OCR)은 `kookabug_platform.screens`가 한다. 실행
중 화면 판정으로 실행을 바꾸지 않는다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.canonical import loads_strict
from kookabug_core.schema import check_shape
from kookabug_core.workspace import Workspace

__all__ = [
    "EXPLORED_DIR",
    "EXPLORE_FILE",
    "KEY_PATTERN",
    "MISPLACED",
    "RESERVED_NAMES",
    "SCREENS_DIR",
    "SESSION_PATTERN",
    "SUFFIX",
    "Condition",
    "ExploredCandidate",
    "OcrCondition",
    "ScreenDef",
    "ScreenElement",
    "ScreenFileError",
    "ScreenMove",
    "ScreenOrigin",
    "ScreenShot",
    "candidate_ref",
    "explored_candidates",
    "is_explored",
    "is_screen_key",
    "parse_screen",
    "read_screen_file",
    "screen_id",
    "screen_index",
]

SCREENS_DIR: Final = "screens"
EXPLORED_DIR: Final = "_explored"
EXPLORE_FILE: Final = "explore.json"
SUFFIX: Final = ".screen.json"
KEY_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")
"""새 화면 ID·후보 키 규칙 (M7 3.1). 기존 `/0` 화면 ID는 파일 이름 그대로 둔다."""
SESSION_PATTERN: Final = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}")
"""탐색 세션 ID `<UTC yyyymmdd-HHMMSS>-<4 hex>` (M7 3.2)."""

type Rect = tuple[float, float, float, float]
_EDGE: Final = 1e-6  # 정규화 사각형 끝 비교 여유 (부동소수 반올림)


class ScreenFileError(Exception):
    """화면 파일을 읽을 수 없거나 형식이 틀렸다."""


@dataclass(frozen=True, slots=True)
class OcrCondition:
    """OCR 조건: 정규화 영역 `rect`에서 읽은 글자에 `text`가 들어 있다 (공백·대소문자 무시)."""

    rect: Rect
    text: str
    match: Literal["contains"] = "contains"


@dataclass(frozen=True, slots=True)
class Condition:
    """판정 조건 하나. `target`(워크스페이스 기준 `*.target.json`)과 `ocr` 중 하나만 있다."""

    group: Literal["all", "none"]
    target: str | None = None
    ocr: OcrCondition | None = None


@dataclass(frozen=True, slots=True)
class ScreenShot:
    image: str
    client_size: tuple[int, int]
    scale: float = 1.0


@dataclass(frozen=True, slots=True)
class ScreenElement:
    name: str
    kind: Literal["button", "text", "field", "list"]
    rect: Rect


@dataclass(frozen=True, slots=True)
class ScreenMove:
    """이동 하나. `via`는 `element`(요소 클릭)·`point`(점 클릭)·`key` 중 하나만 있다."""

    status: Literal["tried", "untried"]
    to: str | None
    element: str | None = None
    point: tuple[float, float] | None = None
    key: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ScreenOrigin:
    kind: Literal["explored"]
    session: str
    agent: str | None = None
    at: str | None = None


@dataclass(frozen=True, slots=True)
class ScreenDef:
    """화면 하나. `all`·`none`은 `$target` 조건의 target 경로(워크스페이스 루트 기준)만이고,
    OCR 조건까지 순서대로 든 것은 `conditions`다(`/1`). `version`은 형식 번호(0·1)."""

    id: str
    path: str
    title: str | None
    all: tuple[str, ...]
    none: tuple[str, ...]
    version: int = 0
    conditions: tuple[Condition, ...] = ()
    description: str | None = None
    kind: Literal["screen", "popup"] = "screen"
    shot: ScreenShot | None = None
    elements: tuple[ScreenElement, ...] = ()
    moves: tuple[ScreenMove, ...] = ()
    origin: ScreenOrigin | None = None
    of: str | None = None

    @property
    def targets(self) -> tuple[str, ...]:
        """`detect`의 target 경로들 (스냅샷·검증이 따라가는 것은 이것뿐, 대표 스크린샷은 아님)."""
        return (*self.all, *self.none)

    def detect(self) -> tuple[Condition, ...]:
        """판정 조건 전부 (`all` 다음 `none`, 파일 순서)."""
        if self.conditions:
            return self.conditions
        return (
            *(Condition("all", target=t) for t in self.all),
            *(Condition("none", target=t) for t in self.none),
        )

    @property
    def incomplete(self) -> bool:
        """판정 조건도 합칠 화면(`of`)도 없는 후보 (새 화면으로 승격할 수 없다). `of` 후보는
        조건이 없어도 확정 화면 조건으로 합치므로 미완성이 아니다."""
        return not self.all and not self.none and not self.conditions and self.of is None


def screen_id(path: str | Path) -> str:
    """파일 경로 → 화면 ID (파일 이름에서 `.screen.json`을 뺀 것)."""
    name = Path(path).name if isinstance(path, Path) else path.rsplit("/", 1)[-1]
    if not name.endswith(SUFFIX):
        raise ValueError(f"{name}은(는) {SUFFIX} 파일이 아니다")
    return name[: -len(SUFFIX)]


RESERVED_NAMES: Final = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{n}" for n in range(1, 10)),
        *(f"lpt{n}" for n in range(1, 10)),
    }
)
"""Windows 예약 장치 이름 — 파일 이름 줄기로 쓰면 그 장치를 연다 (M7 B4)."""


def is_screen_key(text: str) -> bool:
    """새 화면 ID·후보 키 규칙에 맞는가 (Windows 예약 장치 이름은 안 된다)."""
    return KEY_PATTERN.fullmatch(text) is not None and text not in RESERVED_NAMES


def _parts(rel: str) -> list[str]:
    return rel.replace("\\", "/").strip("/").split("/")


def is_explored(rel: str) -> bool:
    """워크스페이스 기준 경로가 `screens/_explored/` 아래인가 (대소문자 무시). 이런 파일은 후보
    규칙(`detect` 생략·`of` 허용)으로 읽는다 — 배치가 맞는지는 `candidate_ref`가 본다."""
    parts = _parts(rel)
    return (
        len(parts) > 2
        and parts[0].casefold() == SCREENS_DIR
        and parts[1].casefold() == EXPLORED_DIR.casefold()
    )


def candidate_ref(rel: str) -> tuple[str, str] | None:
    """정확한 후보 배치 `screens/_explored/<세션 ID>/<키>.screen.json`이면 (세션, 키).

    세션 ID 형식(`SESSION_PATTERN`)과 키 규칙(`KEY_PATTERN`)까지 맞아야 한다. 그 밖의 `_explored/`
    파일(바로 아래·더 깊은 곳·형식 밖 이름)은 읽기만 되고 확인·승격 대상이 아니다.
    """
    parts = _parts(rel)
    if len(parts) != 4 or not is_explored(rel) or not parts[3].endswith(SUFFIX):
        return None
    session, key = parts[2], parts[3][: -len(SUFFIX)]
    if SESSION_PATTERN.fullmatch(session) is None or not is_screen_key(key):
        return None
    return session, key


def screen_index(workspace: Workspace) -> dict[str, list[str]]:
    """워크스페이스의 화면 ID → 파일 경로들(루트 기준, 정렬). `_explored/`는 뺀다."""
    base = workspace.root / SCREENS_DIR
    index: dict[str, list[str]] = {}
    if not base.is_dir():
        return index
    for path in base.rglob(f"*{SUFFIX}"):
        rel_parts = path.relative_to(base).parts
        if rel_parts[0] == EXPLORED_DIR or not path.is_file():
            continue
        rel = "/".join((SCREENS_DIR, *rel_parts))
        index.setdefault(screen_id(path), []).append(rel)
    for paths in index.values():
        paths.sort()
    return index


MISPLACED: Final = (
    "탐색 결과 배치가 잘못됐다: screens/_explored/<세션 ID>/<키>.screen.json만 후보다 "
    "(읽기만 하고 확인·승격 대상이 아니다)"
)


@dataclass(frozen=True, slots=True)
class ExploredCandidate:
    """`screens/_explored/` 아래 화면 파일 하나.

    `placement`가 `session`이면 정확한 후보 배치(`session`·`key` 있음), `misplaced`면 그 밖의 자리
    (`session` None, `key`는 파일 이름 줄기 — 읽기만 한다). 읽지 못했으면 `screen`이 None이다.
    `problem`은 읽기 실패 이유 또는 배치 진단.
    """

    session: str | None
    key: str
    path: str
    screen: ScreenDef | None
    problem: str | None = None
    placement: Literal["session", "misplaced"] = "session"

    @property
    def promotable(self) -> bool:
        """사람 확인(승격·합치기) 대상인가: 정확한 배치, 읽힘, 미완성이 아님."""
        return (
            self.placement == "session" and self.screen is not None and not self.screen.incomplete
        )


def explored_candidates(workspace: Workspace) -> list[ExploredCandidate]:
    """`screens/_explored/` 아래 화면 파일 전부 (경로 순). 링크·정션 폴더는 따라가지 않는다."""
    base = workspace.root / SCREENS_DIR / EXPLORED_DIR
    found: list[ExploredCandidate] = []
    if not base.is_dir():
        return found
    for path in _walk(base):
        rel = "/".join((SCREENS_DIR, EXPLORED_DIR, *path.relative_to(base).parts))
        ref = candidate_ref(rel)
        session, key = ref if ref is not None else (None, screen_id(path))
        placement: Literal["session", "misplaced"] = "session" if ref else "misplaced"
        note = None if ref else MISPLACED
        try:
            screen = read_screen_file(path, rel)
        except ScreenFileError as exc:
            problem = str(exc) if note is None else f"{note}; {exc}"
            found.append(ExploredCandidate(session, key, rel, None, problem, placement))
            continue
        found.append(ExploredCandidate(session, key, rel, screen, note, placement))
    return found


def _walk(base: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d for d in dirnames if not ((here / d).is_symlink() or (here / d).is_junction())
        )
        out.extend(
            here / f for f in sorted(filenames) if f.endswith(SUFFIX) and (here / f).is_file()
        )
    return sorted(out, key=lambda p: p.relative_to(base).parts)


def parse_screen(data: Any, rel: str) -> ScreenDef:
    """형식 검사 → `ScreenDef`. 틀리면 `ScreenFileError`.

    `rel`이 `screens/_explored/` 아래면 후보 규칙(`detect` 없어도 됨, `of` 허용)으로 본다.
    """
    problems = check_shape(data, "screen", file=rel)
    if problems:
        detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:3])
        raise ScreenFileError(f"화면 파일 '{rel}'의 형식이 틀렸다: {detail}")
    version = 1 if data["format"] == "kookabug.screen/1" else 0
    detect: Mapping[str, Any] = data.get("detect", {})
    conditions = tuple(
        _condition(group, item, rel) for group in ("all", "none") for item in detect.get(group, ())
    )

    def refs(group: str) -> tuple[str, ...]:
        return tuple(c.target for c in conditions if c.group == group and c.target is not None)

    sid = screen_id(rel)
    if version == 0:
        return ScreenDef(sid, rel, data.get("title"), refs("all"), refs("none"))
    candidate = is_explored(rel)
    if not candidate and not conditions:
        raise ScreenFileError(f"화면 파일 '{rel}'에 판정 조건(detect)이 없다")
    if not candidate and "of" in data:
        raise ScreenFileError(f"화면 파일 '{rel}': of는 탐색 후보(screens/_explored/)만 쓴다")
    elements = tuple(
        ScreenElement(e["name"], e["kind"], _rect(e["rect"], rel, "elements"))
        for e in data.get("elements", ())
    )
    names = [e.name for e in elements]
    if len(set(names)) != len(names):
        raise ScreenFileError(f"화면 파일 '{rel}': UI 요소 이름이 겹친다")
    moves = tuple(_move(m, set(names), rel) for m in data.get("moves", ()))
    shot = data.get("shot")
    origin = data.get("origin")
    return ScreenDef(
        sid,
        rel,
        data.get("title"),
        refs("all"),
        refs("none"),
        version=1,
        conditions=conditions,
        description=data.get("description"),
        kind=data.get("kind", "screen"),
        shot=None
        if shot is None
        else ScreenShot(
            shot["image"], (shot["client_size"][0], shot["client_size"][1]), shot.get("scale", 1.0)
        ),
        elements=elements,
        moves=moves,
        origin=None
        if origin is None
        else ScreenOrigin(origin["kind"], origin["session"], origin.get("agent"), origin.get("at")),
        of=data.get("of"),
    )


def _condition(group: Literal["all", "none"], item: Mapping[str, Any], rel: str) -> Condition:
    if "$target" in item:
        return Condition(group, target=item["$target"])
    ocr = item["ocr"]
    if not "".join(ocr["text"].split()):
        raise ScreenFileError(f"화면 파일 '{rel}': OCR 조건의 text가 공백뿐이다")
    return Condition(group, ocr=OcrCondition(_rect(ocr["rect"], rel, "OCR 조건"), ocr["text"]))


def _rect(values: Sequence[float], rel: str, where: str) -> Rect:
    x, y, w, h = (float(v) for v in values)
    if w <= 0 or h <= 0 or x + w > 1 + _EDGE or y + h > 1 + _EDGE:
        where = f"화면 파일 '{rel}': {where}의 사각형 {list(values)}"
        raise ScreenFileError(f"{where}이(가) 클라이언트 영역(0~1) 밖이거나 비었다")
    return (x, y, w, h)


def _move(data: Mapping[str, Any], names: set[str], rel: str) -> ScreenMove:
    via: Mapping[str, Any] = data["via"]
    to = data.get("to")
    status = data["status"]
    if status == "tried" and to is None:
        raise ScreenFileError(f"화면 파일 '{rel}': 가 본 이동(tried)에는 to가 있어야 한다")
    click = via.get("click")
    if click is not None and "element" in click:
        if click["element"] not in names:
            raise ScreenFileError(
                f"화면 파일 '{rel}': 이동의 요소 '{click['element']}'이(가) elements에 없다"
            )
        return ScreenMove(status, to, element=click["element"], note=data.get("note"))
    if click is not None:
        x, y = (float(v) for v in click["point"])
        return ScreenMove(status, to, point=(x, y), note=data.get("note"))
    # 키 표는 engine 패키지를 거쳐 로더를 다시 부르므로 쓸 때 읽는다 (import 고리)
    from kookabug_core.inputs.keys import KeyUnknown, canonical_key, split_combo

    key = str(via["key"])
    try:
        for name in split_combo(key):
            canonical_key(name)
    except KeyUnknown as exc:
        raise ScreenFileError(f"화면 파일 '{rel}': 이동의 키 '{key}'을(를) 모른다 ({exc})") from exc
    return ScreenMove(status, to, key=key, note=data.get("note"))


def read_screen_file(path: Path, rel: str) -> ScreenDef:
    """파일 하나를 읽는다. `rel`은 진단·ID용 이름(워크스페이스 기준 경로 또는 파일 이름)."""
    try:
        data = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ScreenFileError(f"화면 파일 '{rel}'을(를) 읽을 수 없다: {exc}") from exc
    return parse_screen(data, rel)

"""금지 동작 판정 (M8 계획 3.7, 9장 R6) — 엄격: 입력 안전·비밀값. **판정 함수는 `judge` 하나**다.

대상은 Agent 주체의 모든 입력이다: Agent 연결의 제어 입력(`control.click/key/type` — daemon이 입력
전에 부르고, 그 제어 실행의 runner도 입력 직전에 다시 부른다)과 Agent가 시작한 그래프 실행의
입력(`effects ∋ input` 노드·워커 노드의 `ctx.input` — 실행기의 공용 입력 경로 `CheckedInput`이
입력 직전에 부른다). 사람 입력·사람·CI 실행·자동 채택 검증 실행과 감독자의 키·버튼 떼기·입력
복구는 이 판정을 거치지 않는다(그 경로는 `CheckedInput`을 지나지 않는다).

판정 (입력 직전 프레임 하나, 메모리에서만):

- 금지 목록이 비면 검사하지 않는다(비용 없음)
- 금지 화면이 지금 화면이거나 금지 target이 보이거나 금지 문구(공백·대소문자 무시 `contains`)가
  화면 어디든 보이면 그 입력(클릭·키·문자 모두)을 거부한다 — `forbidden_visible{kind, value}`.
  클릭 둘레 검사(3.7)는 이 규칙에 포함된다(둘레에 보이면 화면에도 보인다)
- 프레임 없음·화면 식별 실패·target 조회 실패·OCR 실패·보호 화면(글자 항목)은 "안 보임"이 아니라
  거부다 — `forbidden_unverifiable{kind, value?, reason}`
- 응답·오류·로그에는 걸린 항목(정책 값)과 고정 사유만 둔다. OCR 글자 원문은 남기지 않는다

`kookabug.json` `automation.forbidden`이 형식이 틀리거나 읽을 수 없으면 항목을 비우지 않고
`ForbiddenConfigError` — 호출자는 확인 못 함(`forbidden_unverifiable`)으로 거부한다(fail closed).
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

from kookabug_core.canonical import loads_strict
from kookabug_core.workspace import WORKSPACE_FILE

__all__ = [
    "UNVERIFIABLE",
    "VISIBLE",
    "ForbiddenConfigError",
    "Item",
    "PixelSight",
    "Refusal",
    "Sight",
    "UnresolvablePath",
    "Unverifiable",
    "from_spec",
    "items_from",
    "judge",
    "load_items",
    "normalize",
    "protected_paths",
    "real_key",
    "to_spec",
]

VISIBLE: Final = "forbidden_visible"
UNVERIFIABLE: Final = "forbidden_unverifiable"
Kind = Literal["text", "target", "screen"]
_VALUE_KEY: Final[Mapping[str, str]] = {"text": "value", "target": "path", "screen": "id"}


class ForbiddenConfigError(Exception):
    """금지 목록을 읽을 수 없다 (형식·파일). 메시지는 고정 글자."""


class Unverifiable(Exception):
    """화면을 확인하지 못했다. `reason`은 고정 사유 이름."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Item:
    kind: Kind
    value: str
    """문구·target 경로·화면 ID (정책 값 — 비밀값이 아니다)."""


@dataclass(frozen=True, slots=True)
class Refusal:
    code: Literal["forbidden_visible", "forbidden_unverifiable"]
    kind: str | None
    value: str | None
    reason: str

    def fields(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "reason": self.reason}

    def message(self) -> str:
        what = f"{self.kind} {self.value!r}" if self.kind and self.value else "금지 동작"
        if self.code == VISIBLE:
            return f"금지 동작({what})이 화면에 보여 입력하지 않았다"
        return f"금지 동작을 확인하지 못해({self.reason}) 입력하지 않았다 — {what}"


# ---------------------------------------------------------------- 목록


def items_from(raw: Any) -> tuple[Item, ...]:
    """`automation.forbidden` 값 → 항목. 형식이 틀리면 `ForbiddenConfigError`."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ForbiddenConfigError("automation.forbidden이 배열이 아니다")
    out: list[Item] = []
    for entry in cast(list[Any], raw):
        if not isinstance(entry, Mapping):
            raise ForbiddenConfigError("automation.forbidden 항목이 객체가 아니다")
        item = cast(Mapping[str, Any], entry)
        kind = item.get("kind")
        key = _VALUE_KEY.get(kind) if isinstance(kind, str) else None
        value = item.get(key) if key is not None else None
        if key is None or not isinstance(value, str) or not value.strip():
            raise ForbiddenConfigError("automation.forbidden 항목 형식이 틀렸다")
        out.append(Item(cast(Kind, kind), value))
    return tuple(out)


def load_items(root: Path) -> tuple[Item, ...]:
    """`kookabug.json`의 금지 목록 (원문 그대로 읽는다 — 형식이 틀린 설정을 빈 목록으로 보지
    않는다)."""
    try:
        config = loads_strict((root / WORKSPACE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ForbiddenConfigError("kookabug.json을 읽을 수 없다") from exc
    if not isinstance(config, Mapping):
        raise ForbiddenConfigError("kookabug.json이 객체가 아니다")
    automation = cast(Mapping[str, Any], config).get("automation")
    if automation is None:
        return ()
    if not isinstance(automation, Mapping):
        raise ForbiddenConfigError("automation이 객체가 아니다")
    return items_from(cast(Mapping[str, Any], automation).get("forbidden"))


class UnresolvablePath(ForbiddenConfigError):
    """경로를 실제 경로로 풀 수 없거나 워크스페이스 밖이다."""


_LINK_HOPS: Final = 40
"""직접 푸는 `realpath`가 따라가는 링크·정션 수 상한 (넘으면 순환으로 본다)."""


def _realpath_allow_missing(path: str) -> str:
    """`realpath(strict=ALLOW_MISSING)`: 없는 조각은 그대로 붙이고, 그 밖의 OS 오류(링크 순환·
    접근 거부 등)는 `OSError`로 올린다. `ALLOW_MISSING`이 없는 Python이면 같은 의미로 직접 푼다."""
    allow = getattr(os.path, "ALLOW_MISSING", None)
    if allow is not None:
        return os.path.realpath(path, strict=allow)
    return _walk_real(path)


def _split_abs(path: str) -> tuple[str, list[str]]:
    full = os.path.abspath(path)
    drive, rest = os.path.splitdrive(full)
    anchor = drive + os.sep
    return anchor, [p for p in rest.replace("\\", "/").split("/") if p]


def _walk_real(path: str) -> str:
    """경로 조각마다 `lstat`·`readlink`로 푼다(링크 수 상한). 없는 조각에서 멈추고 나머지를
    붙인다."""
    import errno
    import stat

    current, pending = _split_abs(path)
    hops = 0
    while pending:
        part = pending.pop(0)
        if part == ".":
            continue
        if part == "..":
            current = os.path.dirname(current.rstrip("\\/")) or current
            continue
        candidate = os.path.join(current, part)
        try:
            info = os.lstat(candidate)
        except FileNotFoundError:
            return os.path.normpath(os.path.join(candidate, *pending))
        is_junction = getattr(os.path, "isjunction", lambda _p: False)(candidate)
        if not stat.S_ISLNK(info.st_mode) and not is_junction:
            current = candidate
            continue
        hops += 1
        if hops > _LINK_HOPS:
            raise OSError(errno.ELOOP, "링크를 너무 많이 따라갔다 (순환)")
        target = os.readlink(candidate)
        if target.startswith("\\\\?\\"):
            target = target[4:]
        if not os.path.isabs(target):
            target = os.path.join(current, target)
        current, rest = _split_abs(target)
        pending = rest + pending
    return current


def real_key(root: Path, rel: str) -> str:
    """워크스페이스 기준 경로의 **실제 경로 기준 비교 키** — 금지 판정이 읽는 경로(target·PNG·
    화면)와 Agent 쓰기 대상 경로를 모두 이것으로 비교한다(같은 비교는 한 함수로).

    워크스페이스 안에서 `realpath`(링크·정션·8.3 이름을 푼다) → 워크스페이스 실제 루트 기준 상대
    경로 → `adopt.path_key`(구분자·빈 조각·대소문자). 없는 파일(새로 만들 파일)은 있는 조상까지
    풀고 나머지를 붙인다. 링크 순환·접근 거부 같은 그 밖의 OS 오류, 워크스페이스 밖이면
    `UnresolvablePath`(기본 `realpath`처럼 오류를 삼키고 풀리지 않은 경로를 돌려주지 않는다).
    루트도 같은 정책으로 푼다."""
    from kookabug_core.adopt import path_key

    try:
        base = _realpath_allow_missing(os.fspath(root))
        parts = [p for p in rel.replace("\\", "/").split("/") if p]
        real = _realpath_allow_missing(os.path.join(base, *parts))
        relative = os.path.relpath(real, base)
    except (OSError, ValueError) as exc:
        raise UnresolvablePath("경로를 실제 경로로 풀 수 없다") from exc
    if os.path.isabs(relative) or relative == os.pardir or relative.startswith(os.pardir + os.sep):
        raise UnresolvablePath("경로가 워크스페이스 밖을 가리킨다")
    return path_key(relative)


def protected_paths(root: Path, items: Iterable[Item]) -> set[str]:
    """금지 판정이 읽는 팀 파일 (`real_key` 정규형): 금지 target과 그 PNG, 금지 화면 파일과 그 판정
    조건의 target·PNG. Agent는 이 파일들을 그래프·target 도구로 고치지 못한다 — 금지 target을
    "절대 안 찾히는" 그림으로 바꿔 판정을 비우는 옆 경로를 막는다. 판정은 링크·정션을 따라 실제
    파일을 읽으므로 키도 실제 경로다(별칭으로 적힌 금지 경로·별칭으로 쓰는 경로 모두 같은 키).
    어느 경로든 실제 경로로 풀 수 없거나 밖이면, 또 금지 target·화면 파일을 읽지 못하면(없음·형식
    오류) `UnresolvablePath`(fail closed — 쓰기 거부). 목록이 비면 빈 집합이다."""
    from kookabug_core.screens import screen_index
    from kookabug_core.workspace import Workspace

    out: set[str] = set()

    def read(rel: str, what: str) -> Any:
        # 판정이 읽을 파일을 못 읽으면(없음·형식 오류·해석 실패) 보호 목록을 비우지 않는다
        try:
            return loads_strict((root / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise UnresolvablePath(f"{what}을(를) 읽을 수 없다") from exc

    def target(rel: str) -> None:
        out.add(real_key(root, rel))
        value = read(rel, "금지 target 파일")
        if not isinstance(value, Mapping):
            raise UnresolvablePath("금지 target 파일 형식이 틀렸다")
        image = cast(Mapping[str, Any], value).get("image")
        if image is None:
            return
        if not isinstance(image, str):
            raise UnresolvablePath("금지 target 파일 형식이 틀렸다")
        found = Workspace.resolve_from(rel, image)
        if found is None:
            raise UnresolvablePath("금지 target의 이미지가 워크스페이스 밖을 가리킨다")
        out.add(real_key(root, found))

    def targets_in(value: Any) -> None:
        if isinstance(value, Mapping):
            mapping = cast(Mapping[str, Any], value)
            ref = mapping.get("$target")
            if isinstance(ref, str):
                target(ref)
            for v in mapping.values():
                targets_in(v)
        elif isinstance(value, list):
            for v in cast(list[Any], value):
                targets_in(v)

    screens: dict[str, list[str]] | None = None
    for item in items:
        if item.kind == "target":
            target(item.value)
        elif item.kind == "screen":
            if screens is None:
                try:
                    screens = screen_index(Workspace.open(root))
                except Exception as exc:
                    # 금지 화면 파일을 모르면 보호 목록을 비우지 않고 쓰기를 거부한다
                    raise ForbiddenConfigError("화면 목록을 읽을 수 없다") from exc
            for rel in screens.get(item.value, []):
                out.add(real_key(root, rel))
                targets_in(read(rel, "금지 화면 파일"))
    return out


def to_spec(items: Iterable[Item]) -> list[dict[str, str]]:
    return [{"kind": i.kind, "value": i.value} for i in items]


def from_spec(raw: Sequence[Mapping[str, Any]]) -> tuple[Item, ...]:
    return tuple(Item(cast(Kind, str(i["kind"])), str(i["value"])) for i in raw)


# ---------------------------------------------------------------- 판정


def normalize(text: str) -> str:
    """비교용: NFKC, 서식 문자·공백 제거, 대소문자 무시."""
    folded = unicodedata.normalize("NFKC", text)
    plain = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return "".join(plain.split()).casefold()


class Sight(Protocol):
    """입력 직전 화면 한 장 (메모리)."""

    def protected(self) -> str | None:
        """보호 화면이면 그 사유 (글자 항목을 확인하지 않는다), 아니면 None."""
        ...

    def screen_matches(self, screen_id: str) -> bool: ...

    def target_visible(self, rel: str) -> bool: ...

    def text(self) -> str:
        """화면 전체 글자 (`normalize`한 것). 글자는 판정에만 쓰고 밖으로 내지 않는다."""
        ...


def judge(items: Sequence[Item], sight: Sight | None) -> Refusal | None:
    """금지 판정 하나. 거부면 `Refusal`, 통과면 None. 보이는 항목이 하나라도 있으면 그것이 이유이고,
    없으면 확인 못 한 항목이 이유다."""
    if not items:
        return None
    if sight is None:
        return Refusal(UNVERIFIABLE, None, None, "no_frame")
    failure: Refusal | None = None

    def check(item: Item, probe: Callable[[], bool], reason: str) -> Refusal | None:
        nonlocal failure
        try:
            hit = probe()
        except Unverifiable as exc:
            failure = failure or Refusal(UNVERIFIABLE, item.kind, item.value, exc.reason)
            return None
        except Exception as exc:
            failure = failure or Refusal(
                UNVERIFIABLE, item.kind, item.value, f"{reason}:{type(exc).__name__}"
            )
            return None
        return Refusal(VISIBLE, item.kind, item.value, "visible") if hit else None

    for item in items:
        if item.kind == "screen":
            found = check(item, lambda i=item: sight.screen_matches(i.value), "screen_unverified")
        elif item.kind == "target":
            found = check(item, lambda i=item: sight.target_visible(i.value), "target_unverified")
        else:
            continue
        if found is not None:
            return found
    texts = [i for i in items if i.kind == "text"]
    if texts:
        protected = sight.protected()
        if protected is not None:
            return failure or Refusal(UNVERIFIABLE, "text", texts[0].value, protected)
        try:
            seen = sight.text()
        except Unverifiable as exc:
            return failure or Refusal(UNVERIFIABLE, "text", texts[0].value, exc.reason)
        except Exception as exc:
            # 사유에는 예외 종류 이름만 (메시지는 화면·경로 글자를 담을 수 있어 넣지 않는다)
            return failure or Refusal(
                UNVERIFIABLE, "text", texts[0].value, f"ocr_failed:{type(exc).__name__}"
            )
        for item in texts:
            needle = normalize(item.value)
            if needle and needle in seen:
                return Refusal(VISIBLE, "text", item.value, "visible")
    return failure


# ---------------------------------------------------------------- 픽셀 화면


class PixelSight:
    """BGR 픽셀 한 장의 `Sight` (daemon 제어 입력·runner 입력이 같이 쓴다). 플랫폼 패키지
    (`kookabug_platform`)는 판정할 때만 읽는다. `reader`는 `read(pixels) -> OcrResult`(없으면 글자
    항목은 확인 못 함)."""

    def __init__(
        self,
        root: Path,
        pixels: Any,
        *,
        reader: Any = None,
        protected: str | None = None,
        dpi: int = 96,
    ) -> None:
        self.root = root
        self.pixels = pixels
        self.reader = reader
        self._protected = protected
        self.dpi = dpi
        self._text: str | None = None

    def protected(self) -> str | None:
        return self._protected

    def _meta(self) -> Any:
        from kookabug_platform.vision import FrameMeta

        height, width = int(self.pixels.shape[0]), int(self.pixels.shape[1])
        return FrameMeta(client_size=(width, height), dpi=self.dpi)

    def _target(self, rel: str) -> Any:
        from kookabug_core.workspace import Workspace
        from kookabug_platform.vision import load_target_file
        from kookabug_sdk.types import Target

        path = Workspace.resolve_from("", rel)
        if path is None:
            raise Unverifiable("target_outside_workspace")
        try:
            found = load_target_file(self.root.joinpath(*path.split("/")))
        except Exception as exc:
            raise Unverifiable("target_unreadable") from exc
        return Target(name=rel, path=found.path, spec=found.spec)

    def target_visible(self, rel: str) -> bool:
        from kookabug_platform.vision import Vision

        found = Vision().find(self.pixels, self._meta(), self._target(rel))
        return found.match is not None

    def screen_matches(self, screen_id: str) -> bool:
        from kookabug_core.screens import read_screen_file, screen_index
        from kookabug_core.workspace import Workspace
        from kookabug_platform.screens import evaluate_screen
        from kookabug_platform.vision import Vision

        workspace = Workspace.open(self.root)
        paths = screen_index(workspace).get(screen_id) or []
        if len(paths) != 1:
            raise Unverifiable("screen_unknown")
        path = workspace.resolve(paths[0])
        if path is None:
            raise Unverifiable("screen_unknown")
        screen = read_screen_file(path, paths[0])
        if not screen.detect():
            raise Unverifiable("screen_without_detect")
        reader = None if self._protected is not None else self.reader
        result = evaluate_screen(
            screen, self._target, self.pixels, self._meta(), Vision(), ocr=reader
        )
        if result.state == "unknown":
            raise Unverifiable("screen_unverified")
        return result.state == "matched"

    def text(self) -> str:
        if self._text is None:
            if self.reader is None:
                raise Unverifiable("ocr_unavailable")
            self._text = normalize(str(self.reader.read(self.pixels).text))
        return self._text

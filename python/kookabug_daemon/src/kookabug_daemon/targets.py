"""target 편집: 합친 revision·미리보기·저장 (M2 계획 2.9, T6).

**revision** = `sha256(JSON 바이트) + ":" + sha256(image가 가리키는 파일 바이트)`. 이미지가 없거나
읽을 수 없거나 경로가 루트 밖·`.kookabug/`면 `missing`이다. 이미지만 밖에서 바뀌어도 달라진다.

**저장** (`TargetStore.save`). 워크스페이스에 **target 저장 잠금** 하나를 두고 아래 1~5단계 전체를
그 안에서 한다 (daemon 안의 두 저장은 같은 target이든 다른 target이든 끼어들지 못한다).
`crop`이 없으면(기존 파일만) 1단계 검사 뒤 이미지를 만들지 않고 지금 `image`·`recorded`를 그대로 둔
JSON만 4단계로 커밋한다 (조율자 결정: 사양만 고치는 저장).

1. 쓰기 전 검사 — 하나라도 걸리면 아무것도 쓰지 않는다: 경로(루트 안·`.kookabug/` 밖·`targets/`
   아래 `*.target.json`), revision(새 파일이면 없어야 하고 `exists`, 기존 파일이면 합친 revision이
   같아야 하고 `revision_conflict`), 사양(target 메타스키마·수 규칙, `target_invalid`),
   crop(살아 있는 프레임 안·너비·높이 1 이상). 권한은 전송이 처리기 앞에서 판정했다.
   **바로 매칭도 여기서 한다**: 채운 사양과 쓸 PNG 바이트로 그 정지 화면에서 찾아, 못 찾거나 결과를
   계약으로 나타낼 수 없으면(큰 클릭 오프셋 등) `target_invalid`로 거부한다. 응답의 `preview`는 이
   결과다(저장한 바이트와 같은 입력이라 다시 읽어 찾은 것과 같다)
2. 새 이미지는 **배타적 생성**(`open(path, "xb")`)으로만 만든다. 이름 후보는 target 옆
   `<줄기>.png` → `<줄기>-<sha 8>.png` → `-<sha 16>` → `-<sha 64>`. 이미 있으면 그 바이트의 sha256이
   같을 때만 재사용한다(쓰지 않고 소유 기록에도 넣지 않는다 — 남의 파일이다). 있는 파일은 절대
   바꾸지 않는다. 이 요청이 만든 파일만 `.kookabug/editor-images.json`(에디터 소유 기록)에 적는다
3. 사양을 채운다: `image` = 2의 이름, `recorded` = 정지 화면의 클라이언트 크기·DPI, 검색 범위는
   픽셀 왕복이 같은 정규화 값(`dpi.pixels_to_normalized`)
4. 커밋 = target JSON 한 번의 쓰기(`save_text`: 기존 파일이면 원문 보존). 쓰기 직전에 revision을
   다시 잰다. 새 파일은 덮어쓰지 않는 이름 바꾸기로 공개한다. 충돌이면 되돌린다 — 지우는 것은 이
   요청이 2단계에서 **직접 만든 파일 하나**뿐이고, 지금 sha256이 쓴 값과 같고, 디스크의 어떤
   `*.target.json`도 가리키지 않고, 소유 기록에 이 요청의 항목이 있을 때만이다
5. 옛 이미지 정리(커밋 뒤, 어떤 실패도 저장을 실패로 바꾸지 않고 경고가 된다): 소유 기록에 있고 지금
   sha256이 기록과 같고 새 이미지와 다르고 어떤 `*.target.json`도 가리키지 않는 파일만 지운다.
   **사용자가 넣은 PNG는 지우지 않는다.** 같은 target의 앞선 실패가 남긴 기록된 고아 이미지도 같은
   조건으로 정리한다. 커밋 뒤에는 이것 말고 실패할 수 있는 단계가 없다(revision은 쓴 바이트로
   정한다)

"어떤 target도 가리키지 않음"은 워크스페이스의 `*.target.json`을 **모두** 읽었을 때만 성립하고, 지울
이미지마다 지우기 직전에 다시 읽는다(정리 전체가 저장 잠금 안).
하나라도 읽지 못하면(잠김·권한·JSON 아님·폴더 열기 실패) 4·5단계 모두 이미지를 지우지 않는다
(경고·로그).

2와 4 사이에 실패하거나 프로세스가 죽으면 새로 만든 PNG 하나만 남는다(기존 target은 그대로).
기록되기 전에 죽은 고아는 소유를 증명할 수 없으므로 자동으로 지우지 않는다.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final

from kookabug_core.canonical import loads_strict, save_text
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.schema import check_shape
from kookabug_core.workspace import Workspace
from kookabug_daemon.documents import PRIVATE_NAME, WsPath, resolve_path
from kookabug_daemon.frames import EditorFrame, FrameCache, check_rect
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_sdk import _faults
from kookabug_sdk.types import Target

if TYPE_CHECKING:
    from kookabug_platform.errors import PlatformError
    from kookabug_platform.vision import FindResult, TargetImage

__all__ = [
    "OWNERSHIP_FILE",
    "OWNERSHIP_FORMAT",
    "TARGETS_DIR",
    "TARGET_FORMAT",
    "TARGET_SUFFIX",
    "Ownership",
    "SaveOutcome",
    "TargetStore",
    "combined_revision",
    "image_path_of",
    "preview_json",
    "read_bytes",
    "referenced_images",
    "require_platform",
    "target_path",
]

log = logging.getLogger("kookabug_daemon.targets")

TARGET_SUFFIX: Final = ".target.json"
TARGETS_DIR: Final = "targets"
TARGET_FORMAT: Final = "kookabug.target/0"
OWNERSHIP_FILE: Final = "editor-images.json"
OWNERSHIP_FORMAT: Final = "kookabug.editor-images/0"
MISSING: Final = "missing"
SKIP_DIRS: Final = frozenset({PRIVATE_NAME, "runs", ".git"})
"""참조를 찾을 때 건너뛰는 루트 바로 아래 폴더 (실행 스냅샷의 target은 스냅샷 안 이미지를
가리킨다)."""
_PLACEHOLDER: Final = "editor.png"

type Hook = Callable[[dict[str, Any]], None]


def require_platform() -> None:
    """target 편집 메서드는 kookabug-platform(opencv)이 있어야 한다. daemon 패키지는 그것을
    의존성으로 두지 않는다(`kookabug_cli`와 같다: 설치 파일은 둘 다 넣는다). 없으면
    `platform_unavailable`."""
    try:
        importlib.import_module("kookabug_platform.vision")
    except ImportError as exc:
        text = f"kookabug-platform이 없어 target 편집 메서드를 쓸 수 없다 ({exc})"
        raise RequestFailed("platform_unavailable", text, message=text) from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _target_invalid(text: str, diagnostics: Sequence[Diagnostic] = ()) -> RequestFailed:
    found = list(diagnostics) or [Diagnostic("error", "target_invalid", text)]
    return RequestFailed("target_invalid", text, diagnostics=[d.to_dict() for d in found])


def _io_error(text: str) -> RequestFailed:
    return RequestFailed("io_error", text, message=text)


# ---------------------------------------------------------------- 경로


def target_path(root: Path, given: str, *, save: bool = False) -> WsPath:
    """target 파일 경로 검사. 해석 전·후 이름이 `*.target.json`이어야 하고, 저장은 해석 전·후 모두
    `targets/` 아래여야 한다. 거부는 `RequestFailed`, 모양이 틀리면 `InvalidParams`."""
    where = resolve_path(root, given)
    if not (
        given.casefold().endswith(TARGET_SUFFIX)
        and where.path.name.casefold().endswith(TARGET_SUFFIX)
    ):
        raise InvalidParams(f"'{given}'은(는) target 파일(*{TARGET_SUFFIX})이 아니다", path=given)
    if save and not (
        given.split("/", 1)[0].casefold() == TARGETS_DIR
        and where.rel.split("/", 1)[0].casefold() == TARGETS_DIR
    ):
        raise InvalidParams(f"'{given}'은(는) {TARGETS_DIR}/ 아래가 아니다", path=given)
    return where


def _recheck(root: Path, where: WsPath, *, save: bool) -> WsPath:
    current = target_path(root, where.given, save=save)
    if current.key != where.key:
        raise RequestFailed(
            "not_found",
            f"'{where.given}'이(가) 검사한 뒤에 다른 파일({current.rel})을 가리킨다",
            path=where.given,
        )
    return current


def image_path_of(root: Path, target_rel: str, value: Any) -> WsPath | None:
    """target 값의 `image`가 가리키는 파일 (target 파일 기준 상대 경로). 루트 밖·`.kookabug/`·틀린
    경로면 None."""
    if not isinstance(value, dict):
        return None
    image: Any = value.get("image")  # pyright: ignore[reportUnknownMemberType]
    if not isinstance(image, str):
        return None
    rel = Workspace.resolve_from(target_rel, image)
    if rel is None:
        return None
    try:
        return resolve_path(root, rel)
    except RequestFailed, InvalidParams:
        return None


def read_bytes(path: Path) -> bytes | None:
    """지금 디스크 바이트 (파일이 없으면 None). 읽기 실패는 `io_error`."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _io_error(f"'{path}'을(를) 읽을 수 없다: {exc}") from exc


def _parse(data: bytes) -> Any:
    try:
        return loads_strict(data.decode("utf-8", errors="strict"))
    except UnicodeDecodeError, ValueError, RecursionError:
        return None


def combined_revision(root: Path, where: WsPath, data: bytes) -> str:
    """합친 revision (JSON 바이트 `data` + 그 JSON의 image가 가리키는 지금 디스크 파일)."""
    image = image_path_of(root, where.rel, _parse(data))
    image_hash = MISSING
    if image is not None:
        with contextlib.suppress(OSError):
            if image.path.is_file():
                image_hash = _sha(image.path.read_bytes())
    return f"{_sha(data)}:{image_hash}"


def _walk_targets(root: Path, failures: list[str]) -> Iterable[tuple[str, Path]]:
    """워크스페이스의 `*.target.json` (루트 기준 경로, 절대 경로). 링크 폴더는 따라가지 않는다.
    열지 못한 폴더는 `failures`에 적는다."""

    def failed(exc: OSError) -> None:
        failures.append(f"폴더 '{exc.filename}'을(를) 읽을 수 없다: {exc.strerror or exc}")

    for folder, dirs, files in os.walk(root, onerror=failed):
        here = Path(folder)
        if here == root:
            dirs[:] = [d for d in dirs if d.casefold() not in SKIP_DIRS]
        dirs[:] = [d for d in dirs if not (here / d).is_junction()]
        for name in files:
            if name.casefold().endswith(TARGET_SUFFIX):
                path = here / name
                yield path.relative_to(root).as_posix(), path


@dataclass(frozen=True, slots=True)
class References:
    """지금 디스크의 `*.target.json`이 가리키는 이미지 (`WsPath.key`).

    `failures`가 있으면 어떤 target(또는 폴더)을 읽지 못했다는 뜻이다. 그때는 "아무도 가리키지
    않음"을 증명할 수 없으므로 이미지를 지우지 않는다 (2차 검수 N1, T6 검수 1)."""

    keys: frozenset[str]
    failures: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.failures

    def unreferenced(self, image: WsPath) -> bool:
        """그 이미지를 아무 target도 가리키지 않음이 확실한가."""
        return self.complete and image.key not in self.keys


def referenced_images(root: Path) -> References:
    """지금 디스크의 모든 `*.target.json`을 읽어 가리키는 이미지를 모은다. 읽다 사라진 파일은
    가리키는 것이 없다. 읽기·JSON 해석에 실패한 파일은 `failures`에 남긴다(그 안의 참조를
    모른다)."""
    keys: set[str] = set()
    failures: list[str] = []
    for rel, path in _walk_targets(root, failures):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures.append(f"'{rel}'을(를) 읽을 수 없다: {exc.strerror or exc}")
            continue
        value = _parse(data)
        if value is None:
            failures.append(f"'{rel}'이(가) JSON이 아니다")
            continue
        image = image_path_of(root, rel, value)
        if image is not None:
            keys.add(image.key)
    return References(frozenset(keys), tuple(failures))


# ---------------------------------------------------------------- 에디터 소유 기록


@dataclass(frozen=True, slots=True)
class OwnedImage:
    path: str
    """워크스페이스 기준 경로."""
    sha256: str
    created_at: str
    target: str

    def to_json(self) -> dict[str, str]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "target": self.target,
        }


def _same_rel(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


class Ownership:
    """`.kookabug/editor-images.json`: 에디터가 배타적 생성으로 직접 만든 이미지 (이 PC 기준).

    읽을 수 없거나 형식이 틀리면 `load()`가 None이다(= 소유 파일 없음: 정리하지 않는다). 그 상태에서
    새 이미지를 만들면 기록을 새로 쓴다. 쓰기는 target 저장 잠금 안에서만 한다."""

    def __init__(self, root: Path) -> None:
        self.path = root / PRIVATE_NAME / OWNERSHIP_FILE

    def load(self) -> list[OwnedImage] | None:
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError:
            return None
        value = _parse(data)
        if not isinstance(value, dict) or value.get("format") != OWNERSHIP_FORMAT:  # pyright: ignore[reportUnknownMemberType]
            return None
        images: Any = value.get("images")  # pyright: ignore[reportUnknownMemberType]
        if not isinstance(images, list):
            return None
        found: list[OwnedImage] = []
        for item in images:  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(item, dict):
                return None
            fields: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
            if set(fields) != {"path", "sha256", "created_at", "target"} or not all(
                isinstance(v, str) for v in fields.values()
            ):
                return None
            found.append(OwnedImage(**fields))
        return found

    def _write(self, images: list[OwnedImage]) -> None:
        body = {"format": OWNERSHIP_FORMAT, "images": [i.to_json() for i in images]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.path, (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode())

    def add(self, image: OwnedImage) -> None:
        """기록에 더한다. 기록이 깨졌으면 이 항목 하나로 새로 쓴다. 쓰기 실패는 `DocumentError`."""
        images = self.load() or []
        images = [i for i in images if not _same_rel(i.path, image.path)]
        images.append(image)
        self._write(images)

    def remove(self, image: OwnedImage) -> None:
        """그 항목을 뺀다 (경로·sha256·만든 시각이 같은 것). 기록이 깨졌으면 그대로 둔다."""
        images = self.load()
        if images is None or image not in images:
            return
        self._write([i for i in images if i != image])

    def find(self, rel: str) -> OwnedImage | None:
        for image in self.load() or []:
            if _same_rel(image.path, rel):
                return image
        return None


# ---------------------------------------------------------------- 미리보기


def _fill_defaults(spec: Mapping[str, Any], image: str) -> dict[str, Any]:
    value = copy.deepcopy(dict(spec))
    value.setdefault("format", TARGET_FORMAT)
    value["image"] = image
    return value


def _check_spec(value: Mapping[str, Any], file: str | None) -> None:
    problems = check_shape(value, "target", file=file)
    if problems:
        detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:3])
        raise _target_invalid(f"target 사양 형식이 틀렸다: {detail}", problems)


def _fill_frame(value: dict[str, Any], frame: EditorFrame) -> None:
    """`recorded`는 정지 화면 메타, 검색 범위는 그 클라이언트 크기에서 픽셀 왕복이 같은 값으로."""
    recorded: dict[str, Any] = dict(value.get("recorded") or {})
    recorded["client_size"] = list(frame.client_size)
    recorded["dpi"] = frame.dpi
    value["recorded"] = recorded
    _snap_region(value, frame.client_size)


def _snap_region(value: dict[str, Any], client_size: tuple[int, int]) -> None:
    """검색 범위를 그 클라이언트 크기에서 픽셀 왕복이 같은 6자리 값으로. 비면 `target_invalid`."""
    from kookabug_platform.dpi import normalized_to_pixels, pixels_to_normalized

    search: Any = value.get("search")
    region: Any = search.get("region") if isinstance(search, dict) else None  # pyright: ignore[reportUnknownMemberType]
    if region is None:
        return
    pixels = normalized_to_pixels(tuple(region), client_size)
    if pixels[2] < 1 or pixels[3] < 1:
        raise _target_invalid(
            f"검색 범위 {region}이(가) 클라이언트 크기 {list(client_size)}에서 비었다",
            [Diagnostic("error", "target_invalid", "검색 범위가 비었다", pointer="/search/region")],
        )
    snapped = dict(search)  # pyright: ignore[reportUnknownArgumentType]
    snapped["region"] = list(pixels_to_normalized(pixels, client_size))
    value["search"] = snapped


def _crop_image(frame: EditorFrame, rect: Sequence[int]) -> tuple[Any, TargetImage]:
    from kookabug_platform.vision import TargetImage

    x, y, w, h = check_rect(frame, rect, what="템플릿 영역")
    pixels = frame.pixels[y : y + h, x : x + w]
    return pixels, TargetImage.of_pixels(pixels, Path(f"{frame.frame_id}.png"))


def preview_json(result: FindResult, seq: int) -> dict[str, Any]:
    """계약 `PreviewResult` = `target test --json` 필드 + 검색 범위 픽셀 + seq."""
    from kookabug_platform.report import result_json

    body = result_json(result)
    body["search_rect_px"] = list(result.search)
    body["seq"] = seq
    # 유한하지만 큰 클릭 오프셋(1e20 등)은 정수 범위를 넘는 좌표가 된다. 계약으로 보낼 수 없는
    # 결과는 응답 검사(-32603)까지 가지 않게 여기서 사양 오류로 막는다 (저장은 쓰기 전에 부른다)
    problems = check_shape(body, "daemon-rpc", ref="#/$defs/PreviewResult")
    if problems:
        detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:3])
        text = f"이 사양으로 찾은 결과를 나타낼 수 없다 (좌표가 정수 범위를 넘는다 등): {detail}"
        raise _target_invalid(text, [Diagnostic("error", "target_invalid", text)])
    return body


def _find(frame: EditorFrame, target: Target, image: TargetImage | None) -> FindResult:
    """정지 화면에서 찾는다. `image`가 있으면 파일 대신 그 픽셀을 템플릿으로 쓴다."""
    from kookabug_platform.vision import TargetSpec, Vision

    spec = TargetSpec.of(target)
    if image is None:
        return Vision().find(frame.pixels, frame.meta(), spec)

    class _Given(Vision):
        def target_image(self, spec: TargetSpec) -> TargetImage:
            return image

    return _Given().find(frame.pixels, frame.meta(), spec)


def platform_failed(exc: PlatformError) -> RequestFailed:
    """M1 플랫폼 오류 → daemon 오류 (코드 그대로, 계약 `RequestFailedCode`에 있다)."""
    return RequestFailed(exc.code, str(exc), message=str(exc))


# ---------------------------------------------------------------- 저장


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    image: str
    """`image` 파일의 워크스페이스 기준 경로 (crop이 없으면 지금 이미지)."""
    revision: str
    preview: dict[str, Any] | None
    """바로 매칭 결과. crop 없이 저장했으면 찾을 정지 화면이 없어 None."""
    warnings: list[str] = field(default_factory=list[str])


@dataclass(frozen=True, slots=True)
class _Created:
    where: WsPath
    sha256: str
    owned: OwnedImage | None
    """기록에 넣은 항목 (기록하지 못했으면 None)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class TargetStore:
    """target 열기·미리보기·저장. 메서드는 막히는 호출이다(`asyncio.to_thread`로 부른다).

    `hooks`는 검사용 장벽이다(같은 프로세스): 이름 → `fn(정보)`. 지점은 `checks`(잠금을 잡은 직후),
    `publish`(이름 후보마다 `xb` 직전, `path`), `image_write`(새 PNG 쓰는 중), `before_record`,
    `before_commit`(`image`·`target`), `json_write`(JSON 쓰기 직전), `deleted`(정리가 옛 이미지
    하나를 지운 직후, `path`). `before_record`·`before_commit`은 하위 프로세스 검사용 고장 주입
    지점(`target.*`)이기도 하다."""

    def __init__(self, root: Path, frames: FrameCache) -> None:
        self.root = root
        self.frames = frames
        self.ownership = Ownership(root)
        self.save_lock = threading.Lock()
        self.hooks: dict[str, Hook] = {}

    def _point(self, name: str, **info: Any) -> None:
        hook = self.hooks.get(name)
        if hook is not None:
            hook(info)
        if name in ("before_record", "before_commit"):
            _faults.fault_point(f"target.{name}")

    # ------------------------------------------------------------ 열기·미리보기

    def open(self, where: WsPath) -> dict[str, Any]:
        """`target.open` 결과. 형식이 틀린 파일도 연다(진단). JSON이 아니면 `invalid_json`."""
        from kookabug_core.documents import open as open_document
        from kookabug_platform.frames import decode_image

        try:
            doc = open_document(where.path)
        except DocumentError as exc:
            if exc.code == "not_found":
                raise RequestFailed("not_found", exc.message, path=where.given) from exc
            if exc.code == "invalid_json":
                raise RequestFailed(
                    "invalid_json",
                    exc.message,
                    message=exc.message,
                    line=exc.line,
                    column=exc.column,
                ) from exc
            raise _io_error(exc.message) from exc
        if not isinstance(doc.value, dict):
            text = "target 파일의 최상위가 JSON 객체가 아니다"
            raise RequestFailed("invalid_json", text, message=text, line=None, column=None)
        value: dict[str, Any] = doc.value
        diagnostics = list(check_shape(value, "target", file=where.rel))
        image_ref: dict[str, Any] | None = None
        image = image_path_of(self.root, where.rel, value)
        if image is None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "target_invalid",
                    "image 경로가 워크스페이스 밖이거나 틀렸다",
                    file=where.rel,
                    pointer="/image",
                )
            )
        else:
            data = read_bytes(image.path) if image.path.is_file() else None
            pixels = None
            if data is not None:
                with contextlib.suppress(ValueError):
                    pixels = decode_image(data)
            if pixels is None:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "target_invalid",
                        f"이미지 '{image.rel}'이(가) 없거나 읽을 수 없다",
                        file=where.rel,
                        pointer="/image",
                    )
                )
            else:
                image_ref = {
                    "workspace": image.rel,
                    "width": int(pixels.shape[1]),
                    "height": int(pixels.shape[0]),
                }
        return {
            "revision": combined_revision(self.root, where, doc.original_bytes),
            "spec": value,
            "image": image_ref,
            "diagnostics": [d.to_dict() for d in diagnostics],
        }

    def preview(
        self,
        frame_id: str,
        spec: Mapping[str, Any],
        template: Mapping[str, Any],
        base: WsPath | None,
        seq: int,
    ) -> dict[str, Any]:
        """`target.preview`: 저장 전 사양으로 그 정지 화면에서 찾는다. 템플릿은 저장 전 자른 영역
        (`crop`: 저장할 때처럼 `recorded`·검색 범위를 그 정지 화면으로 채운다) 또는 기존 이미지
        (`image`: `base_path` target 기준 경로, 없으면 루트 기준)다."""
        from kookabug_platform.errors import PlatformError
        from kookabug_platform.vision import load_target_image

        frame = self.frames.get(frame_id)
        value = _fill_defaults(spec, _PLACEHOLDER)
        _check_spec(value, None)
        crop: Any = template.get("crop")
        try:
            if crop is not None:
                source = self.frames.get(str(crop["frame_id"]))
                _, image = _crop_image(source, crop["rect"])
                _fill_frame(value, source)
            else:
                given = str(template["image"])
                rel = Workspace.resolve_from(base.rel if base is not None else "", given)
                if rel is None:
                    raise RequestFailed(
                        "path_outside_workspace",
                        f"이미지 '{given}'이(가) 워크스페이스 루트 밖이다",
                        path=given,
                    )
                image = load_target_image(resolve_path(self.root, rel).path)
            # 템플릿 픽셀은 위에서 정했다: target 경로·image 이름은 이름표로만 쓴다
            name = self.root / TARGETS_DIR / f"preview{TARGET_SUFFIX}"
            result = _find(frame, Target(name=name.name, path=name, spec=value), image)
        except PlatformError as exc:
            raise platform_failed(exc) from exc
        return preview_json(result, seq)

    # ------------------------------------------------------------ 저장

    def save(
        self,
        where: WsPath,
        spec: Mapping[str, Any],
        crop: Mapping[str, Any] | None,
        base_revision: str | None,
    ) -> SaveOutcome:
        """`crop`이 없으면 `_save_spec_only` (이미지를 새로 만들지 않고 JSON만)."""
        with self.save_lock:
            self._point("checks", target=where.rel)
            where = _recheck(self.root, where, save=True)
            # 1. 쓰기 전 검사
            frame: EditorFrame | None = None
            pixels: Any = None
            if crop is not None:
                frame = self.frames.get(str(crop["frame_id"]))
                pixels, _ = _crop_image(frame, crop["rect"])
            current = read_bytes(where.path)
            if base_revision is None:
                if current is not None or where.path.exists():
                    revision = (
                        None if current is None else combined_revision(self.root, where, current)
                    )
                    raise RequestFailed(
                        "exists", f"'{where.given}'이(가) 이미 있다", revision=revision
                    )
                original: str | None = None
                old_image: WsPath | None = None
            else:
                revision = None if current is None else combined_revision(self.root, where, current)
                if revision != base_revision:
                    raise RequestFailed(
                        "revision_conflict",
                        "target이 밖에서 바뀌었다 (JSON 또는 이미지가 기준 revision과 다르다)",
                        revision=revision,
                    )
                assert current is not None
                original = current.decode("utf-8", errors="replace")
                old_image = image_path_of(self.root, where.rel, _parse(current))
            if frame is None:
                if current is None or original is None:
                    raise _target_invalid(
                        "새 target은 crop(템플릿 영역)이 있어야 한다",
                        [Diagnostic("error", "target_invalid", "crop이 없다", pointer="/crop")],
                    )
                return self._save_spec_only(
                    where, spec, _parse(current), original, old_image, base_revision
                )
            stem = where.path.name[: -len(TARGET_SUFFIX)]
            value = _fill_defaults(spec, f"{stem}.png")
            _check_spec(value, where.rel)
            _fill_frame(value, frame)
            from kookabug_platform.frames import encode_png

            png = encode_png(pixels)
            # 바로 매칭은 쓰기 전에: 쓸 사양·PNG 그대로 그 정지 화면에서 찾고, 못 찾거나 결과를
            # 나타낼 수 없으면 아무것도 쓰지 않고 거부한다 (T6 검수 2·3)
            preview = self._expected_preview(where, value, frame, png)
            # 2. 새 이미지 (배타적 생성)
            name, image, created = self._publish(where, stem, png)
            # 3·4. 사양을 채워 커밋. 커밋 뒤에는 실패하는 단계를 두지 않는다
            value["image"] = name
            try:
                self._point("before_commit", image=image.rel, target=where.rel)
                data = self._commit(where, original, value, base_revision)
            except BaseException:
                self._rollback(created)
                raise
            # 5. 옛 이미지 정리 (실패는 경고)
            warnings = self._cleanup_quietly(where, old_image, image)
        # revision은 쓴 바이트로 정한다 (다시 읽지 않음: 커밋 뒤 실패 없음)
        return SaveOutcome(image.rel, f"{_sha(data)}:{_sha(png)}", preview, warnings)

    def _expected_preview(
        self, where: WsPath, value: dict[str, Any], frame: EditorFrame, png: bytes
    ) -> dict[str, Any]:
        """저장할 사양과 PNG 바이트(디스크에 쓸 그대로 디코드)로 그 정지 화면에서 찾은 결과.
        찾지 못하면(검색 범위 밖·임계값 등) `target_invalid` — 저장한 대상은 바로 매칭돼야 한다."""
        from kookabug_platform.errors import PlatformError
        from kookabug_platform.frames import decode_image
        from kookabug_platform.vision import TargetImage

        template = TargetImage.of_pixels(decode_image(png), where.path)
        try:
            result = _find(frame, Target(name=where.rel, path=where.path, spec=value), template)
        except PlatformError as exc:
            raise platform_failed(exc) from exc
        preview = preview_json(result, 0)
        if not result.found:
            best = result.best
            why = (
                "검색 범위가 템플릿보다 작다"
                if best is None
                else (
                    f"최고 점수 {best.score:.3f}, 임계값 {result.threshold:.2f}"
                    + (", 색 확인 실패" if best.reason == "color" else "")
                )
            )
            text = f"이 사양으로는 고른 정지 화면에서 대상을 찾지 못한다 ({why}). 저장하지 않았다"
            raise _target_invalid(text, [Diagnostic("error", "target_invalid", text)])
        return preview

    def _save_spec_only(
        self,
        where: WsPath,
        spec: Mapping[str, Any],
        current: Any,
        original: str,
        image: WsPath | None,
        base_revision: str | None,
    ) -> SaveOutcome:
        """crop 없는 저장 (잠금 안, revision 확인 뒤): 지금 `image`·`recorded`를 그대로 두고 JSON만
        커밋한다. 이미지를 만들거나 지우지 않는다. 검색 범위는 `recorded.client_size` 기준 픽셀
        왕복 값이다(그 값이 없으면 받은 그대로). 지금 이미지가 없거나 이미지가 아니면
        `target_invalid`."""
        from kookabug_platform.frames import decode_image

        def missing(text: str) -> RequestFailed:
            diagnostic = Diagnostic(
                "error", "target_invalid", text, file=where.rel, pointer="/image"
            )
            return _target_invalid(text, [diagnostic])

        if not isinstance(current, dict) or image is None:
            raise missing("지금 target의 image 경로가 없거나 틀려 crop 없이 저장할 수 없다")
        data = read_bytes(image.path) if image.path.is_file() else None
        if data is None:
            raise missing(
                f"이미지 '{image.rel}'이(가) 없어 crop 없이 저장할 수 없다 (영역을 고른다)"
            )
        try:
            decode_image(data)
        except ValueError as exc:
            raise missing(f"이미지 '{image.rel}'을(를) 읽을 수 없다: {exc}") from exc
        disk: dict[str, Any] = current
        value = _fill_defaults(spec, str(disk["image"]))
        recorded: Any = disk.get("recorded")
        if recorded is None:
            value.pop("recorded", None)
        else:
            value["recorded"] = copy.deepcopy(recorded)
        _check_spec(value, where.rel)
        size: Any = recorded.get("client_size") if isinstance(recorded, dict) else None  # pyright: ignore[reportUnknownMemberType]
        if size is not None:
            _snap_region(value, (int(size[0]), int(size[1])))
        self._point("before_commit", image=image.rel, target=where.rel)
        written = self._commit(where, original, value, base_revision)
        return SaveOutcome(image.rel, f"{_sha(written)}:{_sha(data)}", None)

    def _publish(self, where: WsPath, stem: str, png: bytes) -> tuple[str, WsPath, _Created | None]:
        """2단계: (target 기준 이름, 경로, 이 요청이 만든 파일 또는 None(재사용))."""
        sha = _sha(png)
        folder_rel = PurePosixPath(where.rel).parent.as_posix()
        names = [f"{stem}.png", *(f"{stem}-{sha[:n]}.png" for n in (8, 16, 64))]
        try:
            where.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _io_error(f"'{where.path.parent}' 폴더를 만들 수 없다: {exc}") from exc
        for name in names:
            rel = name if folder_rel == "." else f"{folder_rel}/{name}"
            try:
                candidate = resolve_path(self.root, rel)
            except RequestFailed, InvalidParams:
                continue  # 링크가 루트 밖·.kookabug/를 가리키는 이름은 쓰지 않는다
            if candidate.path.parent != where.path.parent:
                continue  # 이름이 링크다: 그 자리 밖의 파일을 재사용하지 않는다
            self._point("publish", path=candidate.path)
            try:
                handle = open(candidate.path, "xb")  # noqa: SIM115 (닫기 전에 실패를 처리한다)
            except FileExistsError:
                existing = None
                with contextlib.suppress(OSError):
                    existing = candidate.path.read_bytes()
                if existing is not None and _sha(existing) == sha:
                    return name, candidate, None  # 같은 바이트: 재사용 (남의 파일, 기록 안 함)
                continue
            except OSError as exc:
                raise _io_error(f"'{candidate.rel}'을(를) 만들 수 없다: {exc}") from exc
            try:
                with handle:
                    handle.write(png)
                    self._point("image_write", path=candidate.path)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException as exc:
                # 이 요청이 방금 만든 파일이다 (아직 기록 전): 그것만 지운다
                with contextlib.suppress(OSError):
                    os.unlink(candidate.path)
                if isinstance(exc, OSError):
                    raise _io_error(f"'{candidate.rel}'에 쓸 수 없다: {exc}") from exc
                raise
            self._point("before_record", path=candidate.path)
            owned = OwnedImage(candidate.rel, sha, _now(), where.rel)
            try:
                self.ownership.add(owned)
            except (OSError, DocumentError) as exc:
                log.warning("에디터 소유 기록에 쓰지 못했다 (정리하지 않는다): %s", exc)
                return name, candidate, _Created(candidate, sha, None)
            return name, candidate, _Created(candidate, sha, owned)
        raise _io_error(f"'{where.rel}' 옆에 새 이미지 이름을 고를 수 없다 (후보가 모두 다른 파일)")

    def _commit(
        self, where: WsPath, original: str | None, value: Any, base_revision: str | None
    ) -> bytes:
        """4단계: 직전에 revision을 다시 잰 뒤 JSON 한 번 쓰기. 같은 바이트면 쓰지 않는다.
        디스크에 있게 된 JSON 바이트를 돌려준다."""
        where = _recheck(self.root, where, save=True)
        now = read_bytes(where.path)
        if base_revision is None:
            if now is not None or where.path.exists():
                revision = None if now is None else combined_revision(self.root, where, now)
                raise RequestFailed(
                    "exists", f"'{where.given}'이(가) 저장 중에 밖에서 생겼다", revision=revision
                )
        else:
            revision = None if now is None else combined_revision(self.root, where, now)
            if revision != base_revision:
                raise RequestFailed(
                    "revision_conflict", "target이 저장 중에 밖에서 바뀌었다", revision=revision
                )
        data = save_text(original, value).encode("utf-8")
        if data == now:
            return data
        try:
            self._point("json_write", target=where.rel)
            if now is None:
                _publish_new(where.path, data)
            else:
                write_atomic(where.path, data)
        except FileExistsError as exc:
            raise RequestFailed(
                "exists", f"'{where.given}'이(가) 저장 중에 밖에서 생겼다", revision=None
            ) from exc
        except DocumentError as exc:
            raise _io_error(exc.message) from exc
        except OSError as exc:
            raise _io_error(f"'{where.rel}'에 쓸 수 없다: {exc}") from exc
        return data

    def _rollback(self, created: _Created | None) -> None:
        """커밋이 실패했다: 이 요청이 직접 만든 파일만, 조건을 다시 확인하고 지운다. 예외를 내지
        않는다(원래 실패를 그대로 돌려준다).

        - 기록에 이 요청의 항목이 없으면 아무것도 하지 않는다
        - 파일이 없거나 바이트가 바뀌었거나(사람이 바꿈) 다른 target이 가리키면 지우지 않고 항목만
          뺀다
        - 참조를 다 읽지 못했으면 지우지도 항목을 빼지도 않는다(다음 저장의 정리가 같은 조건으로
          다시 본다)"""
        if created is None or created.owned is None:
            return
        owned = created.owned
        try:
            if owned not in (self.ownership.load() or []):
                return
            data = read_bytes(created.where.path)
            if data is None or _sha(data) != created.sha256:
                self.ownership.remove(owned)
                return
            refs = referenced_images(self.root)
            if not refs.complete:
                log.warning(
                    "참조를 다 읽지 못해 되돌리지 않는다 (새 이미지 %s가 남는다): %s",
                    created.where.rel,
                    "; ".join(refs.failures),
                )
                return
            if created.where.key not in refs.keys:
                os.unlink(created.where.path)
            self.ownership.remove(owned)
        except Exception as exc:  # 되돌리기는 원래 오류를 가리지 않는다
            log.warning("되돌리기 중 실패 (새 이미지 %s가 남는다): %s", created.where.rel, exc)

    def _cleanup_quietly(self, where: WsPath, old: WsPath | None, new: WsPath) -> list[str]:
        """5단계 (커밋 뒤): 어떤 실패도 저장을 실패로 바꾸지 않는다. 실패는 경고로 돌려준다."""
        try:
            return self._cleanup(where, old, new)
        except Exception as exc:
            log.warning("옛 이미지 정리 중 오류: %s", exc)
            return [f"옛 이미지를 정리하지 못했다: {exc}"]

    def _cleanup(self, where: WsPath, old: WsPath | None, new: WsPath) -> list[str]:
        """옛 이미지·같은 target의 기록된 고아 중 소유 기록에 있고, 바이트가 기록과 같고, 어떤
        target도 가리키지 않음이 확실한 것만 지운다. 저장 잠금 안에서 부르고, 참조는 후보마다
        **지우기 직전에** 다시 읽는다. 다시 읽다 실패하면 그 후보와 그 뒤 후보는 지우지 않는다."""
        images = self.ownership.load()
        if images is None:
            return []  # 기록을 읽을 수 없다 = 소유 파일 없음
        candidates: dict[str, WsPath] = {}
        if old is not None:
            candidates[old.key] = old
        for owned in images:
            if _same_rel(owned.target, where.rel):
                with contextlib.suppress(RequestFailed, InvalidParams):
                    found = resolve_path(self.root, owned.path)
                    candidates.setdefault(found.key, found)
        mine: list[tuple[WsPath, OwnedImage]] = []
        for key, image in candidates.items():
            owned = next((i for i in images if _same_rel(i.path, image.rel)), None)
            if key == new.key or owned is None:
                continue  # 새 이미지·사용자 파일: 지우지 않는다
            if not image.path.exists():
                self.ownership.remove(owned)
                continue
            mine.append((image, owned))
        warnings: list[str] = []
        for index, (image, owned) in enumerate(mine):
            data = read_bytes(image.path)
            if data is None or _sha(data) != owned.sha256:
                continue
            # 지우기 직전에 참조를 다시 읽는다. 앞 후보를 정리하는 동안 밖에서 이 이미지를 가리키는
            # target이 생겼을 수 있다 (T6 2차 검수). 읽지 못하면 이 후보와 그 뒤는 지우지 않는다
            refs = referenced_images(self.root)
            if not refs.complete:
                names = ", ".join(f"'{i.rel}'" for i, _ in mine[index:])
                warnings.append(
                    f"다른 target을 다 읽지 못해 옛 이미지 {names}을(를) 지우지 않았다: "
                    + "; ".join(refs.failures)
                )
                break
            if not refs.unreferenced(image):
                continue
            try:
                os.unlink(image.path)
                self.ownership.remove(owned)
            except (OSError, DocumentError) as exc:
                warnings.append(f"옛 이미지 '{image.rel}'을(를) 지우지 못했다: {exc}")
                continue
            self._point("deleted", path=image.path)
        return warnings


def _publish_new(path: Path, data: bytes) -> None:
    """새 파일 공개: 같은 폴더 임시 파일 → fsync → **덮어쓰지 않는** 이름 바꾸기. 그 사이에 파일이
    생겼으면 `FileExistsError` (밖의 파일을 덮지 않는다)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.name == "nt":
            os.rename(tmp, path)  # Windows: 대상이 있으면 FileExistsError
        else:
            os.link(tmp, path)
            os.unlink(tmp)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

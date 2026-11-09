"""증거 묶음 고정 (M8 계획 3.2 증거·C8·C9·U6) — 엄격: 비밀값.

`knowledge/evidence/<묶음 ID>/manifest.json`(`kookabug.evidence/0`) + 최소 증거 파일. 원본 실행이
지워져도 묶음은 남는다. **지우거나 고치는 도구가 없다** — 이 모듈은 새 묶음을 만들기만 한다(이미
있는 ID면 `exists`).

담는 것(부르는 쪽이 이미 가린 값만 넘긴다 — daemon은 에이전트용 기록 보기의 허용 필드):
- `events.jsonl`: 실패 스텝 앞뒤 이벤트(허용 필드만, 입력 값·OCR 글자·`secret_paths` 없음)
- `run.json`: 판정·조건·빌드 요약 (비밀 설정은 `{"secret": true}`)
- 이미지: 보호 판정이 `clear`인 것만 긴 변 480px 사본, 아니면 `omitted`(사유)
- 묶음 전체 2 MB 상한(넘는 파일은 `omitted: size_cap`)

모든 글자 파일은 쓰기 전에 비밀값 글자 검사를 한 번 더 한다(걸리면 그 파일을 `omitted:
secret_in_text`). 사람이 쓴 `note`가 걸리면 묶음을 만들지 않는다. **manifest 자체**(`by`·`extra`·
파일 이름·`omitted` 포함)도 마지막 글자 검사를 거친다: 걸린 필드는 값 없이 빼고 `omitted`에 위치만
(원문·부분 문자열 없이 `#n` 꼴) 남기며, 뺀 뒤에도 직렬화한 manifest·감사 이력 줄에 걸리면 묶음을
만들지 않는다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.adopt import path_key
from kookabug_core.knowledge import store
from kookabug_core.knowledge.formats import Actor, KnowledgeError, SecretCheck, now, shape_problem

__all__ = [
    "EVIDENCE_DIR",
    "EVIDENCE_ID",
    "MAX_BUNDLE_BYTES",
    "MAX_IMAGE_SIDE",
    "NEGATIVE_IGNORED",
    "Bundle",
    "Image",
    "add_to",
    "build",
    "canonical_rel",
    "load_manifest",
    "negative_problem",
    "publish",
    "raw",
    "shrink_png",
]

EVIDENCE_DIR: Final = "knowledge/evidence"
EVIDENCE_ID: Final = re.compile(r"^[a-z][a-z0-9-]{0,95}$")
FILE_NAME: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
MAX_BUNDLE_BYTES: Final = 2 << 20
MAX_IMAGE_SIDE: Final = 480
NEGATIVE_IGNORED: Final = "negative_ignored"
"""`load_manifest`가 정규형이 아닌 `negative`를 음성 대조에서 뺄 때 돌려주는 manifest에만 붙이는 키
(`{"reason", "targets"}` — 파일에는 쓰지 않는다). `targets`는 적힌 그대로다."""


def canonical_rel(rel: object) -> bool:
    """정규형 상대 경로인가: 글자, `/` 구분(역슬래시·`:` 없음), 빈 조각·`.`·`..` 없음."""
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def negative_problem(manifest: Mapping[str, Any]) -> str | None:
    """음성 대조(`negative`)를 쓸 수 없는 이유 (없으면 None): `negative.targets`·`negative.frames`·
    `files[].path`가 정규형이 아니거나, `files[].path` 두 개가 `path_key`로 같은 파일이다(어느 sha가
    그 프레임의 것인지 모른다). `negative`가 없으면 None."""
    negative = manifest.get("negative")
    if negative is None:
        return None
    if not isinstance(negative, Mapping):
        return "negative 형식이 틀렸다"
    for key in ("targets", "frames"):
        values = cast(Mapping[str, Any], negative).get(key) or []
        if not isinstance(values, list):
            return f"negative.{key} 형식이 틀렸다"
        if not all(canonical_rel(v) for v in cast(list[Any], values)):
            return f"negative.{key}에 정규형이 아닌 경로가 있다"
    seen: set[str] = set()
    for item in manifest.get("files") or []:
        rel = cast(Mapping[str, Any], item).get("path") if isinstance(item, Mapping) else None
        if not canonical_rel(rel):
            return "files[].path에 정규형이 아닌 경로가 있다"
        key = path_key(str(rel))
        if key in seen:
            return "files[].path에 같은 파일의 다른 철자가 있다"
        seen.add(key)
    return None


@dataclass(frozen=True, slots=True)
class Image:
    """묶음에 넣을 이미지 후보: 파일 이름, PNG 바이트, 보호 판정(`clear` 또는 막은 사유)."""

    name: str
    png: bytes
    guard: str


@dataclass(slots=True)
class Bundle:
    manifest: dict[str, Any]
    files: dict[str, bytes]


def shrink_png(png: bytes, side: int = MAX_IMAGE_SIDE) -> bytes:
    """긴 변이 `side`보다 크면 가까운 점 표본으로 줄인 PNG (아니면 다시 인코딩만)."""
    import numpy as np

    from kookabug_platform.frames import decode_image, encode_png

    pixels = np.asarray(decode_image(png))
    h, w = int(pixels.shape[0]), int(pixels.shape[1])
    scale = min(1.0, side / max(h, w))
    if scale < 1.0:
        ys = (np.arange(max(1, round(h * scale))) / scale).astype(int).clip(0, h - 1)
        xs = (np.arange(max(1, round(w * scale))) / scale).astype(int).clip(0, w - 1)
        pixels = pixels[ys][:, xs]
    return bytes(encode_png(np.ascontiguousarray(pixels)))


def _secret_hit(check: SecretCheck, name: str, text: str) -> bool:
    try:
        check([(name, text)])
    except KnowledgeError as exc:
        if exc.code == "secret_in_text":
            return True
        raise
    return False


_DROP: Final = object()
_FIXED: Final = ("format", "id", "pinned_at", "files", "omitted", "note")
"""manifest 중 지우지 않는 필드 (형식·ID·시각·파일 목록·생략 목록은 따로 검사, `note`는 걸리면
거부)."""


def _scrub(check: SecretCheck, value: Any, where: str, omitted: list[dict[str, str]]) -> Any:
    """글자 검사에 걸린 잎(글자·수)과 키를 값 없이 뺀다. 위치는 `#n`(순서)으로만 남긴다."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):  # pyright: ignore[reportUnknownVariableType]
            at = f"{where}/#{i}"
            if _secret_hit(check, at, str(k)):  # pyright: ignore[reportUnknownArgumentType]
                omitted.append({"what": at, "reason": "secret_in_text"})
                continue
            got = _scrub(check, v, at, omitted)
            if got is not _DROP:
                out[str(k)] = got  # pyright: ignore[reportUnknownArgumentType]
        return out
    if isinstance(value, list | tuple):
        items: list[Any] = []
        for i, v in enumerate(value):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            got = _scrub(check, v, f"{where}/#{i}", omitted)
            if got is not _DROP:
                items.append(got)
        return items
    if isinstance(value, str | bool | int | float):
        text = value if isinstance(value, str) else json.dumps(value)
        if _secret_hit(check, where, text):
            omitted.append({"what": where, "reason": "secret_in_text"})
            return _DROP
    return value


def _safe_omitted(check: SecretCheck, items: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """`omitted` 항목의 이름·사유가 걸리면 값과 무관한 자리 이름으로 바꾼다."""
    out: list[dict[str, str]] = []
    for n, item in enumerate(items):
        what, reason = str(item["what"]), str(item["reason"])
        if _secret_hit(check, f"omitted/{n}", what):
            what = f"#omitted{n}"
        if _secret_hit(check, f"omitted/{n}", reason):
            reason = "secret_in_text"
        out.append({"what": what, "reason": reason})
    return out


def final_check(check: SecretCheck, manifest: Mapping[str, Any]) -> None:
    """직렬화할 manifest 전체의 마지막 글자 검사 (잎마다 + 직렬화 바이트 통째). 걸리면
    `secret_in_text`(묶음을 만들지 않는다)."""
    from kookabug_core.knowledge.formats import strings_of

    texts = [*strings_of(dict(manifest), "manifest"), ("manifest", store.encode(manifest).decode())]
    try:
        check(texts)
    except KnowledgeError as exc:
        if exc.code == "secret_in_text":
            raise KnowledgeError(
                "secret_in_text", "증거 묶음 manifest에 비밀값이 남아 고정하지 않았다"
            ) from None
        raise


def build(
    *,
    bundle_id: str,
    run_id: str | None,
    by: Mapping[str, Any],
    check_secrets: SecretCheck,
    run_summary: Mapping[str, Any] | None = None,
    events: Sequence[Mapping[str, Any]] = (),
    images: Sequence[Image] = (),
    note: str | None = None,
    extra: Mapping[str, Any] | None = None,
    omitted: Sequence[Mapping[str, str]] = (),
) -> Bundle:
    """묶음을 메모리에서 만든다 (아직 쓰지 않음). `extra`는 manifest에 더할 필드(판정·실패 스텝·
    기준·환경·그래프 sha·출처·음성 대조 등), `omitted`는 부르는 쪽이 미리 뺀 항목. manifest 전체가
    마지막 글자 검사를 거친다(모듈 설명)."""
    if not EVIDENCE_ID.fullmatch(bundle_id):
        raise KnowledgeError("format", "증거 묶음 ID 형식이 틀렸다")
    if note is not None:
        check_secrets([("note", note)])
    files: dict[str, bytes] = {}
    skipped: list[dict[str, str]] = [dict(o) for o in omitted]
    texts: list[tuple[str, bytes]] = []
    if events:
        body = "".join(
            json.dumps(dict(e), ensure_ascii=False, sort_keys=True) + "\n" for e in events
        )
        texts.append(("events.jsonl", body.encode("utf-8")))
    if run_summary is not None:
        body = json.dumps(dict(run_summary), ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        texts.append(("run.json", body.encode("utf-8")))
    total = 0
    for name, data in texts:
        if _secret_hit(check_secrets, name, data.decode("utf-8")):
            skipped.append({"what": name, "reason": "secret_in_text"})
            continue
        if total + len(data) > MAX_BUNDLE_BYTES:
            skipped.append({"what": name, "reason": "size_cap"})
            continue
        files[name] = data
        total += len(data)
    for n, image in enumerate(images):
        if not FILE_NAME.fullmatch(image.name) or path_key(image.name) in {
            path_key(n) for n in files
        }:
            skipped.append({"what": "image", "reason": "bad_name"})
            continue
        if _secret_hit(check_secrets, f"image/{n}", image.name):
            skipped.append({"what": f"#image{n}", "reason": "secret_in_text"})
            continue
        if image.guard != "clear":
            skipped.append({"what": image.name, "reason": image.guard})
            continue
        try:
            data = shrink_png(image.png)
        except Exception:
            skipped.append({"what": image.name, "reason": "image_unreadable"})
            continue
        if total + len(data) > MAX_BUNDLE_BYTES:
            skipped.append({"what": image.name, "reason": "size_cap"})
            continue
        files[image.name] = data
        total += len(data)
    loose: dict[str, Any] = {"run": run_id, "by": dict(by), **dict(extra or {})}
    for key in _FIXED:
        loose.pop(key, None)
    loose = _scrub(check_secrets, loose, "manifest", skipped)
    manifest: dict[str, Any] = {
        "format": "kookabug.evidence/0",
        "id": bundle_id,
        "pinned_at": now(),
        **loose,
        "files": [
            {"path": name, "sha256": filetx.sha256_of(data), "bytes": len(data)}
            for name, data in sorted(files.items())
        ],
        "omitted": _safe_omitted(check_secrets, skipped),
    }
    if note is not None:
        manifest["note"] = note
    reason = negative_problem(manifest)
    if reason is not None:
        # 음성 대조 묶음은 정규형 경로로만 만든다 (`load_manifest`가 아니면 음성 대조에서 뺀다)
        raise KnowledgeError("format", f"증거 묶음 음성 대조 경로가 틀렸다 ({reason})")
    problem = shape_problem(manifest, "evidence")
    if problem is not None:
        if any(o["reason"] == "secret_in_text" for o in manifest["omitted"]):
            # 필수 필드가 비밀값이라 뺄 수 없었다 — 묶음을 만들지 않는다
            raise KnowledgeError(
                "secret_in_text", "증거 묶음의 필수 필드에 비밀값이 있어 고정하지 않았다"
            )
        raise KnowledgeError("format", f"증거 묶음 형식이 틀렸다 ({problem})")
    final_check(check_secrets, manifest)
    return Bundle(manifest, files)


def raw(
    *,
    bundle_id: str,
    files: Mapping[str, bytes],
    by: Mapping[str, Any],
    origin: str,
    extra: Mapping[str, Any] | None = None,
) -> Bundle:
    """바이트 그대로의 묶음 (채택 전 원래 팀 파일 `e-<채택>-prev` — 되돌리기가 sha로 찾는다).
    팀 파일 바이트라 가리지 않는다(이미 커밋된 내용)."""
    manifest: dict[str, Any] = {
        "format": "kookabug.evidence/0",
        "id": bundle_id,
        "run": None,
        "pinned_at": now(),
        "by": dict(by),
        "origin": origin,
        **dict(extra or {}),
        "files": [
            {"path": name, "sha256": filetx.sha256_of(data), "bytes": len(data)}
            for name, data in sorted(files.items())
        ],
        "omitted": [],
    }
    problem = shape_problem(manifest, "evidence")
    if problem is not None:
        raise KnowledgeError("format", f"증거 묶음 형식이 틀렸다 ({problem})")
    return Bundle(manifest, dict(files))


def add_to(tx: filetx.Tx, bundle: Bundle) -> list[str]:
    """묶음을 거래에 만들기로 더한다 (있으면 거래가 `exists`로 실패 — 덮지 않는다)."""
    base = f"{EVIDENCE_DIR}/{bundle.manifest['id']}"
    written: list[str] = []
    for name, data in sorted(bundle.files.items()):
        tx.create(f"{base}/{name}", data)
        written.append(f"{base}/{name}")
    tx.create(f"{base}/manifest.json", store.encode(bundle.manifest))
    written.append(f"{base}/manifest.json")
    return written


def publish(
    root: Path, bundle: Bundle, *, actor: Actor, check_secrets: SecretCheck | None = None
) -> list[str]:
    """새 묶음을 한 거래로 쓴다 (+ 감사 이력). 이미 있으면 `exists`. `check_secrets`를 주면
    manifest와 감사 이력 줄(묶음 ID·파일 이름·주체)을 쓰기 전에 다시 검사한다."""
    from kookabug_core.knowledge.formats import strings_of
    from kookabug_core.knowledge.ops import log_into

    if check_secrets is not None:
        final_check(check_secrets, bundle.manifest)
        check_secrets(
            [
                ("id", str(bundle.manifest["id"])),
                *strings_of([f["path"] for f in bundle.manifest["files"]], "fields"),
                *actor.texts(),
            ]
        )
    try:
        with filetx.locked(root):
            store.ensure_layout(root)
            base = filetx.plain(root, f"{EVIDENCE_DIR}/{bundle.manifest['id']}")
            if base.exists():
                raise KnowledgeError("exists", "같은 ID의 증거 묶음이 이미 있다")
            tx = filetx.Tx(root)
            written = add_to(tx, bundle)
            entry = {
                "op": "evidence_pin",
                "file": f"{EVIDENCE_DIR}/{bundle.manifest['id']}",
                "id": bundle.manifest["id"],
                "fields": [str(f["path"]) for f in bundle.manifest["files"]],
                "result": "applied",
            }
            log_into(root, tx, [entry], actor)
            tx.commit()
    except filetx.TxError as exc:
        raise KnowledgeError(exc.code, exc.message) from exc
    return written


def load_manifest(root: Path, bundle_id: str) -> dict[str, Any] | None:
    """묶음 manifest (없거나 형식이 틀리면 None). 음성 대조 경로가 정규형이 아니면
    (`negative_problem`) 돌려주는 manifest에서 `negative`를 빼고 `NEGATIVE_IGNORED`에 이유와 적힌
    target을 남긴다 — 그 묶음은 음성 대조에 쓰지 않는다(파일은 그대로)."""
    if not EVIDENCE_ID.fullmatch(bundle_id):
        return None
    try:
        data = filetx.read(root, f"{EVIDENCE_DIR}/{bundle_id}/manifest.json")
    except filetx.TxError:
        return None
    if data is None:
        return None
    try:
        doc = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    if not isinstance(doc, dict) or shape_problem(doc, "evidence") is not None:
        return None
    manifest = cast(dict[str, Any], doc)
    reason = negative_problem(manifest)
    if reason is not None:
        negative = manifest.pop("negative")
        targets = negative.get("targets") if isinstance(negative, Mapping) else None
        manifest[NEGATIVE_IGNORED] = {
            "reason": reason,
            "targets": [
                str(t) for t in cast(list[Any], targets if isinstance(targets, list) else [])
            ],
        }
    return manifest

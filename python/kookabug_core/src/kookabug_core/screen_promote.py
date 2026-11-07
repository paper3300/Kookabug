"""화면 지도 승격·버리기·확인 거래 (M7 계획 3.7·10장 R4) — 엄격: 사용자 파일 손상.

daemon(`screens.promote/discard/check`)과 CLI(`kookabug screen promote`)가 이 모듈 하나를
쓴다. 모든 변경은 `.kookabug/screens.lock`(`screen_lock.screens_lock`, `screens.save`·
`explore.json` 쓰기와 같은 잠금) 안에서만 하고, 잠금을 얻으면 먼저 남은 거래를 복구한다
(`recover`).

승격 거래:

1. 잠금 → 복구 → 계획(`plan`): 후보를 읽어 만들 파일·바꿀 파일·지울 파일을 정하고, 사람이
   확인 때 본 revision(`base_revisions`)과 지금 revision을 대조한다. 하나라도 다르면
   `revision_conflict`(아무것도 안 씀)
2. 저널 `.kookabug/screens-tx/<txid>/`: 바꿀 파일의 **원래 바이트 사본**(`backup/<n>`)을 쓰고
   fsync, `journal.json`(`phase: prepare`)을 임시 이름에 쓰고 fsync한 뒤 이름 바꾸기.
   `journal.json`이 생기기 전에는 아무것도 게시하지 않는다
3. 게시: 새 파일은 같은 폴더 임시 이름 → fsync → 배타 이름 바꾸기(있으면 실패), 바꿀 파일은
   지금 sha가 `before_sha256`인지 본 뒤 임시 → fsync → 원자 교체. 그다음 바꾼 폴더들을 flush
4. 커밋 표시: `journal.json`을 `phase: committed`로 원자 교체 + fsync + 폴더 flush. 이 뒤로
   승격은 성공이다
5. 마무리(멱등, 재시도 가능): 지울 파일은 지금 sha가 저널과 같을 때만 지움 → `explore.json`
   `promoted` 갱신(읽은 바이트 sha를 교체 직전에 다시 확인, 같은 키에 다른 승격 ID가 있으면
   덮지 않고 경고 + 저널 유지) → 저널 폴더 지움

실패: 1~3에서 예외면 그 자리에서 롤백. 4(커밋 표시) 중 예외면 응답 실패이고 저널 상태대로
복구한다(교체 전이면 바로 롤백). 5에서 실패하면 성공 응답 + `cleanup_pending: true`.

복구(`recover`): `journal.json`이 없는 거래 폴더는 게시 전에 멈춘 것이라 지운다. `committed`면
5를 다시. `prepare`면 롤백 — 새 파일은 지금 sha가 저널과 같을 때만 지우고, 바꾼 파일은 지금
sha가 `after_sha256`이면 사본으로 되돌리고 `before_sha256`이면 그대로, 그 밖이면(사용자가 고침)
손대지 않고 경고하며 저널을 남긴다(다시 시도 가능). 저널이 깨졌으면 손대지 않고 경고.

쓰는 경로는 모두 경로 조각마다 링크·정션이 아니고 실경로가 워크스페이스 안이어야 한다. 열린 그래프
파일은 건드리지 않는다(새 ID·기존 파일에 더하기만 — 출구 `screen` 참조가 깨지지 않는다).
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import logging
import os
import secrets
import shutil
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.canonical import canonical_dumps, loads_strict
from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.screen_lock import ScreensBusy, screens_lock
from kookabug_core.screens import (
    EXPLORE_FILE,
    EXPLORED_DIR,
    SCREENS_DIR,
    SESSION_PATTERN,
    SUFFIX,
    ScreenDef,
    ScreenFileError,
    explored_candidates,
    is_screen_key,
    parse_screen,
    screen_index,
)
from kookabug_core.workspace import Workspace
from kookabug_sdk import _faults

__all__ = [
    "FAULT_POINT",
    "STAGES",
    "TX_DIR",
    "Plan",
    "PromoteError",
    "PromoteRequest",
    "check",
    "discard",
    "plan",
    "promote",
    "recover",
    "recover_locked",
    "sha256_of",
]

log = logging.getLogger(__name__)

TX_DIR: Final = (".kookabug", "screens-tx")
JOURNAL: Final = "journal.json"
FORMAT: Final = "kookabug.screens-tx/0"
FAULT_POINT: Final = "screens.stage"
STAGES: Final = (
    "journal_write",  # 저널 쓰기 중 (임시 파일 반쯤)
    "created",  # 새 파일 하나 게시 뒤 (nth = k)
    "publish_fsync",  # 게시 파일 fsync 자리
    "replaced",  # 바꿀 파일 하나 교체 뒤
    "before_commit",  # 커밋 표시 원자 교체 직전
    "commit_fsync",  # 커밋 표시 fsync 자리 (교체 전)
    "after_commit",  # 커밋 표시 직후
    "deleted",  # 후보 파일 하나 지운 뒤 (nth = k)
    "before_explore",  # explore.json 갱신 전
    "after_explore",  # explore.json 갱신 뒤
    "before_journal_remove",  # 저널 폴더 지우기 직전
)
"""실패 주입 이벤트 이름 (`KOOKABUG_FAULTS` 지점 `screens.stage`)."""


class PromoteError(Exception):
    """거래를 하지 않았다 (또는 커밋 표시 중 실패). `code`는 daemon 오류 코드와 같다."""

    def __init__(self, code: str, message: str, **fields: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields


def _stage(name: str) -> None:
    _faults.fault_point(FAULT_POINT, event=name)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 경로


def _parts(rel: str) -> list[str]:
    return [p for p in rel.replace("\\", "/").split("/") if p]


def _plain(root: Path, rel: str) -> Path:
    """`root` 아래 `rel`: 있는 조각마다 링크·정션이 아니고 실경로가 워크스페이스 실경로 안. 아니면
    `path_outside_workspace`. 쓰기·지우기 전에 부른다 (B2b `plain_path`와 같은 규칙)."""
    current = root
    for part in _parts(rel):
        if part in (".", ".."):
            raise PromoteError(
                "path_outside_workspace", f"'{rel}'은(는) 쓸 수 없는 경로다", path=rel
            )
        current = current / part
        if current.is_symlink() or (current.exists() and current.is_junction()):
            raise PromoteError(
                "path_outside_workspace", f"'{rel}' 경로에 링크·정션이 있어 쓰지 않는다", path=rel
            )
    if not Path(os.path.realpath(current)).is_relative_to(Path(os.path.realpath(root))):
        raise PromoteError(
            "path_outside_workspace", f"'{rel}'의 실경로가 워크스페이스 밖이다", path=rel
        )
    return current


def _read(root: Path, rel: str) -> bytes | None:
    path = _plain(root, rel)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PromoteError("io_error", f"'{rel}'을(를) 읽을 수 없다: {exc}", path=rel) from exc


def _sha(root: Path, rel: str) -> str | None:
    data = _read(root, rel)
    return None if data is None else sha256_of(data)


def _flush(folder: Path) -> None:
    """폴더 항목을 디스크에 내린다 (Windows `FlushFileBuffers`). 못 하면 기록만 — 거래는 파일
    fsync와 원자 이름 바꾸기에 기댄다."""
    try:
        from kookabug_core.win.files import flush_dir

        flush_dir(folder)
    except (OSError, ImportError) as exc:
        # 전원 손실 대비가 약해진 것을 알 수 있게 (B4 검수 Low 4)
        log.warning("폴더 flush 실패 %s: %s", folder, exc)


def _write_journal(folder: Path, journal: Mapping[str, Any]) -> None:
    """저널을 원자 교체한다 (임시 → fsync → 이름 바꾸기 → 폴더 flush)."""
    body = json.dumps(journal, ensure_ascii=False, indent=1).encode("utf-8")
    tmp = folder / f"{JOURNAL}.tmp"
    with open(tmp, "wb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, folder / JOURNAL)
    _flush(folder)


def _write_file(path: Path, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        _stage("publish_fsync")
        os.fsync(f.fileno())


# ---------------------------------------------------------------- 요청·계획


@dataclass(frozen=True, slots=True)
class PromoteRequest:
    session: str
    key: str
    mode: Literal["new", "merge"] = "new"
    id: str | None = None
    title: str | None = None
    description: str | None = None
    folder: str | None = None
    replace_shot: bool = False
    replace_detect: bool = False
    base_revisions: Mapping[str, str | None] = field(default_factory=dict[str, str | None])


@dataclass(slots=True)
class Plan:
    """승격이 할 일. `revisions`는 이 승격이 읽고 바꾸는 파일 → 지금 sha(없는 파일은 None)."""

    request: PromoteRequest
    id: str
    path: str
    creates: list[tuple[str, bytes]] = field(default_factory=list[tuple[str, bytes]])
    replaces: list[tuple[str, str, bytes]] = field(default_factory=list[tuple[str, str, bytes]])
    """(경로, before sha, 새 바이트)."""
    deletes: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    revisions: dict[str, str | None] = field(default_factory=dict[str, str | None])
    warnings: list[str] = field(default_factory=list[str])
    candidate: ScreenDef | None = None


def _session_rel(session: str) -> str:
    return f"{SCREENS_DIR}/{EXPLORED_DIR}/{session}"


def _require_session(session: str) -> None:
    if SESSION_PATTERN.fullmatch(session) is None:
        raise PromoteError("validation_failed", f"탐색 세션 ID '{session}'의 형식이 틀렸다")


def _load_dict(root: Path, rel: str) -> tuple[dict[str, Any], bytes]:
    data = _read(root, rel)
    if data is None:
        raise PromoteError("not_found", f"'{rel}'이(가) 없다", path=rel)
    try:
        value = loads_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PromoteError(
            "validation_failed", f"'{rel}'을(를) 읽을 수 없다: {exc}", path=rel
        ) from exc
    if not isinstance(value, dict):
        raise PromoteError("validation_failed", f"'{rel}'이(가) JSON 객체가 아니다", path=rel)
    return value, data


def _encode(doc: Mapping[str, Any]) -> bytes:
    return canonical_dumps(doc).encode("utf-8")


def _valid_folder(folder: str | None) -> str:
    """확정 화면을 둘 `screens/` 아래 폴더 (없으면 `screens/` 바로 아래)."""
    if folder is None or not folder.strip("/"):
        return SCREENS_DIR
    parts = _parts(folder)
    if parts and parts[0].casefold() == SCREENS_DIR:
        parts = parts[1:]
    if not parts:
        return SCREENS_DIR
    if any(not is_screen_key(p) for p in parts):  # `_explored`도 여기서 걸린다
        raise PromoteError(
            "validation_failed",
            f"폴더 '{folder}'의 조각은 ^[a-z][a-z0-9_]{{0,63}}$ 규칙이다 (예약 장치 이름 안 됨)",
            reason="folder",
        )
    return "/".join((SCREENS_DIR, *parts))


def _rewrite_to(moves: Any, mapping: Mapping[str, str]) -> tuple[list[Any], bool]:
    """이동의 `to`를 `mapping`(옛 키 → 새 ID)으로 고친다. (새 목록, 바뀜)."""
    out: list[Any] = []
    changed = False
    for m in moves if isinstance(moves, list) else []:
        if isinstance(m, dict) and isinstance(m.get("to"), str) and m["to"] in mapping:
            m = {**m, "to": mapping[m["to"]]}
            changed = True
        out.append(m)
    return out, changed


def _candidate_files(root: Path, session: str, key: str) -> list[str]:
    """후보 하나가 가진 파일들 (카드·대표 스크린샷·이미지 조건 crop). 일반 파일만."""
    base = _session_rel(session)
    files = [f"{base}/{key}{SUFFIX}"]
    shot = f"{base}/{key}.shot.png"
    if _plain(root, shot).is_file():
        files.append(shot)
    targets = _plain(root, f"{base}/targets/{key}")
    if targets.is_dir():
        for entry in sorted(targets.iterdir(), key=lambda p: p.name):
            rel = f"{base}/targets/{key}/{entry.name}"
            if entry.is_symlink() or entry.is_junction():
                raise PromoteError(
                    "path_outside_workspace", f"'{rel}'이(가) 링크·정션이라 쓰지 않는다", path=rel
                )
            if entry.is_file():
                files.append(rel)
    return files


def _copy_targets(
    root: Path,
    detect: Mapping[str, Any],
    session: str,
    key: str,
    dest_dir: str,
    prefix: str,
    p: Plan,
) -> dict[str, Any]:
    """후보 detect의 세션 target을 `dest_dir`로 옮긴 새 detect (만들 파일은 `p.creates`에)."""
    own = f"{_session_rel(session)}/targets/{key}/"
    out: dict[str, Any] = {}
    for group in ("all", "none"):
        items: list[Any] = []
        for item in detect.get(group, []) or []:
            ref = item.get("$target") if isinstance(item, dict) else None
            if not isinstance(ref, str) or not ref.startswith(own):
                items.append(copy.deepcopy(item))
                continue
            name = ref[len(own) :]
            body, data = _load_dict(root, ref)
            image = body.get("image")
            new_ref = f"{dest_dir}/{prefix}{name}"
            if isinstance(image, str) and "/" not in image and "\\" not in image:
                src_image = f"{own}{image}"
                image_bytes = _read(root, src_image)
                if image_bytes is None:
                    raise PromoteError("not_found", f"'{src_image}'이(가) 없다", path=src_image)
                new_image = f"{prefix}{image}"
                body = {**body, "image": new_image}
                p.creates.append((f"{dest_dir}/{new_image}", image_bytes))
                data = json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8")
            p.creates.append((new_ref, data))
            items.append({**item, "$target": new_ref})
        if items:
            out[group] = items
    return out


def plan(root: Path, request: PromoteRequest) -> Plan:
    """읽기만 한다 (잠금 안에서 부른다). 승격할 수 없으면 `PromoteError`."""
    _require_session(request.session)
    key = request.key
    if not is_screen_key(key):
        raise PromoteError("validation_failed", f"후보 키 '{key}'의 형식이 틀렸다")
    session_rel = _session_rel(request.session)
    card_rel = f"{session_rel}/{key}{SUFFIX}"
    doc, raw = _load_dict(root, card_rel)
    try:
        candidate = parse_screen(doc, card_rel)
    except ScreenFileError as exc:
        raise PromoteError("validation_failed", str(exc), path=card_rel) from exc
    workspace = Workspace.open(root)
    index = screen_index(workspace)
    explore_rel = f"{session_rel}/{EXPLORE_FILE}"
    explore_doc: dict[str, Any] = {}
    with contextlib.suppress(PromoteError):
        explore_doc, _ = _load_dict(root, explore_rel)
    promoted: dict[str, str] = {
        str(k): str(v) for k, v in (explore_doc.get("promoted") or {}).items() if isinstance(v, str)
    }

    if request.mode == "new":
        if candidate.incomplete or not candidate.detect():
            raise PromoteError(
                "validation_failed",
                f"후보 '{key}'에 판정 조건이 없어 새 화면으로 옮길 수 없다 (합치기만 가능)",
                reason="incomplete",
            )
        new_id = request.id or key
        if not is_screen_key(new_id):
            raise PromoteError(
                "validation_failed",
                f"화면 ID '{new_id}'는 ^[a-z][a-z0-9_]{{0,63}}$ 규칙이다 (예약 장치 이름 안 됨)",
                reason="id",
            )
        if new_id in index:
            raise PromoteError(
                "screen_exists", f"확정 화면 '{new_id}'이(가) 이미 있다", path=index[new_id][0]
            )
        dest_dir = _valid_folder(request.folder)
        dest = f"{dest_dir}/{new_id}{SUFFIX}"
    else:
        target = request.id or candidate.of
        if target is None:
            raise PromoteError(
                "validation_failed", f"후보 '{key}'에 합칠 화면(of)이 없다", reason="merge_target"
            )
        paths = index.get(target, [])
        if not paths:
            raise PromoteError("not_found", f"합칠 확정 화면 '{target}'이(가) 없다")
        if len(paths) > 1:
            raise PromoteError(
                "validation_failed", f"확정 화면 '{target}'의 파일이 여럿이다", reason="ambiguous"
            )
        new_id, dest = target, paths[0]
        dest_dir = dest.rsplit("/", 1)[0]
    if key in promoted and promoted[key] != new_id:
        raise PromoteError(
            "validation_failed",
            f"후보 키 '{key}'은(는) 이미 '{promoted[key]}'(으)로 승격됐다 — 같은 화면에 합치거나 "
            "다른 키로 저장한다",
            reason="already_promoted",
        )

    p = Plan(request, new_id, dest, candidate=candidate)
    p.revisions[card_rel] = sha256_of(raw)
    mapping = {**promoted, key: new_id} if key != new_id else dict(promoted)
    target_dir = f"targets/{SCREENS_DIR}/{new_id}"

    if request.mode == "new":
        out = copy.deepcopy(doc)
        out["format"] = "kookabug.screen/1"
        out.pop("of", None)
        if request.title is not None:
            out["title"] = request.title
        if request.description is not None:
            out["description"] = request.description
        out["detect"] = _copy_targets(
            root, doc.get("detect") or {}, request.session, key, target_dir, "", p
        )
        shot = doc.get("shot")
        own_shot = f"{session_rel}/{key}.shot.png"
        if isinstance(shot, dict) and shot.get("image") == own_shot:
            image = _read(root, own_shot)
            if image is None:
                out.pop("shot")
                p.warnings.append("대표 스크린샷 파일이 없어 shot을 뺐다")
            else:
                new_shot = f"{dest_dir}/{new_id}.shot.png"
                p.creates.append((new_shot, image))
                out["shot"] = {**shot, "image": new_shot}
        moves, _ = _rewrite_to(out.get("moves"), mapping)
        if moves:
            out["moves"] = moves
        p.revisions[dest] = None
    else:
        out, before = _load_dict(root, dest)
        p.revisions[dest] = sha256_of(before)
        out["format"] = "kookabug.screen/1"  # /0 → /1: 원래 값에 더한다
        moves = [m for m in out.get("moves", []) if isinstance(m, dict)]
        cand_moves, _ = _rewrite_to(doc.get("moves"), mapping)
        added = 0
        for m in cand_moves:
            if not any(_same_move(m, old) for old in moves):
                moves.append(m)
                added += 1
        if moves:
            out["moves"] = moves
        elements = [e for e in out.get("elements", []) if isinstance(e, dict)]
        names = {e.get("name") for e in elements}
        for e in doc.get("elements", []) or []:
            if isinstance(e, dict) and e.get("name") not in names:
                elements.append(e)
                names.add(e.get("name"))
        if elements:
            out["elements"] = elements
        if request.replace_shot:
            shot = doc.get("shot")
            own_shot = f"{session_rel}/{key}.shot.png"
            image = _read(root, own_shot) if isinstance(shot, dict) else None
            if image is None or not isinstance(shot, dict):
                p.warnings.append("후보에 대표 스크린샷이 없어 바꾸지 않았다")
            else:
                new_shot = f"{dest_dir}/{new_id}.shot.png"
                old_shot = _sha(root, new_shot)
                if old_shot is None:
                    p.creates.append((new_shot, image))
                else:
                    p.replaces.append((new_shot, old_shot, image))
                    p.revisions[new_shot] = old_shot
                out["shot"] = {**shot, "image": new_shot}
        if request.replace_detect:
            if not candidate.detect():
                p.warnings.append("후보에 판정 조건이 없어 바꾸지 않았다")
            else:
                prefix = f"{request.session.replace('-', '_')}_{key}_"
                out["detect"] = _copy_targets(
                    root, doc.get("detect") or {}, request.session, key, target_dir, prefix, p
                )
        if added == 0 and not request.replace_shot and not request.replace_detect:
            p.warnings.append("더할 이동·요소가 없다 (후보만 지운다)")
    try:
        parse_screen(out, dest)
    except ScreenFileError as exc:
        raise PromoteError("validation_failed", str(exc), path=dest) from exc
    if request.mode == "new":
        p.creates.insert(0, (dest, _encode(out)))
    else:
        before_sha = p.revisions[dest]
        assert before_sha is not None
        p.replaces.insert(0, (dest, before_sha, _encode(out)))
    for rel, _ in p.creates:
        p.revisions.setdefault(rel, None)

    # 키가 ID와 다르면: 같은 세션 남은 후보·같은 세션에서 승격된 확정 화면의 `to: 키`를 고친다
    if key != new_id:
        rename = {key: new_id}
        for c in explored_candidates(workspace):
            if c.session != request.session or c.key == key or c.placement != "session":
                continue
            _add_rename(root, c.path, rename, p)
        for sid, paths in sorted(index.items()):
            if sid == new_id or len(paths) != 1:
                continue
            try:
                other, _ = _load_dict(root, paths[0])
            except PromoteError:
                continue
            origin = other.get("origin")
            if isinstance(origin, dict) and origin.get("session") == request.session:
                _add_rename(root, paths[0], rename, p)

    # 후보 파일 전부를 지운다
    for rel in _candidate_files(root, request.session, key):
        data = _read(root, rel)
        if data is not None:
            p.deletes.append((rel, sha256_of(data)))
    # 만들 파일 자리가 비어 있어야 한다
    for rel, _ in p.creates:
        if _plain(root, rel).exists():
            raise PromoteError("exists", f"'{rel}'이(가) 이미 있다", path=rel)
    return p


def _add_rename(root: Path, rel: str, rename: Mapping[str, str], p: Plan) -> None:
    if any(r == rel for r, _, _ in p.replaces):
        return
    try:
        doc, raw = _load_dict(root, rel)
    except PromoteError:
        return
    moves, changed = _rewrite_to(doc.get("moves"), rename)
    if not changed:
        return
    doc["moves"] = moves
    before = sha256_of(raw)
    p.replaces.append((rel, before, _encode(doc)))
    p.revisions[rel] = before


def _same_move(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return a.get("via") == b.get("via") and a.get("to") == b.get("to")


# ---------------------------------------------------------------- 잠금


@contextlib.contextmanager
def _locked(root: Path, *, writing: bool = False) -> Iterator[list[str]]:
    """`screens.lock` → 복구. 복구 경고 목록을 준다. `writing`이면 복구 뒤에도 끝나지 않은 저널이
    있을 때 `recovery_pending`으로 거부한다 (B4 검수 High 1 — 멈춘 저널이 뒤 거래가 같은 경로에
    같은 바이트로 쓴 파일을 "이 거래가 쓴 것"으로 오인하지 않게, 저널이 남은 동안 새로 쓰지
    않는다)."""
    try:
        with screens_lock(root):
            warnings = recover(root)
            if writing:
                refuse_if_pending(root)
            yield warnings
    except ScreensBusy as exc:
        raise PromoteError("screens_busy", str(exc)) from exc


def pending(root: Path) -> list[dict[str, Any]]:
    """남은 거래 저널 (사람 확인용): `{txid, phase, paths, warnings, backups, guide}`. 안내·막는
    파일·백업은 저널 단계별로 다르다 (B4 검수 2라운드 Mid 1):

    - `committed`(승격은 끝났고 `explore.json` 기록에서 멈춤): 막는 파일은 그 `explore.json`뿐,
      안내는 `promoted[<키>]`를 확인해 고친다. 승격본·바뀐 파일·백업은 보이지 않는다(되돌리면
      성공한 승격을 망친다)
    - `prepare`(롤백이 사람이 고친 파일에서 멈춤): 남은 경고 항목만, 바꾼 파일은 원래 바이트(백업)로
      되돌린다. 승격이 만든 파일은 다른 곳으로 옮긴다
    - 깨진 저널은 `phase: "corrupt"`
    """
    out: list[dict[str, Any]] = []
    base = root.joinpath(*TX_DIR)
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        return out
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()):
        entry: dict[str, Any] = {"txid": folder.name, "folder": "/".join((*TX_DIR, folder.name))}
        try:
            journal = json.loads((folder / JOURNAL).read_text(encoding="utf-8"))
            if not isinstance(journal, dict) or journal.get("format") != FORMAT:
                raise ValueError("형식이 다르다")
        except (OSError, ValueError) as exc:
            entry.update(phase="corrupt", paths=[], warnings=[f"저널을 읽을 수 없다: {exc}"])
            entry["backups"] = {}
            entry["guide"] = f"승격 저널 {entry['folder']}이(가) 손상됐다 — 직접 확인한다"
            out.append(entry)
            continue
        entry["phase"] = journal.get("phase")
        entry["warnings"] = list(journal.get("warnings", []))
        if journal.get("phase") == "committed":
            explore = journal.get("explore") or {}
            key = str(explore.get("key"))
            rel = f"{_session_rel(str(explore.get('session')))}/{EXPLORE_FILE}"
            entry["paths"] = [rel]
            entry["backups"] = {}
            entry["guide"] = (
                f"승격은 끝났다 — {rel}의 promoted['{key}']를 확인해 고친다 "
                f"('{explore.get('id')}'(으)로 두거나 그 키를 지운다)"
            )
        else:
            creates = sorted(str(i["path"]) for i in journal.get("creates", []))
            replaces = sorted(str(i["path"]) for i in journal.get("replaces", []))
            entry["paths"] = sorted({*creates, *replaces})
            entry["backups"] = {
                str(i["path"]): "/".join((*TX_DIR, folder.name, str(i["backup"])))
                for i in journal.get("replaces", [])
            }
            parts: list[str] = []
            if replaces:
                parts.append(
                    "바뀐 파일(" + ", ".join(replaces) + ")은 원래 바이트(백업)로 되돌린다"
                )
            if creates:
                parts.append(
                    "승격이 만든 파일(" + ", ".join(creates) + ")은 필요하면 다른 곳으로 옮긴다"
                )
            entry["guide"] = "; ".join(parts) or "남은 항목이 없다 (다음 복구가 끝낸다)"
        out.append(entry)
    return out


def refuse_if_pending(root: Path) -> None:
    """끝나지 않은 저널이 있으면 `recovery_pending` (잠금을 쥔 채, 복구 뒤에 부른다)."""
    left = pending(root)
    if not left:
        return
    paths = sorted({p for e in left for p in e["paths"]})
    raise PromoteError(
        "recovery_pending",
        "끝나지 않은 화면 지도 승격 거래가 있어 바꾸지 않는다 — "
        + " / ".join(e["guide"] for e in left)
        + ". 그러면 다음 화면 지도 작업 때 복구가 끝나고 풀린다 (kookabug screen recover --show)",
        paths=paths,
        journals=[e["txid"] for e in left],
    )


def ensure_clear(root: Path) -> None:
    """`screens.lock`을 쥔 쓰기(에이전트 저장 등)가 부른다: 복구한 뒤에도 저널이 남아 있으면
    `recovery_pending`."""
    recover(root)
    refuse_if_pending(root)


def recover_locked(root: Path) -> list[str]:
    """잠금을 얻어 복구만 한다 (daemon 시작·CLI 시작). 잠금을 못 얻으면 `screens_busy`."""
    with _locked(root) as warnings:
        return warnings


# ---------------------------------------------------------------- 확인


def check(root: Path, request: PromoteRequest) -> dict[str, Any]:
    """승격 전 확인 (쓰지 않는다): 할 수 있는지, 고칠 파일 revision, 경고. 이미지 판정은 daemon이
    더한다."""
    with _locked(root) as recovered:
        try:
            refuse_if_pending(root)
            p = plan(root, request)
        except PromoteError as exc:
            if exc.code in ("screens_busy", "io_error", "path_outside_workspace"):
                raise
            return {
                "ok": False,
                "revisions": {},
                "warnings": recovered,
                "problems": [exc.message],
                "code": exc.code,
            }
        return {
            "ok": True,
            "id": p.id,
            "path": p.path,
            "revisions": dict(p.revisions),
            "warnings": [*recovered, *p.warnings],
            "problems": [],
        }


# ---------------------------------------------------------------- 승격


def promote(root: Path, request: PromoteRequest) -> dict[str, Any]:
    """승격 거래 한 번. `{path, id, cleanup_pending, warnings}`."""
    with _locked(root, writing=True) as recovered:
        p = plan(root, request)
        if dict(request.base_revisions) != p.revisions:
            changed = sorted(
                rel
                for rel in set(p.revisions) | set(request.base_revisions)
                if request.base_revisions.get(rel, "?") != p.revisions.get(rel, "?")
            )
            raise PromoteError(
                "revision_conflict",
                "확인한 뒤 화면 지도 파일이 바뀌었다 — 다시 확인한다",
                paths=changed,
            )
        tx = _Tx(root, p)
        try:
            tx.prepare()
            tx.publish()
            _stage("before_commit")
        except BaseException:
            tx.rollback_now()  # 저널이 없으면 거래 폴더만, 있으면 이 거래가 쓴 바이트만 되돌린다
            raise
        tx.commit()
        pending = False
        warnings = [*recovered, *p.warnings]
        try:
            _stage("after_commit")
            warnings += _finish(root, tx.folder, tx.journal)
            pending = tx.folder.exists()
        except Exception as exc:  # 커밋 뒤: 성공이다. 마무리는 다음 잠금에서
            log.warning("승격 마무리가 남았다 (%s): %s", tx.folder.name, exc)
            pending = True
        return {"path": p.path, "id": p.id, "cleanup_pending": pending, "warnings": warnings}


class _Tx:
    def __init__(self, root: Path, p: Plan) -> None:
        self.root = root
        self.plan = p
        self.txid = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        base = _plain(root, "/".join(TX_DIR))
        base.mkdir(parents=True, exist_ok=True)
        self.folder = _plain(root, "/".join((*TX_DIR, self.txid)))
        self.journal: dict[str, Any] = {}

    def prepare(self) -> None:
        p = self.plan
        self.folder.mkdir()
        backup = self.folder / "backup"
        backup.mkdir()
        replaces = []
        for n, (rel, before, after) in enumerate(p.replaces):
            data = _read(self.root, rel)
            if data is None or sha256_of(data) != before:
                raise PromoteError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])
            with open(backup / str(n), "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            replaces.append(
                {
                    "path": rel,
                    "before_sha256": before,
                    "after_sha256": sha256_of(after),
                    "backup": f"backup/{n}",
                }
            )
        # 이 거래가 만들 폴더 (지금 없는 것) — 롤백은 이것만 지운다 (B4 검수 Low 2)
        dirs: list[str] = []
        for rel, _ in p.creates:
            parts = _parts(rel)[:-1]
            for n in range(len(parts), 0, -1):
                folder_rel = "/".join(parts[:n])
                if _plain(self.root, folder_rel).exists():
                    break
                if folder_rel not in dirs:
                    dirs.append(folder_rel)
        self.journal = {
            "format": FORMAT,
            "txid": self.txid,
            "phase": "prepare",
            "created_at": _now(),
            "result": p.path,
            "creates": [{"path": rel, "sha256": sha256_of(data)} for rel, data in p.creates],
            "replaces": replaces,
            "deletes": [{"path": rel, "sha256": sha} for rel, sha in p.deletes],
            "dirs": dirs,
            "explore": {"session": p.request.session, "key": p.request.key, "id": p.id},
        }
        body = json.dumps(self.journal, ensure_ascii=False, indent=1).encode("utf-8")
        tmp = self.folder / f"{JOURNAL}.tmp"
        with open(tmp, "wb") as f:
            half = len(body) // 2
            f.write(body[:half])
            f.flush()
            _stage("journal_write")
            f.write(body[half:])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.folder / JOURNAL)
        _flush(self.folder)
        _flush(self.folder.parent)

    def publish(self) -> None:
        touched: set[Path] = set()
        for rel, data in self.plan.creates:
            path = _plain(self.root, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path = _plain(self.root, rel)  # 만든 폴더도 다시 본다
            tmp = path.with_name(f".{path.name}.{self.txid}.tmp")
            try:
                _write_file(tmp, data)
                os.rename(tmp, path)  # 배타: 있으면 실패
            except FileExistsError as exc:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise PromoteError("exists", f"'{rel}'이(가) 이미 있다", path=rel) from exc
            except BaseException:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            touched.add(path.parent)
            _stage("created")
        for rel, before, data in self.plan.replaces:
            path = _plain(self.root, rel)
            if _sha(self.root, rel) != before:
                raise PromoteError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])
            tmp = path.with_name(f".{path.name}.{self.txid}.tmp")
            try:
                _write_file(tmp, data)
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            touched.add(path.parent)
            _stage("replaced")
        for folder in sorted(touched):
            _flush(folder)

    def commit(self) -> None:
        committed = {**self.journal, "phase": "committed"}
        body = json.dumps(committed, ensure_ascii=False, indent=1).encode("utf-8")
        tmp = self.folder / f"{JOURNAL}.tmp"
        swapped = False
        try:
            with open(tmp, "wb") as f:
                f.write(body)
                f.flush()
                _stage("commit_fsync")
                os.fsync(f.fileno())
            os.replace(tmp, self.folder / JOURNAL)
            swapped = True
            self.journal = committed
            _flush(self.folder)
        except Exception as exc:
            if not swapped:
                # 저널은 아직 prepare다: 지금 되돌린다 (되돌리지 못하면 다음 복구가 한다)
                with contextlib.suppress(OSError):
                    tmp.unlink()
                self.rollback_now()
            raise PromoteError(
                "io_error", f"승격 커밋 표시를 쓰지 못했다 — 저널대로 복구한다: {exc}"
            ) from exc

    def rollback_now(self) -> None:
        """게시 중 실패: 저널이 있으면 그대로 되돌리고, 없으면 거래 폴더만 지운다."""
        try:
            if (self.folder / JOURNAL).is_file():
                _rollback(self.root, self.folder, self.journal)
            else:
                shutil.rmtree(self.folder, ignore_errors=True)
        except Exception:
            log.exception("승격 롤백 실패 (%s) — 다음 복구가 다시 한다", self.txid)


# ---------------------------------------------------------------- 마무리·롤백·복구


def _finish(root: Path, folder: Path, journal: Mapping[str, Any]) -> list[str]:
    """커밋된 거래의 마무리 (멱등). 끝나면 거래 폴더를 지운다. 경고 목록."""
    warnings: list[str] = []
    emptied: set[Path] = set()
    for item in journal.get("deletes", []):
        rel = str(item["path"])
        path = _plain(root, rel)
        current = _sha(root, rel)
        if current is None:
            continue
        if current != item["sha256"]:
            warnings.append(f"'{rel}'이(가) 승격 뒤 바뀌어 지우지 않았다")
            continue
        path.unlink()
        emptied.add(path.parent)
        _stage("deleted")
    for parent in sorted(emptied, key=lambda p: len(p.parts), reverse=True):
        with contextlib.suppress(OSError):
            parent.rmdir()  # 빈 targets/<키>/ 폴더
    _stage("before_explore")
    explore = journal.get("explore") or {}
    done = _mark_promoted(root, str(explore["session"]), str(explore["key"]), str(explore["id"]))
    if done is not None:
        warnings.append(done)
        log.warning("%s", done)
        # 저널을 남긴다 (사람이 explore.json을 고친 뒤 다시 시도). 지우기는 끝났으니 저널에서 뺀다
        _write_journal(folder, {**journal, "deletes": [], "warnings": [done], "updated_at": _now()})
        return warnings
    _stage("after_explore")
    _stage("before_journal_remove")
    shutil.rmtree(folder)
    return warnings


def _mark_promoted(root: Path, session: str, key: str, new_id: str) -> str | None:
    """`explore.json` `promoted[키] = ID`. 이미 같으면 그대로. 다른 ID가 있으면 덮지 않고 경고
    글."""
    rel = f"{_session_rel(session)}/{EXPLORE_FILE}"
    path = _plain(root, rel)
    raw = _read(root, rel)
    if raw is None:
        return None  # 세션 기록이 없다 (사람이 지움): 기록할 곳이 없다
    try:
        doc = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return f"'{rel}'을(를) 읽을 수 없어 승격 기록을 남기지 않았다 (저널 유지)"
    if not isinstance(doc, dict):
        return f"'{rel}'이(가) JSON 객체가 아니라 승격 기록을 남기지 않았다 (저널 유지)"
    promoted = doc.get("promoted")
    if not isinstance(promoted, dict):
        promoted = {}
    if promoted.get(key) == new_id:
        return None
    if key in promoted:
        return (
            f"'{rel}'에 후보 '{key}'이(가) 이미 '{promoted[key]}'(으)로 기록돼 있어 덮지 않았다 "
            "(저널 유지)"
        )
    doc["promoted"] = {**promoted, key: new_id}
    before = sha256_of(raw)

    def unchanged() -> None:
        if _sha(root, rel) != before:
            raise PromoteError("revision_conflict", f"'{rel}'이(가) 바뀌었다 — 다음에 다시 한다")

    try:
        write_atomic(
            path,
            json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"),
            before_replace=unchanged,
        )
    except DocumentError as exc:
        raise PromoteError("io_error", str(exc)) from exc
    return None


def _rollback(root: Path, folder: Path, journal: Mapping[str, Any]) -> list[str]:
    """준비된(커밋 안 된) 거래를 되돌린다. 이 거래가 쓴 바이트일 때만 손댄다.

    끝난 항목(지운 새 파일·되돌렸거나 이미 원래 바이트인 바꾼 파일·사람이 지운 파일)은 저널에서
    빼고 저널을 원자 교체한다 — 다시 실행해도 처리한 경로는 건드리지 않는다. 경고 항목(사람이 고친
    파일·백업 손상)만 남고, 남은 것이 없으면 거래 폴더를 지운다. 저널이 남아 있는 동안 새 승격·
    버리기·저장은 거부되므로(`recovery_pending`) 남은 항목의 경로에 다른 거래가 쓰지 않는다.

    풀리는 길: 바꾼 파일이 원래 바이트(백업)이거나 지워졌으면, 만든 파일이 지워졌거나 이 거래가 쓴
    바이트 그대로면(그때는 지운다) 그 항목이 끝난다."""
    warnings: list[str] = []
    notes: list[str] = []
    """끝났지만 사람이 알아야 하는 것 (저널을 남기지 않는다)."""
    txid = str(journal.get("txid", folder.name))
    left_replaces: list[Any] = []
    left_creates: list[Any] = []
    for item in journal.get("replaces", []):
        rel = str(item["path"])
        path = _plain(root, rel)
        current = _sha(root, rel)
        if current == item["before_sha256"]:
            continue  # 원래 바이트: 끝
        if current is None:
            # 사람이 지웠다: 되살리지 않고 끝내되, 원래 바이트(백업)는 버리지 않는다 — 그 확정 화면
            # 원본의 유일한 사본일 수 있다 (B4 검수 2라운드 Mid 2). 자동으로 지우지 않는다
            kept = _keep_backup(root, folder, txid, item)
            notes.append(f"'{rel}'이(가) 지워져 되살리지 않았다 — 원래 바이트는 {kept}에 남겼다")
            continue
        if current == item["after_sha256"]:
            backup = (folder / str(item["backup"])).read_bytes()
            if sha256_of(backup) != item["before_sha256"]:
                warnings.append(f"'{rel}'의 백업이 손상돼 되돌리지 않았다")
                left_replaces.append(item)
                continue
            tmp = path.with_name(f".{path.name}.{txid}.rb.tmp")
            with open(tmp, "wb") as f:
                f.write(backup)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            _flush(path.parent)
            continue
        warnings.append(
            f"'{rel}'이(가) 승격 중에 바뀌어 되돌리지 않았다 (사용자 바이트 보존 — 원래 바이트는 "
            f"{'/'.join((*TX_DIR, folder.name, str(item['backup'])))})"
        )
        left_replaces.append(item)
    for item in reversed(journal.get("creates", [])):
        rel = str(item["path"])
        path = _plain(root, rel)
        current = _sha(root, rel)
        if current is None:
            continue
        if current != item["sha256"]:
            warnings.append(f"'{rel}'이(가) 승격 중에 바뀌어 지우지 않았다 (사용자 바이트 보존)")
            left_creates.insert(0, item)
            continue
        path.unlink()
    # 남은 임시 파일 (이 거래 이름)
    for item in [*journal.get("creates", []), *journal.get("replaces", [])]:
        parent = _plain(root, str(item["path"])).parent
        if parent.is_dir():
            for tmp in parent.glob(f".*.{txid}*.tmp"):
                with contextlib.suppress(OSError):
                    tmp.unlink()
    # 이 거래가 만든 폴더만, 비었을 때만 지운다 (깊은 것부터)
    left_dirs: list[str] = []
    for folder_rel in sorted(journal.get("dirs", []), key=lambda r: r.count("/"), reverse=True):
        path = _plain(root, str(folder_rel))
        if not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            left_dirs.append(str(folder_rel))
    for note in notes:
        log.warning("승격 롤백: %s", note)
    if warnings:
        for w in warnings:
            log.warning("승격 롤백: %s", w)
        _write_journal(
            folder,
            {
                **journal,
                "creates": left_creates,
                "replaces": left_replaces,
                "deletes": [],
                "dirs": left_dirs,
                "warnings": warnings,
                "updated_at": _now(),
            },
        )
        return [*warnings, *notes]
    shutil.rmtree(folder, ignore_errors=True)
    return notes


KEPT_DIR: Final = (".kookabug", "screens-tx-kept")
"""사람이 지워 끝낸 바꾼 파일의 원래 바이트를 남기는 곳 (자동으로 지우지 않는다)."""


def _keep_backup(root: Path, folder: Path, txid: str, item: Mapping[str, Any]) -> str:
    """백업을 `.kookabug/screens-tx-kept/<txid>/<원래 경로>`로 복사한다. 그 경로(워크스페이스
    기준)."""
    rel = "/".join((*KEPT_DIR, txid, *_parts(str(item["path"]))))
    target = _plain(root, rel)
    data = (folder / str(item["backup"])).read_bytes()
    if target.is_file() and target.read_bytes() == data:
        return rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _plain(root, rel)
    tmp = target.with_name(f".{target.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    _flush(target.parent)
    return rel


def recover(root: Path) -> list[str]:
    """남은 거래를 끝낸다 (`screens.lock`을 쥔 채 부른다). 경고 목록."""
    base = root.joinpath(*TX_DIR)
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        return []
    warnings: list[str] = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()):
        journal_path = folder / JOURNAL
        if not journal_path.exists():
            # 저널을 다 쓰기 전에 멈췄다: 게시한 것이 없다
            shutil.rmtree(folder, ignore_errors=True)
            warnings.append(f"끝나지 않은 승격 준비 {folder.name}을(를) 지웠다 (바뀐 파일 없음)")
            continue
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if not isinstance(journal, dict) or journal.get("format") != FORMAT:
                raise ValueError("형식이 다르다")
            phase = journal["phase"]
        except (OSError, ValueError, KeyError) as exc:
            text = f"승격 저널 {folder.name}이(가) 깨져 손대지 않았다: {exc}"
            log.warning("%s", text)
            warnings.append(text)
            continue
        try:
            if phase == "committed":
                warnings += _finish(root, folder, journal)
            elif phase == "prepare":
                warnings += _rollback(root, folder, journal)
            else:
                warnings.append(f"승격 저널 {folder.name}의 단계 {phase!r}를 몰라 손대지 않았다")
        except PromoteError as exc:
            warnings.append(f"승격 저널 {folder.name}: {exc.message}")
        except Exception as exc:  # 파일이 잠겨 있는 등: 저널을 남기고 다음에 다시
            log.exception("승격 저널 %s 복구 실패", folder.name)
            warnings.append(f"승격 저널 {folder.name}을(를) 복구하지 못했다 (다음에 다시): {exc}")
    return warnings


# ---------------------------------------------------------------- 버리기


def discard(
    root: Path, session: str, key: str | None = None, *, active: Collection[str] = ()
) -> list[str]:
    """`screens/_explored/<세션>/` 아래 일반 파일만 지운다(사람만). 링크·정션이 있으면 아무것도
    지우지 않는다. 세션 전체는 활성 세션이면 `explore_active`. 지운 경로 목록."""
    _require_session(session)
    with _locked(root, writing=True):
        session_rel = _session_rel(session)
        folder = _plain(root, session_rel)
        if not folder.is_dir():
            raise PromoteError("not_found", f"탐색 세션 '{session}'이(가) 없다")
        if key is None:
            if session in active:
                raise PromoteError(
                    "explore_active", f"탐색 세션 '{session}'이(가) 진행 중이다 (끝난 뒤 버린다)"
                )
            files: list[str] = []
            dirs: list[Path] = []
            for dirpath, dirnames, filenames in os.walk(folder):
                here = Path(dirpath)
                for name in [*dirnames, *filenames]:
                    entry = here / name
                    if entry.is_symlink() or entry.is_junction():
                        rel = "/".join((session_rel, *entry.relative_to(folder).parts))
                        raise PromoteError(
                            "path_outside_workspace",
                            f"'{rel}'이(가) 링크·정션이라 아무것도 지우지 않았다",
                            path=rel,
                        )
                dirs.extend(here / d for d in dirnames)
                files.extend(
                    "/".join((session_rel, *(here / f).relative_to(folder).parts))
                    for f in filenames
                )
            for rel in files:
                _plain(root, rel).unlink()
            for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
                with contextlib.suppress(OSError):
                    d.rmdir()
            with contextlib.suppress(OSError):
                folder.rmdir()
            return sorted(files)
        if not is_screen_key(key):
            raise PromoteError("validation_failed", f"후보 키 '{key}'의 형식이 틀렸다")
        card = f"{session_rel}/{key}{SUFFIX}"
        if not _plain(root, card).is_file():
            raise PromoteError("not_found", f"후보 '{session}/{key}'이(가) 없다")
        files = _candidate_files(root, session, key)
        for rel in files:
            _plain(root, rel).unlink()
        with contextlib.suppress(OSError):
            _plain(root, f"{session_rel}/targets/{key}").rmdir()
        return files


def journals(root: Path) -> Sequence[str]:
    """남아 있는 거래 폴더 이름들 (진단·검사용)."""
    base = root.joinpath(*TX_DIR)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())

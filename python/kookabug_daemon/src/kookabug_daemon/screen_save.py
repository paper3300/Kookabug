"""화면 지도 저장·식별 (M7 계획 3.5·3.6, 10장 R4) — `screens.save`(`kb_screen_save`)·
`screens.identify`(`kb_screen_identify`).

저장은 에이전트의 자기 탐색 세션 폴더(`screens/_explored/<세션>/`)에만 쓴다. 경로는 daemon이
조합한다(키는 `^[a-z][a-z0-9_]{0,63}$`). 잠금 순서는 `screens.lock` → 세션 잠금.

정지 화면 보호(3.5a): 프레임 판정(`FrameGuard.effective`)이 `clear`일 때만 대표 스크린샷·이미지 조건
crop·OCR 조건 확인을 한다. 아니면 `detect`에 조건이 있으면 `frame_protected`로 거부하고, 조건이
없으면(이동·요소·제목만) 스크린샷 없이 저장한다. 판정 조건이 없는 새 후보는 `incomplete`다.
쓰기 전에 모든 글자 필드를 3.5b 검사(`explore.check_texts`)로 본다 — 값은 어디에도 쓰지 않는다.

식별은 확정 화면 + 자기 세션 후보의 `detect`를 그 프레임에서 평가한다. 프레임이 `clear`가 아니면
OCR 조건은 평가하지 않는다(`unknown` — 비밀값 추측 통로 차단). 읽은 글자는 결과에 넣지 않는다.
판정 조건 없는 후보·`of`만 있는 후보는 `matches`에 넣지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from kookabug_core.canonical import loads_strict
from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.screens import (
    EXPLORED_DIR,
    SCREENS_DIR,
    SUFFIX,
    ScreenDef,
    ScreenFileError,
    candidate_ref,
    explored_candidates,
    is_screen_key,
    parse_screen,
    read_screen_file,
    screen_index,
)
from kookabug_core.workspace import Workspace
from kookabug_daemon.explore import (
    ExploreSession,
    check_texts,
    job_secrets,
    plain_path,
    write_lock,
)
from kookabug_daemon.protocol import InvalidParams, RequestFailed

if TYPE_CHECKING:
    from kookabug_daemon.frame_guard import FrameGuard
    from kookabug_daemon.frames import EditorFrame
    from kookabug_sdk.types import Target

__all__ = ["SHOT_SIDE", "identify", "save"]

SHOT_SIDE: Final = 1280
"""대표 스크린샷 긴 변 (U7)."""
_LIMITS: Final = {"title": 200, "description": 2000, "element": 100, "note": 256, "ocr": 100}


def _bad(text: str) -> InvalidParams:
    return InvalidParams(text)


def _length(name: str, value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _bad(f"{name}은(는) 빈 글자가 아닌 문자열이어야 한다")
    if len(value) > limit:
        raise _bad(f"{name}은(는) {limit}자 이하여야 한다")
    return value


def _rect_px(value: Any, frame: EditorFrame, name: str) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(cast(list[Any], value)) != 4:
        raise _bad(f"{name}은(는) [x, y, 너비, 높이]다")
    x, y, w, h = (int(v) for v in cast(list[Any], value))
    if w < 1 or h < 1 or x < 0 or y < 0 or x + w > frame.width or y + h > frame.height:
        raise _bad(f"{name} {[x, y, w, h]}이(가) 정지 화면({frame.width}x{frame.height}) 밖이다")
    return x, y, w, h


def _norm(rect: tuple[int, int, int, int], frame: EditorFrame) -> list[float]:
    x, y, w, h = rect
    fw, fh = frame.width, frame.height
    return [round(x / fw, 4), round(y / fh, 4), round(w / fw, 4), round(h / fh, 4)]


def _point_norm(value: Any, frame: EditorFrame) -> list[float]:
    if not isinstance(value, list) or len(cast(list[Any], value)) != 2:
        raise _bad("click.point는 [x, y]다")
    x, y = (int(v) for v in cast(list[Any], value))
    if not (0 <= x < frame.width and 0 <= y < frame.height):
        raise _bad(f"click.point {[x, y]}이(가) 정지 화면 밖이다")
    return [round(x / frame.width, 4), round(y / frame.height, 4)]


def _loader(root: Path) -> Callable[[str], Target]:
    from kookabug_platform.vision import load_target_file
    from kookabug_sdk.types import Target

    cache: dict[str, Target] = {}

    def load(rel: str) -> Target:
        if rel not in cache:
            path = Workspace.resolve_from("", rel)
            if path is None:
                raise ValueError(f"target 경로 '{rel}'이(가) 워크스페이스 밖이다")
            found = load_target_file(root.joinpath(*path.split("/")))
            cache[rel] = Target(name=rel, path=found.path, spec=found.spec)
        return cache[rel]

    return load


def _reader(daemon: Any) -> Any:
    from kookabug_platform.ocr.engine import Ocr

    return Ocr(daemon.targets.ocr())


# ---------------------------------------------------------------- 식별


def _candidates_for(
    workspace: Workspace, session: ExploreSession | None
) -> list[tuple[str, str, str, ScreenDef]]:
    """(node, id 또는 key, state, 화면) — 확정 화면 + 자기 세션 후보."""
    out: list[tuple[str, str, str, ScreenDef]] = []
    for sid, paths in sorted(screen_index(workspace).items()):
        if len(paths) != 1:
            continue
        path = workspace.resolve(paths[0])
        if path is None:
            continue
        try:
            out.append((sid, sid, "confirmed", read_screen_file(path, paths[0])))
        except ScreenFileError:
            continue
    if session is not None:
        for c in explored_candidates(workspace):
            if c.session == session.id and c.placement == "session" and c.screen is not None:
                out.append((f"x:{c.session}/{c.key}", c.key, "explored", c.screen))
    return out


def identify(
    daemon: Any,
    frame: EditorFrame,
    session: ExploreSession | None,
    *,
    exclude: str | None = None,
) -> dict[str, Any]:
    """그 정지 화면에 맞는 화면들. `exclude`는 뺄 node (저장한 자기 자신)."""
    from kookabug_platform.screens import evaluate_screen
    from kookabug_platform.vision import Vision

    workspace = Workspace.open(daemon.root)
    guard: FrameGuard = daemon.guard
    clear = guard.effective(frame).clear
    reader = _reader(daemon) if clear else None
    load = _loader(daemon.root)
    matches: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    checked = 0
    for node, name, state, screen in _candidates_for(workspace, session):
        if node == exclude or not screen.detect():
            continue  # 판정 조건 없는 후보·of만 있는 후보는 판정하지 않는다
        checked += 1
        entry = {"node": node, "state": state, "title": screen.title}
        entry["id" if state == "confirmed" else "key"] = name
        try:
            result = evaluate_screen(screen, load, frame.pixels, frame.meta(), Vision(), ocr=reader)
        except Exception as exc:  # target 깨짐·OCR 실패: 그 화면만 문제로
            problems.append({"node": node, "problem": type(exc).__name__})
            continue
        if result.state == "matched":
            matches.append(entry)
        elif result.state == "unknown":
            unknown.append(entry)
    return {"matches": matches, "unknown": unknown, "checked": checked, "problems": problems}


# ---------------------------------------------------------------- 저장


def _conditions(
    params: Mapping[str, Any], frame: EditorFrame
) -> list[tuple[str, str, tuple[int, int, int, int], str | None]]:
    """(그룹, 종류 image|ocr, 프레임 px 상자, OCR 글자)."""
    detect = params.get("detect")
    if detect is None:
        return []
    if not isinstance(detect, dict):
        raise _bad("detect는 {all?, none?}이다")
    out: list[tuple[str, str, tuple[int, int, int, int], str | None]] = []
    for group in ("all", "none"):
        for i, cond in enumerate(cast(list[Any], cast(dict[str, Any], detect).get(group) or [])):
            if not isinstance(cond, dict):
                raise _bad(f"detect.{group}[{i}]은(는) 객체다")
            item = cast(dict[str, Any], cond)
            if "image" in item:
                out.append((group, "image", _rect_px(item["image"], frame, "image"), None))
            elif "ocr" in item:
                text = _length("ocr text", item.get("text"), _LIMITS["ocr"])
                out.append((group, "ocr", _rect_px(item["ocr"], frame, "ocr"), text))
            else:
                raise _bad(f"detect.{group}[{i}]은(는) image 또는 ocr이다")
    return out


def _texts(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """3.5b 표의 글자 필드 전부 (필드 이름, 글자)."""
    out: list[tuple[str, str]] = [("key", str(params.get("key", "")))]
    for name in ("title", "description", "of"):
        if isinstance(params.get(name), str):
            out.append((name, params[name]))
    for i, e in enumerate(cast(list[Any], params.get("elements") or [])):
        if isinstance(e, dict) and isinstance(cast(dict[str, Any], e).get("name"), str):
            out.append((f"elements[{i}].name", cast(dict[str, Any], e)["name"]))
    for i, m in enumerate(cast(list[Any], params.get("moves") or [])):
        if not isinstance(m, dict):
            continue
        move = cast(dict[str, Any], m)
        for name in ("to", "note"):
            if isinstance(move.get(name), str):
                out.append((f"moves[{i}].{name}", move[name]))
        via = move.get("via")
        if isinstance(via, dict):
            via_map = cast(dict[str, Any], via)
            click = via_map.get("click")
            if isinstance(click, dict) and isinstance(
                cast(dict[str, Any], click).get("element"), str
            ):
                out.append(
                    (f"moves[{i}].via.click.element", cast(dict[str, Any], click)["element"])
                )
            if isinstance(via_map.get("key"), str):
                out.append((f"moves[{i}].via.key", via_map["key"]))
    detect = params.get("detect")
    if isinstance(detect, dict):
        for group in ("all", "none"):
            for j, cond in enumerate(
                cast(list[Any], cast(dict[str, Any], detect).get(group) or [])
            ):
                if isinstance(cond, dict) and isinstance(
                    cast(dict[str, Any], cond).get("text"), str
                ):
                    out.append((f"detect.{group}[{j}].text", cast(dict[str, Any], cond)["text"]))
    return out


def _moves(
    params: Mapping[str, Any], frame: EditorFrame, confirmed: Mapping[str, Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, m in enumerate(cast(list[Any], params.get("moves") or [])):
        if not isinstance(m, dict):
            raise _bad(f"moves[{i}]은(는) 객체다")
        move = cast(dict[str, Any], m)
        via = move.get("via")
        if not isinstance(via, dict):
            raise _bad(f"moves[{i}].via가 없다")
        via_map = cast(dict[str, Any], via)
        click = via_map.get("click")
        if isinstance(click, dict) and "point" in cast(dict[str, Any], click):
            shaped: dict[str, Any] = {
                "click": {"point": _point_norm(cast(dict[str, Any], click)["point"], frame)}
            }
        elif isinstance(click, dict):
            shaped = {"click": {"element": cast(dict[str, Any], click).get("element")}}
        else:
            shaped = {"key": via_map.get("key")}
        to = move.get("to")
        # 새 후보 키(같은 세션)이거나 이미 있는 확정 화면 ID (기존 ID는 파일 이름 그대로)
        if to is not None and (
            not isinstance(to, str) or not (is_screen_key(to) or to in confirmed)
        ):
            raise _bad(f"moves[{i}].to {to!r}은(는) 후보 키 규칙도 확정 화면 ID도 아니다")
        entry: dict[str, Any] = {"via": shaped, "to": to, "status": move.get("status")}
        if move.get("note") is not None:
            entry["note"] = _length(f"moves[{i}].note", move["note"], _LIMITS["note"])
        out.append(entry)
    return out


def _merge_moves(old: Sequence[Any], new: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [dict(cast(dict[str, Any], m)) for m in old if isinstance(m, dict)]
    for move in new:
        same = next(
            (m for m in merged if m.get("via") == move["via"] and m.get("to") == move["to"]), None
        )
        if same is None:
            merged.append(move)
        else:
            same.update(move)
    return merged


def save(call: Any, frame: EditorFrame, session: ExploreSession) -> dict[str, Any]:
    """`screens.save` 본체 (막히는 호출). 판정·세션 확인은 처리기가 했다."""
    daemon = call.daemon
    params: Mapping[str, Any] = call.params
    root: Path = daemon.root
    key = params.get("key")
    if not isinstance(key, str) or not is_screen_key(key):
        raise _bad("key는 ^[a-z][a-z0-9_]{0,63}$ 규칙의 후보 키다")
    rel = f"{session.rel}/{key}{SUFFIX}"
    assert candidate_ref(rel) == (session.id, key)
    title = params.get("title")
    if title is not None:
        _length("title", title, _LIMITS["title"])
    if params.get("description") is not None:
        _length("description", params["description"], _LIMITS["description"])
    elements_in = cast(list[Any], params.get("elements") or [])
    for i, e in enumerate(elements_in):
        if not isinstance(e, dict):
            raise _bad(f"elements[{i}]은(는) 객체다")
        _length(f"elements[{i}].name", cast(dict[str, Any], e).get("name"), _LIMITS["element"])
    # 3.5b: 글자 필드 전부 비밀값 검사 — 아무것도 쓰기 전에
    check_texts(_texts(params), daemon.guard, root, job_secrets(daemon))

    workspace = Workspace.open(root)
    confirmed = screen_index(workspace)
    if key in confirmed:
        raise RequestFailed("screen_exists", f"확정 화면 '{key}'이(가) 이미 있다 (다른 키를 쓴다)")
    of = params.get("of")
    if of is not None and (not isinstance(of, str) or of not in confirmed):
        raise _bad(f"of {of!r}은(는) 확정 화면 ID가 아니다")
    conditions = _conditions(params, frame)
    guard: FrameGuard = daemon.guard
    verdict = guard.effective(frame)
    if conditions and not verdict.clear:
        info = verdict.to_json()
        raise RequestFailed(
            "frame_protected",
            f"보호 중인 정지 화면이라 판정 조건·스크린샷을 만들지 않는다 ({info['hint']})",
            reason=info["reason"],
            message=info["hint"],
        )
    elements = [
        {
            "name": cast(dict[str, Any], e)["name"],
            "kind": cast(dict[str, Any], e).get("kind"),
            "rect": _norm(
                _rect_px(cast(dict[str, Any], e).get("rect"), frame, "element rect"), frame
            ),
        }
        for e in elements_in
    ]
    moves = _moves(params, frame, confirmed)

    # 1) 준비 (잠금 밖): crop 확인·OCR·스크린샷은 스테이징 폴더에 만든다 — 느린 판정이 화면 지도
    #    잠금을 쥐지 않게 (B4 승격·CLI가 기다리지 않게)
    session_parts = (SCREENS_DIR, EXPLORED_DIR, session.id)
    folder = plain_path(root, session_parts)
    staging = Path(tempfile.mkdtemp(prefix=".save-", dir=folder))
    try:
        detect, publish = (
            _detect(daemon, call, frame, session, key, conditions, staging)
            if conditions
            else ({}, [])
        )
        shot: dict[str, Any] | None = None
        # 대표 스크린샷: 보호 통과한 프레임이고 이번에 판정 조건을 주었을 때만 (그 조건이 맞는 이
        # 화면의 프레임이다 — 이동·제목만 고치는 저장은 다른 화면의 프레임일 수 있다)
        if verdict.clear and conditions:
            staged_shot = staging / f"{key}.shot.png"
            staged_shot.write_bytes(_shot_png(frame))
            publish.append((staged_shot, (f"{key}.shot.png",)))
            shot = {
                "image": f"{session.rel}/{key}.shot.png",
                "client_size": [frame.width, frame.height],
                "scale": round(min(1.0, SHOT_SIDE / max(frame.width, frame.height)), 4),
            }
        # 2) 게시 (screens.lock → 세션 잠금): 기존 파일 읽기·합치기·게시만
        with write_lock(root, session):
            parsed = _commit(
                params, session, key, rel, detect, shot, elements, moves, publish, root
            )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # 3) 잠금 뒤: 같은 화면일 수 있는 후보·확정 화면
    node = f"x:{session.id}/{key}"
    also = identify(daemon, frame, session, exclude=node)["matches"]
    result: dict[str, Any] = {
        "path": rel,
        "key": key,
        "revision": _revision(root.joinpath(*rel.split("/"))),
        "also_matches": [{"node": m["node"], "title": m.get("title")} for m in also],
        "shot": "saved" if shot is not None else "omitted",
    }
    if shot is None and not verdict.clear:
        result["reason"] = verdict.to_json()["reason"]
    if parsed.incomplete:
        result["incomplete"] = True
    return result


def _commit(
    params: Mapping[str, Any],
    session: ExploreSession,
    key: str,
    rel: str,
    detect: Mapping[str, Any],
    shot: Mapping[str, Any] | None,
    elements: list[dict[str, Any]],
    moves: list[dict[str, Any]],
    publish: list[tuple[Path, tuple[str, ...]]],
    root: Path,
) -> ScreenDef:
    """잠금 안: 기존 카드를 읽어 합치고, 준비한 파일을 게시하고, 카드를 원자 교체한다. 쓰는 경로는
    모두 세션 폴더 실경로 아래이고 경로 조각에 링크·정션이 없어야 한다 (B2b Mid 1)."""
    session_parts = (SCREENS_DIR, EXPLORED_DIR, session.id)
    folder = plain_path(root, session_parts)
    path = plain_path(root, (*session_parts, f"{key}{SUFFIX}"), within=folder)
    # 끝나지 않은 승격 저널이 있으면 쓰지 않는다 (B4 검수 High 1 — 승격·버리기와 같은 확인)
    from kookabug_core.screen_promote import PromoteError, ensure_clear

    try:
        ensure_clear(root)
    except PromoteError as exc:
        raise RequestFailed(exc.code, exc.message, **exc.fields) from exc
    # 잠금 밖 준비 동안 사람이 같은 키를 확정 화면으로 승격했을 수 있다 (CLI·daemon 승격, R4):
    # 잠금 안에서 다시 본다
    confirmed = screen_index(Workspace.open(root))
    if key in confirmed:
        raise RequestFailed("screen_exists", f"확정 화면 '{key}'이(가) 이미 있다 (다른 키를 쓴다)")
    of = params.get("of")
    if of is not None and of not in confirmed:
        raise _bad(f"of {of!r}은(는) 확정 화면 ID가 아니다")
    old: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = loads_strict(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RequestFailed("io_error", f"후보 파일을 읽을 수 없다: {exc}") from exc
        old = cast(dict[str, Any], loaded) if isinstance(loaded, dict) else {}
    doc: dict[str, Any] = dict(old) or {"format": "kookabug.screen/1"}
    doc["format"] = "kookabug.screen/1"
    for name in ("title", "description", "kind", "of"):
        if params.get(name) is not None:
            doc[name] = params[name]
    if "elements" in params:
        doc["elements"] = elements
    if moves:
        doc["moves"] = _merge_moves(cast(list[Any], doc.get("moves") or []), moves)
    if detect:
        doc["detect"] = dict(detect)
    if shot is not None:
        doc["shot"] = dict(shot)
    doc["origin"] = {
        "kind": "explored",
        "session": session.id,
        "agent": session.agent_id,
        "at": _stamp(),
    }
    try:
        parsed = parse_screen(doc, rel)
    except ScreenFileError as exc:
        raise _bad(str(exc)) from exc
    for source, parts in publish:
        target = plain_path(root, (*session_parts, *parts), within=folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 만든 폴더도 다시 본다 (그 사이 링크로 바뀌지 않았는지)
        target = plain_path(root, (*session_parts, *parts), within=folder)
        os.replace(source, target)
    body = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    try:
        write_atomic(path, body)
    except DocumentError as exc:
        raise RequestFailed("io_error", str(exc)) from exc
    return parsed


def _detect(
    daemon: Any,
    call: Any,
    frame: EditorFrame,
    session: ExploreSession,
    key: str,
    conditions: Iterable[tuple[str, str, tuple[int, int, int, int], str | None]],
    staging: Path,
) -> tuple[dict[str, Any], list[tuple[Path, tuple[str, ...]]]]:
    """조건 → `detect`. 이미지 조건은 잘라 target으로(같은 프레임에서 찾아야), OCR 조건은 그 영역에
    글자가 있어야 한다. 쓸 파일은 `staging`에 두고 (원본, 세션 폴더 기준 게시 경로 조각)으로
    돌려준다."""
    from kookabug_daemon.methods.target import (
        _guard_crop,  # pyright: ignore[reportPrivateUsage]
    )
    from kookabug_platform.frames import encode_png
    from kookabug_platform.screens import normalize_text
    from kookabug_platform.vision import Vision, load_target_file

    detect: dict[str, list[dict[str, Any]]] = {}
    publish: list[tuple[Path, tuple[str, ...]]] = []
    reader = None
    for n, (group, kind, box, text) in enumerate(conditions, start=1):
        x, y, w, h = box
        if kind == "image":
            _guard_crop(call, frame, list(box))
            crop = frame.pixels[y : y + h, x : x + w].copy()
            png = staging / f"{n}.png"
            spec = staging / f"{n}.target.json"
            png.write_bytes(encode_png(crop))
            spec.write_text(
                json.dumps({"format": "kookabug.target/0", "image": f"{n}.png"}), encoding="utf-8"
            )
            found = Vision().find(frame.pixels, frame.meta(), load_target_file(spec))
            if not found.found:
                raise RequestFailed(
                    "detect_not_matching",
                    f"이미지 조건 {n}({list(box)})을(를) 같은 정지 화면에서 찾지 못했다",
                )
            publish += [
                (png, ("targets", key, png.name)),
                (spec, ("targets", key, spec.name)),
            ]
            item: dict[str, Any] = {"$target": f"{session.rel}/targets/{key}/{n}.target.json"}
        else:
            assert text is not None
            if reader is None:
                reader = _reader(daemon)
            read = reader.read(frame.pixels, region=box).text
            if normalize_text(text) not in normalize_text(read):
                raise RequestFailed(
                    "detect_not_matching",
                    f"OCR 조건 {n}의 글자를 그 영역({list(box)})에서 읽지 못했다",
                )
            item = {"ocr": {"rect": _norm(box, frame), "text": text}}
        detect.setdefault(group, []).append(item)
    return detect, publish


def _shot_png(frame: EditorFrame) -> bytes:
    import cv2
    import numpy as np

    from kookabug_platform.frames import encode_png

    side = max(frame.width, frame.height)
    pixels = frame.pixels
    if side > SHOT_SIDE:
        scale = SHOT_SIDE / side
        size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
        pixels = np.asarray(cv2.resize(pixels, size, interpolation=cv2.INTER_AREA), dtype=np.uint8)
    return encode_png(pixels)


def _revision(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _stamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

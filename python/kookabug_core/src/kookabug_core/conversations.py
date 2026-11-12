"""에이전트 패널 이전 대화 (UX4): `.kookabug/conversations/<id>.json` (이 PC, 팀 공유 아님).

- 대화 하나가 파일 하나다: `{format, id, title, agent_id, agent_name, acp_session, created_at,
  updated_at, items}`. `items`는 화면에 보인 줄(사용자·Agent 메시지, 도구 활동 요약, 승인 결과,
  오류)이고 화면에 이미 가려 보인 값은 가린 채로 온다
- 쓰기 직전 전체 글에서 워크스페이스 비밀값(`agent.log`와 같은 가림 대상)을 `***`로 바꾼 뒤
  길이를 자른다. 비밀값을 확인하지 못하면(`None`) 쓰지 않는다 (`secret_unchecked`)
- 제목은 첫 사용자 메시지 앞부분(가린 뒤), 없으면 "(제목 없음)"
- 보관 상한 `MAX_KEPT`개. 넘으면 고친 시각이 오래된 것부터 지운다
- 쓰기·읽기·지우기는 `filetx.plain` 경로 경계(링크·정션·워크스페이스 밖이면 거부)를 지난다
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from kookabug_core import filetx
from kookabug_core.documents import write_atomic

__all__ = [
    "CONV_DIR",
    "FORMAT",
    "MASK",
    "MAX_KEPT",
    "ConversationError",
    "delete",
    "get",
    "list_summaries",
    "redact",
    "save",
]

FORMAT: Final = "kookabug.conversation/0"
CONV_DIR: Final = ".kookabug/conversations"
MAX_KEPT: Final = 50
MAX_ITEMS: Final = 1000
"""대화 하나에 남기는 줄 수 (넘으면 앞쪽을 버린다)."""
MAX_TEXT: Final = 20000
"""줄 하나의 글 상한 (넘으면 자른다)."""
TITLE_MAX: Final = 40
MASK: Final = "***"
ID: Final = re.compile(r"c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4,8}")


class ConversationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _rel(conv_id: str) -> str:
    if not ID.fullmatch(conv_id):
        raise ConversationError("bad_id", "대화 ID 형식이 틀렸다")
    return f"{CONV_DIR}/{conv_id}.json"


def redact(value: Any, secrets: Iterable[str]) -> Any:
    """글 값 안의 비밀값을 `***`로 (긴 값부터 — 한 값이 다른 값을 품어도 남지 않게)."""
    ordered = sorted({s for s in secrets if s}, key=len, reverse=True)

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            for s in ordered:
                if s in v:
                    v = v.replace(s, MASK)
            return v
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    return walk(value)


def _clip_text(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"


def _clip(item: Mapping[str, Any]) -> dict[str, Any]:
    """줄 안의 모든 글 값을 상한으로 자른다 (이미 가린 줄에만 부른다)."""

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return _clip_text(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    return {k: walk(v) for k, v in item.items()}


def _title(items: list[dict[str, Any]]) -> str:
    for item in items:
        if item.get("kind") != "user":
            continue
        text = " ".join(str(item.get("text") or " ".join(item.get("chips") or [])).split())
        if text:
            return text if len(text) <= TITLE_MAX else text[:TITLE_MAX] + "…"
    return "(제목 없음)"


def _read(root: Path, rel: str) -> dict[str, Any] | None:
    raw = filetx.read(root, rel)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    return data


def summary(data: Mapping[str, Any]) -> dict[str, Any]:
    items = data.get("items")
    return {
        "id": data["id"],
        "title": str(data.get("title", "")),
        "agent_id": str(data.get("agent_id", "")),
        "agent_name": str(data.get("agent_name", "")),
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
        "count": len(items) if isinstance(items, list) else 0,
    }


def _all(root: Path) -> list[dict[str, Any]]:
    folder = filetx.plain(root, CONV_DIR)
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in folder.glob("*.json"):
        if not ID.fullmatch(path.stem):
            continue
        data = _read(root, f"{CONV_DIR}/{path.name}")
        if data is not None and data.get("id") == path.stem:
            out.append(data)
    out.sort(key=lambda d: str(d.get("updated_at", "")), reverse=True)
    return out


def list_summaries(root: Path) -> list[dict[str, Any]]:
    """최근 고친 것부터."""
    return [summary(d) for d in _all(root)]


def get(root: Path, conv_id: str) -> dict[str, Any]:
    data = _read(root, _rel(conv_id))
    if data is None or data.get("id") != conv_id:
        raise ConversationError("not_found", "그 대화가 없다")
    return data


def save(
    root: Path,
    conv: Mapping[str, Any],
    secrets: Iterable[str] | None,
    *,
    now: str | None = None,
    keep: int = MAX_KEPT,
) -> dict[str, Any]:
    """대화를 가려 쓴다. 같은 ID가 있으면 만든 시각을 이어 받는다. 상한을 넘으면 오래된 것을
    지운다. 쓴 대화의 요약을 돌려준다."""
    if secrets is None:
        raise ConversationError("secret_unchecked", "비밀값을 확인하지 못해 대화를 저장하지 않았다")
    conv_id = str(conv.get("id", ""))
    rel = _rel(conv_id)
    values = list(secrets)
    raw_items = conv.get("items")
    kept = (
        [dict(i) for i in raw_items if isinstance(i, Mapping)]
        if isinstance(raw_items, list)
        else []
    )
    # 가림이 먼저다: 길이를 자른 뒤 가리면 경계에 걸친 비밀값의 앞부분이 남는다 (UX4 검수 1 H1).
    # 전체 글에서 가린 뒤 자르고, 제목은 자른(가린) 줄에서 만든다
    items = [_clip(i) for i in redact(kept[-MAX_ITEMS:], values)]
    stamp = now or _now()
    before = _read(root, rel)
    acp = conv.get("acp_session")
    data: dict[str, Any] = {
        "format": FORMAT,
        "id": conv_id,
        "title": _title(items),
        "agent_id": str(conv.get("agent_id", "")),
        "agent_name": _clip_text(redact(str(conv.get("agent_name", "")), values)),
        "acp_session": acp if isinstance(acp, str) and acp else None,
        "created_at": str(before.get("created_at", stamp)) if before is not None else stamp,
        "updated_at": stamp,
        "items": items,
    }
    filetx.plain(root, ".kookabug").mkdir(exist_ok=True)
    filetx.plain(root, CONV_DIR).mkdir(exist_ok=True)
    path = filetx.plain(root, rel)
    body = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")

    def inside() -> None:
        # 교체 시도마다 경계를 다시 본다 (`.kookabug`가 정션으로 바뀌면 밖에 쓰지 않는다)
        filetx.plain(root, rel)

    write_atomic(path, body, before_replace=inside)
    for old in _all(root)[keep:]:
        # 지우지 못하면 다음 저장 때 다시 지운다
        with contextlib.suppress(OSError):
            filetx.plain(root, _rel(str(old["id"]))).unlink(missing_ok=True)
    return summary(data)


def delete(root: Path, conv_id: str) -> bool:
    path = filetx.plain(root, _rel(conv_id))
    if not path.is_file():
        return False
    path.unlink()
    return True

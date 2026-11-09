"""사람 전용 지식·정책 쓰기 (M8 계획 3.2·3.4·3.13, B4): 미지수 답, `kookabug.json` 블록.

daemon은 이 함수들을 사람 전용 메서드(`unknowns.answer`·`project.automation.set`·
`project.sources.set`, `ui_only` + `AGENT_DENIED`)에서만 부른다. Agent 연결의 경로는 없다.

- `answer_unknown`: 미지수 항목에 `answer{text, by: human, at}`·`state: answered`, rev+1(옛 rev는
  `history`). 지금 rev가 `base_rev`와 다르면 `revision_conflict`. 감사 이력에 남는다
- `set_config_block`: `kookabug.json`의 키 하나만 바꾼다(형식 검사, 지금 sha가 `base_sha256`와
  다르면 `revision_conflict`). 지식 잠금 + `filetx` 한 거래
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import store
from kookabug_core.knowledge.formats import Actor, KnowledgeError, SecretCheck, now, shape_problem
from kookabug_core.knowledge.ops import log_into
from kookabug_core.workspace import WORKSPACE_FILE

__all__ = ["CONFIG_BLOCKS", "answer_unknown", "set_config_block"]

UNKNOWNS: Final = "knowledge/unknowns.json"
CONFIG_BLOCKS: Final = frozenset({"automation", "sources"})
"""`set_config_block`가 바꾸는 `kookabug.json` 키 (치트 블록은 `cheats.set_policy`)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def answer_unknown(
    root: Path,
    unknown_id: str,
    base_rev: int,
    text: str,
    *,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    if actor.is_agent:
        raise KnowledgeError("answer_reserved", "미지수 답은 사람만 단다")
    check_secrets([("text", text), *actor.texts()])
    try:
        with filetx.locked(root):
            loaded = store.load(root, UNKNOWNS, "unknowns")
            doc = copy.deepcopy(loaded.doc)
            items = cast(list[dict[str, Any]], doc.get("unknowns") or [])
            pos = next((i for i, u in enumerate(items) if u.get("id") == unknown_id), None)
            if pos is None:
                raise KnowledgeError("unknown_id", "없는 미지수다", id=unknown_id)
            current = items[pos]
            if int(current["rev"]) != int(base_rev):
                raise KnowledgeError("revision_conflict", "미지수가 그사이 바뀌었다")
            doc.setdefault("history", []).append(copy.deepcopy(current))
            new = {
                **current,
                "rev": int(current["rev"]) + 1,
                "state": "answered",
                "answer": {"text": text, "by": "human", "at": now()},
            }
            items[pos] = new
            doc["revision"] = int(doc.get("revision", 0)) + 1
            problem = shape_problem(doc, "unknowns")
            if problem is not None:
                raise KnowledgeError("format", f"미지수 형식이 틀렸다 ({problem})")
            tx = filetx.Tx(root)
            tx.write(UNKNOWNS, store.encode(doc), expect_sha=loaded.sha)
            log_into(
                root,
                tx,
                [
                    {
                        "op": "unknown_answer",
                        "file": UNKNOWNS,
                        "id": unknown_id,
                        "base_rev": int(base_rev),
                        "new_rev": new["rev"],
                        "fields": ["answer", "state"],
                        "result": "applied",
                    }
                ],
                actor,
            )
            tx.commit()
            return {"id": unknown_id, "rev": new["rev"]}
    except filetx.TxError as exc:
        raise KnowledgeError(exc.code, exc.message) from exc


def set_config_block(root: Path, key: str, value: Any, *, base_sha256: str) -> str:
    """`kookabug.json`의 `key` 블록만 바꾼다. 새 sha."""
    if key not in CONFIG_BLOCKS:
        raise KnowledgeError("format", f"바꿀 수 없는 설정 블록이다: {key}")
    try:
        with filetx.locked(root):
            data = (root / WORKSPACE_FILE).read_bytes()
            if _sha(data) != base_sha256:
                raise KnowledgeError("revision_conflict", "kookabug.json이 그사이 바뀌었다")
            config = json.loads(data.decode("utf-8"))
            config[key] = value
            problem = shape_problem(config, "workspace")
            if problem is not None:
                raise KnowledgeError("format", f"{key} 형식이 틀렸다 ({problem})")
            body = canonical_dumps(config).encode("utf-8")
            tx = filetx.Tx(root)
            tx.write(WORKSPACE_FILE, body, expect_sha=base_sha256)
            tx.commit()
            return _sha(body)
    except filetx.TxError as exc:
        raise KnowledgeError(exc.code, exc.message) from exc

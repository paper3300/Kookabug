"""`setting.propose` (UX2 C)와 수락 적용 — 엄격: Agent 권한·비밀값.

- `setting.propose`(`kb_setting_propose`)는 작업 토큰 연결 전용(`job_only`). 코어
  `knowledge.setting_change.propose`가 허용 목록·모양·글자 검사를 하고 작업 폴더에 제안만 남긴다.
  설정은 바꾸지 않는다
- `apply_setting`은 사람 전용 `report.decide`(설정 제안 묶음 수락)만 부른다. 그 키의 지금 값이
  제안 때 값과 다르면 `revision_conflict`(적용 안 함). 쓰기는 마법사 그 단계 저장과 같은
  함수·같은 sha/revision 대조다: 게임 제목 = 2단계 `project.setup.set`(`human.set_setup`),
  실행 파일·인자·작업 폴더 = 2단계 `local.settings.set`, 원본 추가 = 6단계 `project.sources.set`
  + `local.settings.set`, 금지 동작 = 7단계 `project.automation.set`, 치트 분류 = 7단계
  `cheats.categories.set`
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.knowledge import cheats, human, setting_change
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.adopt import checker_of
from kookabug_daemon.methods.knowledge import run_guarded
from kookabug_daemon.permission_files import revision_of
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS", "apply_setting"]

_SCALAR: Final = frozenset({"game.title", "game.executable", "game.args", "game.cwd"})


def _propose_sync(call: Call) -> dict[str, Any]:
    job = call.principal.job
    if job is None:
        raise RequestFailed("job_only", "설정 제안은 작업 토큰 연결만 한다")
    p = call.params
    proposal = setting_change.propose(
        call.daemon.root,
        job,
        str(p["key"]),
        p["value"],
        str(p["reason"]),
        [str(u) for u in p.get("unknowns") or []],
        check_secrets=checker_of(call),
    )
    return {"id": proposal["id"], "job": job, "key": proposal["key"]}


async def _propose(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _propose_sync, call)


def _config(root: Any) -> tuple[dict[str, Any], str]:
    data = (root / WORKSPACE_FILE).read_bytes()
    return cast(dict[str, Any], json.loads(data.decode("utf-8-sig"))), hashlib.sha256(
        data
    ).hexdigest()


def _local_revision(root: Any) -> str | None:
    return revision_of(filetx.read(root, LOCAL_FILE))


def _conflict(message: str) -> KnowledgeError:
    return KnowledgeError("revision_conflict", message)


def _same_location(
    source: Mapping[str, Any], entry: Mapping[str, Any], local: str | None, daemon: Any
) -> bool:
    if entry.get("url") is not None:
        return source.get("url") == entry["url"]
    if local is not None:
        if not source.get("local"):
            return False
        raw = filetx.read(daemon.root, LOCAL_FILE)
        doc = json.loads(raw.decode("utf-8-sig")) if raw else {}
        got = ((doc.get("sources") or {}).get(source.get("id")) or {}).get("path")
        return isinstance(got, str) and got.casefold() == local.casefold()
    return str(source.get("path", "")).casefold() == str(entry.get("path", "")).casefold()


def apply_setting(daemon: Any, job: str, setting: Mapping[str, Any]) -> dict[str, Any]:
    """설정 제안 하나를 적용한다 (사람 연결의 `report.decide` 수락에서만). 값과 현재 값 해시는 팀
    보고가 아니라 이 PC 작업 폴더의 `proposals.json`에서 읽는다(검수 1 H1) — 없으면(다른 PC에서
    만든 보고) 적용하지 않는다. 적용한 키·저장 위치."""
    root = daemon.root
    proposal = setting_change.find_proposal(root, job, str(setting.get("id")))
    if proposal is None or proposal.get("key") != setting.get("key"):
        raise KnowledgeError(
            "unknown_id", "이 PC에서 만든 제안이 아니라 적용할 수 없다", id=str(setting.get("id"))
        )
    key = str(proposal.get("key"))
    value = setting_change.validate(key, proposal.get("value"))
    now_value = setting_change.current_value(root, key)
    if key in _SCALAR:
        if setting_change.value_hash(now_value) != proposal.get("current_hash"):
            raise _conflict("제안 뒤에 그 설정이 바뀌어 적용하지 않았다")
        if key in setting_change.LOCAL_KEYS:
            revision = _local_revision(root)
            daemon.permission_files.set_local_settings(
                {key: value}, base_revision=revision, check_revision=True
            )
            return {"key": key, "stored": "local"}
        _, sha = _config(root)
        human.set_setup(root, {}, {key: value}, base_sha256=sha)
        return {"key": key, "stored": "team"}
    config, sha = _config(root)
    if key == "sources.add":
        existing = [
            cast(dict[str, Any], s) for s in config.get("sources") or [] if isinstance(s, dict)
        ]
        entry, local = setting_change.source_entry(value, existing)
        if any(_same_location(s, entry, local, daemon) for s in existing):
            raise KnowledgeError("exists", "같은 위치의 원본이 이미 있다")
        revision = _local_revision(root) if local is not None else None
        human.set_config_block(root, "sources", [*existing, entry], base_sha256=sha)
        if local is not None:
            daemon.permission_files.set_local_settings(
                {}, {str(entry["id"]): local}, base_revision=revision, check_revision=True
            )
        return {"key": key, "stored": "team+local" if local else "team", "id": entry["id"]}
    if key == "cheats.categories.add":
        raw = cast(dict[str, Any], config.get("cheats") or {})
        categories = [c for c in raw.get("categories") or [] if isinstance(c, dict)]
        if any(c.get("id") == value["id"] for c in categories):
            raise KnowledgeError("exists", "이미 있는 치트 분류다")
        cheats.set_policy(
            root,
            enabled=bool(raw.get("enabled", False)),
            categories=[*categories, value],
            base_sha256=sha,
        )
        return {"key": key, "stored": "team"}
    # automation.forbidden.add
    block = dict(cast(dict[str, Any], config.get("automation") or {}))
    forbidden = list(block.get("forbidden") or [])
    if value in forbidden:
        raise KnowledgeError("exists", "이미 있는 금지 동작이다")
    block["forbidden"] = [*forbidden, value]
    human.set_config_block(root, "automation", block, base_sha256=sha)
    return {"key": key, "stored": "team"}


METHODS: Final[dict[str, MethodSpec]] = {
    "setting.propose": MethodSpec(_propose),
}

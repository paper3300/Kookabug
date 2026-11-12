"""첫 프로젝트 설정 마법사 메서드 (M8 계획 3.17, B7). 모두 사람 전용(`ui_only` + `AGENT_DENIED`).

- `wizard.get`: `.kookabug/wizard.json`(`kookabug.wizard/0`, 이 PC) + 단계 판정에 쓰는 지금 설정
  (`kookabug.json` sha·실효 게임 설정·기록 정책). `team_setup` = 팀이 첫 설정을 마친 프로젝트
  (`wiki/index.md` 있음, `kookabug workspace new`가 만든다) — 짧은 마법사 자동 띄우기 조건
- `wizard.set`: 진행을 원자 쓰기. 단계 상태만 받는다(입력 값·비밀값·경로 없음 — 스키마가 막는다)
- `project.setup.set`: 2·8단계 팀 설정(`record`·`retention`·`game.title`·`game.client_size`),
  `kookabug.json` sha 대조 + 지식 잠금 + `filetx`
- `local.settings.set`: 2단계 이 PC 게임 실행 설정(`game.executable`·`game.cwd`·`game.args`)과
  6단계 읽기 허용 폴더(`agent.read_roots`, UX3 — 허용하지 않는 폴더는 `policy_path`) →
  `.kookabug/local.json`(권한 파일과 같은 잠금·쓰기 규칙)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.documents import write_atomic
from kookabug_core.knowledge import human, read_roots
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.schema import check_shape
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE, Workspace
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.knowledge import run_guarded
from kookabug_daemon.permission_files import revision_of
from kookabug_daemon.protocol import InvalidParams, RequestFailed

__all__ = ["METHODS", "WIZARD_FILE", "WIZARD_FORMAT"]

WIZARD_FORMAT: Final = "kookabug.wizard/0"
WIZARD_DIR: Final = ".kookabug"
WIZARD_FILE: Final = ".kookabug/wizard.json"
GAME_KEYS: Final = ("title", "executable", "cwd", "args", "client_size")
SOURCE_ID: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _guarded(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """`run_guarded` + 이 PC 파일 경로 경계는 `local.settings.set`(권한 파일)과 같은
    `path_outside_workspace`로 (지식 메서드는 `policy_path`로 바꾼다)."""

    def inner() -> Any:
        try:
            return fn(*args, **kwargs)
        except filetx.TxError as exc:
            if exc.code != "path_outside_workspace":
                raise
            path = str(exc.fields.get("path", ""))
            raise RequestFailed(exc.code, exc.message, path=path) from exc

    return run_guarded(inner)


def _parse_json(raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError, ValueError:
        return None
    return value if isinstance(value, dict) else None


def _wizard_state(root: Path) -> dict[str, Any] | None:
    """읽지 못하거나 형식이 다르면 없음으로 본다 (처음부터 다시 — 단계 상태뿐이라 잃는 것이
    적다). JSON 문법뿐 아니라 `Kb8WizardState` 구조 전체를 본다 (B7 검수 M7)."""
    data = _parse_json(filetx.read(root, WIZARD_FILE))
    if data is None or check_shape(data, "daemon-rpc", ref="#/$defs/Kb8WizardState"):
        return None
    try:
        return _normalize(data)
    except InvalidParams, KeyError, TypeError, ValueError:
        return None


def _steps(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 9 for v in value
    ):
        raise InvalidParams(f"wizard.{name}는 0~9 단계 번호 목록이다")
    return sorted(set(value))


def _normalize(state: dict[str, Any]) -> dict[str, Any]:
    """정해진 키만 담은 사본 (중복 단계는 하나로, 정렬)."""
    step = state.get("step")
    if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step <= 9:
        raise InvalidParams("wizard.step은 0~9다")
    done = _steps(state.get("done"), "done")
    skipped = [s for s in _steps(state.get("skipped"), "skipped") if s not in done]
    warnings: list[dict[str, Any]] = []
    for w in state.get("warnings") or []:
        if not isinstance(w, dict) or not isinstance(w.get("code"), str):
            raise InvalidParams("wizard.warnings 항목은 {step, code}다")
        item = {"step": int(w["step"]), "code": str(w["code"])}
        if item not in warnings:
            warnings.append(item)
    return {
        "format": WIZARD_FORMAT,
        "step": step,
        "done": done,
        "skipped": skipped,
        "warnings": warnings[:50],
    }


def _local_sources(local: dict[str, Any]) -> dict[str, str]:
    """`local.json` sources의 경로만 (6단계가 칸을 채운다 — 비밀값은 이 블록에 없다)."""
    out: dict[str, str] = {}
    for source_id, entry in dict(local.get("sources") or {}).items():
        path = entry.get("path") if isinstance(entry, dict) else None
        if isinstance(source_id, str) and isinstance(path, str) and path:
            out[source_id] = path
    return out


def _get_sync(call: Call) -> dict[str, Any]:
    root = call.daemon.root
    raw = (root / WORKSPACE_FILE).read_bytes()
    config = json.loads(raw.decode("utf-8-sig"))
    # 이 PC 파일은 쓰기와 같은 경로 경계로 읽는다 (`.kookabug` 정션 밖을 읽지 않는다)
    local_raw = filetx.read(root, LOCAL_FILE)
    local = _parse_json(local_raw) or {}
    merged = {**dict(config.get("settings") or {}), **dict(local.get("settings") or {})}
    game = {key: merged.get(f"game.{key}") for key in GAME_KEYS}
    sources = config.get("sources")
    return {
        "wizard": _wizard_state(root),
        "team_setup": (root / "wiki" / "index.md").is_file(),
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "game": game,
        "record": dict(config.get("record") or {}),
        "retention": dict(config.get("retention") or {}),
        "sources": [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else [],
        "local_sources": _local_sources(local),
        "local_revision": revision_of(local_raw),
        "read_roots": _read_roots_view(root),
    }


def _read_roots_view(root: Path) -> dict[str, Any]:
    """6단계 "Agent가 읽어도 되는 폴더" 묶음 (UX3): 이 PC 목록 + 자동 포함 줄(계산 값)."""
    workspace = Workspace.open(root)
    auto = [
        {
            "id": r["id"],
            "path": r["path"],
            "title": r["title"],
            "state": r["state"],
            "reason": r["reason"],
            "message": None if r["reason"] is None else read_roots.REASONS[r["reason"]],
        }
        for r in read_roots.read_roots(workspace)
        if r["auto"]
    ]
    return {"paths": read_roots.configured(workspace), "auto": auto}


async def _get(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_guarded, _get_sync, call)


def _set_sync(call: Call) -> dict[str, Any]:
    state = _normalize(dict(call.params["wizard"]))
    root = call.daemon.root
    # 쓰기 직전 경로 경계 (B1 filetx.plain): `.kookabug`·`wizard.json`이 링크·정션이거나 실경로가
    # 워크스페이스 밖이면 path_outside_workspace (B7 검수 H2). 폴더를 만든 뒤 다시 본다
    filetx.plain(root, WIZARD_FILE)
    filetx.plain(root, WIZARD_DIR).mkdir(exist_ok=True)
    path = filetx.plain(root, WIZARD_FILE)

    def inside() -> None:
        # 교체 시도마다 경계를 다시 본다: 공유 위반 재시도 사이 `.kookabug`가 정션으로 바뀌면
        # 밖에 쓰지 않고 path_outside_workspace (임시 파일은 write_atomic이 지운다, B7 검수 H1)
        filetx.plain(root, WIZARD_FILE)

    body = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_atomic(path, body, before_replace=inside)
    return {"wizard": state}


async def _set(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_guarded, _set_sync, call)


async def _setup(call: Call) -> dict[str, Any]:
    p = call.params
    blocks = {k: p[k] for k in human.SETUP_BLOCKS if k in p}
    settings = dict(p.get("settings") or {})
    if not blocks and not settings:
        raise InvalidParams("바꿀 설정이 없다")
    sha = await asyncio.to_thread(
        run_guarded,
        human.set_setup,
        call.daemon.root,
        blocks,
        settings,
        base_sha256=str(p["base_sha256"]),
    )
    return {"sha256": sha}


def _read_roots(root: Path, value: list[Any]) -> list[str]:
    """6단계 읽기 허용 폴더 저장 검사 (UX3): 허용하지 않는 폴더면 `policy_path`
    (`reason`·`index`)."""
    workspace = Workspace.open(root)
    try:
        return read_roots.normalize(workspace, value)
    except KnowledgeError as exc:
        code = exc.code if exc.code == "policy_path" else "invalid_params"
        if code == "invalid_params":
            raise InvalidParams(exc.message) from exc
        raise RequestFailed(code, exc.message, **exc.fields) from exc


async def _local(call: Call) -> dict[str, Any]:
    updates = dict(call.params.get("settings") or {})
    sources = dict(call.params.get("sources") or {})
    if not updates and not sources:
        raise InvalidParams("바꿀 설정이 없다")
    for source_id in sources:
        if not SOURCE_ID.fullmatch(source_id):
            raise InvalidParams(f"원본 ID 형식이 틀렸다: {source_id}")
    roots = updates.get(read_roots.KEY)
    if isinstance(roots, list):
        clean = await asyncio.to_thread(_read_roots, call.daemon.root, cast(list[Any], roots))
        # 빈 목록은 키를 지운다 (자동 포함 폴더만 남는다)
        updates[read_roots.KEY] = clean or None
    # base_revision을 주면 화면을 채울 때 읽은 revision과 대조한다 (안 주면 키만 바꾸는 예전 동작)
    check = "base_revision" in call.params
    revision = await asyncio.to_thread(
        call.daemon.permission_files.set_local_settings,
        updates,
        sources,
        base_revision=call.params.get("base_revision"),
        check_revision=check,
    )
    return {"revision": revision}


METHODS: Final[dict[str, MethodSpec]] = {
    "wizard.get": MethodSpec(_get),
    "wizard.set": MethodSpec(_set),
    "project.setup.set": MethodSpec(_setup),
    "local.settings.set": MethodSpec(_local),
}

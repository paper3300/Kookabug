"""`plugins.*` (M6 계획 3.8): 플러그인 목록·설치·제거·준비·다시 잠그기·정리.

- `plugins.list`는 `kb_project_info`로 판정한다 (사람·에이전트 조회). 읽기만 한다
- 나머지(변경·미리보기·취소)는 모두 `ui_only` + `AGENT_DENIED` — agent 연결은 판정 전에
  `permission_denied` (`tools.Authorizer.gate`). 공개 MCP 도구는 없다
- 작업은 `plugin_jobs.PluginJobs` (한 번에 하나·취소·진행 알림·미리보기 5분). 확인은 화면이 받는다:
  미리보기 → `plugins.install`, sync·relock은 사람이 본 정규 잠금 해시(`lock_sha256`), remove는 본
  잠금의 revision(`base_revision`)일 때만 진행하고, gc는 카드에서 본 후보(`candidates`)만 지운다
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from kookabug_core.plugins import Layout, PluginError, PluginOps, Preview
from kookabug_core.plugins import gc as gc_mod
from kookabug_core.plugins.redact import mask_value
from kookabug_core.plugins.runtime import installed_schemas
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.plugin_jobs import plugin_failed

if TYPE_CHECKING:
    from kookabug_daemon.plugin_jobs import PluginJobs

__all__ = ["METHODS", "plugins_list"]


def _jobs(call: Call) -> PluginJobs:
    return call.daemon.plugin_jobs


def _yes(_: Any) -> bool:
    return True  # 확인은 화면이 이미 받았다 (sync: lock_sha256, remove: base_revision)


def _widgets(node: dict[str, Any]) -> dict[str, str]:
    """config 이름 → 위젯 ID (노드 스키마 `config.<이름>.ui.widget`)."""
    out: dict[str, str] = {}
    for name, decl in (node.get("config") or {}).items():
        widget = (decl.get("ui") or {}).get("widget") if isinstance(decl, dict) else None
        if isinstance(widget, str):
            out[str(name)] = widget
    return out


def _nodes(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    if schema is None:
        return []
    out: list[dict[str, Any]] = []
    for node in schema.get("nodes", []):
        item: dict[str, Any] = {"type": node["type"], "effects": list(node.get("effects", []))}
        if "title" in node:
            item["title"] = node["title"]
        if widgets := _widgets(node):
            item["ui"] = widgets
        out.append(item)
    return out


def _widget_host(
    entry: dict[str, Any], env: dict[str, Any] | None, nodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """위젯 호스트 (M6 3.10): 머리에 `ui`가 있고 그 환경이 준비된 플러그인만. 경로는 워크스페이스
    기준 — 앱 주 프로세스가 `kbplugin://<host>/`를 이 폴더 아래 파일로만 푼다."""
    manifest = entry.get("manifest") or {}
    ui, modules = manifest.get("ui"), manifest.get("modules") or []
    if not ui or not modules or env is None or env.get("status") != "ready":
        return None
    folder, fingerprint = env.get("folder"), env.get("fingerprint")
    if not isinstance(folder, str) or not isinstance(fingerprint, str):
        return None
    package = str(modules[0]).split(".", 1)[0]
    widgets = sorted({w for n in nodes for w in (n.get("ui") or {}).values()})
    # CSP 호스트 문법에는 '_'가 없다 → '-'로 (ID에는 '-'가 없어 겹치지 않는다)
    host = str(entry["id"]).replace("_", "-")
    return {
        "host": f"{host}-{fingerprint[:12]}",
        "path": f".kookabug/plugins/envs/{folder}/Lib/site-packages/{package}/{ui}",
        "widgets": widgets,
    }


def plugins_list(jobs: PluginJobs, connection: int | None = None) -> dict[str, Any]:
    """`plugins.list` 결과 (읽기만: 잠금 파일·환경·깨짐 기록을 쓰지 않는다). `connection`: 부른
    연결 (승인 대기 미리보기의 op_id는 연 연결에만)."""
    ops = jobs.reader()
    try:
        status = ops.status()
    except PluginError as exc:
        raise plugin_failed(exc.to_json()) from exc
    schemas = installed_schemas(ops.root) if status["plugins"] else {}
    plugins: list[dict[str, Any]] = []
    for p in status["plugins"]:
        item = {**p, "nodes": _nodes(schemas.get(str(p["id"])))}
        host = _widget_host(item, status["environments"].get(p["env"]), item["nodes"])
        if host is not None:
            item["ui"] = host
        plugins.append(item)
    return mask_value(
        {
            **status,
            "plugins": plugins,
            "gc_candidates": gc_mod.candidates(Layout(ops.root)),
            "busy": jobs.current(connection),
        }
    )


async def _list(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(plugins_list, _jobs(call), call.connection)


def _isolation(call: Call) -> str | None:
    value = call.params.get("isolation")
    return None if value is None else str(value)


def _opt(call: Call, key: str) -> str | None:
    value = call.params.get(key)
    return None if value is None else str(value)


async def _preview(call: Call) -> dict[str, Any]:
    source = str(call.params["source"])
    isolation, ref, sha = _isolation(call), _opt(call, "ref"), _opt(call, "sha256")

    def body(ops: PluginOps, confirm: Any) -> dict[str, Any]:
        def ask(preview: Preview) -> bool:
            return bool(confirm(preview))

        return ops.add(source, isolation=isolation, ref=ref, sha256=sha, confirm=ask)

    return await asyncio.to_thread(_jobs(call).preview, "install", body, owner=call.connection)


async def _upgrade(call: Call) -> dict[str, Any]:
    plugin_id = str(call.params["id"])
    isolation, ref, sha = _isolation(call), _opt(call, "ref"), _opt(call, "sha256")

    def body(ops: PluginOps, confirm: Any) -> dict[str, Any]:
        def ask(preview: Preview) -> bool:
            return bool(confirm(preview))

        return ops.upgrade(plugin_id, ref=ref, sha256=sha, isolation=isolation, confirm=ask)

    return await asyncio.to_thread(_jobs(call).preview, "upgrade", body, owner=call.connection)


async def _install(call: Call) -> dict[str, Any]:
    return _jobs(call).install(str(call.params["op_id"]), call.connection)


async def _remove(call: Call) -> dict[str, Any]:
    plugin_id = str(call.params["id"])
    base = call.params["base_revision"]
    # null = "확인할 때 잠금이 없었다"는 명시값 (비교 생략이 아니다): 거래 안에서 읽은 revision과
    # null까지 비교한다
    base_revision = None if base is None else str(base)

    def body(ops: PluginOps) -> dict[str, Any]:
        return ops.remove(plugin_id, confirm=_yes, base_revision=base_revision)

    return await asyncio.to_thread(_jobs(call).start, "remove", body)


async def _sync(call: Call) -> dict[str, Any]:
    expected = str(call.params["lock_sha256"])
    return await asyncio.to_thread(
        _jobs(call).start, "sync", lambda ops: ops.sync(confirm=_yes, lock_sha256=expected)
    )


async def _relock(call: Call) -> dict[str, Any]:
    # 확인 카드가 본 잠금(정규 해시)일 때만: 카드에 없던 플러그인을 확인 실행하지 않는다 (B5 검수 H)
    expected = str(call.params["lock_sha256"])
    return await asyncio.to_thread(
        _jobs(call).start, "relock", lambda ops: ops.relock(confirm=_yes, lock_sha256=expected)
    )


async def _gc(call: Call) -> dict[str, Any]:
    # 확인 카드가 본 후보만 지운다 (그 사이 생긴 후보는 확인받지 않았다)
    raw = call.params["candidates"]
    only = {k: [str(n) for n in raw.get(k, [])] for k in ("envs", "wheels", "staging")}
    return await asyncio.to_thread(
        _jobs(call).start, "gc", lambda ops: ops.gc(confirm=_yes, only=only)
    )


async def _cancel(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_jobs(call).cancel, str(call.params["op_id"]), call.connection)


METHODS: Final = {
    "plugins.list": MethodSpec(_list),
    "plugins.preview": MethodSpec(_preview),
    "plugins.upgrade": MethodSpec(_upgrade),
    "plugins.install": MethodSpec(_install),
    "plugins.remove": MethodSpec(_remove),
    "plugins.sync": MethodSpec(_sync),
    "plugins.relock": MethodSpec(_relock),
    "plugins.gc": MethodSpec(_gc),
    "plugins.cancel": MethodSpec(_cancel),
}

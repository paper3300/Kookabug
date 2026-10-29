"""테스트 그래프·워크스페이스를 코드로 만든다.

ws = make_workspace(tmp_path)
g = GraphBuilder().entry("n_a").node("n_a", "core.test.pass")
diags = check(ws, g.write(ws, "tests/a.graph.json"))
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.loader import Program
from kookabug_core.registry import Registry
from kookabug_core.validate import check_graph
from kookabug_core.workspace import (
    LOCAL_FILE,
    WORKSPACE_FILE,
    MemorySecrets,
    RunOptions,
    SecretProvider,
    Workspace,
)

CORE_VERSION = "0.1.0"


def link(ref: str) -> dict[str, Any]:
    return {"$link": ref}


def target(path: str) -> dict[str, Any]:
    return {"$target": path}


def setting(key: str) -> dict[str, Any]:
    return {"$setting": key}


def secret(key: str) -> dict[str, Any]:
    return {"$secret": key}


def literal(value: Any) -> dict[str, Any]:
    return {"$literal": value}


class GraphBuilder:
    """그래프 dict를 만든다. 메서드는 자기 자신을 돌려준다 (이어 쓰기)."""

    def __init__(
        self,
        kind: str = "test",
        *,
        interface: Mapping[str, Any] | None = None,
        plugins: Mapping[str, str] | None = None,
    ) -> None:
        self.kind = kind
        self.interface = copy.deepcopy(dict(interface)) if interface is not None else None
        self.plugins = {"core": CORE_VERSION, **(plugins or {})}
        self.nodes: dict[str, dict[str, Any]] = {}

    def node(
        self,
        node_id: str,
        node_type: str,
        *,
        version: int = 1,
        inputs: Mapping[str, Any] | None = None,
        config: Mapping[str, Any] | None = None,
        next: Mapping[str, str] | None = None,
        title: str | None = None,
    ) -> GraphBuilder:
        node: dict[str, Any] = {"type": node_type, "version": version}
        if inputs is not None:
            node["in"] = copy.deepcopy(dict(inputs))
        if config is not None:
            node["config"] = copy.deepcopy(dict(config))
        if next is not None:
            node["next"] = dict(next)
        if title is not None:
            node["title"] = title
        self.nodes[node_id] = node
        return self

    def entry(self, start: str | None = None, node_id: str = "n_entry") -> GraphBuilder:
        return self.node(node_id, "core.graph.entry", next={"start": start} if start else None)

    def exit(
        self, node_id: str, exit: str, inputs: Mapping[str, Any] | None = None
    ) -> GraphBuilder:
        return self.node(node_id, "core.graph.exit", config={"exit": exit}, inputs=inputs)

    def call(
        self,
        node_id: str,
        graph: str,
        *,
        inputs: Mapping[str, Any] | None = None,
        next: Mapping[str, str] | None = None,
    ) -> GraphBuilder:
        return self.node(
            node_id, "core.graph.call", config={"graph": graph}, inputs=inputs, next=next
        )

    def build(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": "kookabug.graph/0",
            "kind": self.kind,
            "nodes": copy.deepcopy(self.nodes),
            "plugins": dict(self.plugins),
        }
        if self.interface is not None:
            data["interface"] = copy.deepcopy(self.interface)
        return data

    def write(self, ws: Workspace | Path, rel: str) -> str:
        write_json(ws, rel, self.build())
        return rel


def subgraph_interface(
    *,
    exits: Mapping[str, str] | None = None,
    inputs: Mapping[str, Any] | None = None,
    outputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`exits`는 이름 → kind. `inputs`·`outputs` 값이 문자열이면 타입만, dict면 그대로."""

    def pins(section: Mapping[str, Any]) -> dict[str, Any]:
        return {k: {"type": v} if isinstance(v, str) else dict(v) for k, v in section.items()}

    interface: dict[str, Any] = {
        "exits": {k: {"kind": v} for k, v in (exits or {"done": "ok"}).items()}
    }
    if inputs:
        interface["inputs"] = pins(inputs)
    if outputs:
        interface["outputs"] = pins(outputs)
    return interface


def _root(ws: Workspace | Path) -> Path:
    return ws.root if isinstance(ws, Workspace) else ws


def write_json(ws: Workspace | Path, rel: str, data: Any) -> Path:
    path = _root(ws).joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_target(
    ws: Workspace | Path,
    rel: str,
    *,
    image: str | None = None,
    create_image: bool = True,
    **extra: Any,
) -> str:
    """target 파일과 (기본) 그 옆 이미지 파일을 만든다."""
    name = rel.rsplit("/", 1)[-1].removesuffix(".target.json")
    image = image if image is not None else f"{name}.png"
    write_json(ws, rel, {"format": "kookabug.target/0", "image": image, **extra})
    if create_image:
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        image_rel = f"{folder}/{image}" if folder else image
        path = _root(ws).joinpath(*image_rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return rel


def make_workspace(
    root: Path,
    *,
    settings: Mapping[str, Any] | None = None,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
    local: Mapping[str, Any] | None = None,
) -> Workspace:
    """`kookabug.json`(그리고 `local`을 주면 `.kookabug/local.json`)을 쓰고 연다.

    `profiles`는 프로필 이름 → 그 프로필의 settings.
    """
    config: dict[str, Any] = {"format": "kookabug.workspace/0"}
    if settings is not None:
        config["settings"] = dict(settings)
    if profiles is not None:
        config["profiles"] = {k: {"settings": dict(v)} for k, v in profiles.items()}
    write_json(root, WORKSPACE_FILE, config)
    if local is not None:
        write_json(root, LOCAL_FILE, {"format": "kookabug.local/0", "settings": dict(local)})
    return Workspace.open(root)


def check(
    ws: Workspace,
    rel: str,
    *,
    registry: Registry | None = None,
    options: RunOptions | None = None,
    secrets: SecretProvider | Mapping[str, str] | None = None,
) -> list[Diagnostic]:
    return check_program(ws, rel, registry=registry, options=options, secrets=secrets)[1]


def check_program(
    ws: Workspace,
    rel: str,
    *,
    registry: Registry | None = None,
    options: RunOptions | None = None,
    secrets: SecretProvider | Mapping[str, str] | None = None,
) -> tuple[Program, list[Diagnostic]]:
    if secrets is None or isinstance(secrets, Mapping):
        secrets = MemorySecrets(secrets or {})
    return check_graph(ws, rel, registry=registry, options=options, secrets=secrets)


def codes(diags: Iterable[Diagnostic]) -> list[str]:
    return [d.code for d in diags]


def errors(diags: Iterable[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diags if d.severity == "error"]


def only(diags: Iterable[Diagnostic], code: str) -> list[Diagnostic]:
    return [d for d in diags if d.code == code]

"""`graph.patch` 연산 적용 (M5 계획 3.4). 순수 함수: 값 사본을 고쳐 돌려주고 파일은 건드리지 않는다.

- 한 묶음은 모두 적용하거나 하나도 안 한다: 틀린 연산이 하나라도 있으면 `PatchInvalid`(순번)
- 노드 ID는 바꾸지 않는다. 새 노드 ID는 에디터와 같은 규칙(`n_` + 소문자 base32 8자, 문서의 노드·
  접힌 그룹·주석 ID와 겹치지 않음)으로 daemon이 만든다
- `id`·`from`·`to`에는 같은 묶음의 `add_node` `ref`도 쓸 수 있다. 기존 노드 ID와 같은 `ref`는 거부
- 노드 지우기 정리 규칙은 에디터(`deleteNodes`)와 같다: 그 노드를 가리키는 `next` 출구, 그 노드를
  `$link`로 읽는 핀(핀 키 전체), `layout.nodes`·접힌 그룹 목록의 그 ID. 비게 된 `next`·`in`도 지운다
"""

from __future__ import annotations

import copy
import secrets
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from kookabug_core.registry import Registry

__all__ = ["ID_ALPHABET", "PatchInvalid", "PatchResult", "apply_ops", "new_node_id"]

ID_ALPHABET: Final = "abcdefghijklmnopqrstuvwxyz234567"
NEW_NODE_GAP: Final = 280
"""위치를 주지 않은 새 노드를 지금 노드들 오른쪽에 둘 간격 (에디터 기본 간격)."""


class PatchInvalid(Exception):
    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"연산 {index}: {message}")
        self.index = index
        self.message = f"연산 {index}: {message}"


@dataclass
class PatchResult:
    value: dict[str, Any]
    created: dict[str, str] = field(default_factory=dict[str, str])
    removed_refs: list[dict[str, str]] = field(default_factory=list[dict[str, str]])


def taken_ids(value: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    nodes = value.get("nodes")
    if isinstance(nodes, dict):
        out.update(nodes)
    layout = value.get("layout")
    if isinstance(layout, dict):
        for key in ("collapsed", "comments"):
            part = layout.get(key)
            if isinstance(part, dict):
                out.update(part)
    return out


def new_node_id(taken: set[str], random: Callable[[int], bytes] = secrets.token_bytes) -> str:
    for _ in range(1000):
        raw = random(8)
        node_id = "n_" + "".join(ID_ALPHABET[b & 31] for b in raw)
        if node_id not in taken:
            return node_id
    raise RuntimeError("겹치지 않는 노드 ID를 만들지 못했다")


def _links(value: Any) -> Iterator[str]:
    """값 안의 `$link` 대상 노드 ID (중첩 객체·배열까지)."""
    if isinstance(value, dict):
        link = value.get("$link")
        if isinstance(link, str) and len(value) == 1:
            yield link.split(".", 1)[0]
            return
        for item in value.values():
            yield from _links(item)
    elif isinstance(value, list):
        for item in value:
            yield from _links(item)


def _obj(parent: dict[str, Any], key: str) -> dict[str, Any]:
    """`parent[key]`가 객체면 그것, 없으면 새로 만든다 (객체가 아니면 바꾼다)."""
    found = parent.get(key)
    if not isinstance(found, dict):
        found = {}
        parent[key] = found
    return found


def _merge(target: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key, item in patch.items():
        if item is None:
            target.pop(key, None)
        else:
            target[key] = copy.deepcopy(item)


def _position(given: Mapping[str, Any]) -> dict[str, int]:
    return {"x": round(float(given["x"])) + 0, "y": round(float(given["y"])) + 0}


class _Patcher:
    def __init__(
        self, value: Mapping[str, Any], registry: Registry, random: Callable[[int], bytes]
    ) -> None:
        self.value: dict[str, Any] = copy.deepcopy(dict(value))
        self.registry = registry
        self.random = random
        self.created: dict[str, str] = {}
        self.removed: list[dict[str, str]] = []
        self.index = 0

    def fail(self, message: str) -> PatchInvalid:
        return PatchInvalid(self.index, message)

    @property
    def nodes(self) -> dict[str, Any]:
        return _obj(self.value, "nodes")

    def node_id(self, given: Any) -> str:
        """`ref` 또는 노드 ID → 있는 노드 ID."""
        name = str(given)
        node_id = self.created.get(name, name)
        if not isinstance(self.nodes.get(node_id), dict):
            raise self.fail(f"노드 {name!r}이(가) 없다")
        return node_id

    def node(self, given: Any) -> tuple[str, dict[str, Any]]:
        node_id = self.node_id(given)
        return node_id, self.nodes[node_id]

    # ---------------------------------------------------------------- 연산

    def add_node(self, op: Mapping[str, Any]) -> None:
        ref = str(op["ref"])
        if ref in self.created:
            raise self.fail(f"ref {ref!r}이(가) 이 묶음에 이미 있다")
        if ref in self.nodes:
            raise self.fail(f"ref {ref!r}이(가) 기존 노드 ID와 같다")
        node_type = str(op["type"])
        found = self.registry.get(node_type)
        version = op.get("version")
        if version is None:
            if found is None:
                raise self.fail(f"모르는 노드 타입 {node_type!r} (version을 주거나 타입을 고친다)")
            version = found.version
        node_id = new_node_id(taken_ids(self.value), self.random)
        node: dict[str, Any] = {"type": node_type, "version": int(version)}
        if op.get("title") is not None:
            node["title"] = str(op["title"])
        for key in ("in", "config"):
            given = op.get(key)
            if given:
                node[key] = {k: copy.deepcopy(v) for k, v in given.items() if v is not None}
        self.nodes[node_id] = node
        position = op.get("position")
        at = _position(position) if position is not None else self._next_position()
        _obj(_obj(self.value, "layout"), "nodes")[node_id] = at
        if found is not None:
            plugins = _obj(self.value, "plugins")
            version_text = self.registry.plugins.get(found.plugin)
            if found.plugin not in plugins and version_text is not None:
                plugins[found.plugin] = version_text
        self.created[ref] = node_id

    def _next_position(self) -> dict[str, int]:
        layout = self.value.get("layout")
        placed = layout.get("nodes") if isinstance(layout, dict) else None
        xs = [
            p["x"]
            for p in (placed or {}).values()
            if isinstance(p, dict) and isinstance(p.get("x"), int | float)
        ]
        return {"x": (round(max(xs)) + NEW_NODE_GAP) if xs else 0, "y": 0}

    def set_node(self, op: Mapping[str, Any]) -> None:
        _, node = self.node(op["id"])
        if "title" in op:
            if op["title"] is None:
                node.pop("title", None)
            else:
                node["title"] = str(op["title"])
        for key in ("in", "config"):
            if key in op:
                target = _obj(node, key)
                _merge(target, op[key])
                if not target:
                    del node[key]
        if "record" in op:
            if op["record"] is None:
                node.pop("record", None)
            else:
                node["record"] = copy.deepcopy(op["record"])

    def remove_node(self, op: Mapping[str, Any]) -> None:
        gone = self.node_id(op["id"])
        for other_id, other in self.nodes.items():
            if other_id == gone or not isinstance(other, dict):
                continue
            nxt = other.get("next")
            if isinstance(nxt, dict):
                for exit_name in [e for e, to in nxt.items() if to == gone]:
                    del nxt[exit_name]
                    self.removed.append({"from": other_id, "kind": "next", "key": exit_name})
                if not nxt:
                    del other["next"]
            inputs = other.get("in")
            if isinstance(inputs, dict):
                for pin in [p for p, v in inputs.items() if gone in set(_links(v))]:
                    del inputs[pin]
                    self.removed.append({"from": other_id, "kind": "link", "key": pin})
                if not inputs:
                    del other["in"]
        del self.nodes[gone]
        layout = self.value.get("layout")
        if isinstance(layout, dict):
            placed = layout.get("nodes")
            if isinstance(placed, dict):
                placed.pop(gone, None)
            groups = layout.get("collapsed")
            if isinstance(groups, dict):
                for group in groups.values():
                    members = group.get("nodes") if isinstance(group, dict) else None
                    if isinstance(members, list) and gone in members:
                        group["nodes"] = [m for m in members if m != gone]
        for ref, node_id in list(self.created.items()):
            if node_id == gone:
                del self.created[ref]

    def connect(self, op: Mapping[str, Any]) -> None:
        _, source = self.node(op["from"])
        to = self.node_id(op["to"])
        _obj(source, "next")[str(op["exit"])] = to

    def disconnect(self, op: Mapping[str, Any]) -> None:
        _, source = self.node(op["from"])
        nxt = source.get("next")
        exit_name = str(op["exit"])
        if not isinstance(nxt, dict) or exit_name not in nxt:
            raise self.fail(f"출구 {exit_name!r}에 연결이 없다")
        del nxt[exit_name]
        if not nxt:
            del source["next"]

    def link(self, op: Mapping[str, Any]) -> None:
        _, target = self.node(op["to"])
        source = self.node_id(op["from"])
        _obj(target, "in")[str(op["pin"])] = {"$link": f"{source}.{op['output']}"}

    def unlink(self, op: Mapping[str, Any]) -> None:
        _, target = self.node(op["to"])
        inputs = target.get("in")
        pin = str(op["pin"])
        if not isinstance(inputs, dict) or not any(True for _ in _links(inputs.get(pin))):
            raise self.fail(f"핀 {pin!r}에 데이터 연결이 없다")
        del inputs[pin]
        if not inputs:
            del target["in"]

    def move(self, op: Mapping[str, Any]) -> None:
        node_id = self.node_id(op["id"])
        placed = _obj(_obj(self.value, "layout"), "nodes")
        at = placed.get(node_id)
        position = _position(op["position"])
        if isinstance(at, dict):
            at.update(position)
        else:
            placed[node_id] = position

    def set_meta(self, op: Mapping[str, Any]) -> None:
        meta = _obj(self.value, "meta")
        _merge(meta, {k: op[k] for k in ("title", "description") if k in op})
        if not meta:
            del self.value["meta"]


_OPS: Final[dict[str, Callable[[_Patcher, Mapping[str, Any]], None]]] = {
    "add_node": _Patcher.add_node,
    "set_node": _Patcher.set_node,
    "remove_node": _Patcher.remove_node,
    "connect": _Patcher.connect,
    "disconnect": _Patcher.disconnect,
    "link": _Patcher.link,
    "unlink": _Patcher.unlink,
    "move": _Patcher.move,
    "set_meta": _Patcher.set_meta,
}


def apply_ops(
    value: Mapping[str, Any],
    ops: Sequence[Mapping[str, Any]],
    registry: Registry,
    *,
    random: Callable[[int], bytes] = secrets.token_bytes,
) -> PatchResult:
    """`ops`를 차례로 적용한 새 값. 원래 값은 바꾸지 않는다. 틀리면 `PatchInvalid`."""
    patcher = _Patcher(value, registry, random)
    for index, op in enumerate(ops):
        patcher.index = index
        handler = _OPS.get(str(op.get("op")))
        if handler is None:
            raise PatchInvalid(index, f"모르는 연산 {op.get('op')!r}")
        handler(patcher, op)
    return PatchResult(patcher.value, patcher.created, patcher.removed)

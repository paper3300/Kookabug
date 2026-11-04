"""커밋 조각의 의미 검사 (M4 계획 2.9, `recorder-fragment.schema.json`).

모양은 메타스키마가 보고, 여기서는 값 규칙과 로컬 ID가 서로 맞는지 본다: in 값이 그래프 Value
규칙(`graph.schema.json` — 메타스키마에 적을 수 없는 "모르는 $ 키"까지)에 맞고 `$link`가
`<로컬 ID>.<출력>`이고, 로컬 ID가 겹치지 않고, chain이 모든 노드를 한 번씩 실행 차례로
늘어놓고, 이웃한 두 노드가 앞 노드의 출구로 이어지고, `next`·`$link`가 조각 안
노드(`$link`는 앞선 노드)만 가리키고, 열린 끝점이 마지막 노드의 비어 있는 출구다. 모양 검사를
거치지 않은 값도 받는다(같은 문제를 여기서도 잡는다).
조각을 만드는 쪽(T6·T8)과 받는 쪽이 같은 규칙을 쓴다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from itertools import pairwise
from typing import Any, Final

from kookabug_core.schema.shape import validator

__all__ = ["LOCAL_LINK", "fragment_problems", "iter_links"]

LOCAL_LINK: Final = re.compile(r"r[1-9][0-9]{0,5}\.[a-z_][a-z0-9_]*")
"""조각 안 `$link` 값 (메타스키마 LocalLink와 같다)."""


def iter_links(value: Any) -> Iterator[Any]:
    """in 값 안(배열·객체 안쪽까지)의 모든 `$link` 값 (문자열이 아닐 수도 있다).

    `$literal` 하나만 가진 객체 안은 값이라 보지 않는다. `$literal`과 다른 키가 섞인 객체는
    특수 값이 아니므로 안쪽도 본다.
    """
    if isinstance(value, list):
        items: list[Any] = value
        for item in items:
            yield from iter_links(item)
    elif isinstance(value, dict):
        obj: dict[str, Any] = value
        if list(obj) == ["$literal"]:
            return
        if "$link" in obj:
            yield obj["$link"]
        for name, item in obj.items():
            if name != "$link":
                yield from iter_links(item)


def fragment_problems(fragment: Mapping[str, Any]) -> list[str]:
    """조각의 값·로컬 ID 문제 목록 (없으면 빈 목록)."""
    problems: list[str] = []
    graph_value = validator("graph", "#/$defs/Value")
    nodes: dict[str, Mapping[str, Any]] = {}
    for node in fragment["nodes"]:
        local_id = node["local_id"]
        if local_id in nodes:
            problems.append(f"로컬 ID {local_id}가 두 번 있다")
        nodes[local_id] = node
    chain: list[str] = list(fragment["chain"])
    order = {local_id: i for i, local_id in enumerate(chain)}
    if len(order) != len(chain):
        problems.append("chain에 같은 노드가 두 번 있다")
    if set(chain) != set(nodes):
        problems.append("chain이 노드를 빠짐없이 한 번씩 담지 않는다")
    for local_id, node in nodes.items():
        for exit_name, target in node.get("next", {}).items():
            if target not in nodes:
                problems.append(f"{local_id}.next.{exit_name}가 조각에 없는 {target}를 가리킨다")
        for pin, value in node["in"].items():
            for error in graph_value.iter_errors(value):
                problems.append(
                    f"{local_id}.in.{pin} 값이 그래프 값 규칙에 맞지 않는다: {error.message}"
                )
        for link in iter_links(node["in"]):
            if not (isinstance(link, str) and LOCAL_LINK.fullmatch(link)):
                problems.append(f"{local_id}의 $link {link!r}가 '<로컬 ID>.<출력>'이 아니다")
                continue
            source = link.split(".", 1)[0]
            if source not in nodes:
                problems.append(f"{local_id}의 $link {link}가 조각에 없는 노드를 가리킨다")
            elif order.get(source, len(chain)) >= order.get(local_id, -1):
                problems.append(f"{local_id}의 $link {link}가 앞선 노드가 아니다")
    for before, after in pairwise(chain):
        if before in nodes and after not in nodes[before].get("next", {}).values():
            problems.append(f"chain의 {before} → {after}가 출구로 이어지지 않는다")
    open_end = fragment.get("open_end")
    if open_end is not None and chain:
        if open_end["node"] != chain[-1]:
            problems.append("open_end가 chain의 마지막 노드가 아니다")
        elif open_end["exit"] in nodes.get(chain[-1], {}).get("next", {}):
            problems.append("open_end 출구가 이미 이어져 있다")
    first_window = fragment.get("first_window_node")
    if first_window is not None and chain and first_window != chain[0]:
        problems.append("first_window_node가 chain의 첫 노드가 아니다")
    return problems

"""치트 구현 그래프의 참조 폐포 (계획 9장 R2).

채택 digest(`formats.cheat_digest`)에 `impl.graph`가 전이적으로 참조하는 파일(서브그래프·target·
이미지·화면 판정)의 바이트 digest와 쓰인 노드 타입을 넣는다. 실행 스냅샷에서 같은 계산으로 다시
확인하는 것은 B2(`core.qa.cheat`)다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from kookabug_core.canonical import canonical_dumps
from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets, Workspace

__all__ = ["Closure", "graph_closure"]


@dataclass(frozen=True, slots=True)
class Closure:
    """`files`: 워크스페이스 기준 경로 → 바이트 sha256(없는 파일은 None). `nodes`: 노드 타입 →
    그래프에 적힌 노드 판(`version`) 목록. `digest`: 둘을 정규화한 sha256."""

    digest: str
    files: dict[str, str | None] = field(default_factory=dict[str, str | None])
    nodes: dict[str, list[int]] = field(default_factory=dict[str, list[int]])


def graph_closure(workspace: Workspace, graph: str) -> Closure:
    """`graph`와 그것이 참조하는 파일 전체(로더의 `references.discovered` — 서브그래프·target·
    이미지·출구 화면)의 바이트 digest. 비밀값은 읽지 않는다(빈 공급자)."""
    program = load_program(workspace, graph, secrets=MemorySecrets())
    rels = {graph, *program.references.discovered}
    files: dict[str, str | None] = {}
    for rel in sorted(rels):
        path = workspace.resolve(rel)
        try:
            data = path.read_bytes() if path is not None and path.is_file() else None
        except OSError:
            data = None
        files[rel] = None if data is None else hashlib.sha256(data).hexdigest()
    nodes: dict[str, set[int]] = {}
    for g in program.graphs.values():
        for node in g.nodes.values():
            nodes.setdefault(node.type, set()).add(node.version)
    node_list = {t: sorted(v) for t, v in sorted(nodes.items())}
    body = canonical_dumps({"files": files, "nodes": node_list})
    return Closure(hashlib.sha256(body.encode("utf-8")).hexdigest(), files, node_list)

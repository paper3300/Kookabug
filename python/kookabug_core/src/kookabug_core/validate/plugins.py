"""설치 플러그인 진단 (M6 계획 3.3·3.7): runner가 잠금·환경을 본 결과(`plugins.runtime`)를 그래프
위치로 옮긴다.

- `plugin_not_installed`·`plugin_env_missing`·`plugin_env_stale` (오류): 그 플러그인을 쓰는 첫 노드
- `plugin_version_differs` (경고): 그래프 `plugins`의 판 ≠ 잠금의 판
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from kookabug_core.codes import diag
from kookabug_core.diagnostics import Diagnostic, json_pointer
from kookabug_core.loader import Program

__all__ = ["plugin_diagnostics", "used_plugins"]


def used_plugins(program: Program) -> set[str]:
    """그래프(서브그래프 포함)의 노드가 쓰는 플러그인 ID."""
    return {node.plugin for graph in program.graphs.values() for node in graph.nodes.values()}


def plugin_diagnostics(
    program: Program,
    problems: Iterable[tuple[str, str, str]],
    versions: Mapping[str, str],
) -> list[Diagnostic]:
    """`problems`: (코드, 플러그인 ID, 메시지). `versions`: 잠금의 플러그인 판."""
    out: list[Diagnostic] = []
    for code, plugin, message in problems:
        where = _first_use(program, plugin)
        if where is None:
            out.append(diag(code, message, file=program.root))
        else:
            path, node = where
            out.append(
                diag(
                    code, message, file=path, node=node, pointer=json_pointer("nodes", node, "type")
                )
            )
    for graph in sorted(program.graphs.values(), key=lambda g: g.path):
        for plugin, declared in sorted(graph.plugins.items()):
            locked = versions.get(plugin)
            if locked is not None and locked != declared:
                out.append(
                    diag(
                        "plugin_version_differs",
                        f"그래프는 {plugin} {declared}을(를) 적었는데 설치된 판은 {locked}이다",
                        file=graph.path,
                        pointer=json_pointer("plugins", plugin),
                    )
                )
    return out


def _first_use(program: Program, plugin: str) -> tuple[str, str] | None:
    for graph in sorted(program.graphs.values(), key=lambda g: g.path):
        for node in sorted(graph.nodes.values(), key=lambda n: n.id):
            if node.plugin == plugin:
                return graph.path, node.id
    return None

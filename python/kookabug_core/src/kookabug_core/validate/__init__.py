"""실행 전 검증.

    workspace = Workspace.find(path)
    program, diagnostics = check_graph(workspace, "tests/inventory/open.graph.json")

진단 코드 표는 `kookabug_core.codes`. 로더가 읽으면서 남긴 진단(파일·형식·`$setting` 등)과 검증
모듈(구조·값·타입·서브그래프·화면·재시도·변수·흐름)의 진단을 합쳐 파일·위치 순으로 돌려준다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.loader import Program, load_program
from kookabug_core.registry import Registry, default_registry
from kookabug_core.validate import (
    dominance,
    pure_cycles,
    retry,
    scopes,
    screens,
    structure,
    subgraph,
    types,
    values,
)
from kookabug_core.validate import vars as vars_
from kookabug_core.validate.context import ValidationContext
from kookabug_core.workspace import RunOptions, SecretProvider, Workspace

__all__ = ["check_graph", "check_graph_value", "sort_diagnostics", "validate"]

CHECKS = (
    structure,
    values,
    types,
    subgraph,
    screens,
    retry,
    vars_,
    scopes,
    pure_cycles,
    dominance,
)


def sort_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return sorted(
        diagnostics, key=lambda d: (d.file or "", d.pointer or "", d.code, d.node or "", d.message)
    )


def validate(program: Program, registry: Registry | None = None) -> list[Diagnostic]:
    """읽은 프로그램을 검증한다. 로더 진단을 포함한다."""
    ctx = ValidationContext(program, registry or default_registry())
    for module in CHECKS:
        module.check(ctx)
    return sort_diagnostics([*program.diagnostics, *ctx.diagnostics])


def check_graph(
    workspace: Workspace,
    graph: str | Path,
    *,
    registry: Registry | None = None,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[Program, list[Diagnostic]]:
    """그래프 파일을 읽고 검증한다."""
    program = load_program(workspace, graph, options=options, secrets=secrets)
    return program, validate(program, registry)


def check_graph_value(
    workspace: Workspace,
    graph: str | Path,
    value: Any,
    *,
    registry: Registry | None = None,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[Program, list[Diagnostic]]:
    """편집 버퍼 검증 (M2 계획 2.7): 루트 그래프만 `value`로 바꾸고 서브그래프·target·화면은 디스크.

    같은 바이트의 파일이면 `check_graph`와 진단이 같다. 비밀값이 없으면 실행과 같이 오류다.
    """
    program = load_program(workspace, graph, options=options, secrets=secrets, root_value=value)
    return program, validate(program, registry)

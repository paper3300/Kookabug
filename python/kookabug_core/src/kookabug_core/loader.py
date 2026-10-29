"""그래프 로더: 파일 읽기 → 형식 검사 → 특수 값 해석 → IR.

테스트 그래프 하나에서 시작해 `core.graph.call`이 부르는 서브그래프를 모두 읽는다. 읽으면서
`$setting`·`$secret`·`$target`을 해석하고, 그 문제(`setting_missing` 등)를 진단으로 남긴다.
`$link`는 `LinkRef`로 바꿔 두기만 한다 (값은 실행 때 읽는다).

참조 파일 목록(`references`)은 서브그래프·target·이미지의 워크스페이스 기준 경로다
(M0b 실행 시작 스냅샷이 쓴다). `discovered`는 파일이 없거나 읽지 못한 경로까지 담는다.
"""

from __future__ import annotations

import copy
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from kookabug_core.canonical import loads_strict
from kookabug_core.codes import diag
from kookabug_core.diagnostics import Diagnostic, json_pointer
from kookabug_core.ir import GRAPH_CALL, Graph, Link, LinkRef, Node, Unresolved
from kookabug_core.schema import check_shape
from kookabug_core.workspace import (
    RunOptions,
    SecretProvider,
    SettingLookup,
    Workspace,
    WorkspaceError,
    default_secrets,
)
from kookabug_sdk import Secret
from kookabug_sdk.types import Target

__all__ = [
    "MAX_CALL_DEPTH",
    "CallRef",
    "Program",
    "References",
    "graph_from_data",
    "load_program",
]

CallStatus = Literal["ok", "missing", "broken", "bad_path", "unloaded"]

MAX_CALL_DEPTH = 16
"""테스트(깊이 0)에서 시작해 중첩 호출 프레임을 16개까지 둔다 (검사는 `validate.subgraph`)."""


@dataclass(frozen=True, slots=True)
class CallRef:
    """`core.graph.call` 노드 하나가 가리키는 그래프.

    `status`: `ok` 읽음, `missing` 파일 없음, `broken` 파일은 있지만 읽기·형식 오류,
    `bad_path` `config.graph`가 워크스페이스 경로가 아님(문자열 아님 포함),
    `unloaded` 호출 깊이 한도를 넘는 곳이라 읽지 않음 (그 앞 호출에 `call_depth`가 난다).
    """

    graph: str
    node: str
    path: str | None
    status: CallStatus


@dataclass
class References:
    """실행이 읽는 파일 (워크스페이스 기준 경로). 루트 그래프 자신은 `graphs`에 들어간다.

    `graphs`·`targets`·`images`는 있는 파일만이다. `discovered`는 그래프가 가리킨 모든 경로
    (서브그래프·target·target의 이미지)로, 파일이 없거나 읽기·형식 오류인 것, 호출 깊이 한도 밖이라
    읽지 않은 서브그래프(`unloaded`)도 든다. 워크스페이스 경로가 아닌 값은 들지 않는다.
    스냅샷이 이것으로 복사할 파일을 찾는다.
    """

    graphs: set[str] = field(default_factory=set[str])
    targets: set[str] = field(default_factory=set[str])
    images: set[str] = field(default_factory=set[str])
    discovered: set[str] = field(default_factory=set[str])

    def all(self) -> list[str]:
        return sorted(self.graphs | self.targets | self.images)


@dataclass
class Program:
    """루트 그래프와 그것이 부르는 서브그래프 전체."""

    workspace: Workspace
    root: str
    options: RunOptions
    graphs: dict[str, Graph] = field(default_factory=dict[str, Graph])
    broken: set[str] = field(default_factory=set[str])
    calls: dict[tuple[str, str], CallRef] = field(default_factory=dict[tuple[str, str], CallRef])
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    references: References = field(default_factory=References)
    settings: dict[str, SettingLookup] = field(default_factory=dict[str, SettingLookup])
    """그래프가 `$setting`으로 쓴 설정 (키 → 찾은 값·계층). 실행 정보(`run.json`)에 남긴다."""

    def callee(self, graph: str, node: str) -> Graph | None:
        ref = self.calls.get((graph, node))
        if ref is None or ref.status != "ok" or ref.path is None:
            return None
        return self.graphs.get(ref.path)


def load_program(
    workspace: Workspace,
    graph: str | Path,
    *,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
) -> Program:
    """`graph`(워크스페이스 기준 경로 또는 절대 경로)와 그 서브그래프를 읽는다."""
    if isinstance(graph, Path):
        rel = workspace.relative(graph)
        if rel is None:
            raise WorkspaceError(f"{graph}은(는) 워크스페이스 {workspace.root} 밖이다")
    else:
        rel = graph
    loader = _Loader(workspace, options or RunOptions(), secrets or default_secrets())
    program = loader.program
    program.root = rel
    program.diagnostics.extend(workspace.diagnostics)
    program.diagnostics.extend(workspace.check_options(program.options))
    if workspace.resolve(rel) is None:
        program.diagnostics.append(
            diag("graph_missing", f"그래프 경로 '{rel}'이(가) 워크스페이스 경로가 아니다", file=rel)
        )
        return program
    if loader.load_all(rel) == "missing":
        program.diagnostics.append(
            diag("graph_missing", f"그래프 파일 '{rel}'이(가) 없다", file=rel)
        )
    return program


def graph_from_data(
    data: Mapping[str, Any],
    path: str,
    workspace: Workspace,
    *,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[Graph, list[Diagnostic]]:
    """형식 검사를 통과한 그래프 dict 하나를 IR로 (서브그래프는 읽지 않는다)."""
    loader = _Loader(workspace, options or RunOptions(), secrets or default_secrets())
    graph = loader.build(path, data)
    return graph, loader.program.diagnostics


def _record_of(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """`record` 객체 (형식 검사를 통과했으므로 있으면 `{screenshots?, video?}`)."""
    record = data.get("record")
    return dict(record) if isinstance(record, Mapping) else None


class _Loader:
    def __init__(self, workspace: Workspace, options: RunOptions, secrets: SecretProvider) -> None:
        self.ws = workspace
        self.secrets = secrets
        self.program = Program(workspace, "", options)
        self._status: dict[str, CallStatus] = {}
        self._targets: dict[str, Target | tuple[str, str]] = {}

    def load_all(self, root: str) -> CallStatus:
        """루트에서 호출을 따라 너비 우선으로 읽는다 (재귀 없음).

        너비 우선이라 각 그래프는 가장 얕은 호출 깊이에서 읽힌다. 깊이가 한도를 넘는 그래프
        (`MAX_CALL_DEPTH + 1`)는 읽기만 하고 그 호출은 따라가지 않는다. 한도를 넘는 호출 사슬은
        `validate.subgraph`가 `call_depth`로 보고하므로, 수백 단계 입력도 끝까지 읽지 않고 멈춘다.
        """
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        while queue:
            rel, depth = queue.popleft()
            if rel in self._status:
                continue  # 이미 읽음 (호출 순환·여러 번 호출)
            if self._load(rel) != "ok" or depth > MAX_CALL_DEPTH:
                continue
            for node in self.program.graphs[rel].nodes_of_type(GRAPH_CALL):
                path = self._call_path(node)
                if path is not None:
                    queue.append((path, depth + 1))

        for graph in self.program.graphs.values():
            for node in graph.nodes_of_type(GRAPH_CALL):
                path = self._call_path(node)
                status: CallStatus = (
                    "bad_path" if path is None else self._status.get(path, "unloaded")
                )
                if path is not None:
                    self.program.references.discovered.add(path)
                self.program.calls[(graph.path, node.id)] = CallRef(
                    graph.path, node.id, path, status
                )
        return self._status[root]

    def _call_path(self, node: Node) -> str | None:
        target = node.config.get("graph")
        if isinstance(target, str) and self.ws.resolve(target) is not None:
            return target
        return None

    def _load(self, rel: str) -> CallStatus:
        path = self.ws.resolve(rel)
        assert path is not None
        self.program.references.discovered.add(rel)
        if not path.is_file():
            self._status[rel] = "missing"
            return "missing"
        self._status[rel] = "ok"
        self.program.references.graphs.add(rel)
        diags = self.program.diagnostics
        try:
            data = loads_strict(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            diags.append(diag("json_invalid", f"'{rel}'을(를) 읽을 수 없다: {exc}", file=rel))
            return self._broken(rel)
        problems = check_shape(data, "graph", file=rel)
        if problems:
            diags.extend(problems)
            return self._broken(rel)
        self.program.graphs[rel] = self.build(rel, data)
        return "ok"

    def _broken(self, rel: str) -> CallStatus:
        self._status[rel] = "broken"
        self.program.broken.add(rel)
        return "broken"

    def build(self, rel: str, data: Mapping[str, Any]) -> Graph:
        graph = Graph(
            path=rel,
            kind=data["kind"],
            nodes={},
            plugins=dict(data.get("plugins", {})),
            interface=data.get("interface"),
            data=data,
            record=_record_of(data),
        )
        for node_id, raw in data["nodes"].items():
            inputs = {
                pin: self._resolve(value, graph, node_id, (pin,))
                for pin, value in raw.get("in", {}).items()
            }
            node = Node(
                id=node_id,
                type=raw["type"],
                version=raw["version"],
                title=raw.get("title"),
                inputs=inputs,
                config=copy.deepcopy(dict(raw.get("config", {}))),
                next=dict(raw.get("next", {})),
                raw=raw,
                record=_record_of(raw),
            )
            graph.nodes[node_id] = node
        return graph

    # ------------------------------------------------------------ 특수 값

    def _resolve(self, value: Any, graph: Graph, node: str, path: tuple[str | int, ...]) -> Any:
        if isinstance(value, list):
            return [self._resolve(v, graph, node, (*path, i)) for i, v in enumerate(value)]
        if not isinstance(value, dict):
            return value
        if len(value) == 1:
            ((key, inner),) = value.items()
            if isinstance(key, str) and key.startswith("$"):
                return self._special(key, inner, graph, node, path)
        return {k: self._resolve(v, graph, node, (*path, k)) for k, v in value.items()}

    def _special(
        self, tag: str, inner: Any, graph: Graph, node: str, path: tuple[str | int, ...]
    ) -> Any:
        pointer = json_pointer("nodes", node, "in", *path)
        where = {"file": graph.path, "node": node, "pointer": pointer}
        match tag:
            case "$literal":
                return copy.deepcopy(inner)
            case "$link":
                producer, output = inner.split(".", 1)
                graph.links.append(Link(node, path, producer, output))
                return LinkRef(producer, output)
            case "$setting":
                lookup = self.ws.lookup_setting(inner, self.program.options)
                problem = self.ws.setting_problem(lookup, self.program.options)
                if problem is None:
                    self.program.settings[inner] = lookup
                    return copy.deepcopy(lookup.value)
                self.program.diagnostics.append(diag(problem[0], problem[1], **where))
                return Unresolved(tag, inner)
            case "$secret":
                secret = self.secrets.get(inner)
                if secret is None:
                    self.program.diagnostics.append(
                        diag(
                            "secret_missing",
                            f"비밀값 '{inner}'을(를) 찾지 못했다 "
                            "(환경 변수 KOOKABUG_SECRET_* 또는 비밀값 저장소에 넣는다)",
                            **where,
                        )
                    )
                    return Unresolved(tag, inner)
                return Secret(secret)
            case "$target":
                target = self._target(inner)
                if isinstance(target, Target):
                    return target
                self.program.diagnostics.append(diag(target[0], target[1], **where))
                return Unresolved(tag, inner)
            case _:  # 형식 검사가 막는다 (닫힌 목록)
                raise ValueError(f"모르는 특수 값 {tag}")

    def _target(self, rel: str) -> Target | tuple[str, str]:
        if rel not in self._targets:
            self._targets[rel] = self._read_target(rel)
        return self._targets[rel]

    def _read_target(self, rel: str) -> Target | tuple[str, str]:
        path = self.ws.resolve(rel)
        if path is None:
            return "target_missing", f"target 경로 '{rel}'이(가) 워크스페이스 경로가 아니다"
        refs = self.program.references
        refs.discovered.add(rel)
        if not path.is_file():
            return "target_missing", f"target 파일 '{rel}'이(가) 없다"
        refs.targets.add(rel)
        try:
            data = loads_strict(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return "target_invalid", f"target 파일 '{rel}'을(를) 읽을 수 없다: {exc}"
        problems = check_shape(data, "target", file=rel)
        if problems:
            detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:3])
            return "target_invalid", f"target 파일 '{rel}'의 형식이 틀렸다: {detail}"
        image = self.ws.resolve_from(rel, data["image"])
        if image is None:
            return "target_invalid", f"target '{rel}'의 image 경로가 워크스페이스 밖이거나 틀렸다"
        image_path = self.ws.resolve(image)
        if image_path is not None:
            refs.discovered.add(image)
        if image_path is None or not image_path.is_file():
            return "target_invalid", f"target '{rel}'의 이미지 '{image}'이(가) 없다"
        refs.images.add(image)
        return Target(name=rel, path=path, spec=data)

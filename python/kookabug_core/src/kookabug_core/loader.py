"""그래프 로더: 파일 읽기 → 형식 검사 → 특수 값 해석 → IR.

테스트 그래프 하나에서 시작해 `core.graph.call`이 부르는 서브그래프를 모두 읽는다. 읽으면서
`$setting`·`$secret`·`$target`을 해석하고, 그 문제(`setting_missing` 등)를 진단으로 남긴다.
`$link`는 `LinkRef`로 바꿔 두기만 한다 (값은 실행 때 읽는다).

참조 파일 목록(`references`)은 서브그래프·target·이미지·화면 파일의 워크스페이스 기준 경로다
(M0b 실행 시작 스냅샷이 쓴다). `discovered`는 파일이 없거나 읽지 못한 경로까지 담는다.

서브그래프 출구의 `screen`(화면 ID)은 `screens/`에서 찾아 읽고 그 target까지 따라간다(M1 2.10).
결과는 `Program.screens`이고, 진단은 `validate.screens`가 낸다.

M8 `qa`·치트: 루트 `qa.claims`가 가리키는 `knowledge/features/<기능>.json`, 치트 노드
(`core.qa.cheat`)·`qa.cheats`가 있으면 `knowledge/cheats.json`을 읽어 `Program.knowledge`에 두고
참조 목록에 넣는다 (스냅샷이 복사해 실행 시작 때 고정). 치트 노드의 구현 서브그래프
(`impl.graph`)는 그 정의에서 찾아 `core.graph.call`처럼 읽고 `Program.calls`에 둔다.
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
from kookabug_core.ir import GRAPH_CALL, QA_CHEAT, Graph, Link, LinkRef, Node, Unresolved
from kookabug_core.schema import check_shape
from kookabug_core.screens import ScreenDef, ScreenFileError, read_screen_file, screen_index
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
    "CHEATS_FILE",
    "MAX_CALL_DEPTH",
    "CallRef",
    "Program",
    "References",
    "ScreenRef",
    "exit_screens",
    "graph_from_data",
    "load_program",
]

CallStatus = Literal["ok", "missing", "broken", "bad_path", "unloaded"]

MAX_CALL_DEPTH = 16
"""테스트(깊이 0)에서 시작해 중첩 호출 프레임을 16개까지 둔다 (검사는 `validate.subgraph`)."""

CHEATS_FILE = "knowledge/cheats.json"
"""치트 정의 (M8 3.2). 치트 노드·`qa.cheats`가 있는 실행은 이 파일을 스냅샷에 고정한다."""


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

    `graphs`·`targets`·`images`·`screens`는 있는 파일만이다. `discovered`는 그래프가 가리킨 모든
    경로(서브그래프·target·target의 이미지·화면 파일)로, 파일이 없거나 읽기·형식 오류인 것, 호출
    깊이 한도 밖이라 읽지 않은 서브그래프(`unloaded`)도 든다. 워크스페이스 경로가 아닌 값은 들지
    않는다. 스냅샷이 이것으로 복사할 파일을 찾는다. `screen_ids`는 출구가 가리킨 화면 ID다
    (스냅샷은 원본 워크스페이스에서 그 ID의 파일을 찾는다 — 스냅샷 폴더에는 아직 없으므로).
    """

    graphs: set[str] = field(default_factory=set[str])
    targets: set[str] = field(default_factory=set[str])
    images: set[str] = field(default_factory=set[str])
    screens: set[str] = field(default_factory=set[str])
    discovered: set[str] = field(default_factory=set[str])
    screen_ids: set[str] = field(default_factory=set[str])

    def all(self) -> list[str]:
        return sorted(self.graphs | self.targets | self.images | self.screens)


ScreenStatus = Literal["ok", "unknown", "ambiguous", "invalid"]


@dataclass(frozen=True, slots=True)
class ScreenRef:
    """출구가 가리킨 화면 ID 하나를 찾은 결과.

    `status`: `ok` 읽음(`screen`), `unknown` 그 ID의 파일이 없음, `ambiguous` 둘 이상(`paths`),
    `invalid` 파일 형식이 틀렸거나 그 target을 쓸 수 없음(`problem`).
    """

    id: str
    status: ScreenStatus
    paths: tuple[str, ...] = ()
    screen: ScreenDef | None = None
    problem: str | None = None


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
    screens: dict[str, ScreenRef] = field(default_factory=dict[str, ScreenRef])
    """출구 `screen`이 가리킨 화면 ID → 찾은 결과."""
    knowledge: dict[str, Any] = field(default_factory=dict[str, Any])
    """M8: 읽은 지식 파일(워크스페이스 기준 경로 → 형식 검사를 통과한 값, 없거나 틀리면 None)."""
    cheat_checks: dict[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    """M8: 실행 스냅샷이 **원본**에서 본 치트 구현 폐포의 문제 (치트 ID → 문제, 스냅샷만 채운다).
    문제가 있으면 그 치트 노드는 `cheat_not_adopted`."""

    @property
    def qa(self) -> Mapping[str, Any] | None:
        """루트 그래프의 `qa` (없으면 None)."""
        root = self.graphs.get(self.root)
        qa = root.data.get("qa") if root is not None else None
        return qa if isinstance(qa, Mapping) else None

    def cheat(self, cheat_id: str) -> Mapping[str, Any] | None:
        """`knowledge/cheats.json`의 그 치트 정의 (파일·정의가 없으면 None)."""
        doc = self.knowledge.get(CHEATS_FILE)
        if not isinstance(doc, Mapping):
            return None
        for item in doc.get("cheats", ()):
            if isinstance(item, Mapping) and item.get("id") == cheat_id:
                return item
        return None

    def callee(self, graph: str, node: str) -> Graph | None:
        ref = self.calls.get((graph, node))
        if ref is None or ref.status != "ok" or ref.path is None:
            return None
        return self.graphs.get(ref.path)


_NO_VALUE: Any = object()


def load_program(
    workspace: Workspace,
    graph: str | Path,
    *,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
    root_value: Any = _NO_VALUE,
) -> Program:
    """`graph`(워크스페이스 기준 경로 또는 절대 경로)와 그 서브그래프를 읽는다.

    `root_value`를 주면 루트 그래프 파일 대신 그 값(편집 버퍼, JSON 트리)을 쓴다. 서브그래프·target·
    화면은 디스크에서 읽는다 (루트가 자기 자신을 부르면 그 호출도 버퍼다).
    """
    if isinstance(graph, Path):
        rel = workspace.relative(graph)
        if rel is None:
            raise WorkspaceError(f"{graph}은(는) 워크스페이스 {workspace.root} 밖이다")
    else:
        rel = graph
    loader = _Loader(workspace, options or RunOptions(), secrets or default_secrets(workspace))
    if root_value is not _NO_VALUE:
        loader.buffers[rel] = copy.deepcopy(root_value)
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
    loader.load_qa()
    loader.load_screens()
    return program


def exit_screens(graph: Graph) -> list[tuple[str, str]]:
    """그래프 `interface.exits`의 (출구 이름, 화면 ID). 형식 검사를 통과한 그래프만 넘긴다."""
    interface = graph.interface if isinstance(graph.interface, Mapping) else {}
    exits = interface.get("exits")
    if not isinstance(exits, Mapping):
        return []
    found = []
    for name, spec in exits.items():
        screen = spec.get("screen") if isinstance(spec, Mapping) else None
        if isinstance(screen, str):
            found.append((name, screen))
    return found


def graph_from_data(
    data: Mapping[str, Any],
    path: str,
    workspace: Workspace,
    *,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[Graph, list[Diagnostic]]:
    """형식 검사를 통과한 그래프 dict 하나를 IR로 (서브그래프는 읽지 않는다)."""
    loader = _Loader(workspace, options or RunOptions(), secrets or default_secrets(workspace))
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
        self.buffers: dict[str, Any] = {}
        """경로 → 파일 대신 쓸 값 (편집 버퍼)."""

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
            for node in self._callers(self.program.graphs[rel]):
                path = self._call_path(node)
                if path is not None:
                    queue.append((path, depth + 1))

        for graph in list(self.program.graphs.values()):
            for node in self._callers(graph):
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

    @staticmethod
    def _callers(graph: Graph) -> list[Node]:
        """서브그래프를 부르는 노드: `core.graph.call`과 치트 노드 (구현 서브그래프)."""
        return [n for n in graph.nodes.values() if n.type in (GRAPH_CALL, QA_CHEAT)]

    def _call_path(self, node: Node) -> str | None:
        if node.type == QA_CHEAT:
            return self._cheat_path(node)
        target = node.config.get("graph")
        if isinstance(target, str) and self.ws.resolve(target) is not None:
            return target
        return None

    def _cheat_path(self, node: Node) -> str | None:
        """치트 노드의 구현 서브그래프: 지식 파일의 그 치트 `impl.graph`(콘솔 구현만)."""
        cheat_id = node.config.get("cheat")
        self.knowledge_doc(CHEATS_FILE, "cheats")
        cheat = self.program.cheat(cheat_id) if isinstance(cheat_id, str) else None
        impl = cheat.get("impl") if cheat is not None else None
        if not isinstance(impl, Mapping) or impl.get("kind") != "console":
            return None
        target = impl.get("graph")
        if isinstance(target, str) and self.ws.resolve(target) is not None:
            return target
        return None

    # ------------------------------------------------------------ 지식 (M8)

    def knowledge_doc(self, rel: str, kind: Literal["claims", "cheats"]) -> Any:
        """지식 파일 하나를 읽어 `Program.knowledge`에 둔다 (한 번만). 참조 목록에 넣으므로 스냅샷이
        복사한다. 없거나 형식이 틀리면 None (진단은 `validate.qa`)."""
        knowledge = self.program.knowledge
        if rel in knowledge:
            return knowledge[rel]
        knowledge[rel] = None
        path = self.ws.resolve(rel)
        if path is None:
            return None
        self.program.references.discovered.add(rel)
        try:
            data = loads_strict(path.read_text(encoding="utf-8")) if path.is_file() else None
        except OSError, UnicodeDecodeError, ValueError:
            data = None
        if data is not None and not check_shape(data, kind, file=rel):
            knowledge[rel] = data
        return knowledge[rel]

    def load_qa(self) -> None:
        """루트 `qa`가 가리키는 주장 파일, 치트를 쓰거나 허용하는 그래프면 치트 파일."""
        qa = self.program.qa
        if qa is not None:
            for claim in qa.get("claims", ()):
                claim_id = claim.get("id") if isinstance(claim, Mapping) else None
                if isinstance(claim_id, str):
                    feature = claim_id.split(".", 1)[0]
                    self.knowledge_doc(f"knowledge/features/{feature}.json", "claims")
        for graph in self.program.graphs.values():
            if "cheats" in (graph.data.get("qa") or {}) or graph.nodes_of_type(QA_CHEAT):
                self.knowledge_doc(CHEATS_FILE, "cheats")

    def _load(self, rel: str) -> CallStatus:
        path = self.ws.resolve(rel)
        assert path is not None
        self.program.references.discovered.add(rel)
        buffered = rel in self.buffers
        if not buffered and not path.is_file():
            self._status[rel] = "missing"
            return "missing"
        self._status[rel] = "ok"
        self.program.references.graphs.add(rel)
        diags = self.program.diagnostics
        if buffered:
            data = self.buffers[rel]
        else:
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

    # ------------------------------------------------------------ 화면

    def load_screens(self) -> None:
        """읽은 그래프의 출구가 가리킨 화면 ID를 `screens/`에서 찾아 읽는다 (그 target까지)."""
        refs = self.program.references
        for graph in self.program.graphs.values():
            refs.screen_ids.update(screen for _, screen in exit_screens(graph))
        if not refs.screen_ids:
            return
        index = screen_index(self.ws)
        for screen_id in sorted(refs.screen_ids):
            paths = tuple(index.get(screen_id, []))
            refs.discovered.update(paths)
            self.program.screens[screen_id] = self._screen(screen_id, paths)

    def _screen(self, screen_id: str, paths: tuple[str, ...]) -> ScreenRef:
        if len(paths) != 1:
            return ScreenRef(screen_id, "ambiguous" if paths else "unknown", paths)
        rel = paths[0]
        path = self.ws.resolve(rel)
        assert path is not None
        self.program.references.screens.add(rel)
        try:
            screen = read_screen_file(path, rel)
        except ScreenFileError as exc:
            return ScreenRef(screen_id, "invalid", paths, problem=str(exc))
        problems: list[str] = []
        for target in screen.targets:
            found = self._target(target)
            if not isinstance(found, Target):
                problems.append(found[1])
        if problems:
            return ScreenRef(screen_id, "invalid", paths, screen, "; ".join(problems))
        return ScreenRef(screen_id, "ok", paths, screen)

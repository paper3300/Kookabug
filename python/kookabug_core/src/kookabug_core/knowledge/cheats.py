"""치트 구현의 참조 폐포와 채택 digest (계획 3.2·9장 R2).

채택 digest(`formats.cheat_digest`)에는 정의 필드 + `impl.graph`가 전이적으로 참조하는 파일
(서브그래프·target·이미지·화면 판정)의 바이트 digest + 그 폐포가 쓰는 **노드 구현 revision**이 든다.
같은 함수가 채택(사람, 워크스페이스)과 실행(치트 노드, 실행 스냅샷)에서 돈다 — 실행 스냅샷에서 다시
계산한 값이 채택 때와 다르면 그 치트는 채택되지 않은 것이다(`cheat_not_adopted`).

노드 구현 revision (`node_revision`):
- 코어 노드(`core.*`): 선언(노드 스키마) + 노드 함수가 든 모듈 소스 바이트 + `kookabug_nodes` 판.
  실행기가 직접 처리하는 노드(`engine`)는 실행기 소스까지
- 플러그인 노드: `kookabug.lock`의 그 플러그인 `wheel_sha256`·`schema_sha256`·판. 잠금에 없으면
  (개발 모듈 등) 알 수 없음

**미해결·동적 의존성**(`Closure.problems`)이 하나라도 있으면 채택·실행 모두 거부한다: 읽지 못한
파일·서브그래프·화면, `$setting`(프로필·이 PC 설정에 따라 콘솔 입력이 달라짐)·`$secret`, 구현
revision을 알 수 없는 노드, 구현 안의 치트 노드(중첩), 콘솔 구현 모양(`command` 입력을 받는
서브그래프)이 아님, 허용 목록(`IMPL_NODE_TYPES`) 밖 노드(설정·Agent·OCR·프로세스·플러그인 환경을
읽을 수 있음), 실행 의존성이 `knowledge/` 아래(적힌 경로·실경로 — Agent가 지식 연산으로 쓸 수
있는 자리라 실행 코드를 두지 않는다).
실행 스냅샷은 경로를 복사하며 정션 같은 위치 정보를 잃으므로, 스냅샷을 만들 때 **원본**에서 계산한
문제 목록(`source_checks`)을 `Program.cheat_checks`에 남기고 치트 노드가 그것도 본다.
폐포에서 빼는 것은 로더가 지식 형식으로 읽은 메타데이터 파일(치트 정의·주장)뿐이다 — 넣으면 채택
기록 자체가 digest를 바꾼다. 그 파일이 실행 의존성으로도 쓰이면 넣고 위 규칙으로 거부한다.
그래서 digest 폐포는 실행이 쓰는 스냅샷·설정과 같다 — 설정·`RunOptions`가 구현 그래프에 닿는 길이
없다.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from kookabug_core.canonical import canonical_dumps
from kookabug_core.ir import QA_CHEAT, Unresolved
from kookabug_core.knowledge.formats import cheat_digest
from kookabug_core.loader import Program, load_program
from kookabug_core.registry import Registry, default_registry
from kookabug_core.workspace import MemorySecrets, RunOptions, Workspace
from kookabug_sdk import Secret

__all__ = [
    "COMMAND_INPUT",
    "IMPL_NODE_TYPES",
    "Closure",
    "adoption_digest",
    "graph_closure",
    "node_revision",
    "read_lock_plugins",
    "source_checks",
]

IMPL_NODE_TYPES: Final = frozenset(
    {
        # 흐름: 실행기가 직접 처리 (호출 프레임만 다룬다)
        "core.graph.entry",
        "core.graph.exit",
        "core.graph.call",
        # 흐름: 입력값(조건·밀리초)만 본다
        "core.flow.branch",
        "core.flow.delay",
        # 입력: 받은 키·글자·좌표만 보낸다 (`ctx.input`)
        "core.input.key",
        "core.input.type_text",
        "core.input.click",
        # 화면·target 확인: 캡처 + target 파일로 찾기 (`ctx.vision`). 출력은 위치(Match)라 보내는
        # 글자 내용이 되지 않는다
        "core.image.wait",
        "core.image.wait_gone",
        "core.image.click",
    }
)
"""v1 치트 구현에 쓸 수 있는 노드 타입 (허용 목록, 계획 9장 R2 — 검수 B2 3라운드 결정).

이 노드들의 실행 함수는 실행 중 설정(`ctx.setting`)·판단(`ctx.judge` → 사용자 Agent 설정)·외부
프로세스(`ctx.process`)·OCR(`ctx.ocr` — 엔진 설정에 따라 읽은 글자가 달라짐)·환경 변수·파일을 쓰지
않는다(`test_impl_allowlist_nodes_read_no_outside_bytes`가 소스로 검사). 목록 밖 노드
(`core.agent.*`·`core.ocr.*`·`core.app.*`·`core.var.*`·플러그인 등)는 채택·실행 거부
(`impl_node_not_allowed`)."""

COMMAND_INPUT: Final = "command"
"""콘솔 구현 서브그래프가 받는 입력 이름 (템플릿에 인자를 넣은 글자)."""

LOCK_FILE: Final = "kookabug.lock"


@dataclass(frozen=True, slots=True)
class Closure:
    """`files`: 워크스페이스 기준 경로 → 바이트 sha256(없는 파일은 None). `nodes`: 노드 타입 →
    구현 revision(알 수 없으면 None). `problems`: 미해결·동적 의존성(있으면 채택 불가).
    `digest`: 파일·노드를 정규화한 sha256."""

    digest: str
    files: dict[str, str | None] = field(default_factory=dict[str, str | None])
    nodes: dict[str, str | None] = field(default_factory=dict[str, str | None])
    problems: tuple[str, ...] = ()


def read_lock_plugins(root: Path) -> dict[str, Mapping[str, Any]]:
    """`kookabug.lock`의 플러그인 ID → 항목. 없거나 읽지 못하면 빈 표 (그 플러그인 노드는
    미해결)."""
    from kookabug_core.plugins.lockfile import read_lock

    try:
        lock, _ = read_lock(root / LOCK_FILE)
    except Exception:
        return {}
    if not isinstance(lock, Mapping):
        return {}
    return {
        str(p["id"]): p
        for p in lock.get("plugins", ())
        if isinstance(p, Mapping) and isinstance(p.get("id"), str)
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SOURCE_CACHE: dict[str, str | None] = {}


def _source_sha(path: str | None) -> str | None:
    if path is None:
        return None
    if path not in _SOURCE_CACHE:
        try:
            _SOURCE_CACHE[path] = _sha(Path(path).read_bytes())
        except OSError:
            _SOURCE_CACHE[path] = None
    return _SOURCE_CACHE[path]


def node_revision(
    node_type: str, registry: Registry, plugins: Mapping[str, Mapping[str, Any]]
) -> str | None:
    """노드 타입 하나의 구현 revision (모듈 설명). 알 수 없으면 None."""
    plugin = node_type.split(".", 1)[0]
    if plugin != "core":
        entry = plugins.get(plugin)
        if entry is None:
            return None
        body = {
            "plugin": plugin,
            "schema_sha256": entry.get("schema_sha256"),
            "type": node_type,
            "version": entry.get("version"),
            "wheel_sha256": entry.get("wheel_sha256"),
        }
        return _sha(canonical_dumps(body).encode("utf-8"))
    nodedef = registry.get(node_type)
    if nodedef is None or nodedef.function is None:
        return None
    fn = getattr(nodedef.function, "__wrapped__", nodedef.function)
    try:
        source = _source_sha(inspect.getsourcefile(fn))
    except TypeError:
        source = None
    if source is None:
        return None
    import kookabug_nodes

    body = {
        "decl": nodedef.decl,
        "nodes_version": kookabug_nodes.__version__,
        "source": source,
        "type": node_type,
    }
    if nodedef.engine is not None:
        from kookabug_core.engine import executor

        body["engine"] = _source_sha(inspect.getsourcefile(executor))
    return _sha(canonical_dumps(body).encode("utf-8"))


def _has_secret(value: Any) -> bool:
    if isinstance(value, Secret):
        return True
    if isinstance(value, Unresolved):
        return value.tag == "$secret"
    if isinstance(value, Mapping):
        return any(_has_secret(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_secret(v) for v in value)
    return False


def _problems(program: Program, graph: str, files: Mapping[str, str | None]) -> list[str]:
    problems: list[str] = []
    for d in program.diagnostics:
        # 폐포 파일의 진단만 (워크스페이스·이 PC 설정 진단은 구현과 무관하다)
        if d.severity == "error" and d.file in files:
            problems.append(f"{d.code}:{d.file}")
    for rel, sha in files.items():
        if sha is None:
            problems.append(f"missing:{rel}")
    for (caller, node), ref in sorted(program.calls.items()):
        if ref.status != "ok":
            problems.append(f"call_{ref.status}:{caller}#{node}")
    for screen_id, ref in sorted(program.screens.items()):
        if ref.status != "ok":
            problems.append(f"screen_{ref.status}:{screen_id}")
    for key in sorted(program.settings):
        problems.append(f"setting:{key}")
    for g in program.graphs.values():
        for node in g.nodes.values():
            if node.type == QA_CHEAT:
                problems.append(f"nested_cheat:{g.path}#{node.id}")
            if _has_secret(node.inputs):
                problems.append(f"secret:{g.path}#{node.id}")
    impl = program.graphs.get(graph)
    inputs = (impl.interface or {}).get("inputs", {}) if impl is not None else {}
    decl = inputs.get(COMMAND_INPUT) if isinstance(inputs, Mapping) else None
    if (
        impl is None
        or impl.kind != "subgraph"
        or not isinstance(decl, Mapping)
        or decl.get("type") != "string"
        or set(inputs) != {COMMAND_INPUT}
    ):
        problems.append(f"impl_interface:{graph}")
    return problems


def _under_knowledge(workspace: Workspace, rel: str) -> bool:
    """실행 의존성이 `knowledge/` 아래인가: 적힌 경로(대소문자 무시)와 실경로(링크·정션·짧은 이름
    해석) 둘 다 본다."""
    if rel.replace("\\", "/").split("/", 1)[0].casefold() == "knowledge":
        return True
    path = workspace.resolve(rel)
    if path is None:
        return False
    try:
        real = Path(os.path.realpath(path))
        base = Path(os.path.realpath(workspace.root))
        first = real.relative_to(base).parts[0]
    except ValueError, IndexError, OSError:
        return False
    return first.casefold() == "knowledge"


def graph_closure(
    workspace: Workspace,
    graph: str,
    *,
    registry: Registry | None = None,
    plugins: Mapping[str, Mapping[str, Any]] | None = None,
) -> Closure:
    """`graph`와 그것이 참조하는 파일 전체(로더의 `references.discovered` — 서브그래프·target·
    이미지·출구 화면)의 바이트 digest와 노드 구현 revision. 비밀값은 읽지 않는다(빈 공급자).
    설정은 기본값(`RunOptions()`)으로 읽지만 `$setting`을 쓰면 동적 의존성이라 문제로 남는다."""
    registry = registry or default_registry()
    if plugins is None:
        plugins = read_lock_plugins(workspace.root)
    program = load_program(workspace, graph, options=RunOptions(), secrets=MemorySecrets())
    # 지식 메타데이터(로더가 지식 형식으로 읽은 치트 정의·주장 파일)만 뺀다 — 넣으면 채택 기록이
    # digest를 바꾼다. 실행 의존성(그래프·target·이미지·화면)은 위치와 무관하게 넣는다
    refs = program.references
    used = refs.graphs | refs.targets | refs.images | refs.screens
    used |= {c.path for c in program.calls.values() if c.path is not None}
    # 메타데이터 파일이 실행 의존성으로도 쓰이면 폐포에 넣는다 (아래 knowledge 규칙으로 거부)
    metadata = set(program.knowledge) - used
    rels = {graph, *(r for r in refs.discovered if r not in metadata)}
    files: dict[str, str | None] = {}
    for rel in sorted(rels):
        path = workspace.resolve(rel)
        try:
            data = path.read_bytes() if path is not None and path.is_file() else None
        except OSError:
            data = None
        files[rel] = None if data is None else _sha(data)
    types = sorted({n.type for g in program.graphs.values() for n in g.nodes.values()})
    nodes = {t: node_revision(t, registry, plugins) for t in types}
    problems = _problems(program, graph, files)
    problems += [f"node:{t}" for t, rev in nodes.items() if rev is None]
    # 허용 목록 밖 노드는 폐포 밖 바이트(사용자 Agent 설정·OCR 설정·외부 프로세스·플러그인 환경
    # 등)에 기댈 수 있다 — 접두(`core.*`)로 판정하지 않는다
    problems += [f"impl_node_not_allowed:{t}" for t in types if t not in IMPL_NODE_TYPES]
    # Agent가 지식 연산으로 쓸 수 있는 자리(knowledge/)에는 실행 코드를 두지 않는다 (보수 규칙)
    problems += [f"knowledge_dependency:{r}" for r in files if _under_knowledge(workspace, r)]
    body = canonical_dumps({"files": files, "nodes": nodes})
    return Closure(_sha(body.encode("utf-8")), files, nodes, tuple(sorted(set(problems))))


def source_checks(
    source: Workspace, program: Program, *, aliased: frozenset[str] | set[str] = frozenset()
) -> dict[str, tuple[str, ...]]:
    """실행 스냅샷을 만들 때 **원본** 워크스페이스에서 본 치트 구현 폐포의 문제 (치트 ID → 문제).
    스냅샷은 경로를 그대로 복사해 정션·링크로 금지 위치(`knowledge/`)를 가리키던 사실을 잃는다.
    `aliased`: 복사할 때 실경로가 `knowledge/` 아래였던 경로 — 스냅샷 쪽 폐포에 들면 문제다."""
    out: dict[str, tuple[str, ...]] = {}
    snap = program.workspace
    for g in program.graphs.values():
        for node in g.nodes_of_type(QA_CHEAT):
            cheat_id = node.config.get("cheat")
            if not isinstance(cheat_id, str) or cheat_id in out:
                continue
            cheat = program.cheat(cheat_id)
            impl = cheat.get("impl") if cheat is not None else None
            graph = impl.get("graph") if isinstance(impl, Mapping) else None
            if not isinstance(graph, str) or source.resolve(graph) is None:
                continue  # 치트 노드가 정의·구현 없음으로 거부한다
            try:
                problems = set(graph_closure(source, graph).problems)
                copied = graph_closure(snap, graph).files if aliased else {}
                problems |= {f"knowledge_dependency:{r}" for r in copied if r in aliased}
                out[cheat_id] = tuple(sorted(problems))
            except Exception as exc:  # 원본을 읽지 못함: 확인 불가 = 거부
                out[cheat_id] = (f"source_check_error:{type(exc).__name__}",)
    return out


def adoption_digest(
    workspace: Workspace,
    cheat: Mapping[str, Any],
    *,
    registry: Registry | None = None,
    plugins: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str | None, tuple[str, ...]]:
    """그 치트 정의를 지금 워크스페이스(또는 실행 스냅샷)에서 채택한다면의 digest와 문제 목록.
    문제가 있으면 digest는 None (채택·실행 거부). v1 구현은 콘솔 서브그래프만."""
    impl = cheat.get("impl")
    if not isinstance(impl, Mapping) or impl.get("kind") != "console":
        return None, ("impl_unsupported",)
    graph = impl.get("graph")
    if not isinstance(graph, str) or workspace.resolve(graph) is None:
        return None, ("impl_path",)
    closure = graph_closure(workspace, graph, registry=registry, plugins=plugins)
    if closure.problems:
        return None, closure.problems
    revisions = {t: rev for t, rev in closure.nodes.items() if rev is not None}
    return cheat_digest(cheat, closure=closure.digest, nodes=revisions), ()


# ---------------------------------------------------------------- 사람 경로 (daemon·CLI 공통)


def _no_text(texts: Any) -> None:
    """채택 연산은 형식이 정한 ID(치트·분류, 패턴 제한)만 담는다 — 자유 글자가 없다."""


def list_cheats(root: Path) -> dict[str, Any]:
    """`cheats.list`·`kookabug cheat list`: 정의 요약 + 채택 상태(지금 정의·구현과 digest가
    같은가)."""
    from kookabug_core.knowledge import store
    from kookabug_core.knowledge.formats import file_rel

    workspace = Workspace.open(root)
    loaded = store.load(root, file_rel("cheats"), "cheats", None)
    policy = workspace.config.get("cheats")
    policy = policy if isinstance(policy, Mapping) else {}
    categories = [dict(c) for c in policy.get("categories", ()) if isinstance(c, Mapping)]
    known = {c.get("id") for c in categories}
    registry = default_registry()
    plugins = read_lock_plugins(root)
    out = []
    for cheat in loaded.doc.get("cheats", ()):
        adoption = cheat.get("adoption")
        problem: str | None = None
        adopted = False
        digest, problems = adoption_digest(workspace, cheat, registry=registry, plugins=plugins)
        if digest is None:
            problem = "구현에 미해결·동적 의존성: " + ", ".join(problems[:5])
        elif isinstance(adoption, Mapping):
            if adoption.get("category") not in known:
                problem = "채택 분류가 kookabug.json에 없다"
            elif adoption.get("digest") != digest:
                problem = "채택 뒤 정의·구현이 바뀌었다 (다시 채택)"
            else:
                adopted = True
        out.append(
            {
                "id": cheat["id"],
                "rev": cheat["rev"],
                "title": cheat["title"],
                "effect": cheat["effect"],
                "args": cheat.get("args") or {},
                "adoption": adoption,
                "category": adoption.get("category") if isinstance(adoption, Mapping) else None,
                "adopted": adopted,
                "problem": problem,
            }
        )
    return {
        "revision": int(loaded.doc.get("revision", 0)),
        "enabled": policy.get("enabled") is True,
        "categories": categories,
        "cheats": out,
    }


_ID: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _request(op: dict[str, Any]) -> dict[str, Any]:
    """사람 채택 요청. ID·분류는 형식이 정한 패턴만 — 자유 글자가 감사 이력에 가지 않게 먼저
    본다."""
    import uuid

    from kookabug_core.knowledge.formats import KnowledgeError

    for key in ("id", "category"):
        if key in op and not _ID.fullmatch(str(op[key])):
            raise KnowledgeError("format", f"{key}는 영문 소문자·숫자·_ 64자 이내다")
    return {"request_id": f"human-{op['op']}-{uuid.uuid4().hex}", "ops": [op]}


def adopt(root: Path, cheat_id: str, rev: int, category: str, *, by: str) -> dict[str, Any]:
    """사람의 치트 채택: B1 지식 연산(`ops.apply` → `filetx` 한 거래)으로만 쓴다. `by`는 사람 주체
    표시(감사 이력)."""
    from kookabug_core.knowledge import ops
    from kookabug_core.knowledge.formats import Actor

    op = {"op": "adopt", "file": "cheats", "id": cheat_id, "base_rev": rev, "category": category}
    result = ops.apply(root, _request(op), actor=Actor("human", id=by), check_secrets=_no_text)
    return _adoption_result(root, cheat_id, result)


def unadopt(root: Path, cheat_id: str, rev: int, *, by: str) -> dict[str, Any]:
    from kookabug_core.knowledge import ops
    from kookabug_core.knowledge.formats import Actor

    op = {"op": "unadopt", "file": "cheats", "id": cheat_id, "base_rev": rev}
    result = ops.apply(root, _request(op), actor=Actor("human", id=by), check_secrets=_no_text)
    return _adoption_result(root, cheat_id, result)


def _adoption_result(root: Path, cheat_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    from kookabug_core.knowledge import store
    from kookabug_core.knowledge.formats import file_rel

    loaded = store.load(root, file_rel("cheats"), "cheats", None)
    item = next((c for c in loaded.doc.get("cheats", ()) if c.get("id") == cheat_id), {})
    revision = result.get("revisions", {}).get("cheats", loaded.doc.get("revision", 0))
    return {"id": cheat_id, "adoption": item.get("adoption"), "revision": int(revision)}


def set_policy(
    root: Path, *, enabled: bool, categories: list[dict[str, Any]], base_sha256: str
) -> str:
    """`cheats.categories.set`(사람 전용): `kookabug.json`의 `cheats` 블록만 바꾼다. 지금 파일 sha가
    `base_sha256`와 다르면 `revision_conflict`. 같은 `filetx` 거래·지식 잠금으로 쓴다. 새 sha."""
    import json

    from kookabug_core import filetx
    from kookabug_core.knowledge.formats import KnowledgeError, shape_problem
    from kookabug_core.workspace import WORKSPACE_FILE

    try:
        with filetx.locked(root):
            path = root / WORKSPACE_FILE
            data = path.read_bytes()
            if _sha(data) != base_sha256:
                raise KnowledgeError("revision_conflict", "kookabug.json이 그사이 바뀌었다")
            config = json.loads(data.decode("utf-8"))
            config["cheats"] = {"enabled": enabled, "categories": categories}
            problem = shape_problem(config, "workspace")
            if problem is not None:
                raise KnowledgeError("format", f"치트 정책 형식이 틀렸다 ({problem})")
            body = canonical_dumps(config).encode("utf-8")
            tx = filetx.Tx(root)
            tx.write(WORKSPACE_FILE, body, expect_sha=base_sha256)
            tx.commit()
            return _sha(body)
    except filetx.TxError as exc:
        raise KnowledgeError(exc.code, str(exc)) from exc

"""실패 실행 → 사건 시그니처 재료 (M8 계획 3.2 사건, B4).

`cases.open`과 정체 감지(`RunManager` — 같은 작업에서 같은 시그니처 실패 3번)가 같은 함수로 읽는다.
읽는 것은 에이전트용 보기(`AgentRun`)의 안전 필드와 실행 스냅샷의 그래프 바이트 sha뿐이다(입력 값·
글자 없음).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, cast

from kookabug_core.cases import Facts
from kookabug_core.knowledge import sources, store
from kookabug_core.workspace import Workspace
from kookabug_daemon.agent_view import AgentRun

__all__ = [
    "SNAPSHOT_DIR",
    "failed_facts",
    "planned_unchanged",
    "run_facts",
    "run_signature",
    "settings_digest",
    "tree_digest",
]

SNAPSHOT_DIR = "snapshot"


def _graph_sha(folder: Path, graph: Any) -> str | None:
    if not isinstance(graph, str):
        return None
    try:
        data = (folder / SNAPSHOT_DIR / PurePosixPath(graph)).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _snapshot_digest(folder: Path) -> str | None:
    """실행 스냅샷 폐포 전체(경로·바이트)의 digest. 스냅샷이 없으면 None."""
    return tree_digest(folder / SNAPSHOT_DIR)


def tree_digest(base: Path) -> str | None:
    """스냅샷 폴더 하나의 digest (실행 스냅샷과 실행 전 dry 스냅샷이 같은 함수). 없으면 None."""
    if not base.is_dir():
        return None
    digest = hashlib.sha256()
    try:
        files = sorted(p for p in base.rglob("*") if p.is_file())
        for path in files:
            digest.update(path.relative_to(base).as_posix().casefold().encode("utf-8") + b"\n")
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    except OSError:
        return None
    return digest.hexdigest()


def _node_type(folder: Path, graph: Any, node: str | None) -> str | None:
    """실행 스냅샷의 루트 그래프에서 그 노드의 타입 (서브그래프 안 노드·읽기 실패면 None)."""
    if not isinstance(graph, str) or node is None:
        return None
    try:
        value = json.loads((folder / SNAPSHOT_DIR / PurePosixPath(graph)).read_text("utf-8"))
        found = value["nodes"][node]["type"]
    except OSError, ValueError, KeyError, TypeError:
        return None
    return found if isinstance(found, str) else None


def _claims(run_json: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    qa = run_json.get("qa")
    out: list[tuple[str, int]] = []
    if isinstance(qa, Mapping):
        for claim in cast(list[Any], cast(Mapping[str, Any], qa).get("claims") or []):
            if isinstance(claim, Mapping):
                c = cast(Mapping[str, Any], claim)
                if isinstance(c.get("id"), str) and isinstance(c.get("rev"), int):
                    out.append((str(c["id"]), int(c["rev"])))
    return tuple(sorted(out))


def _source_hashes(root: Path, claims: tuple[tuple[str, int], ...]) -> dict[str, str | None]:
    """주장들의 `source` 근거가 가리키는 원본의 지금 해시 (원본 상태 캐시)."""
    ids: set[str] = set()
    for claim_id, _ in claims:
        feature = claim_id.split(".", 1)[0]
        try:
            doc = store.load(root, f"knowledge/features/{feature}.json", "claims", feature).doc
        except Exception:
            continue
        for item in cast(list[Any], doc.get("claims") or []):
            if not isinstance(item, Mapping) or item.get("id") != claim_id:
                continue
            for basis in cast(list[Any], cast(Mapping[str, Any], item).get("basis") or []):
                if isinstance(basis, Mapping) and basis.get("type") == "source":
                    ref = str(cast(Mapping[str, Any], basis).get("ref", ""))
                    if ref.startswith("sources:"):
                        ids.add(ref.removeprefix("sources:").split("#", 1)[0])
    if not ids:
        return {}
    try:
        cache = {str(s.get("id")): s.get("hash") for s in sources.read_cache(Workspace.open(root))}
    except Exception:
        cache = {}
    return {i: cast(str | None, cache.get(i)) for i in sorted(ids)}


def run_facts(root: Path, run_id: str, folder: Path) -> Facts:
    view = AgentRun.load(run_id, folder)
    info = view.run_info()
    run_json = view.run_json
    end = next((e for e in view.events if e.get("event") == "run.end"), None)
    end_info = view.event(end) if end is not None else {}
    step = info.get("failure_step") or end_info.get("failure_step")
    facts = view.steps.get(step) if isinstance(step, str) else None
    conditions = cast(Mapping[str, Any], run_json.get("conditions") or {})
    basis = run_json.get("basis")
    claims = _claims(run_json)
    code = info.get("code") if isinstance(info.get("code"), str) else None
    if facts is not None and facts.error_code:
        code = facts.error_code
    node = facts.node if facts is not None and facts.node else None
    return Facts(
        node_type=_node_type(folder, info.get("graph"), node),
        snapshot=_snapshot_digest(folder),
        run=run_id,
        test=info.get("graph") if isinstance(info.get("graph"), str) else None,
        graph_sha=_graph_sha(folder, info.get("graph")),
        verdict=info.get("verdict") if isinstance(info.get("verdict"), str) else None,
        code=code,
        node=facts.node if facts is not None and facts.node else None,
        profile=conditions.get("profile") if isinstance(conditions.get("profile"), str) else None,
        game_build=run_json.get("game_build")
        if isinstance(run_json.get("game_build"), str)
        else None,
        platform=conditions.get("platform")
        if isinstance(conditions.get("platform"), str)
        else None,
        claims=claims,
        sources=_source_hashes(root, claims),
        basis=str(cast(Mapping[str, Any], basis).get("kind", "team"))
        if isinstance(basis, Mapping)
        else "team",
    )


def failed_facts(root: Path, run_id: str, folder: Path) -> Facts | None:
    """실패·오류로 끝난 실행의 시그니처 재료 (통과·건너뜀·읽을 수 없으면 None)."""
    try:
        facts = run_facts(root, run_id, folder)
    except Exception:
        return None
    if facts.verdict not in ("fail", "error"):
        return None
    return facts


def run_signature(root: Path, run_id: str, folder: Path) -> str | None:
    """실패·오류로 끝난 실행의 시그니처 (통과·건너뜀·읽을 수 없으면 None)."""
    facts = failed_facts(root, run_id, folder)
    return None if facts is None else facts.signature()


def settings_digest(root: Path, settings: Mapping[str, Any], profile: str | None) -> str | None:
    """실행이 쓰는 실효 설정(요청·`local.json`·프로필·워크스페이스 계층을 `$setting` 탐색과 같은
    `Workspace.effective_settings`로 합친 값)의 정규 JSON sha256. 계산하지 못하면 None.

    비밀값이 담길 수 있는 값은 digest 입력으로만 쓴다 — 원문을 돌려주거나 남기지 않는다."""
    from kookabug_core.canonical import canonical_dumps
    from kookabug_core.workspace import RunOptions

    try:
        merged = Workspace.open(root).effective_settings(
            RunOptions(settings=dict(settings), profile=profile)
        )
        text = canonical_dumps(merged)
    except Exception:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def planned_unchanged(
    root: Path,
    graph: str,
    *,
    overlay: Mapping[str, bytes],
    profile: str | None,
    settings: Mapping[str, Any],
    last: Facts,
) -> bool:
    """이번 요청의 실효 시그니처 재료 중 실행 전에 알 수 있는 것(루트 그래프 sha·스냅샷 폐포
    digest — 덧씌움·주장 파일 포함, 프로필, 원본 해시)이 지난 실패(`last`)와 모두 같으면 True.

    폐포는 실행과 같은 스냅샷 함수로 임시 폴더에 dry 스냅샷을 떠서 실행 스냅샷과 같은 digest로
    비교한다(주장 파일도 스냅샷에 들어간다). 무엇이든 계산하지 못하면 False(정체 감지는 편의
    기능 — 거부하지 않는다)."""
    import shutil
    import tempfile

    from kookabug_core.record.snapshot import take_snapshot
    from kookabug_core.workspace import RunOptions

    if profile != last.profile or last.snapshot is None or last.graph_sha is None:
        return False
    folder = Path(tempfile.mkdtemp(prefix="kookabug-stall-"))
    try:
        take_snapshot(
            Workspace.open(root),
            graph,
            folder,
            options=RunOptions(settings=dict(settings), profile=profile),
            overlay=dict(overlay) or None,
        )
        if tree_digest(folder) != last.snapshot:
            return False
        root_graph = (folder / PurePosixPath(graph)).read_bytes()
        if hashlib.sha256(root_graph).hexdigest() != last.graph_sha:
            return False
    except Exception:
        return False
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    # 주장 rev는 그래프 `qa`가 고정하고 주장 파일은 스냅샷에 들어가므로 위 digest가 담는다. 원본
    # 상태 캐시는 스냅샷 밖이라 따로 본다
    try:
        return _source_hashes(root, last.claims) == dict(last.sources)
    except Exception:
        return False

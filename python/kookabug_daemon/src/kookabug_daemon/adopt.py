"""자동 채택 검증 오케스트레이션 (M8 계획 3.8·E5·C5·C6·9장 R1·R10) — 엄격: 사용자 파일 손상·채택
조건 우회.

`adopt.request{case, change}`를 daemon이 순서대로 검사하고 처음 실패한 조건에서 멈춘다. 실패해도
변경은 작업 기준에 남는다(`kept: working`).

1. 정책 (`automation.auto_repair`·범위·프로필·`qa.claims`·`repair.allowed_changes`)
2. 후보 모양 — 코어 `adopt.candidate_problem`
3. 판정 의존성 — 사건 `original`과 원래 실패 실행의 스냅샷 대비 지금 팀 (`adopt.oracle_problem`)
- **manifest 고정 (R1)**: 후보 바이트 digest, 후보를 적용한 의존성 폐포(원래 테스트 + 영향
  테스트마다 dry 스냅샷의 파일 전부 — 그래프·서브그래프·target·공유 PNG·화면·`kookabug.json`),
  관련 주장 rev, 정책 digest, 영향 테스트 목록, 팀 sha. **검증 실행은 그 폐포 바이트 전체를
  덧씌움으로만 돈다** — 검증 중 팀·작업 파일이 바뀌어도 실행이 보는 바이트는 manifest
  그대로이고, 실행의 스냅샷 sha가 manifest와 다르면 그 검증은 무효(`verify_error`)
4. 원래 테스트를 Kookabug가 직접 무인으로 실행 → pass + `qa.claims[].assertions` 전부 실행·통과
5. 음성 대조: 새 locator가 음성 프레임 전부에서 못 찾아야 한다. 음성 프레임 = 화면 지도 이미지 중
   원래 화면이 아닌 것(옛 locator가 찾지 못하는 것) + 이 target에 묶인 `knowledge/evidence/neg-*`
   (출처 필수) + 요청이 준 이 연결의 정지 화면(출처 기록). 1장 이상
6. 영향 테스트(팀에서 후보 경로를 폐포에 담는 다른 테스트) 전부 4와 같은 방식 → pass
7·8. 코어 `adopt.publish_auto`: 채택 잠금 안에서 후보·정책·팀 폐포·주장 rev·누적 상한을 다시
   확인하고 한 거래로 게시
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import os
import posixpath
import re
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from kookabug_core import adopt as rules
from kookabug_core import basis, evidence, filetx
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.record.runfolder import RUN_JSON_FILE, SNAPSHOT_DIR
from kookabug_core.workspace import WORKSPACE_FILE, RunOptions, Workspace
from kookabug_daemon.protocol import RequestFailed

if TYPE_CHECKING:
    from kookabug_daemon.runs import RunManager

__all__ = [
    "Adopter",
    "Negative",
    "RunVerifier",
    "Verifier",
    "VerifyOutcome",
    "snapshot_shas",
    "target_found",
]

log = logging.getLogger(__name__)

BUSY_CODES: Final = frozenset({"run_busy", "recording_active", "input_lease_busy", "shutting_down"})
VERIFY_TIMEOUT_S: Final = 600.0
CACHE_DIR: Final = (".kookabug", "cache", "adopt")


@dataclass(slots=True)
class VerifyOutcome:
    """검증 실행 하나의 결과. `error`는 시작하지 못한 이유(`input_busy`·`verify_error`)."""

    run_id: str | None
    verdict: str | None = None
    code: str | None = None
    qa: Mapping[str, Any] | None = None
    snapshot: dict[str, str] = field(default_factory=dict[str, str])
    error: str | None = None


class Verifier(Protocol):
    def run(
        self,
        graph: str,
        overlay: Mapping[str, bytes],
        *,
        profile: str | None,
        basis: Mapping[str, Any],
    ) -> VerifyOutcome: ...


def snapshot_shas(folder: Path) -> dict[str, str]:
    """실행 폴더 `snapshot/`의 파일 → sha (워크스페이스 기준 경로)."""
    out: dict[str, str] = {}
    base = folder / SNAPSHOT_DIR
    if not base.is_dir():
        return out
    for dirpath, _, filenames in os.walk(base):
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(base).as_posix()
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class RunVerifier:
    """daemon 실행 관리자로 검증 실행을 돌린다 (`RunManager.start_verify` — 공개 RPC 아님)."""

    def __init__(self, manager: RunManager, *, timeout_s: float = VERIFY_TIMEOUT_S) -> None:
        self.manager = manager
        self.timeout_s = timeout_s

    def run(
        self,
        graph: str,
        overlay: Mapping[str, bytes],
        *,
        profile: str | None,
        basis: Mapping[str, Any],
    ) -> VerifyOutcome:
        try:
            run_id = self.manager.start_verify(graph, overlay=overlay, profile=profile, basis=basis)
        except RequestFailed as exc:
            if exc.code in BUSY_CODES:
                return VerifyOutcome(None, error="input_busy")
            return VerifyOutcome(None, error="verify_error", code=exc.code)
        outcome = self.manager.wait_outcome(run_id, self.timeout_s)
        if outcome is None:
            with contextlib.suppress(RequestFailed):
                self.manager.cancel(run_id)
            return VerifyOutcome(run_id, error="verify_error", code="verify_timeout")
        run_json = outcome.run_json or {}
        if not run_json:
            try:
                run_json = json.loads((outcome.run_dir / RUN_JSON_FILE).read_text("utf-8"))
            except OSError, ValueError:
                run_json = {}
        code = run_json.get("code")
        if code in BUSY_CODES or code == "input_lease_busy":
            return VerifyOutcome(run_id, error="input_busy", code=str(code))
        return VerifyOutcome(
            run_id,
            verdict=run_json.get("verdict"),
            code=None if code is None else str(code),
            qa=run_json.get("qa"),
            snapshot=snapshot_shas(outcome.run_dir),
        )


@dataclass(frozen=True, slots=True)
class Negative:
    """음성 대조 프레임 하나: 이름, 픽셀(높이, 너비, 채널), 출처."""

    frame: str
    pixels: Any
    source: str
    note: str | None = None


def target_found(
    root: Path, target_rel: str, value: Mapping[str, Any], template_png: bytes, pixels: Any
) -> bool:
    """그 target 사양·템플릿 바이트로 정지 화면에서 찾나 (편집기 미리보기와 같은 엔진)."""
    from kookabug_daemon.frames import EditorFrame
    from kookabug_daemon.targets import _find  # pyright: ignore[reportPrivateUsage]
    from kookabug_platform.frames import decode_image
    from kookabug_platform.vision import TargetImage
    from kookabug_sdk.types import Target

    template = TargetImage.of_pixels(decode_image(template_png), root / target_rel)
    size = (int(pixels.shape[1]), int(pixels.shape[0]))
    frame = EditorFrame("adopt-negative", pixels, size, 96, "")
    target = Target(name=target_rel, path=root / target_rel, spec=dict(value))
    return bool(_find(frame, target, template).found)


def _decode(png: bytes) -> Any:
    import numpy as np

    from kookabug_platform.frames import decode_image

    return np.asarray(decode_image(png))


# ---------------------------------------------------------------- 팀 파일 읽기


def _walk(root: Path, top: str, suffix: str) -> list[str]:
    base = root / top
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        return []
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d for d in dirnames if not (here / d).is_symlink() and not (here / d).is_junction()
        )
        for name in sorted(filenames):
            if rules.has_suffix(name, suffix) and not (here / name).is_symlink():
                found.append((here / name).relative_to(root).as_posix())
    return found


def _json(root: Path, rel: str) -> Any:
    try:
        data = filetx.read(root, rel)
    except filetx.TxError:
        return None
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None


def _team_files(root: Path) -> dict[str, tuple[Any, str]]:
    """참조를 찾을 팀 JSON: tests·subgraphs의 그래프, screens의 화면 (경로 → (값, 바이트 sha))."""
    out: dict[str, tuple[Any, str]] = {}
    for top, suffix in (("tests", ".json"), ("subgraphs", ".json"), ("screens", ".json")):
        for rel in _walk(root, top, suffix):
            try:
                data = filetx.read(root, rel)
            except filetx.TxError:
                continue
            if data is None:
                continue
            try:
                value = json.loads(data.decode("utf-8"))
            except UnicodeDecodeError, ValueError:
                continue
            out[rel] = (value, hashlib.sha256(data).hexdigest())
    return out


def reference_scan(
    root: Path, target: str, image: str | None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], tuple[str, ...]]:
    """조건 2 참조 스캔: (팀 JSON 값, 팀 target 값, 이 target을 읽는 파일 → sha, 이 PNG를 함께
    쓰는 다른 target). manifest에 고정하고 게시 직전에 다시 계산해 같아야 한다 (R1)."""
    files = _team_files(root)
    values = {rel: value for rel, (value, _) in files.items()}
    targets = _team_targets(root)
    using = {use.file for use in rules.target_uses(values, target)}
    refs = {rel: files[rel][1] for rel in sorted(using)}
    users = tuple(rules.image_users(targets, target, image)) if image is not None else ()
    return values, targets, refs, users


def _spelled_on_disk(root: Path, rel: str) -> bool:
    """`rel`의 있는 조각마다 디스크의 실제 철자와 같은가 (없는 조각은 같은 이름이 없을 때만)."""
    current = root
    for part in rel.split("/"):
        try:
            names = os.listdir(current)
        except OSError:
            return True  # 없는 폴더: 그 아래는 새 경로
        if part in names:
            current = current / part
            continue
        return not any(name.casefold() == part.casefold() for name in names)
    return True


def alias_problem(root: Path, rels: Sequence[str]) -> rules.Problem | None:
    """후보 경로 별칭 (R1·조건 2): 같은 파일을 가리키는 키가 둘 이상이거나, 키 철자가 디스크의 실제
    철자와 다르면 거부한다 (`path_alias`) — 포함·공유·폐포 검사가 한 철자로만 돌게."""
    keys = [rules.path_key(rel) for rel in rels]
    if len(set(keys)) != len(keys):
        return rules.Problem(2, "path_alias", "같은 파일을 가리키는 후보 경로가 둘 이상이다")
    for rel in rels:
        if not _spelled_on_disk(root, rel):
            return rules.Problem(
                2, "path_alias", f"후보 경로 '{rel}'의 철자가 디스크의 실제 철자와 다르다"
            )
    return None


def _in_scope(test: str, scope: str) -> bool:
    """원래 테스트가 자동 수리 범위(경로 앞부분) 안인가 — 둘 다 `rules.path_key` 위에서 본다.
    `/`로 끝나는 범위는 폴더 경계까지만 맞춘다(`tests/shop/`은 `tests/shopping/`을 담지 않는다)."""
    want = rules.path_key(scope)
    if not want:
        return scope == ""
    key = rules.path_key(test)
    if scope.replace("\\", "/").endswith("/"):
        return key.startswith(want + "/")
    return key.startswith(want)


def _team_targets(root: Path) -> dict[str, Any]:
    return {rel: _json(root, rel) for rel in _walk(root, "targets", rules.TARGET_SUFFIX)}


def _run_folder(root: Path, run_id: str) -> Path | None:
    runs = root / "runs"
    if not runs.is_dir():
        return None
    for path in runs.glob(f"*_{run_id}"):
        if path.is_dir() and not path.is_symlink():
            return path
    return None


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _claim_revs(root: Path, ids: Sequence[str]) -> dict[str, int | None]:
    from kookabug_core.knowledge import store
    from kookabug_core.knowledge.formats import file_rel

    out: dict[str, int | None] = {}
    for cid in ids:
        feature = cid.split(".", 1)[0]
        try:
            doc = store.load(root, file_rel(f"features/{feature}"), "claims", feature).doc
        except KnowledgeError, filetx.TxError:
            out[cid] = None
            continue
        out[cid] = next((int(c["rev"]) for c in doc["claims"] if c.get("id") == cid), None)
    return out


@functools.cache
def _core_registry() -> Any:
    from kookabug_core.registry import default_registry

    return default_registry()


def _is_assertion(node_type: str) -> bool:
    """판정 노드인가. 코어 표에 없는 타입(플러그인 등)은 판정으로 본다 — 모르는 노드가 읽는
    파일을 판정 의존성에서 빼지 않게 (안전 쪽, `_is_known`이 거짓이라 자동 채택하지 않는다)."""
    found = _core_registry().get(node_type)
    return found is None or bool(found.assertion)


def _is_known(node_type: str) -> bool:
    return _core_registry().get(node_type) is not None


# ---------------------------------------------------------------- 채택


class Adopter:
    """`adopt.request` 하나를 끝까지 (막히는 호출). `verifier`는 검증 실행, `negatives_of`는 요청이
    준 음성 프레임(이 연결의 정지 화면)."""

    def __init__(
        self,
        root: Path,
        verifier: Verifier,
        *,
        check_secrets: Callable[[Sequence[tuple[str, str]]], None] | None = None,
    ) -> None:
        self.root = root
        self.verifier = verifier
        self.check_secrets = check_secrets
        """채택 기록·감사 이력에 들어갈 글자(요청 메모·경로·ID) 검사기 (daemon이 보호 기록 키로)."""
        self.runs: list[str] = []
        self.manifest: rules.Manifest | None = None
        self.negatives: list[dict[str, Any]] = []
        self.negative_shas: dict[str, str] = {}
        """음성 대조 후보 프레임 → sha (게시 직전 재확인)."""

    # ------------------------------------------------------------ 결과

    def _result(
        self, record: Mapping[str, Any] | None, problem: rules.Problem | None
    ) -> dict[str, Any]:
        return {
            "adopted": record is not None,
            "adoption": None if record is None else record["id"],
            "failed": None if problem is None else problem.to_json(),
            "kept": "working",
            "manifest": None if self.manifest is None else self.manifest.digest,
            "negatives": [str(n["frame"]) for n in self.negatives],
            "runs": list(self.runs),
        }

    # ------------------------------------------------------------ 본체

    def request(
        self, case_id: str, change_id: str, extra: Sequence[Negative] = ()
    ) -> dict[str, Any]:
        root = self.root
        case_doc, _ = rules.load_case(root, case_id)
        change = basis.load_change(root, change_id)
        if change is None:
            raise KnowledgeError("unknown_id", "없는 작업 기준 변경이다", id=change_id)
        if change.state != "active":
            raise KnowledgeError(
                "change_not_active", f"작업 기준 변경은 {change.state}이다", id=change_id
            )
        if change.doc.get("case") not in (None, case_id):
            raise KnowledgeError("format", "작업 기준 변경이 다른 사건에 묶여 있다", id=change_id)
        if self.check_secrets is not None:
            # 요청 메모·프레임 이름은 채택 기록에 들어간다 — 무엇이든 하기 전에 검사한다
            self.check_secrets(
                [(f"negatives/{n}/note", neg.note) for n, neg in enumerate(extra) if neg.note]
                + [(f"negatives/{n}/frame", neg.frame) for n, neg in enumerate(extra)]
            )
        problem, ctx = self._precheck(case_doc, change)
        if problem is not None:
            return self._result(None, problem)
        assert ctx is not None
        try:
            problem = self._verify(ctx, extra)
            if problem is not None:
                return self._result(None, problem)
            assert self.manifest is not None
            try:
                record = rules.publish_auto(
                    root,
                    self.manifest,
                    case_id=case_id,
                    runs=self.runs,
                    negatives=self.negatives,
                    max_adoptions=int(ctx.repair.get("max_adoptions", 20)),
                    check=lambda: self._recheck(ctx),
                    check_secrets=self.check_secrets,
                )
            except rules.AdoptFailed as exc:
                return self._result(None, exc.problem)
            except filetx.TxError as exc:
                if exc.code == "revision_conflict":
                    return self._result(None, rules.Problem(8, "revision_conflict", exc.message))
                return self._result(None, rules.Problem(8, "tx_failed", exc.message))
        finally:
            # 게시 직전 재확인도 dry 스냅샷을 쓰므로 게시가 끝난 뒤에 지운다
            ctx.cleanup()
        return self._result(record, None)

    # ------------------------------------------------------------ 조건 1~3·manifest

    def _precheck(
        self, case_doc: Mapping[str, Any], change: basis.Change
    ) -> tuple[rules.Problem | None, _Context | None]:
        root = self.root
        workspace = Workspace.open(root)
        automation = workspace.automation()
        repair = cast(dict[str, Any], automation["auto_repair"])
        symptom = cast(Mapping[str, Any], case_doc.get("symptom") or {})
        original = cast(Mapping[str, Any], case_doc.get("original") or {})
        test = symptom.get("test")
        if not isinstance(test, str):
            return rules.Problem(1, "out_of_scope", "사건에 원래 테스트 경로가 없다"), None
        folder = _run_folder(root, str(original.get("run")))
        run_json = _json_file(folder / RUN_JSON_FILE) if folder is not None else None
        profile = (run_json or {}).get("conditions", {}).get("profile")
        # 조건 1
        if not repair.get("enabled", True):
            return rules.Problem(1, "policy_off", "자동 수리가 꺼져 있다"), None
        if not any(_in_scope(test, str(s)) for s in repair.get("scope") or []):
            return rules.Problem(1, "out_of_scope", "테스트가 자동 수리 범위 밖이다"), None
        profiles = repair.get("profiles")
        if profiles is not None and profile not in profiles:
            return rules.Problem(1, "out_of_scope", "프로필이 자동 수리 범위 밖이다"), None
        graph_value = _json(root, test)
        qa = graph_value.get("qa") if isinstance(graph_value, dict) else None
        if not isinstance(qa, dict):
            return rules.Problem(1, "no_qa_claims", "테스트에 qa.claims가 없다 (C3)"), None
        qa_map = cast(dict[str, Any], qa)
        claims = cast(list[dict[str, Any]], qa_map.get("claims") or [])
        if not claims:
            return rules.Problem(1, "no_qa_claims", "테스트에 qa.claims가 없다 (C3)"), None
        allowed = cast(dict[str, Any], qa_map.get("repair") or {}).get(
            "allowed_changes", ["locator"]
        )
        if "locator" not in allowed:
            return rules.Problem(1, "out_of_scope", "테스트가 locator 수리를 허용하지 않는다"), None
        # 조건 2
        if basis.effective_state(root, change) != "active":
            return rules.Problem(
                8, "revision_conflict", "팀 기준이 바뀌어 다시 확인 필요 (stale)"
            ), None
        problem = alias_problem(root, [str(entry["path"]) for entry in change.files])
        if problem is not None:
            return problem, None
        changed: dict[str, tuple[bytes | None, bytes]] = {}
        for entry in change.files:
            data = basis.copy_bytes(root, change, entry)
            rel = str(entry["path"])
            if data is None:
                return rules.Problem(8, "revision_conflict", "작업 사본이 기록과 다르다"), None
            try:
                changed[rel] = (filetx.read(root, rel), data)
            except filetx.TxError as exc:
                return rules.Problem(2, exc.code, f"'{rel}'을(를) 읽을 수 없는 경로다"), None
        target = next((r for r in changed if rules.is_target(r)), "")
        after_value = _loads(changed[target][1]) if target else None
        image = rules.image_rel(target, after_value) if target else None
        team_files, team_targets, refs, users = reference_scan(root, target, image)
        problem = rules.candidate_problem(changed, team_files=team_files, team_targets=team_targets)
        if problem is not None:
            return problem, None
        try:
            ctx = _Context(
                root, workspace, test, profile, repair, automation, change, changed, claims
            )
        except filetx.TxError as exc:
            # dry 스냅샷 캐시 경로에 링크·정션 — 바깥 폴더를 만들거나 지우지 않고 멈춘다
            return rules.Problem(1, exc.code, f"검증용 캐시 경로를 쓸 수 없다: {exc.message}"), None
        ctx.target, ctx.image, ctx.refs, ctx.image_users = target, image, refs, users
        try:
            # 조건 3
            team_closure = ctx.closure(test, {})
            graphs = {
                rel: json.loads(data) for rel, data in team_closure.items() if rules.is_graph(rel)
            }
            judged = rules.judgment_inputs(
                graphs,
                test,
                is_assertion=_is_assertion,
                is_known=_is_known,
                targets=team_targets,
            )
            if judged.untraceable is not None:
                ctx.cleanup()
                return rules.Problem(3, "oracle_untraceable", judged.untraceable), None
            if rules.path_key(target) in {rules.path_key(f) for f in judged.files}:
                ctx.cleanup()
                return rules.Problem(
                    2, "target_used_for_judgment", "판정 입력이 $link로 이 target을 거쳐 온다"
                ), None
            deps = judged.files
            by_key = {rules.path_key(rel): data for rel, data in team_closure.items()}
            current = {rel: _sha(by_key.get(rules.path_key(rel))) for rel in deps}
            snap = None if folder is None else folder / SNAPSHOT_DIR
            original_deps = {
                rel: (None if snap is None else _sha(_read(snap / PurePosixPath(rel))))
                for rel in deps
            }
            # 판정이 읽는 설정: 원래 실패 스냅샷의 kookabug.json과 지금 폐포의 것 (manifest에 고정)
            original_config = None if snap is None else _json_file(snap / WORKSPACE_FILE)
            current_config = _loads(by_key.get(rules.path_key(WORKSPACE_FILE)))
            original_settings = {
                key: rules.team_setting(original_config, key, profile) for key in judged.settings
            }
            current_settings = {
                key: rules.team_setting(current_config, key, profile) for key in judged.settings
            }
            claim_refs = [c for c in original.get("claims") or [] if isinstance(c, Mapping)]
            problem = rules.oracle_problem(
                original_graph_sha=cast(str | None, original.get("graph_sha")),
                current_graph_sha=_sha(by_key.get(rules.path_key(test))),
                original_claims=claim_refs,
                current_claims=_claim_revs(root, [str(c.get("id")) for c in claim_refs]),
                original_deps=original_deps,
                current_deps=current,
                original_settings=original_settings,
                current_settings=current_settings,
            )
            if problem is not None:
                ctx.cleanup()
                return problem, None
            self.manifest = ctx.fix_manifest(_team_tests(root))
            # 조건 2 (팀 기준 전체): 원래 테스트 밖 그래프의 `$link` 판정 사용 (폐포 그래프 포함)
            problem = _judged_problem(ctx, team_files, team_targets)
            if problem is not None:
                ctx.cleanup()
                self.manifest = None
                return problem, None
        except Exception:
            ctx.cleanup()
            raise
        return None, ctx

    # ------------------------------------------------------------ 조건 4~6

    def _verify(self, ctx: _Context, extra: Sequence[Negative]) -> rules.Problem | None:
        assert self.manifest is not None
        problem = self._run_test(ctx, ctx.test, condition=4, claims=ctx.claims)
        if problem is not None:
            return problem
        problem = self._negative_control(ctx, extra)
        if problem is not None:
            return problem
        for test in self.manifest.tests[1:]:
            problem = self._run_test(ctx, test, condition=6, claims=())
            if problem is not None:
                return problem
        return None

    def _run_test(
        self, ctx: _Context, test: str, *, condition: int, claims: Sequence[Mapping[str, Any]]
    ) -> rules.Problem | None:
        assert self.manifest is not None
        overlay = ctx.closures[test]
        record = {
            "kind": "working",
            "working": [{"id": ctx.change.id, "files": dict(self.manifest.candidate)}],
            "stale": [],
            "knowledge": basis.knowledge_revisions(self.root),
            "adopt": self.manifest.digest,
        }
        out = self.verifier.run(test, overlay, profile=ctx.profile, basis=record)
        if out.run_id is not None:
            self.runs.append(out.run_id)
        if out.error == "input_busy":
            return rules.Problem(
                4, "input_busy", "입력 임대권·녹화·다른 실행 중이라 검증하지 못했다"
            )
        if out.error is not None:
            return rules.Problem(condition, "verify_error", f"검증 실행 오류 ({out.code})")
        want = {rel: hashlib.sha256(data).hexdigest() for rel, data in overlay.items()}
        if out.snapshot != want:
            return rules.Problem(
                condition, "verify_error", "검증 실행의 스냅샷이 manifest와 다르다 (무효)"
            )
        if condition == 6:
            if out.verdict != "pass":
                return rules.Problem(
                    6, "affected_failed", f"영향 테스트 {test}이(가) 통과하지 못했다"
                )
            return None
        executed = _qa_lists(out.qa, "executed")
        passed = _qa_lists(out.qa, "passed")
        for claim in claims:
            need = [str(n) for n in claim.get("assertions") or []]
            cid = str(claim.get("id"))
            if not need or not set(need) <= executed.get(cid, set()):
                return rules.Problem(
                    4, "oracle_not_run", f"주장 {cid}의 검증 노드가 실행되지 않았다"
                )
            if not set(need) <= passed.get(cid, set()):
                return rules.Problem(
                    4, "oracle_failed", f"주장 {cid}의 검증 노드가 통과하지 못했다"
                )
        if out.verdict != "pass":
            return rules.Problem(
                4, "oracle_failed", f"원래 테스트가 통과하지 못했다 ({out.verdict})"
            )
        return None

    def _negative_control(self, ctx: _Context, extra: Sequence[Negative]) -> rules.Problem | None:
        target = ctx.target
        after = json.loads(ctx.changed[target][1])
        before_raw = ctx.changed[target][0]
        before = json.loads(before_raw) if before_raw is not None else None
        image_after = rules.image_rel(target, after)
        by_key = {rules.path_key(rel): data for rel, (_, data) in ctx.changed.items()}
        template = (
            by_key[rules.path_key(image_after)]
            if image_after is not None and rules.path_key(image_after) in by_key
            else filetx.read(self.root, image_after or "")
        )
        if template is None:
            return rules.Problem(5, "no_negative_control", "새 locator 이미지를 읽을 수 없다")
        old_template = (
            None
            if before is None
            else filetx.read(self.root, rules.image_rel(target, before) or "")
        )
        frames: list[Negative] = []
        inputs, ignored = negative_scan(self.root, target)
        # 게시 직전에 같은 목록·바이트인지 다시 본다 (검증 중 생긴·바뀐 음성 프레임)
        self.negative_shas = {name: _sha(data) or "" for name, data, _ in inputs}
        if ignored:
            # 이 target에 묶였지만 쓰지 못한 묶음·프레임(정규형 아님·목록에 없음·읽기 실패·sha
            # 다름)이 있으면 그 음성 대조를 빼고 채택하지 않는다 (사람이 고쳐야 한다)
            return rules.Problem(
                5,
                "no_negative_control",
                f"이 target의 음성 대조 묶음을 쓸 수 없다 ({'; '.join(ignored)})",
            )
        try:
            for name, data, source in inputs:
                pixels = _decode(data)
                # 원래 화면(옛 locator가 찾는 화면 지도 이미지)은 음성 프레임이 아니다
                if (
                    source == "screens"
                    and before is not None
                    and old_template is not None
                    and target_found(self.root, target, before, old_template, pixels)
                ):
                    continue
                frames.append(Negative(name, pixels, source))
            frames += list(extra)
            if not frames:
                return rules.Problem(
                    5, "no_negative_control", "음성 대조 프레임이 하나도 없다 (C6)"
                )
            for neg in frames:
                self.negatives.append(
                    {"frame": neg.frame, "source": neg.source}
                    | ({"note": neg.note} if neg.note else {})
                )
                if target_found(self.root, target, after, template, neg.pixels):
                    return rules.Problem(
                        5,
                        "negative_matched",
                        f"새 locator가 음성 프레임 '{neg.frame}'에서 찾아진다",
                    )
        except RequestFailed as exc:
            return rules.Problem(5, "verify_error", f"음성 대조를 하지 못했다 ({exc.code})")
        return None

    # ------------------------------------------------------------ 게시 직전 재확인 (R1)

    def _recheck(self, ctx: _Context) -> rules.Problem | None:
        assert self.manifest is not None
        workspace = Workspace.open(self.root)
        if rules.policy_sha(workspace.automation()) != self.manifest.policy_sha:
            return rules.Problem(8, "revision_conflict", "자동화 정책이 검증 뒤 바뀌었다")
        for rel, sha in sorted(self.manifest.team.items()):
            if basis.team_sha(self.root, rel) != sha:
                return rules.Problem(
                    8, "revision_conflict", f"판정 의존성 '{rel}'이(가) 검증 뒤 바뀌었다"
                )
        if _claim_revs(self.root, list(self.manifest.claims)) != dict(self.manifest.claims):
            return rules.Problem(8, "revision_conflict", "주장 rev가 검증 뒤 바뀌었다")
        now_inputs, now_ignored = negative_scan(self.root, ctx.target)
        now_negatives = {name: _sha(data) or "" for name, data, _ in now_inputs}
        if now_negatives != self.negative_shas or now_ignored:
            return rules.Problem(8, "revision_conflict", "음성 대조 프레임이 검증 뒤 바뀌었다")
        # 조건 2·6의 판정 참조 집합을 지금 팀으로 다시 계산한다 (새로 생긴·지운·바뀐 참조, 새 영향
        # 테스트). 다르면 다시 요청해야 한다 — 검증 중 생긴 테스트를 여기서 더 돌리지 않는다
        values, targets, refs, users = reference_scan(self.root, ctx.target, ctx.image)
        if refs != dict(self.manifest.refs) or users != tuple(self.manifest.image_users):
            return rules.Problem(
                8, "revision_conflict", "이 target·PNG를 읽는 팀 파일 목록이 검증 뒤 바뀌었다"
            )
        # 요청 시작과 같은 판정 함수로 지금 팀 그래프의 `$link` 판정 사용을 다시 본다
        problem = _judged_problem(ctx, values, targets)
        if problem is not None:
            return problem
        try:
            affected = ctx.affected(_team_tests(self.root))
        except (KnowledgeError, filetx.TxError) as exc:
            return rules.Problem(
                8, "revision_conflict", f"영향 테스트를 다시 계산하지 못했다 ({exc.code})"
            )
        if affected != list(self.manifest.tests[1:]):
            return rules.Problem(8, "revision_conflict", "영향 테스트 목록이 검증 뒤 바뀌었다")
        return None


def _judged_problem(
    ctx: _Context, team_files: Mapping[str, Any], team_targets: Mapping[str, Any]
) -> rules.Problem | None:
    """조건 2의 `$link` 판정 사용 검사 (`rules.judged_use_problem`): 팀 tests·subgraphs 그래프와
    원래·영향 테스트 폐포의 그래프(스냅샷 바이트 — 다른 폴더의 서브그래프도) 전부."""
    graphs: dict[str, Any] = {}
    for closure in ctx.closures.values():
        for rel, data in closure.items():
            if rules.is_graph(rel):
                graphs[rel] = _loads(data)
    graphs.update({rel: v for rel, v in team_files.items() if rules.is_graph(rel)})
    return rules.judged_use_problem(
        graphs,
        ctx.target,
        is_assertion=_is_assertion,
        is_known=_is_known,
        targets=team_targets,
    )


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _loads(data: bytes | None) -> dict[str, Any] | None:
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _json_file(path: Path) -> dict[str, Any] | None:
    return _loads(_read(path))


def _qa_lists(qa: Mapping[str, Any] | None, key: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for claim in (qa or {}).get("claims") or []:
        if isinstance(claim, Mapping):
            out[str(claim.get("id"))] = {str(n) for n in claim.get(key) or []}
    return out


def _team_tests(root: Path) -> list[str]:
    return [rel for rel in _walk(root, "tests", rules.GRAPH_SUFFIX)]


def negative_inputs(root: Path, target_rel: str) -> list[tuple[str, bytes, str]]:
    """음성 대조 후보 프레임 (이름, PNG 바이트, 출처): 화면 지도 이미지 `screens/*.png` 전부(원래
    화면은 부르는 쪽이 뺀다) + 이 target에 묶인 증거 묶음 프레임."""
    return negative_scan(root, target_rel)[0]


def negative_scan(root: Path, target_rel: str) -> tuple[list[tuple[str, bytes, str]], list[str]]:
    """`negative_inputs`와 이 target에 묶였지만 쓰지 못한 묶음·프레임 (`_bound_negatives`)."""
    out: list[tuple[str, bytes, str]] = []
    for rel in _walk(root, "screens", rules.PNG_SUFFIX):
        try:
            data = filetx.read(root, rel)
        except filetx.TxError:
            continue
        if data is not None:
            out.append((rel, data, "screens"))
    bound, ignored = _bound_negatives(root, target_rel)
    return out + bound, ignored


def _bound_negatives(root: Path, target_rel: str) -> tuple[list[tuple[str, bytes, str]], list[str]]:
    """이 target에 묶인 음성 대조 증거 묶음 `knowledge/evidence/neg-*` (출처 필수, R10)의 프레임과,
    이 target에 묶였지만 쓰지 못한 묶음·프레임(`"<묶음>[/<프레임>]: <이유>"` — `load_manifest`가
    정규형이 아니라 뺀 묶음, 목록에 없거나 읽을 수 없거나 sha가 다른 프레임). 묶음 target·후보
    target, 프레임 이름·`files[].path`는 모두 `rules.path_key`로 비교한다."""
    out: list[tuple[str, bytes, str]] = []
    ignored: list[str] = []
    base = root / evidence.EVIDENCE_DIR
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        return out, ignored
    key = rules.path_key(target_rel)
    for folder in sorted(base.glob("neg-*")):
        manifest = evidence.load_manifest(root, folder.name)
        if manifest is None or not manifest.get("origin"):
            continue
        skipped = manifest.get(evidence.NEGATIVE_IGNORED)
        if isinstance(skipped, Mapping):
            # 적힌 target을 `.`·`..`·빈 조각까지 풀어 이 target이면 알린다 (쓰지는 않는다)
            named = cast(Mapping[str, Any], skipped).get("targets") or []
            if any(rules.path_key(posixpath.normpath(str(t))) == key for t in named):
                ignored.append(f"{folder.name}: {cast(Mapping[str, Any], skipped).get('reason')}")
            continue
        negative = manifest.get("negative")
        if not isinstance(negative, Mapping):
            continue
        targets = {
            rules.path_key(str(t)) for t in cast(Mapping[str, Any], negative).get("targets") or []
        }
        if key not in targets:
            continue
        listed = {
            rules.path_key(str(f.get("path"))): f.get("sha256") for f in manifest.get("files") or []
        }
        for name in cast(Mapping[str, Any], negative).get("frames") or []:
            # 이 target의 음성 프레임을 조용히 빼지 않는다: 읽을 수 없거나 묶음 목록의 sha와
            # 다르면 쓰지 않고 알린다 (부르는 쪽이 조건 5로 거부 — 바이트·sha 값은 남기지 않는다)
            want = listed.get(rules.path_key(str(name)))
            try:
                data = filetx.read(root, f"{evidence.EVIDENCE_DIR}/{folder.name}/{name}")
            except filetx.TxError:
                data = None
            if want is None:
                ignored.append(f"{folder.name}/{name}: 묶음 파일 목록에 없는 프레임이다")
            elif data is None:
                ignored.append(f"{folder.name}/{name}: 프레임을 읽을 수 없다")
            elif _sha(data) != want:
                ignored.append(f"{folder.name}/{name}: 프레임 바이트가 묶음 sha와 다르다")
            else:
                out.append((f"{folder.name}/{name}", data, f"evidence:{folder.name}"))
    return out, ignored


SCRATCH_KEEP_S: Final = 24 * 3600.0
SCRATCH_NAME: Final = re.compile(r"^[0-9a-f]{32}$")
SCRATCH_OWNER: Final = ".kookabug-adopt-scratch"
"""서비스가 만든 dry 스냅샷 폴더의 소유 표시 파일 (내용 `_owner_text(이름)`)."""


def _owner_text(name: str) -> bytes:
    return f"kookabug.adopt-scratch/0 {name}\n".encode()


def _scratch_rel(*parts: str) -> str:
    return "/".join((*CACHE_DIR, *parts))


def _scratch_base(root: Path) -> Path:
    """`.kookabug/cache/adopt` (B1 filetx 쓰기 경계 — 조상까지 링크·정션이 아니고 실경로가
    워크스페이스 안). 만든 뒤 다시 확인한다. 경계 밖이면 `TxError(path_outside_workspace)`."""
    base = filetx.plain(root, _scratch_rel())
    base.mkdir(parents=True, exist_ok=True)
    return filetx.plain(root, _scratch_rel())


def _owned_scratch(root: Path, name: str) -> Path | None:
    """서비스가 만든 dry 스냅샷 폴더면 그 경로: 이름이 UUID 형식이고, 경계 안이고, 소유 표시
    파일(일반 파일)의 내용이 맞다. 아니면 None (건드리지 않는다)."""
    if not SCRATCH_NAME.fullmatch(name):
        return None
    try:
        folder = filetx.plain(root, _scratch_rel(name))
        marker = filetx.plain(root, _scratch_rel(name, SCRATCH_OWNER))
    except filetx.TxError:
        return None
    try:
        if not folder.is_dir() or not marker.is_file():
            return None
        if marker.read_bytes() != _owner_text(name):
            return None
    except OSError:
        return None
    return folder


def _remove_scratch(root: Path, name: str) -> None:
    folder = _owned_scratch(root, name)
    if folder is not None:
        # rmtree는 안의 링크·정션을 따라가지 않고 링크만 지운다 (Windows 3.8+)
        shutil.rmtree(folder, ignore_errors=True)


def _prune_scratch(root: Path, base: Path) -> None:
    """중단된 요청이 남긴 dry 스냅샷 폴더 중 서비스가 만든 것만 하루 지나면 지운다."""
    now = time.time()
    for child in base.iterdir():
        try:
            if _owned_scratch(root, child.name) is None:
                continue
            if now - child.stat().st_mtime > SCRATCH_KEEP_S:
                _remove_scratch(root, child.name)
        except OSError:
            continue


class _Context:
    """요청 하나의 검사 재료와 dry 스냅샷(임시 폴더 `.kookabug/cache/adopt/<UUID>/`, 소유 표시
    파일). 캐시 경로가 쓰기 경계 밖이면 만들 때 `TxError`."""

    def __init__(
        self,
        root: Path,
        workspace: Workspace,
        test: str,
        profile: str | None,
        repair: Mapping[str, Any],
        automation: Mapping[str, Any],
        change: basis.Change,
        changed: Mapping[str, tuple[bytes | None, bytes]],
        claims: Sequence[Mapping[str, Any]],
    ) -> None:
        self.root = root
        self.workspace = workspace
        self.test = test
        self.profile = profile
        self.repair = repair
        self.automation = automation
        self.change = change
        self.changed = changed
        self.claims = claims
        self.closures: dict[str, dict[str, bytes]] = {}
        self.absent: set[str] = set()
        self.target = ""
        self.image: str | None = None
        self.refs: dict[str, str] = {}
        self.image_users: tuple[str, ...] = ()
        base = _scratch_base(root)
        _prune_scratch(root, base)
        self.name = uuid.uuid4().hex
        self.scratch = filetx.plain(root, _scratch_rel(self.name))
        self.scratch.mkdir(exist_ok=False)
        filetx.plain(root, _scratch_rel(self.name, SCRATCH_OWNER)).write_bytes(
            _owner_text(self.name)
        )

    def cleanup(self) -> None:
        _remove_scratch(self.root, self.name)

    def closure(self, graph: str, overlay: Mapping[str, bytes]) -> dict[str, bytes]:
        """dry 스냅샷의 파일 전부 (경로 → 바이트). 실행과 같은 스냅샷 함수로 폐포를 정한다."""
        from kookabug_core.record.snapshot import SnapshotError, take_snapshot

        part = uuid.uuid4().hex[:8]
        # 쓰기 전마다 경계를 다시 본다 (요청 도중 캐시 조상이 정션으로 바뀐 경우)
        dest = filetx.plain(self.root, _scratch_rel(self.name, part))
        try:
            snap = take_snapshot(
                self.workspace,
                graph,
                dest,
                options=RunOptions(profile=self.profile),
                overlay=overlay,
            )
        except SnapshotError as exc:
            raise KnowledgeError(
                "verify_error", f"의존성 폐포를 정하지 못했다 ({exc.code})"
            ) from exc
        # 참조했지만 원본에 없던 경로도 기억한다 (그 뒤 생기면 동작이 달라진다)
        self.absent |= set(snap.absent)
        out: dict[str, bytes] = {}
        for dirpath, dirnames, filenames in os.walk(dest):
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not (here / d).is_junction()]
            for name in filenames:
                path = here / name
                if path.is_symlink():
                    continue
                out[path.relative_to(dest).as_posix()] = path.read_bytes()
        with contextlib.suppress(filetx.TxError):
            shutil.rmtree(filetx.plain(self.root, _scratch_rel(self.name, part)))
        return out

    def affected(self, tests: Sequence[str]) -> list[str]:
        """영향 테스트: 원래 테스트 밖에서 팀 폐포가 후보 경로를 담는 테스트 (정규화 키 비교)."""
        keys = {rules.path_key(rel) for rel in self.changed}
        out: list[str] = []
        for test in tests:
            if rules.path_key(test) == rules.path_key(self.test):
                continue
            team = self.closure(test, {})
            if keys & {rules.path_key(rel) for rel in team}:
                out.append(test)
        return out

    def fix_manifest(self, tests: Sequence[str]) -> rules.Manifest:
        """R1 manifest: 원래 테스트와 영향 테스트의 후보 적용 폐포, 조건 2 참조 스캔(이 target을
        읽는 파일과 sha·PNG를 함께 쓰는 target), 영향 테스트 목록을 고정한다."""
        candidate = {rel: data for rel, (_, data) in self.changed.items()}
        keys = {rules.path_key(rel) for rel in candidate}
        ordered = [self.test, *self.affected(tests)]
        team_shas: dict[str, str | None] = {}
        self.absent = set()
        for test in ordered:
            closure = self.closure(test, candidate)
            self.closures[test] = closure
            for rel, data in closure.items():
                if rules.path_key(rel) not in keys:
                    # 검증이 실제로 쓰는 바이트의 sha (팀 파일을 다시 읽지 않는다 — 폐포를 만든 뒤
                    # 바뀐 팀 파일도 게시 직전 재확인에서 잡히게)
                    team_shas[rel] = hashlib.sha256(data).hexdigest()
        for rel in self.absent:
            if rules.path_key(rel) not in keys:
                team_shas.setdefault(rel, None)
        claim_ids = sorted({str(c.get("id")) for c in self.claims})
        body = {
            "change": self.change.id,
            "candidate": {
                rel: hashlib.sha256(d).hexdigest() for rel, d in sorted(candidate.items())
            },
            "base": {rel: _sha(before) for rel, (before, _) in sorted(self.changed.items())},
            "team": dict(sorted(team_shas.items())),
            "closures": {
                t: {rel: hashlib.sha256(d).hexdigest() for rel, d in sorted(c.items())}
                for t, c in self.closures.items()
            },
            "claims": _claim_revs(self.root, claim_ids),
            "policy_sha": rules.policy_sha(self.automation),
            "tests": ordered,
            "refs": dict(sorted(self.refs.items())),
            "image_users": list(self.image_users),
        }
        digest = hashlib.sha256(canonical_dumps(body).encode("utf-8")).hexdigest()
        return rules.Manifest(
            digest=digest,
            change=self.change.id,
            candidate=body["candidate"],
            base=body["base"],
            team=body["team"],
            claims=body["claims"],
            policy_sha=body["policy_sha"],
            tests=tuple(ordered),
            refs=dict(self.refs),
            image_users=tuple(self.image_users),
        )


def request_negatives(frames: Sequence[tuple[str, Any, str, str]]) -> list[Negative]:
    """요청의 `negatives[{frame_id, note}]`를 이미 고른 정지 화면 픽셀로 (메서드 층이 연결 소유를
    확인한 뒤 부른다)."""
    return [Negative(f"frame:{fid}", pixels, source, note) for fid, pixels, source, note in frames]


# ---------------------------------------------------------------- 증거 묶음 고정 (3.2·C9)

EVENT_WINDOW: Final = 20
"""실패 스텝 앞뒤로 담는 이벤트 수."""


def _safe_event(view: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    """에이전트용으로 가린 이벤트에서 다시 안전 필드만 (입력 값·글자·OCR·사유 없음)."""
    from kookabug_daemon.agent_view import SAFE_EVENT_FIELDS

    masked = view.event(raw)
    out = {k: v for k, v in masked.items() if k in SAFE_EVENT_FIELDS}
    error = masked.get("error")
    if isinstance(error, Mapping) and "code" in error:
        out["error"] = {"code": cast(Mapping[str, Any], error)["code"]}
    return out


def secret_keys_of(folder: Path) -> set[str]:
    """실행 스냅샷 그래프가 참조한 `$secret` 키 (글자 검사 대상)."""
    keys: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            mapping = cast(Mapping[str, Any], value)
            if set(mapping) == {"$secret"} and isinstance(mapping["$secret"], str):
                keys.add(mapping["$secret"])
                return
            for v in mapping.values():
                walk(v)
        elif isinstance(value, list):
            for v in cast(list[Any], value):
                walk(v)

    base = folder / SNAPSHOT_DIR
    for path in base.rglob("*.json") if base.is_dir() else ():
        value = _json_file(path)
        if value is not None:
            walk(value)
    return keys


def pin_run(
    root: Path,
    folder: Path,
    run_id: str,
    *,
    step: str | None,
    note: str | None,
    by: Mapping[str, Any],
    actor: Any,
    check_secrets: Any,
    guard_of: Callable[[Any], str],
    bundle_id: str | None = None,
) -> dict[str, Any]:
    """실행 기록 → 최소 증거 묶음 (`evidence.pin`, 사건 열기의 원래 실패 자동 고정). 이벤트는
    에이전트용 가림 뒤 안전 필드만, 이미지는 그 스텝의 증거 중 에이전트용 분류를 지나고 보호 판정
    (`guard_of(픽셀)`)이 `clear`인 것만 480px 사본. 나머지는 `omitted`."""
    from kookabug_core.knowledge.formats import new_id
    from kookabug_daemon.agent_view import AgentRun

    view = AgentRun.load(run_id, folder)
    info = view.run_info()
    end = next((e for e in view.events if e.get("event") == "run.end"), None)
    end_info = view.event(end) if end is not None else {}
    chosen = step or info.get("failure_step") or end_info.get("failure_step")
    if step is not None and step not in view.steps:
        raise KnowledgeError("unknown_id", "그 실행에 없는 스텝이다", id=step)
    chain: set[str] = set()
    current = chosen if isinstance(chosen, str) else None
    while current is not None and current in view.steps:
        chain.add(current)
        current = view.steps[current].parent
    hits = [i for i, e in enumerate(view.events) if e.get("step") in chain]
    if hits:
        lo, hi = max(0, hits[0] - EVENT_WINDOW), min(len(view.events), hits[-1] + EVENT_WINDOW + 1)
    else:
        lo, hi = max(0, len(view.events) - 2 * EVENT_WINDOW), len(view.events)
    events = [_safe_event(view, e) for e in view.events[lo:hi]]
    conditions = cast(Mapping[str, Any], view.run_json.get("conditions") or {})
    settings = cast(Mapping[str, Any], conditions.get("settings") or {})
    summary = {
        "verdict": info.get("verdict"),
        "code": info.get("code"),
        "graph": info.get("graph"),
        "started_at": info.get("started_at"),
        "ended_at": info.get("ended_at"),
        "conditions": {
            "profile": conditions.get("profile"),
            "platform": conditions.get("platform"),
            "settings": {
                key: {"secret": bool(isinstance(use, Mapping) and use.get("secret"))}
                for key, use in sorted(settings.items())
            },
        },
        "game_build": info.get("game_build"),
    }
    images: list[evidence.Image] = []
    omitted_early: list[dict[str, str]] = []  # build가 마지막 글자 검사까지 거친다
    facts = view.steps.get(chosen) if isinstance(chosen, str) else None
    for rel in [] if facts is None else facts.files:
        name = PurePosixPath(rel).name
        if not rules.is_png(name):
            continue
        refused = view.refusal(rel)
        if refused is not None:
            omitted_early.append({"what": name, "reason": refused.code})
            continue
        data = _read(folder / PurePosixPath(rel))
        if data is None:
            continue
        try:
            state = guard_of(_decode(data))
        except Exception:
            state = "guard_error"
        images.append(evidence.Image(name, data, state))
    failed = None
    if facts is not None:
        failed = {"step": facts.step, "node": facts.node or None, "code": facts.error_code}
    graph = info.get("graph")
    graph_sha = (
        _sha(_read(folder / SNAPSHOT_DIR / PurePosixPath(str(graph))))
        if isinstance(graph, str)
        else None
    )
    run_basis = view.run_json.get("basis")
    extra: dict[str, Any] = {
        "verdict": info.get("verdict")
        if info.get("verdict") in ("pass", "fail", "error", "skip")
        else None,
        "failed_step": failed,
        "basis": {"kind": cast(Mapping[str, Any], run_basis).get("kind", "team")}
        if isinstance(run_basis, Mapping)
        else {"kind": "team"},
        "graph_sha": graph_sha,
        "env": {
            "profile": conditions.get("profile"),
            "game_build": info.get("game_build")
            if isinstance(info.get("game_build"), str)
            else None,
            "platform": conditions.get("platform"),
        },
    }
    bundle = evidence.build(
        bundle_id=bundle_id or new_id("e"),
        run_id=run_id,
        by=by,
        check_secrets=check_secrets,
        run_summary=summary,
        events=events,
        images=images,
        note=note,
        extra=extra,
        omitted=omitted_early,
    )
    written = evidence.publish(root, bundle, actor=actor, check_secrets=check_secrets)
    return {
        "id": bundle.manifest["id"],
        "files": [w.rsplit("/", 1)[1] for w in written],
        "omitted": bundle.manifest["omitted"],
    }

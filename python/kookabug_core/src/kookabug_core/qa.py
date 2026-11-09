"""그래프 최상위 `qa`(`kookabug.qa/0`)와 치트 허용 판정 (M8 계획 3.5·9장 R2, KB문서 10장).

- `qa.claims`: 이 테스트가 검증하는 주장 revision과 검증 노드. 실행이 끝나면 `run.json.qa.claims`에
  그 노드가 실제로 실행(`executed`)·통과(`passed`)했는지 남긴다 (자동 채택 조건 4의 근거)
- 설정 오류(`qa_invalid` 진단 → 판정 `error`/`qa_config`): 주장·rev 없음, `assertions`가 루트
  그래프의 검증 노드가 아님, 치트 ID 없음, 치트 구현이 없음. skip으로 묻지 않는다
- `qa.profiles`가 이번 프로필을 담지 않으면 미적용(판정 `skipped`/`qa_not_applicable`)

치트 노드(`core.qa.cheat`)의 실행 허용 = 다음 전부의 교집합(`CheatGate`):
워크스페이스 `cheats.enabled` ∩ 채택됨(분류가 있고 digest가 실행 스냅샷에서 다시 계산한 값과 같음)
∩ (무인 실행이면 분류 `unattended`) ∩ 루트 테스트 `qa.cheats.allow` 범위 ∩ 호출 사슬의 각
서브그래프 `qa.cheats.allow`(있으면 — 줄이기만) ∩ `max_calls`(루트 실행 전체에서 센다) ∩ 정의 `env`
프로필. 거부 코드: 채택·digest 문제는 `cheat_not_adopted`, 나머지는 `cheat_denied`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from kookabug_core.canonical import canonical_dumps
from kookabug_core.loader import CHEATS_FILE, Program

__all__ = [
    "CHEAT_DENIED",
    "CHEAT_NOT_ADOPTED",
    "QA_CONFIG",
    "QA_INVALID",
    "QA_NOT_APPLICABLE",
    "CheatDenied",
    "CheatGate",
    "QaTrace",
    "find_claim",
    "not_applicable",
    "render_command",
    "run_qa",
]

QA_INVALID: Final = "qa_invalid"
QA_CONFIG: Final = "qa_config"
QA_NOT_APPLICABLE: Final = "qa_not_applicable"
CHEAT_DENIED: Final = "cheat_denied"
CHEAT_NOT_ADOPTED: Final = "cheat_not_adopted"

_ID_VALUE: Final = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_INT_VALUE: Final = re.compile(r"-?[0-9]{1,19}")
_PLACEHOLDER: Final = re.compile(r"\{([a-z][a-z0-9_]{0,31})\}")


class CheatDenied(Exception):
    """치트 노드 거부 (`code` = `cheat_denied`·`cheat_not_adopted`). 메시지에 인자 값을 넣지
    않는다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- qa 해석


def find_claim(program: Program, claim_id: str, rev: int) -> bool:
    """그 주장 revision이 실행 스냅샷의 지식 파일(지금 또는 옛 rev)에 있나."""
    feature = claim_id.split(".", 1)[0]
    doc = program.knowledge.get(f"knowledge/features/{feature}.json")
    if not isinstance(doc, Mapping):
        return False
    for item in [*doc.get("claims", ()), *doc.get("history", ())]:
        if isinstance(item, Mapping) and item.get("id") == claim_id and item.get("rev") == rev:
            return True
    return False


def not_applicable(qa: Mapping[str, Any] | None, profile: str | None) -> str | None:
    """`qa.profiles`가 이번 프로필을 담지 않으면 그 까닭 (아니면 None)."""
    if qa is None or "profiles" not in qa:
        return None
    profiles = [str(p) for p in qa.get("profiles", ())]
    if profile in profiles:
        return None
    shown = profile if profile is not None else "(기본)"
    return f"이 테스트의 qa.profiles({', '.join(profiles)})에 이번 프로필 {shown}이(가) 없다"


@dataclass
class QaTrace:
    """실행이 모은 qa 사실: 루트 그래프에서 실행·통과한 노드, 쓴 치트 (`run.json.qa`)."""

    executed: set[str] = field(default_factory=set[str])
    passed: set[str] = field(default_factory=set[str])
    cheats: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    """치트 ID → `{cheat, rev, digest, calls}`."""


def run_qa(
    program: Program,
    trace: QaTrace | None,
    *,
    config_errors: Sequence[str] = (),
    not_applicable_reason: str | None = None,
) -> dict[str, Any] | None:
    """`run.json.qa`. 루트에 `qa`가 없고 치트도 안 썼으면 None."""
    qa = program.qa
    used = list(trace.cheats.values()) if trace is not None else []
    if qa is None and not used and not config_errors:
        return None
    executed = trace.executed if trace is not None else set[str]()
    passed = trace.passed if trace is not None else set[str]()
    claims = []
    for claim in (qa or {}).get("claims", ()):
        nodes = [str(n) for n in claim.get("assertions", ())]
        claims.append(
            {
                "id": str(claim.get("id")),
                "rev": int(claim.get("rev", 1)),
                "assertions": nodes,
                "executed": [n for n in nodes if n in executed],
                "passed": [n for n in nodes if n in passed],
            }
        )
    out: dict[str, Any] = {
        "claims": claims,
        "cheats_used": sorted(used, key=lambda c: str(c["cheat"])),
        "config_errors": list(config_errors),
    }
    if not_applicable_reason is not None:
        out["not_applicable"] = not_applicable_reason
    return out


# ---------------------------------------------------------------- 치트 인자


def _check_value(name: str, spec: Mapping[str, Any], value: Any) -> str:
    """정의 인자 하나 검사 → 템플릿에 넣을 글자. 값은 메시지에 넣지 않는다."""
    kind = spec.get("type")
    if kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'은(는) 정수여야 한다")
        if not int(spec["min"]) <= value <= int(spec["max"]):
            raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'이(가) 정의 범위 밖이다")
        text = str(value)
        if not _INT_VALUE.fullmatch(text):
            raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'을(를) 쓸 수 없다")
        return text
    if not isinstance(value, str) or not _ID_VALUE.fullmatch(value):
        raise CheatDenied(
            CHEAT_DENIED, f"인자 '{name}'에 쓸 수 없는 글자가 있다 (영문·숫자·_.- 1~64자만)"
        )
    if kind == "enum" and value not in spec.get("values", ()):
        raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'이(가) 정의된 값이 아니다")
    if kind not in ("enum", "id"):
        raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'의 정의 형식을 모른다")
    return value


def _check_limit(name: str, limit: Mapping[str, Any], value: Any, where: str) -> None:
    if "enum" in limit:
        allowed = [str(v) for v in limit.get("enum", ())]
        if str(value) not in allowed:
            raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'이(가) {where} 허용 값이 아니다")
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'에 {where} 범위를 적용할 수 없다")
    if "min" in limit and value < int(limit["min"]):
        raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'이(가) {where} 허용 범위 밖이다")
    if "max" in limit and value > int(limit["max"]):
        raise CheatDenied(CHEAT_DENIED, f"인자 '{name}'이(가) {where} 허용 범위 밖이다")


def render_command(template: str, values: Mapping[str, str]) -> str:
    """템플릿 자리 `{이름}`에 검사한 글자를 넣는다 (자리 밖 글자는 정의 그대로)."""
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def args_digest(args: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_dumps(dict(args)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 허용 판정


def _allow_entry(qa: Any, cheat_id: str) -> Mapping[str, Any] | None:
    cheats = qa.get("cheats") if isinstance(qa, Mapping) else None
    allow = cheats.get("allow", ()) if isinstance(cheats, Mapping) else ()
    for entry in allow:
        if isinstance(entry, Mapping) and entry.get("id") == cheat_id:
            return entry
    return None


@dataclass(frozen=True, slots=True)
class Granted:
    """허용된 호출 하나: 넣을 명령 글자와 기록용 값."""

    command: str
    rev: int
    digest: str
    args_digest: str
    max_calls: int


@dataclass
class CheatGate:
    """실행 하나의 치트 허용 판정 (실행기가 실행마다 하나 만든다).

    `digest_of(정의)`는 실행 스냅샷에서 채택 digest를 다시 계산한다 → (digest, 문제 목록).
    """

    program: Program
    unattended: bool
    digest_of: Any
    calls: dict[str, int] = field(default_factory=dict[str, int])
    _digests: dict[str, tuple[str | None, tuple[str, ...]]] = field(
        default_factory=dict[str, tuple[str | None, tuple[str, ...]]]
    )

    def check(
        self,
        cheat_id: Any,
        args: Any,
        chain: Sequence[str],
        *,
        nested: bool,
    ) -> Granted:
        """`chain`: 루트부터 이 노드가 든 그래프까지의 그래프 경로. 통과하면 `Granted`."""
        program = self.program
        if not isinstance(cheat_id, str):
            raise CheatDenied(CHEAT_DENIED, "config.cheat가 없다")
        if nested:
            raise CheatDenied(CHEAT_DENIED, "치트 구현 안에서는 치트를 부를 수 없다")
        cheat = program.cheat(cheat_id)
        if cheat is None:
            raise CheatDenied(CHEAT_DENIED, f"치트 '{cheat_id}'이(가) {CHEATS_FILE}에 없다")
        policy = program.workspace.config.get("cheats")
        policy = policy if isinstance(policy, Mapping) else {}
        if policy.get("enabled") is not True:
            raise CheatDenied(CHEAT_DENIED, "워크스페이스 치트 사용이 꺼져 있다 (cheats.enabled)")
        adoption = cheat.get("adoption")
        if not isinstance(adoption, Mapping):
            raise CheatDenied(CHEAT_NOT_ADOPTED, f"치트 '{cheat_id}'은(는) 사람이 채택하지 않았다")
        categories = {
            str(c.get("id")): c for c in policy.get("categories", ()) if isinstance(c, Mapping)
        }
        category = categories.get(str(adoption.get("category")))
        if category is None:
            raise CheatDenied(
                CHEAT_NOT_ADOPTED, f"치트 '{cheat_id}'의 채택 분류가 워크스페이스에 없다"
            )
        if cheat_id not in self._digests:
            self._digests[cheat_id] = self.digest_of(cheat)
        digest, problems = self._digests[cheat_id]
        if problems:
            raise CheatDenied(
                CHEAT_NOT_ADOPTED,
                f"치트 '{cheat_id}' 구현에 미해결·동적 의존성이 있다: {', '.join(problems[:5])}",
            )
        recorded = program.cheat_checks.get(cheat_id, ())
        if recorded:
            # 실행 스냅샷이 원본에서 본 문제 (정션으로 knowledge/를 가리키던 구현 등 — 복사본에는
            # 위치 정보가 없다)
            raise CheatDenied(
                CHEAT_NOT_ADOPTED,
                f"치트 '{cheat_id}' 구현이 원본에서 거부 대상이다: {', '.join(recorded[:5])}",
            )
        if digest != adoption.get("digest"):
            raise CheatDenied(
                CHEAT_NOT_ADOPTED,
                f"치트 '{cheat_id}'의 정의·구현이 채택 뒤 바뀌었다 (digest 불일치 — 다시 채택)",
            )
        if self.unattended and category.get("unattended") is not True:
            raise CheatDenied(
                CHEAT_DENIED, f"치트 '{cheat_id}'의 분류는 무인 실행을 허용하지 않는다"
            )
        env = cheat.get("env")
        profiles = env.get("profiles") if isinstance(env, Mapping) else None
        profile = program.options.profile
        if profiles is not None and profile not in profiles:
            raise CheatDenied(CHEAT_DENIED, f"치트 '{cheat_id}'의 대상 프로필이 아니다")
        entries = self._entries(cheat_id, chain)
        values = self._args(cheat, args, entries)
        max_calls = min(int(e["max_calls"]) for _, e in entries if "max_calls" in e)
        if self.calls.get(cheat_id, 0) >= max_calls:
            raise CheatDenied(
                CHEAT_DENIED, f"치트 '{cheat_id}' 호출이 이 실행의 max_calls({max_calls})를 넘는다"
            )
        impl = cheat.get("impl") or {}
        command = render_command(str(impl.get("template", "")), values)
        if re.search(r"[\r\n\x00]", command):
            raise CheatDenied(CHEAT_DENIED, "명령에 줄바꿈이 들어간다")
        self.calls[cheat_id] = self.calls.get(cheat_id, 0) + 1
        return Granted(command, int(cheat["rev"]), str(digest), args_digest(args), max_calls)

    def _entries(self, cheat_id: str, chain: Sequence[str]) -> list[tuple[str, Mapping[str, Any]]]:
        """루트 `qa.cheats.allow` 항목(필수) + 호출 사슬 서브그래프가 `qa.cheats`를 두면 그 항목."""
        program = self.program
        entries: list[tuple[str, Mapping[str, Any]]] = []
        for i, path in enumerate(chain):
            graph = program.graphs.get(path)
            qa = graph.data.get("qa") if graph is not None else None
            if i == 0:
                entry = _allow_entry(qa, cheat_id)
                if entry is None:
                    raise CheatDenied(
                        CHEAT_DENIED, f"루트 테스트 qa.cheats.allow에 치트 '{cheat_id}'이(가) 없다"
                    )
                entries.append(("루트 테스트", entry))
            elif isinstance(qa, Mapping) and "cheats" in qa:
                entry = _allow_entry(qa, cheat_id)
                if entry is None:
                    raise CheatDenied(
                        CHEAT_DENIED,
                        f"서브그래프 '{path}'의 qa.cheats.allow가 치트 '{cheat_id}'을(를) 막는다",
                    )
                entries.append((f"서브그래프 '{path}'", entry))
        return entries

    @staticmethod
    def _args(
        cheat: Mapping[str, Any],
        args: Any,
        entries: Iterable[tuple[str, Mapping[str, Any]]],
    ) -> dict[str, str]:
        spec = cheat.get("args") or {}
        if not isinstance(args, Mapping):
            raise CheatDenied(CHEAT_DENIED, "config.args는 객체여야 한다")
        extra = sorted(set(args) - set(spec))
        if extra:
            raise CheatDenied(CHEAT_DENIED, "정의에 없는 인자가 있다")
        missing = sorted(set(spec) - set(args))
        if missing:
            raise CheatDenied(CHEAT_DENIED, f"인자 {', '.join(missing)}이(가) 없다")
        values = {name: _check_value(name, spec[name], args[name]) for name in spec}
        for where, entry in entries:
            limits = entry.get("args") or {}
            for name, limit in limits.items():
                if name not in spec:
                    raise CheatDenied(CHEAT_DENIED, f"{where} 허용에 정의에 없는 인자가 있다")
                _check_limit(name, limit, args[name], where)
        return values

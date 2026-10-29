"""에이전트 권한 판정 (구현 계획 3장 계약 "권한", 7장 MCP 도구).

판정 대상은 **에이전트**다. 사람(UI·CLI 직접 사용)은 판정하지 않고 허용한다. 권한은 서버 API를
거치는 동작에만 보장된다 (설치한 플러그인 코드는 사용자 권한으로 돈다, 결정 현황 "권한").

정책 계층 (각 파일의 `permissions`):

- 사용자 `%APPDATA%\\Kookabug\\settings.json` (`KOOKABUG_USER_CONFIG_DIR`로 폴더를 바꾼다)
- 프로젝트 `.kookabug/local.json`
- 팀 `kookabug.json` — 툴셋·프리셋 값은 상한

판정 순서는 `decide` 참고. `decide`는 순수 함수이고, 파일 읽기는 `load_policy`가 한다.
"""

from __future__ import annotations

import dataclasses
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Final, Literal, get_args

from kookabug_core.canonical import loads_strict
from kookabug_core.codes import diag
from kookabug_core.diagnostics import Diagnostic, has_errors
from kookabug_core.schema import check_shape
from kookabug_core.schema.shape import SchemaKind
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE

__all__ = [
    "DEFAULT_PRESET",
    "PRESETS",
    "TOOLS",
    "TOOLSETS",
    "USER_CONFIG_ENV",
    "USER_SETTINGS_FILE",
    "Decision",
    "LayerName",
    "LayerPolicy",
    "Policy",
    "Preset",
    "Principal",
    "Rule",
    "ToolInfo",
    "Toolset",
    "Verdict",
    "decide",
    "load_policy",
    "parse_rule",
    "preset_verdict",
    "user_config_dir",
]

Verdict = Literal["allow", "ask", "deny"]
Toolset = Literal["core", "graph_edit", "run", "observe", "control", "screens"]
Preset = Literal["read_only", "graph_author", "runner", "full"]
LayerName = Literal["user", "project", "team"]
Reason = Literal[
    "human", "policy_invalid", "unknown_tool", "rule", "toolset", "preset", "team_ceiling",
    "unattended_ask",
]  # fmt: skip

TOOLSETS: Final[tuple[Toolset, ...]] = get_args(Toolset)
PRESETS: Final[tuple[Preset, ...]] = get_args(Preset)
DEFAULT_PRESET: Final[Preset] = "graph_author"

USER_CONFIG_ENV: Final = "KOOKABUG_USER_CONFIG_DIR"
USER_SETTINGS_FILE: Final = "settings.json"

_STRICTNESS: Final[dict[Verdict, int]] = {"allow": 0, "ask": 1, "deny": 2}


@dataclass(frozen=True, slots=True)
class ToolInfo:
    toolset: Toolset
    mutating: bool  # False = 조회 도구 (읽기만)


def _tools(toolset: Toolset, mutating: bool, *names: str) -> dict[str, ToolInfo]:
    return dict.fromkeys(names, ToolInfo(toolset, mutating))


# 설계 7장 MCP 도구 전체
TOOLS: Final[Mapping[str, ToolInfo]] = {
    **_tools(
        "core", False,
        "kb_project_info", "kb_toolset_enable", "kb_graph_list", "kb_graph_get",
        "kb_graph_validate", "kb_node_search", "kb_run_status", "kb_log_search",
    ),
    **_tools("graph_edit", True, "kb_graph_create", "kb_graph_patch", "kb_target_create"),
    **_tools("run", True, "kb_run_start", "kb_run_cancel"),
    **_tools("run", False, "kb_run_events", "kb_run_artifact_get"),
    **_tools("observe", False, "kb_screen_capture", "kb_image_find", "kb_ocr_read"),
    **_tools("control", True, "kb_input_click", "kb_input_key", "kb_input_type", "kb_app_launch"),
    **_tools("screens", False, "kb_screen_list", "kb_screen_get"),
    **_tools("screens", True, "kb_screen_save"),
}  # fmt: skip

# 프리셋의 변경 도구 값 (툴셋별). 조회 도구는 모든 프리셋에서 allow
_PRESET_MUTATING: Final[dict[Preset, dict[Toolset, Verdict]]] = {
    "read_only": {"graph_edit": "deny", "run": "deny", "control": "deny", "screens": "deny"},
    "graph_author": {"graph_edit": "ask", "run": "deny", "control": "deny", "screens": "ask"},
    "runner": {"graph_edit": "ask", "run": "allow", "control": "ask", "screens": "ask"},
    "full": {"graph_edit": "allow", "run": "allow", "control": "allow", "screens": "allow"},
}


def preset_verdict(preset: Preset, tool: str) -> Verdict:
    """프리셋 표의 값. `tool`은 `TOOLS`에 있는 이름이어야 한다."""
    info = TOOLS[tool]
    return _PRESET_MUTATING[preset][info.toolset] if info.mutating else "allow"


def _toolset_verdict(value: Verdict, info: ToolInfo) -> Verdict:
    # 툴셋 값은 변경 도구에 그대로. 조회 도구는 툴셋을 deny로 막았을 때만 막는다
    if info.mutating:
        return value
    return "deny" if value == "deny" else "allow"


# ---------------------------------------------------------------- 규칙

_RULE: Final = re.compile(r"([a-z0-9_*?]+)(?:\((.*)\))?")


@dataclass(frozen=True, slots=True)
class Rule:
    """`도구` 또는 `도구(인자 패턴)`. 도구·인자 모두 glob(`fnmatch`), 대소문자 구분.

    인자를 생략하면 모든 인자(`*`), `도구()`는 인자가 빈 문자열일 때만 맞는다.
    """

    verdict: Verdict
    tool: str
    arg: str
    text: str

    def matches(self, tool: str, arg: str) -> bool:
        return fnmatchcase(tool, self.tool) and fnmatchcase(arg, self.arg)


def parse_rule(text: str, verdict: Verdict) -> Rule:
    """규칙 문자열 → `Rule`. 형식이 틀리면 `ValueError` (메타스키마의 `rule` 패턴과 같은 규칙)."""
    m = _RULE.fullmatch(text)
    if m is None:
        raise ValueError(f"규칙 {text!r}이(가) '도구' 또는 '도구(인자 패턴)' 형식이 아니다")
    if verdict not in _STRICTNESS:
        raise ValueError(f"규칙 {text!r}의 verdict {verdict!r}는 allow·ask·deny가 아니다")
    tool, arg = m.group(1), m.group(2)
    return Rule(verdict, tool, "*" if arg is None else arg, text)


# ---------------------------------------------------------------- 정책


@dataclass(frozen=True, slots=True)
class LayerPolicy:
    """한 계층의 정책. `source`는 읽은 파일(표시용), 파일이 없으면 None."""

    layer: LayerName
    source: str | None = None
    preset: Preset | None = None
    toolsets: Mapping[Toolset, Verdict] = field(default_factory=dict[Toolset, Verdict])
    rules: tuple[Rule, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def invalid(self) -> bool:
        return has_errors(self.diagnostics)

    @classmethod
    def from_permissions(
        cls, layer: LayerName, permissions: Mapping[str, Any] | None, source: str | None = None
    ) -> LayerPolicy:
        """메타스키마 `Permissions` 형식을 통과한 값 → 정책."""
        if not permissions:
            return cls(layer, source)
        rules = tuple(parse_rule(r["rule"], r["verdict"]) for r in permissions.get("rules", []))
        return cls(
            layer,
            source,
            permissions.get("preset"),
            dict(permissions.get("toolsets", {})),
            rules,
        )


@dataclass(frozen=True, slots=True)
class Policy:
    user: LayerPolicy = field(default_factory=lambda: LayerPolicy("user"))
    project: LayerPolicy = field(default_factory=lambda: LayerPolicy("project"))
    team: LayerPolicy = field(default_factory=lambda: LayerPolicy("team"))

    @property
    def layers(self) -> tuple[LayerPolicy, LayerPolicy, LayerPolicy]:
        """규칙이 같은 강도일 때 앞 계층을 판정 근거로 적는다."""
        return (self.team, self.project, self.user)

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(d for layer in self.layers for d in layer.diagnostics)

    @property
    def invalid(self) -> bool:
        return any(layer.invalid for layer in self.layers)


@dataclass(frozen=True, slots=True)
class Principal:
    """요청 주체. `attended`는 결과를 사람이 그 자리에서 확인할 수 있는지 (아니면 ask = deny)."""

    kind: Literal["user", "agent"]
    id: str
    attended: bool


@dataclass(frozen=True, slots=True)
class Decision:
    """판정 결과.

    `verdict`는 정책이 준 값(규칙 → 툴셋 → 프리셋 → 팀 상한), `final`은 집행하는 값이다.
    둘은 사람 없는 실행의 ask(`unattended_ask` → deny)에서만 다르다. `layer`·`source`는 판정을
    정한 계층·항목(`rule:…`, `toolset:…`, `preset:…`)이다.
    """

    verdict: Verdict
    final: Verdict
    layer: LayerName | Literal["default"] | None
    source: str
    reason: Reason
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.final == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.final == "ask"

    def describe(self, tool: str) -> str:
        """사람이 읽는 한 줄."""
        word = {"allow": "허용", "ask": "확인 필요", "deny": "거부"}[self.final]
        where = {
            "user": "사용자 설정",
            "project": LOCAL_FILE,
            "team": WORKSPACE_FILE,
            "default": "기본값",
            None: "",
        }[self.layer]
        why = {
            "human": "사람의 직접 사용",
            "policy_invalid": "권한 설정 파일 오류",
            "unknown_tool": "모르는 도구",
            "rule": "규칙",
            "toolset": "툴셋 값",
            "preset": "프리셋",
            "team_ceiling": "팀 상한",
            "unattended_ask": "사람 없는 실행의 확인 요청",
        }[self.reason]
        detail = ", ".join(x for x in (where, self.source) if x)
        return f"{tool}: {word} — {why}" + (f" ({detail})" if detail else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "final": self.final,
            "layer": self.layer,
            "reason": self.reason,
            "source": self.source,
            "verdict": self.verdict,
        }


@dataclass(frozen=True, slots=True)
class _Pick:
    verdict: Verdict
    layer: LayerName | Literal["default"] | None
    source: str
    reason: Reason


def decide(policy: Policy, principal: Principal, tool: str, arg: str = "") -> Decision:
    """권한 판정 (순수 함수).

    1. 사람이면 허용. 정책 파일이 잘못됐으면 deny(`policy_invalid`), 모르는 도구는 deny
    2. 세 계층 규칙 중 맞는 것: deny > ask > allow
    3. 없으면 툴셋 값(프로젝트 → 사용자). 변경 도구에는 그대로, 조회 도구는 deny일 때만 deny
    4. 툴셋 값이 없으면 프리셋 표(프리셋: 프로젝트 → 사용자 → 기본 `graph_author`)
    5. 팀 계층의 툴셋 값(없으면 프리셋 값)은 상한: 결과보다 엄격하면 팀 값
    6. 사람이 없고(`attended: false`) ask면 deny
    """
    if principal.kind == "user":
        return Decision("allow", "allow", None, "principal:user", "human")
    if policy.invalid:
        bad = next(layer for layer in policy.layers if layer.invalid)
        return Decision(
            "deny", "deny", bad.layer, bad.source or "", "policy_invalid", policy.diagnostics
        )
    info = TOOLS.get(tool)
    if info is None:
        return Decision("deny", "deny", None, f"tool:{tool}", "unknown_tool")

    pick = (
        _by_rules(policy, tool, arg)
        or _by_toolset(policy, info)
        or _by_preset(policy, tool)
    )  # fmt: skip
    ceiling = _team_ceiling(policy.team, tool, info)
    if ceiling is not None and _STRICTNESS[ceiling.verdict] > _STRICTNESS[pick.verdict]:
        pick = ceiling

    if pick.verdict == "ask" and not principal.attended:
        return Decision("ask", "deny", pick.layer, pick.source, "unattended_ask")
    return Decision(pick.verdict, pick.verdict, pick.layer, pick.source, pick.reason)


def _by_rules(policy: Policy, tool: str, arg: str) -> _Pick | None:
    best: _Pick | None = None
    for layer in policy.layers:
        for rule in layer.rules:
            if not rule.matches(tool, arg):
                continue
            if best is None or _STRICTNESS[rule.verdict] > _STRICTNESS[best.verdict]:
                best = _Pick(rule.verdict, layer.layer, f"rule:{rule.text}", "rule")
    return best


def _by_toolset(policy: Policy, info: ToolInfo) -> _Pick | None:
    for layer in (policy.project, policy.user):
        value = layer.toolsets.get(info.toolset)
        if value is not None:
            verdict = _toolset_verdict(value, info)
            return _Pick(verdict, layer.layer, f"toolset:{info.toolset}", "toolset")
    return None


def _by_preset(policy: Policy, tool: str) -> _Pick:
    for layer in (policy.project, policy.user):
        if layer.preset is not None:
            return _Pick(
                preset_verdict(layer.preset, tool), layer.layer, f"preset:{layer.preset}", "preset"
            )
    return _Pick(
        preset_verdict(DEFAULT_PRESET, tool), "default", f"preset:{DEFAULT_PRESET}", "preset"
    )


def _team_ceiling(team: LayerPolicy, tool: str, info: ToolInfo) -> _Pick | None:
    # 팀 계층 안에서도 툴셋 값이 프리셋보다 먼저다 (다른 계층과 같은 순서)
    value = team.toolsets.get(info.toolset)
    if value is not None:
        return _Pick(
            _toolset_verdict(value, info), "team", f"toolset:{info.toolset}", "team_ceiling"
        )
    if team.preset is not None:
        return _Pick(
            preset_verdict(team.preset, tool), "team", f"preset:{team.preset}", "team_ceiling"
        )
    return None


# ---------------------------------------------------------------- 정책 파일


def user_config_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """사용자 설정 폴더: `KOOKABUG_USER_CONFIG_DIR`, 없으면 `%APPDATA%\\Kookabug`."""
    env = os.environ if environ is None else environ
    if folder := env.get(USER_CONFIG_ENV):
        return Path(folder)
    appdata = env.get("APPDATA")
    return Path(appdata) / "Kookabug" if appdata else None


def load_policy(workspace_root: str | Path, user_dir: Path | None) -> Policy:
    """세 계층 정책을 읽는다.

    사용자 설정·`local.json`은 파일이 없으면 빈 계층이다. `kookabug.json`은 워크스페이스에 반드시
    있으므로 없으면 오류다(지우면 팀 상한이 사라진다). 그 밖에 읽을 수 없는 경로(폴더, 접근 거부,
    끊긴 링크, 부모가 파일)와 형식 오류는 그 계층의 `diagnostics`.
    """
    root = Path(workspace_root)
    user_path = user_dir / USER_SETTINGS_FILE if user_dir is not None else None
    return Policy(
        user=_read_layer("user", user_path, str(user_path), "user-settings"),
        project=_read_layer("project", root.joinpath(*LOCAL_FILE.split("/")), LOCAL_FILE, "local"),
        team=_read_layer("team", root / WORKSPACE_FILE, WORKSPACE_FILE, "workspace", required=True),
    )


def _read_layer(
    layer: LayerName, path: Path | None, shown: str, kind: SchemaKind, *, required: bool = False
) -> LayerPolicy:
    if path is None:
        return LayerPolicy(layer)
    # is_file()로 먼저 거르면 폴더·접근 거부가 "파일 없음"과 같아져 정책이 조용히 빈다.
    # 읽어 보고 예외로 나눈다
    try:
        data = loads_strict(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if not required and not _abnormal_missing(path):
            return LayerPolicy(layer)
        problem = diag("json_invalid", f"{shown}을(를) 읽을 수 없다: {exc}", file=shown)
        return LayerPolicy(layer, shown, diagnostics=(problem,))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        problem = diag("json_invalid", f"{shown}을(를) 읽을 수 없다: {exc}", file=shown)
        return LayerPolicy(layer, shown, diagnostics=(problem,))
    if not isinstance(data, dict):
        return LayerPolicy(layer, shown, diagnostics=tuple(check_shape(data, kind, file=shown)))
    if "permissions" not in data:
        return LayerPolicy(layer, shown)
    permissions = data["permissions"]
    # 파일의 다른 부분이 틀려도 권한은 따로 본다. 권한만 틀린 파일을 빈 정책으로 보면 팀 상한이
    # 조용히 사라진다
    problems = check_shape(permissions, kind, file=shown, ref="#/$defs/Permissions")
    if problems:
        moved = tuple(
            dataclasses.replace(d, pointer="/permissions" + (d.pointer or "")) for d in problems
        )
        return LayerPolicy(layer, shown, diagnostics=moved)
    return LayerPolicy.from_permissions(layer, permissions, shown)


def _abnormal_missing(path: Path) -> bool:
    """`FileNotFoundError`가 났지만 "파일 없음"이 아닌 경우: 끊긴 링크, 부모 경로가 폴더가 아님."""
    if os.path.lexists(path):
        return True
    return any(os.path.lexists(p) and not p.is_dir() for p in path.parents)

"""실행 전 검증 진단 코드 표.

코드는 영문 snake_case(도구·테스트가 구분용으로 쓴다), 설명은 사람이 읽는 한국어 한 줄이다.
진단 메시지는 위치·이름을 넣어 따로 만든다. 형식 검사 코드(`missing_field` 등)는
`kookabug_core.schema.shape`가 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from kookabug_core.diagnostics import Diagnostic, Severity

__all__ = ["CODES", "CodeInfo", "diag"]


@dataclass(frozen=True, slots=True)
class CodeInfo:
    severity: Severity
    group: str
    summary: str


def _e(group: str, summary: str) -> CodeInfo:
    return CodeInfo("error", group, summary)


def _w(group: str, summary: str) -> CodeInfo:
    return CodeInfo("warning", group, summary)


CODES: Final[dict[str, CodeInfo]] = {
    # 파일·워크스페이스
    "graph_missing": _e("file", "그래프 파일이 없다"),
    "json_invalid": _e("file", "JSON으로 읽을 수 없는 파일"),
    "profile_missing": _e("file", "선택한 프로필이 kookabug.json에 없다"),
    # 구조
    "entry_count": _e("structure", "core.graph.entry가 정확히 하나가 아니다"),
    "unknown_node_type": _e("structure", "설치된 플러그인에 없는 노드 타입"),
    "node_version_mismatch": _e("structure", "노드 version이 설치된 노드 스키마와 다르다"),
    "plugin_not_declared": _e("structure", "노드 타입의 플러그인이 그래프 plugins에 없다"),
    "unknown_input": _e("structure", "노드에 없는 입력 핀"),
    "missing_required_input": _e("structure", "기본값 없는 입력 핀에 값이 없다"),
    "input_invalid": _e("structure", "상수 입력값이 핀의 선택지·범위를 벗어난다"),
    "unknown_exit": _e("structure", "노드에 없는 출구를 next에 연결했다"),
    "dangling_next": _e("structure", "next가 없는 노드를 가리킨다"),
    "exec_into_pure": _e("structure", "next가 순수 노드를 가리킨다 (순수 노드는 exec 핀이 없다)"),
    "config_invalid": _e("structure", "config가 노드 스키마의 config 선언과 맞지 않는다"),
    "kind_folder_mismatch": _w("structure", "폴더와 kind가 어긋난다 (tests/·subgraphs/)"),
    # 값
    "setting_missing": _e("values", "$setting 키가 어느 설정 계층에도 없다"),
    "setting_null": _e("values", "$setting으로 고른 값이 null이다 (local.json에 넣어야 하는 값)"),
    "secret_missing": _e("values", "$secret 키의 값을 비밀값 제공자에서 찾지 못했다"),
    "target_missing": _e("values", "$target 파일이 없다"),
    "target_invalid": _e("values", "$target 파일 형식이 틀렸거나 이미지가 없다"),
    "link_bad_node": _e("values", "$link가 없는 노드를 가리킨다"),
    "link_bad_output": _e("values", "$link가 노드에 없는 출력을 가리킨다"),
    # 타입
    "type_mismatch": _e("types", "값·연결의 타입을 입력 핀이 받지 않는다"),
    # 서브그래프
    "call_target_missing": _e("subgraph", "core.graph.call이 가리키는 그래프 파일이 없다"),
    "call_target_not_subgraph": _e("subgraph", "core.graph.call이 테스트 그래프를 가리킨다"),
    "call_cycle": _e("subgraph", "서브그래프 호출이 순환한다"),
    "call_depth": _e("subgraph", "서브그래프 호출이 너무 깊다 (최대 16)"),
    "terminal_in_subgraph": _e("subgraph", "서브그래프에 core.test.* 종료 노드가 있다"),
    "graph_exit_in_test": _e("subgraph", "테스트에 core.graph.exit가 있다"),
    "exit_name_unknown": _e("subgraph", "core.graph.exit의 config.exit가 interface.exits에 없다"),
    "exit_missing_required_output": _e(
        "subgraph", "core.graph.exit가 nullable 아닌 interface 출력을 주지 않는다"
    ),
    "interface_exit_unused": _w("subgraph", "어느 core.graph.exit도 쓰지 않는 interface 출구"),
    # 재시도
    "retry_not_allowed": _e("retry", "재시도를 선언하지 않은(never) 노드에 config.retry가 있다"),
    "retry_exit_not_allowed": _e("retry", "config.retry.on이 노드가 선언한 재시도 출구 밖이다"),
    "retry_max_attempts": _e("retry", "config.retry.max_attempts는 1 이상의 정수다"),
    # 변수
    "var_never_set": _w("vars", "같은 그래프에 그 이름을 상수로 정하는 core.var.set이 없다"),
    # 흐름
    "exec_cycle": _e("flow", "exec 연결이 순환한다 (반복은 body의 암묵적 귀환으로만)"),
    "pure_cycle": _e("flow", "순수 노드끼리 $link가 순환한다"),
    "link_not_dominated": _e(
        "flow", "$link로 읽는 exec 출력을 주는 출구를 지나지 않고 소비 노드에 닿는 경로가 있다"
    ),
    "loop_scope_entry": _e("flow", "반복 범위 밖에서 범위 안 노드로 들어온다 (body 출구로만)"),
    "link_out_of_scope": _e("flow", "반복 범위 밖에서 범위 안 노드(또는 index)의 출력을 읽는다"),
    "unconnected_ok_exit": _w(
        "flow", "테스트에서 연결 안 된 ok 출구로 끝나는 경로 (검증 노드 제외)"
    ),
    "subgraph_path_open": _e("flow", "서브그래프에서 연결 안 된 ok 출구로 끝나는 경로"),
    "while_requires_limit": _e("flow", "core.flow.while에 max_iterations가 없다"),
}


def diag(
    code: str,
    message: str,
    *,
    file: str | None,
    node: str | None = None,
    pointer: str | None = None,
) -> Diagnostic:
    """표의 심각도로 진단을 만든다. 표에 없는 코드는 프로그램 오류."""
    return Diagnostic(CODES[code].severity, code, message, file=file, node=node, pointer=pointer)

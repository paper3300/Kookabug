# 생성물 (packages/schema/daemon-rpc.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class AgentClientInfo(BaseModel):
    """
    에이전트 연결 → 그 에이전트 주체 (id 필수)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    attended: Annotated[
        bool | None, Field(description="사람이 지켜보는 연결인가 (생략하면 false)")
    ] = None
    id: Annotated[str, Field(description="에이전트 주체 ID", min_length=1)]
    kind: Literal["agent"]
    name: str
    version: str


class BreakpointsResult(BaseModel):
    """
    debug.breakpoints.get·set 결과, debug.breakpoints.changed 알림 (다른 연결이 바꿨을 때)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    breakpoints: Annotated[
        Any, Field(description="urn:kookabug:breakpoints:0#/$defs/BreakpointList")
    ]


class BreakpointsSetParams(BaseModel):
    """
    목록 전체를 바꾼다: .kookabug/breakpoints.json에 원자적으로 쓰고, 진행 중인 UI 실행에 밀어 넣는다(다음 경계부터)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    breakpoints: Annotated[
        Any, Field(description="urn:kookabug:breakpoints:0#/$defs/BreakpointList")
    ]


class DaemonErrorCode(RootModel[Literal[-32700, -32600, -32601, -32602, -32603, -32100]]):
    root: Annotated[
        Literal[-32700, -32600, -32601, -32602, -32603, -32100],
        Field(
            description="JSON-RPC 표준: -32700 parse_error(읽은 뒤 연결을 닫는다), -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32100 request_failed (종류는 error.data.code)",
            title="DaemonErrorCode",
        ),
    ]


class DaemonShutdownParams(BaseModel):
    """
    진행 중인 실행이 있으면 run_active로 거부. force면 실행을 취소하고 마무리를 기다린 뒤 끝낸다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    force: bool | None = None


class DaemonStandardError(BaseModel):
    """
    JSON-RPC 표준 오류
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: Literal[-32700, -32600, -32601, -32602, -32603]
    data: Annotated[Any | None, Field(description="생략하거나 사람이 읽는 정보")] = None
    message: str


class Diagnostic(BaseModel):
    """
    검증 진단 (kookabug_core.diagnostics.Diagnostic.to_dict)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: str
    file: str | None = None
    message: str
    node: str | None = None
    pointer: str | None = None
    severity: Literal["error", "warning"]


class DocId(RootModel[str]):
    root: Annotated[
        str, Field(description="daemon이 연 문서 번호 (연결과 무관)", min_length=1, title="DocId")
    ]


class EmptyParams(BaseModel):
    """
    인자 없음
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class EmptyResult(BaseModel):
    """
    결과 없음
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class ExitShape(BaseModel):
    """
    출구. outputs는 그 출구로 나갈 때 값이 있는 출력 이름
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["fail", "ok"]
    name: str
    outputs: list[str]


class GraphCloseParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    doc_id: DocId


class GraphValue(BaseModel):
    """
    그래프 파일 값 전체 (JSON 트리). 편집 중이라 형식이 틀릴 수 있다. JS에서 보낼 때는 반드시 wireStringify로 직렬화한다
    """


class ImageRef1(BaseModel):
    """
    이미지는 RPC에 싣지 않는다. cache는 .kookabug/cache/editor/<이름>(kbimg://cache/<이름>), workspace는 워크스페이스 파일(kbimg://ws/<경로>)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    cache: Annotated[str, Field(pattern="^[A-Za-z0-9_-]+\\.png$")]
    height: Annotated[int, Field(ge=0, le=9007199254740991)]
    width: Annotated[int, Field(ge=0, le=9007199254740991)]


class JsonRpcVersion(RootModel[Literal["2.0"]]):
    root: Annotated[Literal["2.0"], Field(title="JsonRpcVersion")]


class LeaseChangedParams(BaseModel):
    """
    입력 임대권 소유자 (없으면 null)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    owner: dict[str, Any] | None


class ClickItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class MethodName(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="점으로 나눈 소문자 이름 (예: graph.open)",
            pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$",
            title="MethodName",
        ),
    ]


class DaemonShutdown(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: DaemonShutdownParams
    renderer: Literal[False]
    result: EmptyResult
    tool: Literal["ui_only"]


class DebugBreakpointsGet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: BreakpointsResult
    tool: Literal["ui_only"]


class DebugBreakpointsSet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: BreakpointsSetParams
    renderer: Literal[True]
    result: BreakpointsResult
    tool: Literal["ui_only"]


class GraphClose(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphCloseParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["ui_only"]


class NodesListResult(BaseModel):
    """
    팔레트: 레지스트리의 플러그인마다 노드 스키마 문서 하나 (kookabug_core.palette.export)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schemas: list[dict[str, Any]]


class DebugBreakpointsChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: BreakpointsResult


class LeaseChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: LeaseChangedParams


class OutputShape(BaseModel):
    """
    출력 핀
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    nullable: bool
    type: str


class Params(BaseModel):
    """
    이름 있는 인자만 쓴다 (배열 params는 쓰지 않는다). 메서드별 모양은 Methods 표의 params
    """

    model_config = ConfigDict(
        extra="allow",
    )


class PinShape(BaseModel):
    """
    입력 핀. required = 기본값도 optional도 없음. 모르는 노드의 핀은 type 'any'
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    default: Any | None = None
    description: str | None = None
    enum: list[Any] | None = None
    maximum: float | None = None
    min_items: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    minimum: float | None = None
    name: str
    nullable: bool
    optional: bool
    required: bool
    type: str


class PluginSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    title: str | None = None
    version: str


class SearchItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class Principal(BaseModel):
    """
    연결의 주체 (kookabug_core.permissions.Principal)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    attended: bool
    id: str
    kind: Literal["agent", "user"]


class RectItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class Rect(RootModel[list[RectItem]]):
    """
    [x, y, w, h] 물리 픽셀
    """

    root: Annotated[
        list[RectItem],
        Field(description="[x, y, w, h] 물리 픽셀", max_length=4, min_length=4, title="Rect"),
    ]


class RequestFailedCode(
    RootModel[
        Literal[
            "approval_required",
            "capture_failed",
            "capture_timeout",
            "capture_unsupported",
            "doc_not_open",
            "dpi_awareness_unavailable",
            "exists",
            "frame_expired",
            "idempotency_conflict",
            "input_desktop_unavailable",
            "invalid_json",
            "io_error",
            "key_unknown",
            "launch_failed",
            "not_found",
            "not_paused",
            "ocr_model_corrupt",
            "ocr_model_missing",
            "path_outside_workspace",
            "permission_denied",
            "platform_unavailable",
            "point_obscured",
            "private_path",
            "protocol_mismatch",
            "read_only",
            "revision_conflict",
            "run_active",
            "run_busy",
            "run_not_debuggable",
            "run_not_found",
            "shutting_down",
            "target_elevated",
            "target_image_invalid",
            "target_invalid",
            "unauthenticated",
            "validation_failed",
            "window_gone",
            "window_minimized",
            "window_mismatch",
            "window_not_foreground",
            "window_not_found",
        ]
    ]
):
    root: Annotated[
        Literal[
            "approval_required",
            "capture_failed",
            "capture_timeout",
            "capture_unsupported",
            "doc_not_open",
            "dpi_awareness_unavailable",
            "exists",
            "frame_expired",
            "idempotency_conflict",
            "input_desktop_unavailable",
            "invalid_json",
            "io_error",
            "key_unknown",
            "launch_failed",
            "not_found",
            "not_paused",
            "ocr_model_corrupt",
            "ocr_model_missing",
            "path_outside_workspace",
            "permission_denied",
            "platform_unavailable",
            "point_obscured",
            "private_path",
            "protocol_mismatch",
            "read_only",
            "revision_conflict",
            "run_active",
            "run_busy",
            "run_not_debuggable",
            "run_not_found",
            "shutting_down",
            "target_elevated",
            "target_image_invalid",
            "target_invalid",
            "unauthenticated",
            "validation_failed",
            "window_gone",
            "window_minimized",
            "window_mismatch",
            "window_not_foreground",
            "window_not_found",
        ],
        Field(
            description="-32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로. M3: read_only(스냅샷 그래프 저장), not_paused(멈추지 않은 실행에 Step), run_not_debuggable(이 daemon이 띄운 UI 실행이 아님)",
            title="RequestFailedCode",
        ),
    ]


class RequestId(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="보낸 쪽이 1부터 붙이는 요청 번호. 응답은 같은 번호로 짝짓는다",
            ge=1,
            le=9007199254740991,
            title="RequestId",
        ),
    ]


class RequestSeq(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="요청 순번 (graph.validate·target.preview). 응답이 같은 값을 돌려주고, 클라이언트는 마지막으로 보낸 seq의 응답만 쓴다",
            ge=0,
            le=9007199254740991,
            title="RequestSeq",
        ),
    ]


class Revision(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="그래프 파일 revision: 디스크 바이트의 sha256 hex",
            pattern="^[0-9a-f]{64}$",
            title="Revision",
        ),
    ]


class RunChildrenResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    offset: Annotated[int, Field(ge=0, le=9007199254740991)]
    steps: list[Any]
    total: Annotated[
        int, Field(description="그 부모(·회차) 아래 스텝 수", ge=0, le=9007199254740991)
    ]


class RunCompareResult(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description="run.compare 결과 (run-index.schema.json CompareResult)",
            title="RunCompareResult",
        ),
    ]


class RunControlResult(BaseModel):
    """
    run.pause·run.resume 결과: runner가 답한 상태 (running·pausing·paused·cancelling)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    state: Literal["cancelling", "paused", "pausing", "running"]


class RunExportResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int, Field(ge=0, le=9007199254740991)]
    path: str


class RunFileResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int, Field(description="파일 전체 크기", ge=0, le=9007199254740991)]
    text: str
    truncated: Annotated[
        bool, Field(description="1 MiB를 넘어 앞(events_tail은 뒤만 남김)을 잘랐다")
    ]


class RunId(RootModel[str]):
    root: Annotated[
        str,
        Field(description="실행 ID: 소문자·숫자 8자", pattern="^[a-z0-9]{8}$", title="RunId"),
    ]


class RunIdParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: RunId


class RunIndexResult(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description="run.index 결과: 실행 색인 (run-index.schema.json)",
            title="RunIndexResult",
        ),
    ]


class RunLaggedParams(BaseModel):
    """
    송신 큐가 차서 구독을 끊음 → 다시 구독
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: RunId


class RunOutcome(BaseModel):
    """
    실행 결과 (run.end 판정·CLI 종료 코드 규칙의 값·마무리한 쪽)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exit_code: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]
    finalized_by: Literal["runner", "supervisor"]
    verdict: Literal["error", "fail", "pass", "skipped"]


class RunResumeIdParams(BaseModel):
    """
    run.resume params. mode를 빼면 continue. 멈추지 않은 실행에 Step(step_*)이면 not_paused
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Annotated[Any | None, Field(description="urn:kookabug:events:0#/$defs/ResumeMode")] = None
    run_id: RunId


class RunStepResult(BaseModel):
    """
    스텝 하나의 자세한 기록. 파일 경로는 실행 폴더 기준 ('/' 구분, kbimg://ws/<run_dir>/<경로>로 연다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    events: Annotated[
        list[Any],
        Field(description="그 스텝의 step.start·attempt.end·step.end·log 이벤트 (seq 순)"),
    ]
    ocr_text: Annotated[str | None, Field(description="steps/<스텝>_ocr.txt 내용 (없으면 null)")]
    run_dir: Annotated[str, Field(description="실행 폴더 (워크스페이스 기준)")]
    step: Annotated[Any, Field(description="urn:kookabug:run-index:0#/$defs/StepNode")]
    thumbnail: Annotated[
        str | None, Field(description="썸네일 파일 (thumbs/<스텝>.jpg, 없으면 null)")
    ]


class RunSubscribeParams(BaseModel):
    """
    after_seq = 클라이언트가 실제로 적용한 마지막 seq (처음이면 0). 순서·커서 규칙은 M2 계획 2.8
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    after_seq: Annotated[int, Field(ge=0, le=9007199254740991)]
    run_id: RunId


class FailurePath(RootModel[list[str]]):
    root: Annotated[list[str], Field(description="실패 위치 호출 경로 (노드 ID)", min_length=1)]


class Seq(RootModel[int]):
    root: Annotated[int, Field(description="저널 안 순번", ge=1, title="Seq")]


class SessionHelloResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    daemon_version: str
    principal: Principal
    protocol: Annotated[int, Field(ge=1, le=9007199254740991)]
    start_id: str
    workspace: str


class SizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=0, le=9007199254740991)]


class Size(RootModel[list[SizeItem]]):
    """
    [w, h] 물리 픽셀
    """

    root: Annotated[
        list[SizeItem],
        Field(description="[w, h] 물리 픽셀", max_length=2, min_length=2, title="Size"),
    ]


class StepId(RootModel[str]):
    root: Annotated[str, Field(pattern="^s[1-9][0-9]*$", title="StepId")]


class SuccessResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: RequestId
    jsonrpc: JsonRpcVersion
    result: Annotated[Any, Field(description="메서드별 결과 (JSON 값)")]


class TargetCaptureParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    window: Annotated[int, Field(description="창 handle", ge=0, le=9007199254740991)]


class TargetRevision(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="target revision: sha256(JSON 바이트) + ':' + sha256(image가 가리키는 파일 바이트). 이미지가 없으면 'missing' (M2 계획 2.9)",
            pattern="^[0-9a-f]{64}:([0-9a-f]{64}|missing)$",
            title="TargetRevision",
        ),
    ]


class Timestamp(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
            title="Timestamp",
        ),
    ]


class ToolName(
    RootModel[
        Literal[
            "kb_graph_create",
            "kb_graph_get",
            "kb_graph_patch",
            "kb_graph_validate",
            "kb_image_find",
            "kb_node_search",
            "kb_project_info",
            "kb_run_cancel",
            "kb_run_events",
            "kb_run_start",
            "kb_run_status",
            "kb_screen_capture",
            "kb_target_create",
            "ui_only",
        ]
    ]
):
    root: Annotated[
        Literal[
            "kb_graph_create",
            "kb_graph_get",
            "kb_graph_patch",
            "kb_graph_validate",
            "kb_image_find",
            "kb_node_search",
            "kb_project_info",
            "kb_run_cancel",
            "kb_run_events",
            "kb_run_start",
            "kb_run_status",
            "kb_screen_capture",
            "kb_target_create",
            "ui_only",
        ],
        Field(
            description="권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon의 AGENT_DENIED 목록 — daemon.shutdown, M3 디버그 메서드 debug.breakpoints.get·set·run.pause·run.resume·run.restart, run.export — 를 판정 전에 거부)",
            title="ToolName",
        ),
    ]


class UiClientInfo(BaseModel):
    """
    UI 연결 → 판정하지 않는 사용자 주체
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["ui"]
    name: str
    version: str


class Verdict(RootModel[Literal["error", "fail", "pass", "skipped"]]):
    root: Annotated[Literal["error", "fail", "pass", "skipped"], Field(title="Verdict")]


class WindowInfo(BaseModel):
    """
    보이는 최상위 창 하나
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_size: Size
    dpi: Annotated[int, Field(ge=1, le=9007199254740991)]
    handle: Annotated[int, Field(ge=0, le=9007199254740991)]
    pid: Annotated[int, Field(ge=0, le=9007199254740991)]
    process: str
    title: str


class WindowsListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    windows: list[WindowInfo]


class Retention(BaseModel):
    """
    실행 기록 보관 정책 (kookabug.json retention, 없는 값은 기본값: 통과 14일·실패 60일·최근 50개). 기록 뷰어 상태 바 문구용 (M3 T11). 정리는 보류 H1
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    failed_days: Annotated[int, Field(ge=0)]
    keep_last: Annotated[int, Field(ge=0)]
    passed_days: Annotated[int, Field(ge=0)]


class Runtime(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    capture: str | None
    ocr: str | None
    platform: str
    python: str


class WorkspaceInfoResult(BaseModel):
    """
    루트(절대 경로), kookabug.json 요약(프로필 이름·진단), 플러그인, 상태 바용 실행 환경
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: Annotated[
        int | None,
        Field(
            description='run.start에 deadline_ms를 주지 않았을 때의 실행 전체 기한 (kookabug.json run.deadline_ms, 없으면 30분). 실행 툴바의 기한 고르기가 "기본"에 보인다',
            ge=1,
            le=9007199254740991,
        ),
    ] = None
    diagnostics: list[Diagnostic]
    plugins: list[PluginSummary]
    profiles: list[str]
    retention: Annotated[
        Retention | None,
        Field(
            description="실행 기록 보관 정책 (kookabug.json retention, 없는 값은 기본값: 통과 14일·실패 60일·최근 50개). 기록 뷰어 상태 바 문구용 (M3 T11). 정리는 보류 H1"
        ),
    ] = None
    root: str
    runtime: Runtime


class WorkspacePath(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="워크스페이스 루트 기준 경로 ('/' 구분). daemon이 루트 밖·.kookabug/ 안을 거부한다",
            min_length=1,
            title="WorkspacePath",
        ),
    ]


class ClientInfo(RootModel[UiClientInfo | AgentClientInfo]):
    root: Annotated[UiClientInfo | AgentClientInfo, Field(title="ClientInfo")]


class CropRef(BaseModel):
    """
    정지 화면에서 자른 영역 (저장 전 템플릿)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frame_id: Annotated[str, Field(min_length=1)]
    rect: Rect


class GraphChangedParams(BaseModel):
    """
    열린 문서의 디스크 revision이 바뀜 (파일이 없어졌으면 null)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    doc_id: DocId
    revision: Revision | None


class GraphCreateParams(BaseModel):
    """
    새 그래프 (canonical 틀). 파일이 있으면 exists. 결과는 graph.open과 같다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["subgraph", "test"]
    path: WorkspacePath
    title: str | None = None


class GraphOpenParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath


class GraphSaveParams(BaseModel):
    """
    값 전체 저장 (M2 계획 2.6). 디스크가 base_revision과 다르면 revision_conflict(force면 덮어씀). 수 규칙(number_out_of_range·number_not_finite)에 걸리면 validation_failed
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: Revision
    doc_id: DocId
    force: bool | None = None
    value: GraphValue


class GraphSaveResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    canonicalized: Annotated[
        bool,
        Field(
            description="canonical이 아니던 원문을 처음 편집해 저장해서 파일 전체가 canonical이 됨"
        ),
    ]
    diagnostics: list[Diagnostic]
    revision: Revision
    wrote: Annotated[
        bool, Field(description="false면 지금 디스크 바이트와 같아 쓰지 않음 (mtime 그대로)")
    ]


class GraphValidateParams(BaseModel):
    """
    편집 버퍼 값으로 검증 (루트만 버퍼, 서브그래프·target·화면은 디스크)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    doc_id: DocId
    seq: RequestSeq
    value: GraphValue


class ImageRef2(BaseModel):
    """
    이미지는 RPC에 싣지 않는다. cache는 .kookabug/cache/editor/<이름>(kbimg://cache/<이름>), workspace는 워크스페이스 파일(kbimg://ws/<경로>)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    height: Annotated[int, Field(ge=0, le=9007199254740991)]
    width: Annotated[int, Field(ge=0, le=9007199254740991)]
    workspace: WorkspacePath


class ImageRef(RootModel[ImageRef1 | ImageRef2]):
    root: Annotated[
        ImageRef1 | ImageRef2,
        Field(
            description="이미지는 RPC에 싣지 않는다. cache는 .kookabug/cache/editor/<이름>(kbimg://cache/<이름>), workspace는 워크스페이스 파일(kbimg://ws/<경로>)",
            title="ImageRef",
        ),
    ]


class MatchInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    click: Annotated[list[ClickItem], Field(max_length=2, min_length=2)]
    method: str
    rect: Rect
    scale: float
    score: float


class GraphSave(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphSaveParams
    renderer: Literal[True]
    result: GraphSaveResult
    tool: Literal["kb_graph_patch"]


class NodesList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: NodesListResult
    tool: Literal["kb_node_search"]


class RunCancel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["kb_run_cancel"]


class RunIndex(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[True]
    result: RunIndexResult
    tool: Literal["kb_run_events"]


class RunPause(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[True]
    result: RunControlResult
    tool: Literal["ui_only"]


class RunResume(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunResumeIdParams
    renderer: Literal[True]
    result: RunControlResult
    tool: Literal["ui_only"]


class RunSubscribe(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunSubscribeParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["kb_run_events"]


class RunUnsubscribe(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["ui_only"]


class WindowsList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: WindowsListResult
    tool: Literal["kb_screen_capture"]


class WorkspaceInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: WorkspaceInfoResult
    tool: Literal["kb_project_info"]


class NodeShape(BaseModel):
    """
    노드 하나의 핀·출구 (daemon이 계산, 에디터는 계산하지 않는다). unknown이면 레지스트리에 없는 타입·버전이거나 서브그래프를 읽지 못한 호출이라 JSON 키(in·next·다른 노드의 $link)로 만든 대체 모양이다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exits: list[ExitShape]
    inputs: list[PinShape]
    outputs: list[OutputShape]
    unknown: bool


class NodeShapes(RootModel[dict[str, NodeShape]]):
    """
    노드 ID → 모양
    """

    root: dict[str, NodeShape]


class Notification(BaseModel):
    """
    응답이 없는 알림 (daemon → 클라이언트). 이름별 모양은 Notifications 표
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: MethodName
    params: Params | None = None


class GraphChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphChangedParams


class RunLagged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunLaggedParams


class PreviewResult(BaseModel):
    """
    kookabug target test --json의 결과 필드(target_cmd.result_json) + 검색 범위 픽셀 + seq. 화면에는 찾음/못 찾음과 (최고) 점수만 쓴다 (candidates는 화면 안 대상 개수가 아니다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    best: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    elapsed_ms: float
    expected_scale: float
    found: bool
    match: MatchInfo | None
    search: list[SearchItem]
    search_rect_px: Rect
    seq: RequestSeq
    threshold: float


class PreviewTemplate1(BaseModel):
    """
    crop = 편집 중 새로 고른 영역, image = 기존 target 이미지(target 기준 경로)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    crop: CropRef


class PreviewTemplate2(BaseModel):
    """
    crop = 편집 중 새로 고른 영역, image = 기존 target 이미지(target 기준 경로)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    image: WorkspacePath


class PreviewTemplate(RootModel[PreviewTemplate1 | PreviewTemplate2]):
    root: Annotated[
        PreviewTemplate1 | PreviewTemplate2,
        Field(
            description="crop = 편집 중 새로 고른 영역, image = 기존 target 이미지(target 기준 경로)",
            title="PreviewTemplate",
        ),
    ]


class Request(BaseModel):
    """
    응답을 기다리는 요청 (클라이언트 → daemon)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: RequestId
    jsonrpc: JsonRpcVersion
    method: MethodName
    params: Params | None = None


class RequestFailedData(BaseModel):
    """
    error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found·run_not_debuggable·not_paused → run_id, read_only → path, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: RequestFailedCode
    column: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    decision: Annotated[
        dict[str, Any] | None,
        Field(
            description="권한 판정 결과 (permission_denied·approval_required). kookabug_core.permissions.Decision 그대로"
        ),
    ] = None
    diagnostics: list[Diagnostic] | None = None
    line: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    message: str | None = None
    path: str | None = None
    protocol: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    revision: str | None = None
    run_id: RunId | None = None


class RunChildrenParams(BaseModel):
    """
    그 스텝 바로 아래 스텝을 쪽으로 읽는다. 반복 스텝이면 iteration으로 회차를 고른다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    iteration: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    limit: Annotated[int, Field(ge=1, le=500)]
    offset: Annotated[int, Field(ge=0, le=9007199254740991)]
    parent: StepId
    run_id: RunId


class RunCompareParams(BaseModel):
    """
    baseline을 빼면 기준 실행을 고른다 (같은 테스트·같은 프로필·pass·디버거 개입 아님 중 이 실행보다 먼저 시작한 가장 최근). step은 화면을 비교할 스텝 (빼면 실패 스텝)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: RunId | None = None
    run_id: RunId
    step: StepId | None = None


class RunEndedParams(BaseModel):
    """
    감독자 마무리와 파일 끝까지 보낸 뒤
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    last_seq: Annotated[int, Field(ge=0, le=9007199254740991)]
    outcome: RunOutcome
    run_id: RunId


class RunEventParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    event: Annotated[Any, Field(description="events.jsonl 한 줄 (events.schema.json 형식 그대로)")]
    run_id: RunId
    seq: Seq


class RunExportParams(BaseModel):
    """
    실행 폴더를 zip으로 내보낸다 (Electron 주 프로세스 내부용: dest는 저장 대화 상자가 고른 절대 경로). dest 옆 임시 파일에 쓰고 끝나면 replace. 진행 중 실행은 run_active
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    dest: Annotated[str, Field(min_length=1)]
    run_id: RunId


class RunFileParams(BaseModel):
    """
    run.json 원문, 또는 events.jsonl 끝부분 (1 MiB까지)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    name: Literal["events_tail", "run.json"]
    run_id: RunId


class RunListParams(BaseModel):
    """
    최신순. before는 앞 쪽 결과의 next (그보다 먼저 시작한 실행부터). graph(이 테스트 그래프의 실행만)·verdict(이 판정의 끝난 실행만)는 거르기 (M3)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    before: Annotated[
        str | None,
        Field(description="쪽 커서 (앞 결과의 next 그대로, 뜻은 daemon만 안다)", min_length=1),
    ] = None
    graph: WorkspacePath | None = None
    limit: Annotated[int | None, Field(ge=1, le=1000)] = None
    verdict: Verdict | None = None


class RunStartParams(BaseModel):
    """
    디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    idempotency_key: Annotated[str | None, Field(min_length=1)] = None
    path: WorkspacePath
    profile: str | None = None
    settings: Annotated[
        dict[str, Any] | None, Field(description="$setting 키 → 값 (CLI --set)")
    ] = None


class RunStartResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    graph: WorkspacePath
    run_dir: str
    run_id: RunId


class RunStatusResult(BaseModel):
    """
    실행 요약 + 실행 스냅샷의 호출 관계 (화면이 실행 중 강조를 실행한 그래프 파일에 붙인다. 편집 버퍼가 아니라 스냅샷 기준)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    calls: Annotated[
        dict[str, dict[str, WorkspacePath]],
        Field(
            description="스냅샷 그래프 파일(워크스페이스 기준) → 그 그래프의 호출 노드. 스냅샷을 아직 만들지 않았으면 빈 객체"
        ),
    ]
    graph: WorkspacePath
    last_seq: Annotated[int, Field(ge=0, le=9007199254740991)]
    outcome: RunOutcome | None
    run_dir: str
    run_id: RunId
    started_at: Timestamp | None
    state: Literal["ended", "running"]


class RunStepParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: RunId
    step: StepId


class RunSummary(BaseModel):
    """
    실행 요약 (record.reader.read_run). outcome은 끝난 실행만. code부터 아래 필드는 M3 run.list가 채운다(run.json에서 읽고, 없으면 뺀다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: str | None = None
    debug_intervened: Annotated[bool | None, Field(description='배지 "디버거 개입"')] = None
    duration_ms: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    failure_path: Annotated[
        FailurePath | None, Field(description="실패 위치 호출 경로 (노드 ID)")
    ] = None
    failure_title: Annotated[
        str | None,
        Field(description="실패 위치를 노드 제목으로 이은 것 (예: 월드 접속 > 타이틀 대기)"),
    ] = None
    flaky: Annotated[
        bool | None,
        Field(
            description='배지 "불안정": 재시도 끝에 성공한 스텝이 있는 pass (run.json retried_steps)'
        ),
    ] = None
    game_build: str | None = None
    graph: WorkspacePath
    last_seq: Annotated[int, Field(ge=0, le=9007199254740991)]
    outcome: RunOutcome | None
    profile: str | None = None
    reason: str | None = None
    run_dir: str
    run_id: RunId
    started_at: Timestamp | None
    state: Literal["ended", "running"]


class SessionHelloParams(BaseModel):
    """
    연결의 첫 메시지 (5초 안). 토큰은 session.json의 token
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client: ClientInfo
    protocol: Annotated[int, Field(ge=1, le=9007199254740991)]
    token: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class TargetLoadImageParams(BaseModel):
    """
    워크스페이스·실행 폴더 PNG
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath


class TargetOpenParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath


class TargetOpenResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    diagnostics: list[Diagnostic]
    image: ImageRef | None
    revision: TargetRevision
    spec: Annotated[dict[str, Any], Field(description="target 파일 값 (target 형식)")]


class TargetPreviewParams(BaseModel):
    """
    저장 전 사양으로 그 프레임에서 찾는다. base_path는 image 경로를 풀 target 파일 경로
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_path: WorkspacePath | None = None
    frame_id: Annotated[str, Field(min_length=1)]
    seq: RequestSeq
    spec: Annotated[dict[str, Any], Field(description="저장 전 target 사양")]
    template: PreviewTemplate


class TargetSaveParams(BaseModel):
    """
    새 파일이면 base_revision null(파일이 있으면 exists), 기존 파일이면 target.open의 revision (M2 계획 2.9 저장 단계). crop이 없으면 이미지를 새로 만들지 않고 지금 image·recorded를 그대로 둔 채 JSON만 저장한다(기존 파일만, 검색 범위는 recorded.client_size 기준)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: TargetRevision | None
    crop: CropRef | None = None
    path: WorkspacePath
    spec: dict[str, Any]


class TargetSaveResult(BaseModel):
    """
    preview = 저장한 파일을 다시 읽어 crop의 정지 화면에서 찾은 결과 (바로 매칭). crop 없이 저장했으면 찾을 정지 화면이 없어 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    image: WorkspacePath
    preview: PreviewResult | None
    revision: TargetRevision
    warnings: list[str]


class TreeEntry(BaseModel):
    """
    탐색기 항목. 그래프는 graph_kind, 읽을 수 없으면 problem
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    git_ignored: bool | None = None
    graph_kind: Literal["subgraph", "test"] | None = None
    kind: Literal["agents", "graph", "lock", "other", "screen", "target", "workspace"] | None = None
    name_only: Annotated[
        bool | None, Field(description="runs/·.kookabug/처럼 이름만 보이고 안을 나열하지 않는 폴더")
    ] = None
    path: WorkspacePath
    problem: str | None = None
    type: Literal["dir", "file"]


class WorkspaceChangedParams(BaseModel):
    """
    1초 폴링으로 바뀐 파일 (mtime·크기)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    paths: list[WorkspacePath]


class WorkspaceTreeResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    entries: list[TreeEntry]


class DaemonRequestFailedError(BaseModel):
    """
    앱 오류 -32100 request_failed. data(종류 data.code와 추가 필드)가 반드시 있다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: Literal[-32100]
    data: RequestFailedData
    message: str


class Frame(BaseModel):
    """
    편집기 정지 화면 (daemon 프레임 캐시, 최대 16장. 사라지면 frame_expired)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_size: Size
    dpi: Annotated[int, Field(ge=1, le=9007199254740991)]
    frame_id: Annotated[str, Field(min_length=1)]
    height: Annotated[int, Field(ge=0, le=9007199254740991)]
    image: ImageRef
    width: Annotated[int, Field(ge=0, le=9007199254740991)]


class GraphOpenResult(BaseModel):
    """
    value는 Python이 읽은 값. 원문 텍스트는 보내지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    canonical: Annotated[bool, Field(description="원문이 canonical 형식인가")]
    diagnostics: list[Diagnostic]
    doc_id: DocId
    read_only: Annotated[
        bool | None,
        Field(
            description="실행 폴더(runs/ 아래)의 스냅샷 그래프라 읽기만 한다. graph.save는 read_only로 거부 (M3, 없으면 false)"
        ),
    ] = None
    revision: Revision
    shapes: NodeShapes
    value: GraphValue


class GraphValidateResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    diagnostics: list[Diagnostic]
    seq: RequestSeq
    shapes: NodeShapes


class GraphCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphCreateParams
    renderer: Literal[True]
    result: GraphOpenResult
    tool: Literal["kb_graph_create"]


class GraphOpen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphOpenParams
    renderer: Literal[True]
    result: GraphOpenResult
    tool: Literal["kb_graph_get"]


class GraphValidate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphValidateParams
    renderer: Literal[True]
    result: GraphValidateResult
    tool: Literal["kb_graph_validate"]


class RunChildren(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunChildrenParams
    renderer: Literal[True]
    result: RunChildrenResult
    tool: Literal["kb_run_events"]


class RunCompare(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunCompareParams
    renderer: Literal[True]
    result: RunCompareResult
    tool: Literal["kb_run_events"]


class RunExport(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunExportParams
    renderer: Literal[False]
    result: RunExportResult
    tool: Literal["ui_only"]


class RunFile(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunFileParams
    renderer: Literal[True]
    result: RunFileResult
    tool: Literal["kb_run_events"]


class RunRestart(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[True]
    result: RunStartResult
    tool: Literal["ui_only"]


class RunStart(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunStartParams
    renderer: Literal[True]
    result: RunStartResult
    tool: Literal["kb_run_start"]


class RunStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[True]
    result: RunStatusResult
    tool: Literal["kb_run_status"]


class RunStep(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunStepParams
    renderer: Literal[True]
    result: RunStepResult
    tool: Literal["kb_run_events"]


class SessionHello(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: SessionHelloParams
    renderer: Literal[False]
    result: SessionHelloResult
    tool: Literal["ui_only"]


class TargetCapture(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: TargetCaptureParams
    renderer: Literal[True]
    result: Frame
    tool: Literal["kb_screen_capture"]


class TargetLoadImage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: TargetLoadImageParams
    renderer: Literal[True]
    result: Frame
    tool: Literal["kb_image_find"]


class TargetOpen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: TargetOpenParams
    renderer: Literal[True]
    result: TargetOpenResult
    tool: Literal["kb_image_find"]


class TargetPreview(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: TargetPreviewParams
    renderer: Literal[True]
    result: PreviewResult
    tool: Literal["kb_image_find"]


class TargetSave(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: TargetSaveParams
    renderer: Literal[True]
    result: TargetSaveResult
    tool: Literal["kb_target_create"]


class WorkspaceTree(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: WorkspaceTreeResult
    tool: Literal["kb_project_info"]


class RunEnded(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunEndedParams


class RunEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunEventParams


class WorkspaceChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: WorkspaceChangedParams


class Notifications(BaseModel):
    """
    알림 표 (daemon → 클라이언트). 타입 표다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    debug_breakpoints_changed: Annotated[
        DebugBreakpointsChanged, Field(alias="debug.breakpoints.changed")
    ]
    graph_changed: Annotated[GraphChanged, Field(alias="graph.changed")]
    lease_changed: Annotated[LeaseChanged, Field(alias="lease.changed")]
    run_ended: Annotated[RunEnded, Field(alias="run.ended")]
    run_event: Annotated[RunEvent, Field(alias="run.event")]
    run_lagged: Annotated[RunLagged, Field(alias="run.lagged")]
    workspace_changed: Annotated[WorkspaceChanged, Field(alias="workspace.changed")]


class RunListResult(BaseModel):
    """
    최근 실행부터. next가 null이면 마지막 쪽
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    next: str | None = None
    runs: list[RunSummary]
    runs_bytes: Annotated[
        int | None,
        Field(
            description="runs/ 폴더 합계 크기 (캐시, 1분마다 다시 잼). 모르면 없음",
            ge=0,
            le=9007199254740991,
        ),
    ] = None


class DaemonErrorObject(RootModel[DaemonStandardError | DaemonRequestFailedError]):
    root: Annotated[
        DaemonStandardError | DaemonRequestFailedError,
        Field(description="표준 오류 또는 -32100 (DaemonErrorCode)", title="DaemonErrorObject"),
    ]


class DaemonErrorResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: DaemonErrorObject
    id: Annotated[
        RequestId | None, Field(description="요청을 읽지 못했으면(JSON 아님·id 없음) null")
    ]
    jsonrpc: JsonRpcVersion


class RunList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunListParams
    renderer: Literal[True]
    result: RunListResult
    tool: Literal["kb_run_status"]


class Methods(BaseModel):
    """
    메서드 표 (단일 출처). 메시지가 아니라 타입 표다: params·result 모양, 권한 도구, 렌더러 표면에 내놓는지(false = Electron 주 프로세스 내부용)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    daemon_shutdown: Annotated[DaemonShutdown, Field(alias="daemon.shutdown")]
    debug_breakpoints_get: Annotated[DebugBreakpointsGet, Field(alias="debug.breakpoints.get")]
    debug_breakpoints_set: Annotated[DebugBreakpointsSet, Field(alias="debug.breakpoints.set")]
    graph_close: Annotated[GraphClose, Field(alias="graph.close")]
    graph_create: Annotated[GraphCreate, Field(alias="graph.create")]
    graph_open: Annotated[GraphOpen, Field(alias="graph.open")]
    graph_save: Annotated[GraphSave, Field(alias="graph.save")]
    graph_validate: Annotated[GraphValidate, Field(alias="graph.validate")]
    nodes_list: Annotated[NodesList, Field(alias="nodes.list")]
    run_cancel: Annotated[RunCancel, Field(alias="run.cancel")]
    run_children: Annotated[RunChildren, Field(alias="run.children")]
    run_compare: Annotated[RunCompare, Field(alias="run.compare")]
    run_export: Annotated[RunExport, Field(alias="run.export")]
    run_file: Annotated[RunFile, Field(alias="run.file")]
    run_index: Annotated[RunIndex, Field(alias="run.index")]
    run_list: Annotated[RunList, Field(alias="run.list")]
    run_pause: Annotated[RunPause, Field(alias="run.pause")]
    run_restart: Annotated[RunRestart, Field(alias="run.restart")]
    run_resume: Annotated[RunResume, Field(alias="run.resume")]
    run_start: Annotated[RunStart, Field(alias="run.start")]
    run_status: Annotated[RunStatus, Field(alias="run.status")]
    run_step: Annotated[RunStep, Field(alias="run.step")]
    run_subscribe: Annotated[RunSubscribe, Field(alias="run.subscribe")]
    run_unsubscribe: Annotated[RunUnsubscribe, Field(alias="run.unsubscribe")]
    session_hello: Annotated[SessionHello, Field(alias="session.hello")]
    target_capture: Annotated[TargetCapture, Field(alias="target.capture")]
    target_load_image: Annotated[TargetLoadImage, Field(alias="target.load_image")]
    target_open: Annotated[TargetOpen, Field(alias="target.open")]
    target_preview: Annotated[TargetPreview, Field(alias="target.preview")]
    target_save: Annotated[TargetSave, Field(alias="target.save")]
    windows_list: Annotated[WindowsList, Field(alias="windows.list")]
    workspace_info: Annotated[WorkspaceInfo, Field(alias="workspace.info")]
    workspace_tree: Annotated[WorkspaceTree, Field(alias="workspace.tree")]


class DaemonRpcMessage(RootModel[Request | Notification | SuccessResponse | DaemonErrorResponse]):
    root: Annotated[
        Request | Notification | SuccessResponse | DaemonErrorResponse,
        Field(
            description="UI·에이전트 ↔ daemon JSON-RPC 2.0 메시지 하나 (WebSocket 텍스트 프레임 하나, UTF-8 JSON, 최대 16 MiB). 값 규칙은 M0b와 같다: NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단. 메서드·알림 모양은 $defs의 Methods·Notifications 표",
            title="DaemonRpcMessage",
        ),
    ]

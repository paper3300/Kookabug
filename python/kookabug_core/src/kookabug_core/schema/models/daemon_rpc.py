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
            "ocr_model_corrupt",
            "ocr_model_missing",
            "path_outside_workspace",
            "permission_denied",
            "platform_unavailable",
            "point_obscured",
            "private_path",
            "protocol_mismatch",
            "revision_conflict",
            "run_active",
            "run_busy",
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
            "ocr_model_corrupt",
            "ocr_model_missing",
            "path_outside_workspace",
            "permission_denied",
            "platform_unavailable",
            "point_obscured",
            "private_path",
            "protocol_mismatch",
            "revision_conflict",
            "run_active",
            "run_busy",
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
            description="-32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로",
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


class RunLaggedParams(BaseModel):
    """
    송신 큐가 차서 구독을 끊음 → 다시 구독
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: RunId


class RunListParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    limit: Annotated[int | None, Field(ge=1, le=1000)] = None


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


class RunSubscribeParams(BaseModel):
    """
    after_seq = 클라이언트가 실제로 적용한 마지막 seq (처음이면 0). 순서·커서 규칙은 M2 계획 2.8
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    after_seq: Annotated[int, Field(ge=0, le=9007199254740991)]
    run_id: RunId


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
            description="권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon.shutdown만 거부)",
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
    diagnostics: list[Diagnostic]
    plugins: list[PluginSummary]
    profiles: list[str]
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
    error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found → run_id, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message
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


class RunSummary(BaseModel):
    """
    실행 요약 (record.reader.read_run). outcome은 끝난 실행만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    graph: WorkspacePath
    last_seq: Annotated[int, Field(ge=0, le=9007199254740991)]
    outcome: RunOutcome | None
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
    새 파일이면 base_revision null(파일이 있으면 exists), 기존 파일이면 target.open의 revision (M2 계획 2.9 저장 단계)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: TargetRevision | None
    crop: CropRef
    path: WorkspacePath
    spec: dict[str, Any]


class TargetSaveResult(BaseModel):
    """
    preview = 저장한 파일을 다시 읽어 같은 정지 화면에서 찾은 결과 (바로 매칭)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    image: WorkspacePath
    preview: PreviewResult
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
    result: RunSummary
    tool: Literal["kb_run_status"]


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
    graph_changed: Annotated[GraphChanged, Field(alias="graph.changed")]
    lease_changed: Annotated[LeaseChanged, Field(alias="lease.changed")]
    run_ended: Annotated[RunEnded, Field(alias="run.ended")]
    run_event: Annotated[RunEvent, Field(alias="run.event")]
    run_lagged: Annotated[RunLagged, Field(alias="run.lagged")]
    workspace_changed: Annotated[WorkspaceChanged, Field(alias="workspace.changed")]


class RunListResult(BaseModel):
    """
    최근 실행부터
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    runs: list[RunSummary]


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
    graph_close: Annotated[GraphClose, Field(alias="graph.close")]
    graph_create: Annotated[GraphCreate, Field(alias="graph.create")]
    graph_open: Annotated[GraphOpen, Field(alias="graph.open")]
    graph_save: Annotated[GraphSave, Field(alias="graph.save")]
    graph_validate: Annotated[GraphValidate, Field(alias="graph.validate")]
    nodes_list: Annotated[NodesList, Field(alias="nodes.list")]
    run_cancel: Annotated[RunCancel, Field(alias="run.cancel")]
    run_list: Annotated[RunList, Field(alias="run.list")]
    run_start: Annotated[RunStart, Field(alias="run.start")]
    run_status: Annotated[RunStatus, Field(alias="run.status")]
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

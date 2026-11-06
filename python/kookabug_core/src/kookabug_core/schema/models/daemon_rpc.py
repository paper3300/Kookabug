# 생성물 (packages/schema/daemon-rpc.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class AgentCandidate(BaseModel):
    """
    감지 표의 에이전트 하나 (kookabug_core.agents.detect). 경로에서 찾기만 하고 설치하지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    args: list[str]
    command: str
    id: str
    installed: bool
    name: str
    path: Annotated[str | None, Field(description="찾은 실행 파일 (없으면 null)")]


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


class AgentConnectionsChangedParams(BaseModel):
    """
    agent 연결이 붙거나 끊기거나 툴셋을 켬 (ui 연결에만). 목록은 agent.connections로 다시 읽는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class AgentSecretRef(BaseModel):
    """
    비밀값 저장소의 키 (값은 실행 때 찾는다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_secret: Annotated[str, Field(alias="$secret", min_length=1)]


class AgentSpec(BaseModel):
    """
    판단 노드·에이전트 패널이 띄우는 ACP 에이전트 하나. env의 비밀값은 {"$secret": 키}로만 쓴다 (실행 때 찾음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    args: list[str] | None = None
    command: Annotated[str, Field(min_length=1)]
    env: Annotated[
        dict[str, str | AgentSecretRef] | None,
        Field(
            description="환경 변수 (이름 규칙은 사용자 설정 스키마가 쓰기 때 본다 — 틀리면 settings_invalid)"
        ),
    ] = None
    id: Annotated[str, Field(pattern="^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]
    name: Annotated[str, Field(min_length=1)]


class AgentsDetectResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    candidates: list[AgentCandidate]


class AppLaunchParams(BaseModel):
    """
    게임을 띄운다 (설정 game.executable·game.args·game.cwd, 프로필 계층 포함). 실행·녹화 중이면 거부. 실행 Job 밖
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    profile: str | None = None


class AppLaunchResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pid: Annotated[int, Field(ge=1, le=9007199254740991)]


class ApprovalAnswer(RootModel[Literal["allow_always", "allow_once", "deny"]]):
    root: Annotated[
        Literal["allow_always", "allow_once", "deny"],
        Field(
            description="사람 확인 답 (M5 3.6). allow_always는 프로젝트 계층(.kookabug/local.json)에 그 도구·인자에만 맞는 allow 규칙을 더한 뒤 실행한다. control 도구에는 받지 않는다(always_not_allowed)",
            title="ApprovalAnswer",
        ),
    ]


class ApprovalId(RootModel[str]):
    root: Annotated[
        str,
        Field(description="사람 확인 요청 ID", pattern="^ap_[0-9a-f]{16}$", title="ApprovalId"),
    ]


class ApprovalIdParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: ApprovalId


class ApprovalAgent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    name: str


class ApprovalResolvedParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    by: Annotated[
        str, Field(description="답한 ui 연결(ui:<번호>) 또는 daemon(시간 초과·요청 연결 끊김)")
    ]
    id: ApprovalId
    verdict: Literal["allow_always", "allow_once", "cancelled", "deny", "timeout"]


class ApprovalRespondParams(BaseModel):
    """
    사람 확인 답. 끝난(답함·시간 초과·취소) 요청이면 not_found
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: ApprovalId
    verdict: ApprovalAnswer


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


class PointItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class ControlKeyParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    keys: Annotated[
        str, Field(description="키 하나나 조합 (ctrl+a). 누르고 바로 뗀다", min_length=1)
    ]
    window: Annotated[
        str, Field(description="창 제목 (정확히 같은 제목의 창, 권한 인자)", min_length=1)
    ]


class ControlError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: str
    message: str | None = None


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


class AgentImage(BaseModel):
    """
    agent 연결의 target.capture만 (M5 kb_screen_capture): 긴 변 1568·1 MiB 이하 PNG를 .kookabug/cache/agent/<cache>에 썼다 (읽은 쪽이 지운다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    cache: Annotated[str, Field(pattern="^c\\d+/[0-9a-f]{16}\\.png$")]
    height: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1)]


class GraphCheckResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    diagnostics: list[Diagnostic]


class GraphCloseParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    doc_id: DocId


class GraphListParams(BaseModel):
    """
    그래프 파일 목록 (kb_graph_list로 판정, M5). 범위는 workspace.tree와 같다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    under: Annotated[str | None, Field(description="이 폴더 아래만 (예: tests). 권한 인자")] = None


class GraphPatchNodeRef(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="노드 ID 또는 같은 묶음의 add_node ref",
            min_length=1,
            title="GraphPatchNodeRef",
        ),
    ]


class GraphPatchOpSetNode(BaseModel):
    """
    노드 고치기 (type·id는 바꿀 수 없다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    config: Annotated[
        dict[str, Any] | None, Field(description="키 단위 병합. 값이 null이면 그 키를 지운다")
    ] = None
    id: GraphPatchNodeRef
    in_: Annotated[
        dict[str, Any] | None,
        Field(alias="in", description="키 단위 병합. 값이 null이면 그 키를 지운다"),
    ] = None
    op: Literal["set_node"]
    record: dict[str, Any] | None = None
    title: str | None = None


class GraphPatchOpRemoveNode(BaseModel):
    """
    노드와 그 노드를 가리키는 next·$link를 지운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: GraphPatchNodeRef
    op: Literal["remove_node"]


class GraphPatchOpConnect(BaseModel):
    """
    exec 연결 (next)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exit: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$")]
    from_: Annotated[GraphPatchNodeRef, Field(alias="from")]
    op: Literal["connect"]
    to: GraphPatchNodeRef


class GraphPatchOpDisconnect(BaseModel):
    """
    exec 연결 끊기
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exit: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$")]
    from_: Annotated[GraphPatchNodeRef, Field(alias="from")]
    op: Literal["disconnect"]


class GraphPatchOpLink(BaseModel):
    """
    데이터 연결 ($link)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    from_: Annotated[GraphPatchNodeRef, Field(alias="from")]
    op: Literal["link"]
    output: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$")]
    pin: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$")]
    to: GraphPatchNodeRef


class GraphPatchOpUnlink(BaseModel):
    """
    데이터 연결 끊기 (그 핀 값을 지운다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    op: Literal["unlink"]
    pin: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$")]
    to: GraphPatchNodeRef


class GraphPatchOpSetMeta(BaseModel):
    """
    그래프 머리 (null이면 지운다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    op: Literal["set_meta"]
    title: str | None = None


class GraphPatchPosition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    x: float
    y: float


class GraphPatchRemovedRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    from_: Annotated[str, Field(alias="from")]
    key: Annotated[str, Field(description="next면 출구 이름, link면 핀 이름")]
    kind: Literal["link", "next"]


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


class LeaseDevice(BaseModel):
    """
    소유자가 입력을 보내는 장치. 다음 획득자가 앞 소유자의 키를 이 장치로 뗀다. none은 입력 장치가 없는 소유자(녹화) — 뗄 것이 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    input_log: Annotated[
        str | None, Field(description="fake 장치의 입력 기록 파일 (절대 경로)", min_length=1)
    ] = None
    kind: Literal["fake", "none", "windows"]


class Created(RootModel[int]):
    root: Annotated[
        int, Field(description="프로세스 생성 시각 (Windows FILETIME, 100ns 단위)", ge=0)
    ]


class Created1(RootModel[str]):
    root: Annotated[
        str,
        Field(description="프로세스 생성 시각 (Windows FILETIME, 100ns 단위)", pattern="^[0-9]+$"),
    ]


class LeaseOwner(BaseModel):
    """
    입력 임대권 소유자 (옆 파일 input-lease.json의 owner, lease.changed 알림, input_lease_busy 오류). 예전 옆 파일(M0b: kind 둘·device 없음)도 맞는다. created는 FILETIME이라 옆 파일은 정수, 알림·오류는 10진 문자열. 녹화 소유자(recorder)는 실행이 없어 run_id·run_dir이 null(또는 없음)이고 장치는 none
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    created: Annotated[
        Created | Created1, Field(description="프로세스 생성 시각 (Windows FILETIME, 100ns 단위)")
    ]
    device: LeaseDevice | None = None
    kind: Annotated[Any, Field(description="urn:kookabug:events:0#/$defs/LeaseOwnerKind")]
    pid: Annotated[int, Field(ge=0, le=9007199254740991)]
    run_dir: str | None = None
    run_id: str | None = None
    workspace: str | None = None


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


class AgentsDetect(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: AgentsDetectResult
    tool: Literal["ui_only"]


class AppLaunch(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: AppLaunchParams
    renderer: Literal[False]
    result: AppLaunchResult
    tool: Literal["kb_app_launch"]


class ApprovalRespond(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ApprovalRespondParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["ui_only"]


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


class AgentConnectionsChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: AgentConnectionsChangedParams


class ApprovalResolved(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ApprovalResolvedParams


class DebugBreakpointsChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: BreakpointsResult


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


class PermissionVerdict(RootModel[Literal["allow", "ask", "deny"]]):
    root: Annotated[
        Literal["allow", "ask", "deny"],
        Field(description="권한 판정 값", title="PermissionVerdict"),
    ]


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


class PluginEnvStatus(RootModel[Literal["ready", "missing", "stale", "broken"]]):
    root: Annotated[
        Literal["ready", "missing", "stale", "broken"],
        Field(
            description="ready 준비됨 · missing 환경 없음([준비…]) · stale 조건(Python·SDK)이 앱과 다름([다시 잠그기…]) · broken 환경이 깨짐([준비…]로 새로)",
            title="PluginEnvStatus",
        ),
    ]


class PluginGcCandidates(BaseModel):
    """
    gc가 지울 후보 이름 (표시용 — 실제 gc는 검증한 선택으로 다시 판정한다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    envs: list[str]
    staging: list[str]
    wheels: list[str]


class PluginInstalled(BaseModel):
    """
    nodes.list의 설치 플러그인 요약 (kb_node_search가 노드마다 보인다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    env: str
    env_status: PluginEnvStatus
    id: str
    permissions: list[str]
    title: str | None = None
    version: str


class PluginIsolation(RootModel[Literal["auto", "shared", "isolated"]]):
    root: Annotated[Literal["auto", "shared", "isolated"], Field(title="PluginIsolation")]


class PluginNodeInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    effects: list[str]
    title: str | None = None
    type: str


class PluginOpId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="플러그인 작업 ID (= 설치 거래 ID, 작업 로그 이름)",
            pattern="^[0-9a-f]{32}$",
            title="PluginOpId",
        ),
    ]


class PluginOpKind(RootModel[Literal["install", "upgrade", "remove", "sync", "relock", "gc"]]):
    root: Annotated[
        Literal["install", "upgrade", "remove", "sync", "relock", "gc"],
        Field(title="PluginOpKind"),
    ]


class PluginSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    title: str | None = None
    version: str


class PluginsOpIdParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    op_id: PluginOpId


class PluginsOpResult(BaseModel):
    """
    작업을 시작했다. 진행은 plugins.progress, 끝은 plugins.done
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    op_id: PluginOpId


class PluginsPreviewParams(BaseModel):
    """
    원천: git+<url>[@ref] · *.whl 경로·https URL(sha256 필수) · 폴더. 받고 정적으로 읽기만 한다 (코드 실행 없음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    isolation: PluginIsolation | None = None
    ref: Annotated[str | None, Field(min_length=1)] = None
    sha256: Annotated[str | None, Field(pattern="^[0-9a-fA-F]{64}$")] = None
    source: Annotated[str, Field(min_length=1)]


class PluginsPreviewResult(BaseModel):
    """
    신뢰 확인 재료 (설치 거래 ①②). expires_in_s 안에 plugins.install {op_id}로 승인, plugins.cancel로 취소. untrusted = 이 PC에서 신뢰 확인하지 않은 잠금이면 함께 신뢰할 기존 플러그인 ID 전체
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    dependencies: list[str]
    dist: str
    expires_in_s: Annotated[float, Field(ge=0.0)]
    id: str
    isolation: PluginIsolation
    op_id: PluginOpId
    permissions: list[str]
    replaces: Annotated[str | None, Field(description="upgrade면 바꾸는 판")]
    source: Annotated[dict[str, Any], Field(description="원천 출처 (인증 정보 없음)")]
    title: str | None
    untrusted: list[str]
    version: str


class PluginsProgressParams(BaseModel):
    """
    플러그인 작업 진행 (ui 연결에만). stage = 거래 단계 (kookabug_core.plugins.STAGES)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    message: str
    op_id: PluginOpId
    stage: str


class PluginsUpgradeParams(BaseModel):
    """
    잠금의 원천을 다시 받아 미리보기 (plugins.preview와 같은 흐름 — plugins.install {op_id}로 승인)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    isolation: PluginIsolation | None = None
    ref: Annotated[str | None, Field(min_length=1)] = None
    sha256: Annotated[str | None, Field(pattern="^[0-9a-fA-F]{64}$")] = None


class SearchItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class Scale(RootModel[float]):
    root: Annotated[float, Field(ge=0.0)]


class Score(RootModel[float]):
    root: Annotated[float, Field(ge=-1.0, le=1.0)]


class PreviewScaleScore(BaseModel):
    """
    다른 배율 점수 한 줄: factor = 정지 화면을 바꾼 배율, found = 그 화면에서 찾음, score = 받아들인(없으면 최고) 점수 (시도한 것이 없으면 null), scale = 그 후보의 배율
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    factor: float
    found: bool
    scale: Scale | None
    score: Score | None


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


class RecorderBadge(BaseModel):
    """
    스텝 메모 (시안 '녹화된 스텝'의 메모 줄). severity review는 확인 필요(노랑·주황). 글자 원문을 담지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$")]
    message: str | None = None
    severity: Literal["info", "review", "warning"]


class RecorderCommitToken(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="커밋 토큰 (commit_prepare가 주고 commit_finish·commit_abort가 받는다)",
            pattern="^[A-Za-z0-9_-]{16,64}$",
            title="RecorderCommitToken",
        ),
    ]


class RecorderCommitTokenParams(BaseModel):
    """
    recorder.commit_abort: 그래프 단계가 실패 → stopped로 돌아가 다른 이름·위치로 다시 commit_prepare (써진 target 재사용)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    token: RecorderCommitToken


class RecorderCounts(BaseModel):
    """
    스텝·만든 target 수와 녹화하지 않은 입력 수 (다른 프로그램이 보낸 입력, 게임 창 밖, 게임의 팝업 창)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    ignored_injected: Annotated[int, Field(ge=0, le=9007199254740991)]
    ignored_outside: Annotated[int, Field(ge=0, le=9007199254740991)]
    ignored_popup: Annotated[int, Field(ge=0, le=9007199254740991)]
    steps: Annotated[int, Field(ge=0, le=9007199254740991)]
    targets: Annotated[int, Field(ge=0, le=9007199254740991)]


class RecorderFrameWhich(RootModel[Literal["live", "pre_click", "pre_hover", "pre_next"]]):
    root: Annotated[
        Literal["live", "pre_click", "pre_hover", "pre_next"],
        Field(title="RecorderFrameWhich"),
    ]


class RecorderHotkey(BaseModel):
    """
    Electron 주 프로세스가 녹화 중에만 등록한 단축키. 변환기가 이 조합의 키 이벤트와 그 조합 때문에만 눌린 수정 키를 지운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    keys: Annotated[
        str,
        Field(
            description="키 이름 조합 (입력 노드 keys와 같은 이름, 예: ctrl+shift+r)",
            pattern="^[a-z0-9_]+(\\+[a-z0-9_]+)*$",
        ),
    ]
    role: Literal["mark_secret", "stop"]


class RecorderNeedsReviewReason(
    RootModel[
        Literal[
            "cursor_moved_in_field",
            "cut_by_stop",
            "field_box_unknown",
            "geometry_unresolved",
            "ime_unknown",
            "no_evidence",
            "no_frame",
            "secret_overlap",
            "wait_target_unknown",
            "window_undetermined",
        ]
    ]
):
    root: Annotated[
        Literal[
            "cursor_moved_in_field",
            "cut_by_stop",
            "field_box_unknown",
            "geometry_unresolved",
            "ime_unknown",
            "no_evidence",
            "no_frame",
            "secret_overlap",
            "wait_target_unknown",
            "window_undetermined",
        ],
        Field(
            description="스텝을 사람이 확인해야 하는 이유 (커밋 전 남기거나 지움). geometry_unresolved 클릭과 프레임의 기하 세대가 확정적으로 같지 않음, no_frame 클릭 직전 프레임이 없음, window_undetermined 어느 창에 들어간 입력인지 판정 불가, ime_unknown 입력기 상태 판정 불가, cursor_moved_in_field 칸 안에서 커서를 옮김, field_box_unknown 칸 상자를 못 정함, no_evidence 비밀 근거도 일반 근거도 없음, cut_by_stop 정지·끊김 순간의 입력, secret_overlap 비밀번호 칸과 겹쳐 대상을 못 만듦, wait_target_unknown 기다릴 화면을 못 정함",
            title="RecorderNeedsReviewReason",
        ),
    ]


class RecorderOptions(BaseModel):
    """
    변환 옵션 (시안 체크). 커밋 때 적용하므로 녹화 뒤에 바꿔도 된다. 없는 값은 켬. 'Kookabug가 보낸 입력은 녹화하지 않기'는 항상 켬이라 옵션이 아니다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    crop_targets: Annotated[
        bool | None,
        Field(
            description="클릭 직전 화면에서 클릭 지점 주변을 잘라 찾기 대상 만들기 (끄면 core.input.click 픽셀 좌표)"
        ),
    ] = None
    wait_as_appear: Annotated[
        bool | None,
        Field(description="기다린 시간을 '나타날 때까지 대기'로 바꾸기 (끄면 core.flow.delay)"),
    ] = None


class RecorderSessionId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="녹화 세션 ID: 소문자·숫자 8자",
            pattern="^[a-z0-9]{8}$",
            title="RecorderSessionId",
        ),
    ]


class Launch(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    profile: str | None = None


class RecorderStartParams1(BaseModel):
    """
    recorder.start: 떠 있는 창(window 핸들)에 붙어 녹화하거나, 워크스페이스 game.* 설정으로 게임을 띄워 녹화(launch, profile은 설정 계층). hotkeys는 주 프로세스가 등록에 성공한 단축키. 오류: input_lease_busy·recording_active·window_gone·capture_unsupported·hook_failed
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    hotkeys: list[RecorderHotkey]
    launch: Launch | None = None
    options: RecorderOptions | None = None
    window: Annotated[int, Field(description="창 handle", ge=0, le=9007199254740991)]


class RecorderStartParams2(BaseModel):
    """
    recorder.start: 떠 있는 창(window 핸들)에 붙어 녹화하거나, 워크스페이스 game.* 설정으로 게임을 띄워 녹화(launch, profile은 설정 계층). hotkeys는 주 프로세스가 등록에 성공한 단축키. 오류: input_lease_busy·recording_active·window_gone·capture_unsupported·hook_failed
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    hotkeys: list[RecorderHotkey]
    launch: Launch
    options: RecorderOptions | None = None
    window: Annotated[int | None, Field(description="창 handle", ge=0, le=9007199254740991)] = None


class RecorderStartParams(RootModel[RecorderStartParams1 | RecorderStartParams2]):
    root: Annotated[
        RecorderStartParams1 | RecorderStartParams2,
        Field(
            description="recorder.start: 떠 있는 창(window 핸들)에 붙어 녹화하거나, 워크스페이스 game.* 설정으로 게임을 띄워 녹화(launch, profile은 설정 계층). hotkeys는 주 프로세스가 등록에 성공한 단축키. 오류: input_lease_busy·recording_active·window_gone·capture_unsupported·hook_failed",
            title="RecorderStartParams",
        ),
    ]


class RecorderState(
    RootModel[
        Literal[
            "committed",
            "committing",
            "discarded",
            "idle",
            "paused",
            "recording",
            "starting",
            "stopped",
        ]
    ]
):
    root: Annotated[
        Literal[
            "committed",
            "committing",
            "discarded",
            "idle",
            "paused",
            "recording",
            "starting",
            "stopped",
        ],
        Field(
            description="녹화 세션 상태: idle → starting → recording ⇄ paused → stopped → committing → committed | stopped, 또는 discarded. 오류로 멈춤(hook_lost·input_overflow·window_gone·storage_full)도 stopped (stop_reason)",
            title="RecorderState",
        ),
    ]


class Node(BaseModel):
    """
    노드 초안 요약 (시안 '이미지 클릭 "강화"')
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    title: str
    type: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$")]


class RecorderStepId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="녹화 스텝 ID (세션 안에서 바뀌지 않음)",
            pattern="^rs[1-9][0-9]{0,8}$",
            title="RecorderStepId",
        ),
    ]


class EndItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class RecorderStepInput(BaseModel):
    """
    원래 입력 요약 (시안 'click (858, 562) · 00:09.4'). 좌표는 클라이언트 물리 픽셀. 글자는 싣지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    amount: Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)] = None
    button: Literal["left", "middle", "right", "x1", "x2"] | None = None
    count: Annotated[int | None, Field(ge=1, le=2)] = None
    duration_ms: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    end: Annotated[list[EndItem] | None, Field(max_length=2, min_length=2)] = None
    gap_ms: Annotated[
        int | None,
        Field(description="앞 동작부터 이 입력까지 (대기·지연 스텝)", ge=0, le=9007199254740991),
    ] = None
    hold_ms: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    keys: Annotated[str | None, Field(pattern="^[a-z0-9_]+(\\+[a-z0-9_]+)*$")] = None
    point: Annotated[list[PointItem] | None, Field(max_length=2, min_length=2)] = None


class RecorderStepsParams(BaseModel):
    """
    recorder.steps: 스텝 목록. after_rev는 마지막으로 받은 판 (같으면 steps가 그대로)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    after_rev: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None


class RecorderStopReason(
    RootModel[Literal["hook_lost", "input_overflow", "storage_full", "user", "window_gone"]]
):
    root: Annotated[
        Literal["hook_lost", "input_overflow", "storage_full", "user", "window_gone"],
        Field(
            description="녹화가 멈춘 까닭: user(정지 단추·단축키·커밋), hook_lost(훅 끊김), input_overflow(중요 입력 유실), window_gone(대상 창 닫힘), storage_full(세션 저장소 상한)",
            title="RecorderStopReason",
        ),
    ]


class RecorderTextState(RootModel[Literal["needs_review", "ordinary", "pending", "secret"]]):
    root: Annotated[
        Literal["needs_review", "ordinary", "pending", "secret"],
        Field(
            description="입력 칸 구간의 글자 판정: pending(판정 중) → ordinary(일반 글자 — 긍정 근거 또는 사람 확인) | secret(비밀값, 끈적) | needs_review(근거 없음 — 사람이 고를 때까지 커밋 거부)",
            title="RecorderTextState",
        ),
    ]


class RecorderWarning(BaseModel):
    """
    녹화 알림 (예: injected_ignored '다른 프로그램이 보낸 입력 N개는 녹화하지 않았어요', popup_ignored, not_foreground, no_assertion)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$")]
    count: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    message: str | None = None


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
            "classification_pending",
            "hook_failed",
            "hook_lost",
            "input_lease_busy",
            "input_overflow",
            "no_frame",
            "not_owner",
            "recorder_state_invalid",
            "recording_active",
            "secret_region_overlap",
            "secret_unresolved",
            "target_missing",
            "text_review_required",
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
            "toolset_disabled",
            "force_not_allowed",
            "patch_invalid",
            "agent_use_safe_api",
            "secret_step",
            "unclassified_run",
            "not_evidence",
            "video_not_served",
            "recorder_frame",
            "sensitive_region",
            "frame_not_owned",
            "approval_denied",
            "approval_timeout",
            "always_not_allowed",
            "settings_invalid",
            "recorder_store_unclean",
            "plugin_failed",
            "op_not_found",
        ]
    ]
):
    root: Annotated[
        Literal[
            "approval_required",
            "classification_pending",
            "hook_failed",
            "hook_lost",
            "input_lease_busy",
            "input_overflow",
            "no_frame",
            "not_owner",
            "recorder_state_invalid",
            "recording_active",
            "secret_region_overlap",
            "secret_unresolved",
            "target_missing",
            "text_review_required",
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
            "toolset_disabled",
            "force_not_allowed",
            "patch_invalid",
            "agent_use_safe_api",
            "secret_step",
            "unclassified_run",
            "not_evidence",
            "video_not_served",
            "recorder_frame",
            "sensitive_region",
            "frame_not_owned",
            "approval_denied",
            "approval_timeout",
            "always_not_allowed",
            "settings_invalid",
            "recorder_store_unclean",
            "plugin_failed",
            "op_not_found",
        ],
        Field(
            description="-32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로. M3: read_only(스냅샷 그래프 저장), not_paused(멈추지 않은 실행에 Step), run_not_debuggable(이 daemon이 띄운 UI 실행이 아님). M4 녹화: recording_active(이 daemon이 녹화 중이라 실행 거부 — starting 포함), input_lease_busy(입력 임대권을 다른 주체가 쥠), not_owner(녹화 세션을 연 연결이 아님), recorder_state_invalid(지금 녹화 상태에 맞지 않는 조작·없는 커밋 토큰), hook_failed(훅 프로세스를 띄우지 못함), hook_lost·input_overflow(훅이 끊김·중요 입력 유실로 녹화가 멈춤), no_frame(고를 프레임이 없음), 커밋 거부 classification_pending(비밀 판정 중)·text_review_required(확인 필요 입력)·secret_unresolved(키 없는 비밀값)·target_missing(대상 없는 클릭)·secret_region_overlap(비밀번호 칸과 겹치는 영역). M5: toolset_disabled(agent 연결이 켜지 않은 툴셋의 메서드 — 판정 전), force_not_allowed(agent 연결의 graph.save force), patch_invalid(graph.patch 연산이 틀림), agent_use_safe_api(agent 연결의 기록 원문 경로 — run.index·children·step·file·compare·subscribe, runs/ 이미지의 target.load_image·preview), secret_step(비밀값 스텝·agent_withhold 증거), unclassified_run(비밀값 분류 없는 옛 기록의 파일), not_evidence(그 실행의 증거 파일이 아님), video_not_served(영상 조각), recorder_frame(녹화 세션 프레임), sensitive_region(sensitive target이 보이는 화면의 OCR), frame_not_owned(agent 연결이 다른 연결이 만든 정지 화면을 씀). M5 B3: approval_required(사람 확인 필요 — data.reason no_approver면 확인할 사람 연결 없음), approval_denied(사람이 거부), approval_timeout(120초 안에 답 없음), always_not_allowed(control 도구에 항상 허용), settings_invalid(형식이 틀린 설정 파일 — 고치지 않음). M5 SECFIX: recorder_store_unclean(녹화 임시 파일을 정리하지 못함 — 메모리 스텝은 바뀌었고 daemon이 다시 정리한다). M6: plugin_failed(플러그인 작업 오류 — data.plugin_error의 code·stage·message, plugin_busy 포함), op_not_found(승인·취소할 플러그인 작업·미리보기가 없음 — 5분 지남·끝남)",
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


class RunArtifactResult(BaseModel):
    """
    kind image: 줄인 PNG를 .kookabug/cache/agent/<cache>에 썼다 (긴 변 ≤1568, ≤1 MiB — 읽은 쪽이 지운다). kind text: 글자 (256 KiB에서 자름). kind frame: 정지 화면 frame_id
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int | None, Field(ge=0)] = None
    cache: Annotated[str | None, Field(pattern="^c\\d+/[0-9a-f]{16}\\.png$")] = None
    frame_id: Annotated[str | None, Field(min_length=1)] = None
    height: Annotated[int | None, Field(ge=1)] = None
    kind: Literal["frame", "image", "text"]
    path: str
    text: str | None = None
    truncated: bool | None = None
    width: Annotated[int | None, Field(ge=1)] = None


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


class RunDiffResult(BaseModel):
    """
    run.compare 결과(CompareResult)와 같은 모양 + classified. 비밀값 스텝·분류 없는 기록의 화면 파일은 null이고 reason이 secret_step·agent_withheld
    """


class RunEventsResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    classified: bool
    events: list[dict[str, Any]]
    next_seq: Annotated[int, Field(ge=0)]
    truncated: bool


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


class RunSearchParams(BaseModel):
    """
    run.search (kb_log_search, M5): 가린 뒤의 메시지·오류·사유에서 글자 찾기 (대소문자 무시). runs를 빼면 최근 20개, 분류 없는 기록은 건너뛴다(skipped)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    limit: Annotated[int | None, Field(ge=1, le=500)] = None
    query: Annotated[str, Field(min_length=1)]
    runs: list[RunId] | None = None


class Match(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: str | None
    run: RunId
    seq: int | None
    step: str | None
    text: str


class RunSearchResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    matches: list[Match]
    skipped: list[str]
    truncated: bool


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


class ScreenReadTextParams(BaseModel):
    """
    screen.read_text (kb_ocr_read, M5): 정지 화면(창 캡처) 영역의 글자. rect를 빼면 전체. 녹화 세션 프레임은 recorder_frame, sensitive target이 보이는 영역과 겹치면 sensitive_region
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frame_id: Annotated[str, Field(min_length=1)]
    rect: Rect | None = None


class ScreensListParams(BaseModel):
    """
    screens.list (kb_screen_list, M5): under(screens/ 기준 또는 워크스페이스 기준 폴더) 아래 화면 지도
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    under: str | None = None


class SecretKey(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="비밀값 키 (그래프 $secret 키와 같은 규칙)",
            pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$",
            title="SecretKey",
        ),
    ]


class SecretKeyInfo(BaseModel):
    """
    비밀값 키 하나 (값 없음). source credential = 자격 증명 관리자 kookabug:<워크스페이스 ID>:<키>
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    key: SecretKey
    source: Literal["credential"]


class SecretsCreateParams(BaseModel):
    """
    secrets.create: 녹화 스텝(from_step, 비밀값·확인 필요 글자 구간)의 메모리 원문을 자격 증명 관리자에 그 키로 쓴다. 값을 RPC로 받지 않는다. 키가 이미 있으면 exists
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    from_step: RecorderStepId
    key: SecretKey


class SecretsListResult(BaseModel):
    """
    secrets.list: 자격 증명 관리자의 이 워크스페이스 키 (값 없음). 환경 변수(KOOKABUG_SECRET_<키>)는 원래 키 이름을 되살릴 수 없어 목록에 없고 env_note로 안내한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    env_note: str
    keys: list[SecretKeyInfo]


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


class Scale1(RootModel[float]):
    root: Annotated[float, Field(ge=0.25, le=4.0)]


class TargetReadTextParams(BaseModel):
    """
    target.read_text: 편집기 정지 화면 영역의 글자 (OCR). 녹화 프레임의 보호 영역과 겹치면 secret_region_overlap
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frame_id: Annotated[str, Field(min_length=1)]
    rect: Rect


class Line(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rect: Rect
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    text: str


class TargetReadTextResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lines: list[Line]
    text: str


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
            "kb_app_launch",
            "kb_graph_create",
            "kb_graph_get",
            "kb_graph_list",
            "kb_graph_patch",
            "kb_graph_validate",
            "kb_image_find",
            "kb_input_click",
            "kb_input_key",
            "kb_input_type",
            "kb_log_search",
            "kb_node_search",
            "kb_ocr_read",
            "kb_project_info",
            "kb_run_artifact_get",
            "kb_run_cancel",
            "kb_run_compare",
            "kb_run_events",
            "kb_run_start",
            "kb_run_status",
            "kb_screen_capture",
            "kb_screen_get",
            "kb_screen_list",
            "kb_target_create",
            "kb_toolset_enable",
            "ui_only",
        ]
    ]
):
    root: Annotated[
        Literal[
            "kb_app_launch",
            "kb_graph_create",
            "kb_graph_get",
            "kb_graph_list",
            "kb_graph_patch",
            "kb_graph_validate",
            "kb_image_find",
            "kb_input_click",
            "kb_input_key",
            "kb_input_type",
            "kb_log_search",
            "kb_node_search",
            "kb_ocr_read",
            "kb_project_info",
            "kb_run_artifact_get",
            "kb_run_cancel",
            "kb_run_compare",
            "kb_run_events",
            "kb_run_start",
            "kb_run_status",
            "kb_screen_capture",
            "kb_screen_get",
            "kb_screen_list",
            "kb_target_create",
            "kb_toolset_enable",
            "ui_only",
        ],
        Field(
            description="권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon의 AGENT_DENIED 목록 — daemon.shutdown, M3 디버그 메서드 debug.breakpoints.get·set·run.pause·run.resume·run.restart, run.export, M4 녹화·비밀값 메서드 recorder.*·secrets.*·target.read_text — 를 판정 전에 거부)",
            title="ToolName",
        ),
    ]


class Toolset(RootModel[Literal["control", "core", "graph_edit", "observe", "run", "screens"]]):
    root: Annotated[
        Literal["control", "core", "graph_edit", "observe", "run", "screens"],
        Field(description="MCP 툴셋 (구현 계획 7장). core는 늘 켜져 있다", title="Toolset"),
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
    agents_md: Annotated[
        str | None, Field(description="AGENTS.md의 Kookabug 관리 구간 (없으면 null, M5 3.12)")
    ] = None
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


class WorkspaceReadParams(BaseModel):
    """
    탐색기에 보이는 파일 하나의 내용 (보기 탭, 읽기 전용). 범위는 workspace.tree와 같다: tests·subgraphs·targets·screens 아래와 루트의 kookabug.json·kookabug.lock·AGENTS.md
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath


class WorkspaceReadResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    binary: Annotated[
        bool, Field(description="글자 파일이 아니다 (앞부분에 NUL 바이트가 있다). text는 빈 문자열")
    ]
    bytes: Annotated[int, Field(description="파일 전체 크기", ge=0, le=9007199254740991)]
    text: Annotated[str, Field(description="UTF-8로 읽은 앞부분 (1 MiB까지, 깨진 바이트는 U+FFFD)")]
    truncated: Annotated[bool, Field(description="1 MiB를 넘어 뒤를 잘랐다")]


class AgentConnection(BaseModel):
    """
    daemon에 붙은 agent 연결 하나 (kookabug mcp)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    attended: bool
    connection: Annotated[int, Field(ge=0, le=9007199254740991)]
    id: str
    name: str
    since: Timestamp
    toolsets: list[Toolset]


class AgentConnectionsResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    connections: list[AgentConnection]


class AgentToolsetsEnableParams(BaseModel):
    """
    툴셋을 켠다 (끄기는 없다). 켜도 각 도구의 권한 판정은 그대로다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    toolsets: Annotated[list[Toolset], Field(min_length=1)]


class AgentToolsetsEnableResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    enabled: list[Toolset]
    tools: Annotated[
        list[str], Field(description="이번에 새로 쓸 수 있게 된 도구 이름 (권한 표 이름)")
    ]


class AgentToolsetsResult(BaseModel):
    """
    자기 연결의 켜진 툴셋 (M5 계획 D3). ui 연결은 툴셋과 무관해 모두 켜짐으로 답한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    available: list[Toolset]
    enabled: list[Toolset]


class AgentsGetResult(BaseModel):
    """
    사용자 설정의 에이전트 목록 (M5 계획 3.12). 파일이 없으면 빈 목록·revision null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agents: list[AgentSpec]
    default_agent: str | None
    problem: Annotated[
        str | None,
        Field(
            description="파일 형식이 틀려 목록을 읽지 못했으면 그 이유 (agents.set도 settings_invalid로 거부)"
        ),
    ]
    revision: Annotated[
        Revision | None, Field(description="사용자 설정 파일 revision (없으면 null)")
    ]
    source: Annotated[str | None, Field(description="사용자 설정 파일 경로 (정할 수 없으면 null)")]


class AgentsSetParams(BaseModel):
    """
    사용자 설정의 agents·default_agent만 바꾼다. 다른 키·순서는 보존, revision이 다르면 revision_conflict, 형식이 틀린 파일은 settings_invalid (permissions.set과 같은 쓰기 규칙)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agents: list[AgentSpec]
    base_revision: Annotated[
        Revision | None, Field(description="읽은 때의 파일 revision (파일이 없었으면 null)")
    ]
    default_agent: Annotated[str | None, Field(description="null이면 키를 지운다")]


class AgentsSetResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    revision: Revision


class ApprovalPreviewResult(BaseModel):
    """
    승인하면 쓰일 그래프 값 (쓰지 않는다, "캔버스에서 보기" U10)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath
    revision: Annotated[
        Revision | None, Field(description="기준 디스크 revision (새 파일이면 null)")
    ]
    value: GraphValue


class ApprovalRequest(BaseModel):
    """
    에이전트의 ask 판정 요청 하나 (approval.requested·approval.list). 기다리는 동안 daemon은 아무것도 쓰지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Annotated[ApprovalAgent, Field(title="ApprovalAgent")]
    always_rule: Annotated[
        str | None,
        Field(
            description='"항상 허용"을 고르면 저장할 규칙 글자. control 도구·규칙으로 쓸 수 없는 인자면 null(단추 없음)'
        ),
    ]
    arg: Annotated[
        str, Field(description="권한 인자 (그래프·target 경로, 실행 그래프 경로, 창 제목 등)")
    ]
    connection: Annotated[
        int, Field(description="요청한 agent 연결 번호", ge=0, le=9007199254740991)
    ]
    expires_at: Timestamp
    id: ApprovalId
    method: MethodName
    previewable: Annotated[
        bool,
        Field(
            description="approval.preview로 바뀔 그래프 값을 볼 수 있다 (graph.patch·graph.save·graph.create)"
        ),
    ]
    summary: Annotated[list[str], Field(description="사람이 읽는 요약 줄")]
    tool: ToolName


class ClientInfo(RootModel[UiClientInfo | AgentClientInfo]):
    root: Annotated[UiClientInfo | AgentClientInfo, Field(title="ClientInfo")]


class ControlClickParams(BaseModel):
    """
    창을 클릭한다 (point와 target 중 하나). daemon이 한 스텝짜리 제어 실행으로 돌린다 (M5 3.9)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: Literal["left", "middle", "right"] | None = None
    count: Annotated[int | None, Field(ge=1, le=3)] = None
    point: Annotated[
        list[PointItem] | None,
        Field(description="[x, y] 클라이언트 영역 물리 픽셀", max_length=2, min_length=2),
    ] = None
    target: WorkspacePath | None = None
    window: Annotated[
        str, Field(description="창 제목 (정확히 같은 제목의 창, 권한 인자)", min_length=1)
    ]


class ControlResult(BaseModel):
    """
    제어 실행 결과 (runs/ 아래 source agent_control 기록). 실패면 error (메시지는 3.8로 가림)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    error: Annotated[ControlError | None, Field(title="ControlError")] = None
    run_id: RunId
    verdict: Verdict


class ControlTypeParams(BaseModel):
    """
    글자 입력 (text와 secret 중 하나). secret은 비밀값 키 — 값은 runner가 찾고 결과·기록·오류에 원문이 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    secret: SecretKey | None = None
    text: str | None = None
    window: Annotated[
        str, Field(description="창 제목 (정확히 같은 제목의 창, 권한 인자)", min_length=1)
    ]


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


class GraphCheckParams(BaseModel):
    """
    경로로 검증 (kb_graph_validate로 판정, M5). value가 없으면 디스크 값, 있으면 그 값(쓰지 않음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath
    value: GraphValue | None = None


class GraphListEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["subgraph", "test"] | None = None
    path: WorkspacePath
    problem: str | None = None
    title: str | None = None


class GraphListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    graphs: list[GraphListEntry]


class GraphOpenParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath


class GraphPatchOpAddNode(BaseModel):
    """
    새 노드. ID는 daemon이 만든다 (n_ + 8자)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    config: dict[str, Any] | None = None
    in_: Annotated[dict[str, Any] | None, Field(alias="in")] = None
    op: Literal["add_node"]
    position: GraphPatchPosition | None = None
    ref: Annotated[
        str, Field(description="이 묶음 안 임시 이름 (결과 created에 ref → 새 ID)", min_length=1)
    ]
    title: str | None = None
    type: Annotated[str, Field(min_length=1)]
    version: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None


class GraphPatchOpMove(BaseModel):
    """
    레이아웃만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: GraphPatchNodeRef
    op: Literal["move"]
    position: GraphPatchPosition


class GraphPatchOp(
    RootModel[
        GraphPatchOpAddNode
        | GraphPatchOpSetNode
        | GraphPatchOpRemoveNode
        | GraphPatchOpConnect
        | GraphPatchOpDisconnect
        | GraphPatchOpLink
        | GraphPatchOpUnlink
        | GraphPatchOpMove
        | GraphPatchOpSetMeta
    ]
):
    root: Annotated[
        GraphPatchOpAddNode
        | GraphPatchOpSetNode
        | GraphPatchOpRemoveNode
        | GraphPatchOpConnect
        | GraphPatchOpDisconnect
        | GraphPatchOpLink
        | GraphPatchOpUnlink
        | GraphPatchOpMove
        | GraphPatchOpSetMeta,
        Field(
            description="graph.patch 연산 하나 (M5 계획 3.4). 노드 ID는 바꿀 수 없다",
            title="GraphPatchOp",
        ),
    ]


class GraphPatchParams(BaseModel):
    """
    경로로 그래프를 고친다 (M5 계획 3.4). 모두 적용하거나 하나도 안 한다. 디스크가 base_revision과 다르면 revision_conflict, 연산이 틀리면 patch_invalid, 적용한 값이 그래프 형식에 맞지 않으면 validation_failed
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: Revision
    ops: Annotated[list[GraphPatchOp], Field(max_length=1000, min_length=1)]
    path: WorkspacePath


class GraphPatchResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created: Annotated[dict[str, str], Field(description="add_node ref → 새 노드 ID")]
    diagnostics: list[Diagnostic]
    removed_refs: Annotated[
        list[GraphPatchRemovedRef], Field(description="remove_node가 함께 지운 연결")
    ]
    revision: Revision
    wrote: bool


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


class LeaseChangedParams(BaseModel):
    """
    입력 임대권 소유자 (없으면 null). 녹화 세션이면 kind recorder (상태 바 '입력: 녹화')
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    owner: LeaseOwner | None


class LeaseFile(BaseModel):
    """
    입력 임대권 옆 파일 (%LOCALAPPDATA%\\Kookabug\\input-lease.json, kookabug_core.inputs.lease). 쥔 동안 {owner, clean: false}, 깨끗하게 놓으면 {owner: null, clean: true, last_owner}
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    clean: bool
    last_owner: LeaseOwner | None = None
    owner: LeaseOwner | None


class MatchInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    click: Annotated[list[ClickItem], Field(max_length=2, min_length=2)]
    method: str
    rect: Rect
    scale: float
    score: float


class AgentConnections(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: AgentConnectionsResult
    tool: Literal["ui_only"]


class AgentToolsetsEnable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: AgentToolsetsEnableParams
    renderer: Literal[False]
    result: AgentToolsetsEnableResult
    tool: Literal["kb_toolset_enable"]


class AgentToolsetsGet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[False]
    result: AgentToolsetsResult
    tool: Literal["kb_toolset_enable"]


class AgentsGet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: AgentsGetResult
    tool: Literal["ui_only"]


class AgentsSet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: AgentsSetParams
    renderer: Literal[True]
    result: AgentsSetResult
    tool: Literal["ui_only"]


class ApprovalPreview(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ApprovalIdParams
    renderer: Literal[True]
    result: ApprovalPreviewResult
    tool: Literal["ui_only"]


class ControlClick(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ControlClickParams
    renderer: Literal[False]
    result: ControlResult
    tool: Literal["kb_input_click"]


class ControlKey(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ControlKeyParams
    renderer: Literal[False]
    result: ControlResult
    tool: Literal["kb_input_key"]


class ControlType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ControlTypeParams
    renderer: Literal[False]
    result: ControlResult
    tool: Literal["kb_input_type"]


class GraphCheck(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphCheckParams
    renderer: Literal[False]
    result: GraphCheckResult
    tool: Literal["kb_graph_validate"]


class GraphList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphListParams
    renderer: Literal[False]
    result: GraphListResult
    tool: Literal["kb_graph_list"]


class GraphPatch(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphPatchParams
    renderer: Literal[False]
    result: GraphPatchResult
    tool: Literal["kb_graph_patch"]


class GraphSave(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphSaveParams
    renderer: Literal[True]
    result: GraphSaveResult
    tool: Literal["kb_graph_patch"]


class PluginsCancel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsOpIdParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["ui_only"]


class PluginsGc(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: PluginsOpResult
    tool: Literal["ui_only"]


class PluginsInstall(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsOpIdParams
    renderer: Literal[True]
    result: PluginsOpResult
    tool: Literal["ui_only"]


class PluginsPreview(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsPreviewParams
    renderer: Literal[True]
    result: PluginsPreviewResult
    tool: Literal["ui_only"]


class PluginsRelock(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: PluginsOpResult
    tool: Literal["ui_only"]


class PluginsUpgrade(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsUpgradeParams
    renderer: Literal[True]
    result: PluginsPreviewResult
    tool: Literal["ui_only"]


class RecorderCommitAbort(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderCommitTokenParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["ui_only"]


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


class RunSearch(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunSearchParams
    renderer: Literal[False]
    result: RunSearchResult
    tool: Literal["kb_log_search"]


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


class ScreenReadText(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ScreenReadTextParams
    renderer: Literal[False]
    result: TargetReadTextResult
    tool: Literal["kb_ocr_read"]


class SecretsCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: SecretsCreateParams
    renderer: Literal[True]
    result: SecretKeyInfo
    tool: Literal["ui_only"]


class SecretsList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: SecretsListResult
    tool: Literal["ui_only"]


class TargetReadText(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: TargetReadTextParams
    renderer: Literal[True]
    result: TargetReadTextResult
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


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: WorkspaceReadParams
    renderer: Literal[True]
    result: WorkspaceReadResult
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


class NodesListResult(BaseModel):
    """
    팔레트: 레지스트리의 플러그인마다 노드 스키마 문서 하나 (kookabug_core.palette.export). M6: plugins = 설치 플러그인 요약 (잠금이 없거나 깨졌으면 빈 목록)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    plugins: list[PluginInstalled] | None = None
    schemas: list[dict[str, Any]]


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


class ApprovalRequested(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ApprovalRequest


class GraphChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: GraphChangedParams


class LeaseChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: LeaseChangedParams


class PluginsProgress(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsProgressParams


class RunLagged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunLaggedParams


class PermissionsLayer(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    diagnostics: list[Diagnostic]
    editable: Annotated[
        bool,
        Field(
            description="permissions.set으로 고칠 수 있는 계층 (team은 false — kookabug.json에서 편집)"
        ),
    ]
    layer: Literal["project", "team", "user"]
    permissions: Annotated[
        dict[str, Any] | None, Field(description="그 파일의 permissions 값 그대로 (없으면 null)")
    ]
    revision: Annotated[
        Revision | None,
        Field(
            description="그 파일 바이트의 sha256 (파일이 없으면 null). permissions.set의 base_revision"
        ),
    ]
    source: Annotated[str | None, Field(description="파일 경로 (표시용, 정할 수 없으면 null)")]


class PermissionsSetParams(BaseModel):
    """
    권한 계층 하나의 permissions만 바꾼다. 다른 키·순서는 보존, 같은 폴더 임시 파일 → 교체. 형식이 틀린 파일은 고치지 않고 settings_invalid
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: Annotated[
        Revision | None,
        Field(
            description="읽은 때의 파일 revision (파일이 없었으면 null). 다르면 revision_conflict"
        ),
    ]
    layer: Literal["project", "user"]
    permissions: Annotated[
        dict[str, Any], Field(description="새 permissions 값 (메타스키마 Permissions)")
    ]


class PermissionsSetResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    revision: Revision


class PermissionsToolDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    final: PermissionVerdict
    layer: Literal["default", "project", "team", "user"] | None
    mutating: bool
    reason: str
    source: str
    tool: Annotated[str, Field(description="권한 표 도구 이름 (M7 kb_screen_save 포함)")]
    toolset: Toolset
    verdict: PermissionVerdict


class PluginEnvInfo(BaseModel):
    """
    잠금의 환경 하나의 상태 (M6 3.8). folder = runner가 고를 폴더 이름 (검증 없이 찾은 것)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    folder: str | None
    plugins: list[str]
    status: PluginEnvStatus


class PluginErrorInfo(BaseModel):
    """
    플러그인 작업 오류 요약 (kookabug_core.plugins.PluginError.to_json — 인증 정보를 가린 값). code는 설치 거래 오류 코드(M6 3.5)·plugin_busy·internal_error, 원문은 작업 로그(.kookabug/plugins/logs/<op_id>.log)
    """

    code: str
    conflicts: list[str] | None = None
    env: str | None = None
    message: str
    op_id: PluginOpId | None = None
    packages: list[str] | None = None
    plugin: str | None = None
    stage: str | None


class PluginJob(BaseModel):
    """
    이 daemon에서 진행 중인 플러그인 작업 (waiting = 미리보기가 승인을 기다림). 승인을 기다리는 미리보기의 op_id는 그 미리보기를 연 연결에만 보이고 다른 연결에는 null (승인·취소는 연 연결만)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: PluginOpKind
    op_id: PluginOpId | None
    stage: str | None
    waiting: bool


class PluginListEntry(BaseModel):
    """
    잠금의 플러그인 항목(plugin-lock LockPlugin) + 환경 상태 + 노드 (커밋된 wheel의 스키마)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    conflicts: list[str] | None = None
    dist: str | None = None
    env: str
    env_status: PluginEnvStatus
    id: str
    isolated_because: str | None = None
    manifest: Annotated[
        dict[str, Any],
        Field(description="잠금의 manifest (title·modules·permissions·min_core·isolation·ui)"),
    ]
    nodes: list[PluginNodeInfo]
    requires: list[str] | None = None
    schema_sha256: str | None = None
    source: Annotated[
        dict[str, Any], Field(description="원천 출처 (git·wheel·path — 인증 정보 없음)")
    ]
    version: str
    wheel: str | None = None
    wheel_sha256: str | None = None


class PluginsChangedParams(BaseModel):
    """
    kookabug.lock이 바뀌었다 (daemon 작업이든 밖에서든). daemon은 레지스트리를 다시 만들었다 — nodes.list·검증을 다시 부른다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    revision: Annotated[
        Revision | None, Field(description="잠금 파일 바이트 sha256 (없어졌으면 null)")
    ]


class PluginsDoneParams(BaseModel):
    """
    플러그인 작업이 끝났다 (ui 연결에만). ok가 거짓이면 error, 참이면 result (작업별 결과)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    error: PluginErrorInfo | None = None
    kind: PluginOpKind
    ok: bool
    op_id: PluginOpId
    result: dict[str, Any] | None = None


class PluginsListResult(BaseModel):
    """
    플러그인 목록 (M6 3.8, 읽기만). lock_sha256 = 정규 잠금 해시 — 준비(plugins.sync)에 그대로 넘긴다. trusted = 이 PC에서 신뢰 확인한 잠금
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    busy: PluginJob | None
    environments: dict[str, PluginEnvInfo]
    gc_candidates: PluginGcCandidates
    lock_sha256: Revision | None
    plugins: list[PluginListEntry]
    revision: Annotated[
        Revision | None,
        Field(description="잠금 파일 revision (plugins.remove의 base_revision)"),
    ]
    stale_reason: str | None
    trusted: bool


class PluginsRemoveParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: Annotated[
        Revision | None,
        Field(
            description="확인할 때 본 잠금 revision (plugins.list). null = 확인할 때 잠금이 없었다 (비교 생략이 아님). 거래 안에서 읽은 잠금과 null까지 비교해 다르면 revision_conflict"
        ),
    ]
    id: str


class PluginsSyncParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lock_sha256: Annotated[
        Revision,
        Field(
            description="사람이 확인한 잠금의 정규 해시 (plugins.list lock_sha256). 그 사이 바뀌면 revision_conflict"
        ),
    ]


class PreviewPeak(BaseModel):
    """
    같은 사양으로 찾은 자리 하나 (target.preview peaks)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rect: Rect
    scale: Annotated[float, Field(ge=0.0)]
    score: Annotated[float, Field(ge=-1.0, le=1.0)]


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
    peaks: Annotated[
        list[PreviewPeak] | None,
        Field(
            description="임계값 이상이고 서로 겹치지 않는 자리 (점수 높은 차례, 최대 8 — '같은 모양 N곳', M4). 없으면 아직 세지 않음",
            max_length=8,
        ),
    ] = None
    scale_scores: Annotated[
        list[PreviewScaleScore] | None,
        Field(
            description="params.scales 차례대로 그 배율로 바꾼 정지 화면에서 찾은 결과 (scales를 보냈을 때만)",
            max_length=6,
        ),
    ] = None
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


class RecorderChangedParams(BaseModel):
    """
    recorder.changed: 녹화 상태·스텝이 바뀜. 소유 연결에는 rev·counts·warnings도 (스텝 목록은 rev로 recorder.steps를 다시 부른다), 다른 연결에는 state만. 글자는 싣지 않는다. session은 그 알림의 녹화 세션(idle이면 없음) — 받는 쪽은 아는 지금 세션과 다른 알림으로 상태를 바꾸지 않는다 (M5 SECFIX)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    counts: RecorderCounts | None = None
    rev: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    session: RecorderSessionId | None = None
    state: RecorderState
    warnings: list[RecorderWarning] | None = None


class RecorderCommitFinishParams(BaseModel):
    """
    recorder.commit_finish: 렌더러가 조각을 넣은 그래프를 저장했다 → 세션 committed, 정리
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    graph_path: WorkspacePath
    token: RecorderCommitToken


class RecorderCommitPrepareParams(BaseModel):
    """
    recorder.commit_prepare: 녹화를 멈추고(아직이면) 검사(classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap) → target 파일 쓰기(멱등: 이미 쓴 초안은 다시 쓰지 않음) → 조각. graph_path는 새 테스트면 만들 파일, 삽입이면 열린 그래프 파일 (target 폴더 이름 targets/rec/<줄기>/). options는 이 커밋에 적용할 변환 옵션(녹화 뒤 사이드바에서 바꾼 값). 빼면 세션 옵션(recorder.start의 options, recorder.state가 보임). 옵션이 다르면 다른 조각이다(같은 옵션으로 다시 부를 때만 같은 조각)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: Revision | None = None
    graph_path: WorkspacePath
    mode: Literal["insert", "new_test"]
    options: RecorderOptions | None = None


class RecorderFrameParams(BaseModel):
    """
    recorder.frame: 그 스텝이 붙잡은 프레임(pre_click 클릭 직전·pre_hover 커서 들어오기 전·pre_next 다음 동작 직전) 또는 live(링의 지금 프레임, step 없음, stopped에서는 no_frame)를 편집기 프레임 캐시에 올린다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    step: RecorderStepId | None = None
    which: RecorderFrameWhich


class RecorderInsertCheckParams(BaseModel):
    """
    recorder.insert_check: 녹화 중 '화면 확인 삽입'(visible → core.assert.visible) · '값 확인 삽입'(text → core.assert.text, 영역 OCR 글자를 기댓값으로 제안). rect는 그 frame_id 정지 화면의 클라이언트 물리 픽셀 영역 (보호 영역과 겹치면 secret_region_overlap)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frame_id: Annotated[str, Field(min_length=1)]
    kind: Literal["text", "visible"]
    rect: Rect


class RecorderMaterializeParams(BaseModel):
    """
    recorder.target.materialize: REC 탭 '찾기 대상 탭으로 열기' — 그 스텝의 녹화 초안만 지금 target 파일로 쓴다(최신 보호 영역 재검사 뒤, targets/rec/<세션 ID>/). 그 스텝은 이후 그 파일을 가리키고 커밋은 다시 쓰지 않는다. 초안이 없는 스텝이면 target_missing
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    step: RecorderStepId


class RecorderTargetSpec(BaseModel):
    """
    target 초안 사양 (읽기 RecorderTargetDraft.spec = 전체, 쓰기 RecorderStepPatch.target = 바꿀 필드만 — 같은 모양). rect·search는 자른 프레임의 클라이언트 물리 픽셀(search null = 검색 범위 없음). 나머지는 target 파일 필드와 같다: click.anchor·click.offset, match.threshold·rgb(색까지 확인)·methods·color_tolerance, sensitive
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    anchor: (
        Literal[
            "bottom",
            "bottom_left",
            "bottom_right",
            "center",
            "left",
            "right",
            "top",
            "top_left",
            "top_right",
        ]
        | None
    ) = None
    color_tolerance: Annotated[float | None, Field(ge=0.0, le=255.0)] = None
    methods: Annotated[
        list[Literal["template", "template_multiscale"]] | None,
        Field(max_length=2, min_length=1),
    ] = None
    offset: Annotated[list[float] | None, Field(max_length=2, min_length=2)] = None
    rect: Rect | None = None
    rgb: bool | None = None
    search: Rect | None = None
    sensitive: bool | None = None
    threshold: Annotated[float | None, Field(ge=0.0, le=1.0)] = None


class RecorderWindow(BaseModel):
    """
    녹화 대상 창 (시작 때의 값)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_size: Size
    dpi: Annotated[int, Field(ge=1, le=9007199254740991)]
    handle: Annotated[int, Field(ge=0, le=9007199254740991)]
    process: str
    title: str


class RecorderWrittenTarget(BaseModel):
    """
    커밋이 쓴(또는 재사용한) target 파일
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath
    reused: bool
    revision: TargetRevision


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
    error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found·run_not_debuggable·not_paused → run_id, read_only → path, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message. M4: input_lease_busy → owner(살아 있음이 확인된 소유자, 모르면 null), recording_active·not_owner·recorder_state_invalid → state, classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap → steps(걸린 스텝). M5: toolset_disabled → toolset, patch_invalid → index·message. M5 B3: approval_required → decision·reason. M6: plugin_failed → plugin_error, op_not_found → op_id
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
    index: Annotated[
        int | None,
        Field(description="patch_invalid: 틀린 연산의 순번 (0부터)", ge=0, le=9007199254740991),
    ] = None
    line: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    message: str | None = None
    op_id: str | None = None
    owner: LeaseOwner | None = None
    path: str | None = None
    plugin_error: PluginErrorInfo | None = None
    protocol: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    reason: Annotated[
        str | None,
        Field(
            description="approval_required: no_approver(사람 연결 없음). M6: permission_denied: dev_modules_agent(개발 모듈 daemon의 에이전트 실행)"
        ),
    ] = None
    revision: str | None = None
    run_id: RunId | None = None
    state: RecorderState | None = None
    steps: list[RecorderStepId] | None = None
    toolset: Toolset | None = None


class RunArtifactParams(BaseModel):
    """
    run.artifact (kb_run_artifact_get, M5 3.8): 실행 폴더의 증거 파일 하나 (steps/·thumbs/ 아래 그 스텝의 증거, video/index.json). 비밀값 스텝(안쪽 포함)·agent_withhold 증거는 secret_step, 분류 없는 기록은 unclassified_run, 영상 조각은 video_not_served. max_side는 이미지 긴 변 상한(≤1568), as_frame이면 정지 화면으로
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    as_frame: bool | None = None
    max_side: Annotated[int | None, Field(ge=1, le=1568)] = None
    path: Annotated[str, Field(min_length=1)]
    run_id: RunId


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


class RunCropRef(BaseModel):
    """
    실행 증거 이미지에서 자른 영역 (kb_target_create의 {run, file} 출처, M5). 에이전트용 비밀값 분류를 지난 이미지만 (아니면 secret_step·unclassified_run·not_evidence)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    file: Annotated[str, Field(description="실행 폴더 기준 경로 ('/')", min_length=1)]
    rect: Rect
    run_id: RunId


class RunDiffParams(BaseModel):
    """
    run.diff (kb_run_compare, M5): run.compare와 같은 비교를 두 실행에 3.8(비밀값 분류)을 적용해 준다. baseline을 빼면 지난 성공
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: RunId | None = None
    run_id: RunId


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


class RunEventsParams(BaseModel):
    """
    run.events (kb_run_events, M5 3.8): after_seq 뒤 이벤트 (secret_paths 자리는 ***, 분류 없는 기록은 안전 필드만). step·kinds로 거른다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    after_seq: Annotated[int | None, Field(ge=0)] = None
    kinds: list[str] | None = None
    limit: Annotated[int | None, Field(ge=1, le=500)] = None
    run_id: RunId
    step: StepId | None = None


class RunExportParams(BaseModel):
    """
    실행 폴더를 zip으로 내보낸다 (Electron 주 프로세스 내부용: dest는 저장 대화 상자가 고른 절대 경로). dest 옆 임시 파일에 쓰고 끝나면 replace. 진행 중 실행은 run_active
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    dest: Annotated[str, Field(min_length=1)]
    run_id: RunId


class RunFailureResult(BaseModel):
    """
    run.failure (kb_run_status, M5): 실패 요약 — 판정·실패 위치(스텝·노드·출구·오류)·증거 파일(에이전트에게 줄 수 있는 것만)·영상 요약·지난 성공. 사유·메시지는 3.8대로 가린다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    chain: list[dict[str, Any]]
    classified: bool
    code: str | None = None
    evidence: list[str]
    failure: dict[str, Any] | None
    failure_path: list[str] | None = None
    failure_step: str | None = None
    last_success: RunId | None
    reason: str | None = None
    run_id: RunId
    state: Literal["ended", "running"]
    verdict: str | None = None
    video: dict[str, Any] | None = None


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
    디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy. 이 daemon의 녹화 세션이 starting·recording·paused면 runner를 띄우기 전에 recording_active (M4, 같은 시작 잠금 안에서 판정)
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
    source: Annotated[
        Literal["agent_control"] | None,
        Field(description='배지 "에이전트 제어": source agent_control 실행 (M5 3.9, run.json에서)'),
    ] = None
    started_at: Timestamp | None
    state: Literal["ended", "running"]


class ScreensGetParams(BaseModel):
    """
    screens.get (kb_screen_get, M5): screens/ 아래 *.screen.json 하나
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath


class ScreensGetResult(BaseModel):
    """
    읽을 수 없거나 형식이 틀리면 problem
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: WorkspacePath
    problem: str | None = None
    value: Any | None = None


class Screen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explored: Literal[True] | None = None
    id: str
    path: WorkspacePath
    problem: str | None = None
    title: str | None = None


class ScreensListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    screens: list[Screen]


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
    scales: Annotated[
        list[Scale1] | None,
        Field(
            description="다른 배율 점수 (M4 T11): 정지 화면을 이 배율로 바꿔 같은 사양으로 찾는다. 결과 scale_scores (편집기 접힌 줄 '다른 배율에서'를 펼쳤을 때만 보낸다)",
            max_length=6,
        ),
    ] = None
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
    crop: CropRef | RunCropRef | None = None
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


class ApprovalListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    requests: list[ApprovalRequest]


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
    agent_image: Annotated[
        AgentImage | None,
        Field(
            description="agent 연결의 target.capture만 (M5 kb_screen_capture): 긴 변 1568·1 MiB 이하 PNG를 .kookabug/cache/agent/<cache>에 썼다 (읽은 쪽이 지운다)"
        ),
    ] = None
    client_size: Size
    dpi: Annotated[int, Field(ge=1, le=9007199254740991)]
    frame_id: Annotated[str, Field(min_length=1)]
    height: Annotated[int, Field(ge=0, le=9007199254740991)]
    image: ImageRef
    width: Annotated[int, Field(ge=0, le=9007199254740991)]


class GraphCreateParams(BaseModel):
    """
    새 그래프 (canonical 틀). 파일이 있으면 exists. 결과는 graph.open과 같다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["subgraph", "test"]
    ops: Annotated[
        list[GraphPatchOp] | None,
        Field(
            description="만들 틀에 적용할 graph.patch 연산 (M5). 틀리면 파일을 만들지 않는다",
            max_length=1000,
        ),
    ] = None
    path: WorkspacePath
    title: str | None = None


class GraphOpenResult(BaseModel):
    """
    value는 Python이 읽은 값. 원문 텍스트는 보내지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    canonical: Annotated[bool, Field(description="원문이 canonical 형식인가")]
    created: Annotated[
        dict[str, str] | None,
        Field(description="graph.create ops의 add_node ref → 새 노드 ID (M5, ops를 줬을 때만)"),
    ] = None
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


class ApprovalList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: ApprovalListResult
    tool: Literal["ui_only"]


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


class NodesList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: NodesListResult
    tool: Literal["kb_node_search"]


class PermissionsSet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PermissionsSetParams
    renderer: Literal[True]
    result: PermissionsSetResult
    tool: Literal["ui_only"]


class PluginsList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: PluginsListResult
    tool: Literal["kb_project_info"]


class PluginsRemove(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsRemoveParams
    renderer: Literal[True]
    result: PluginsOpResult
    tool: Literal["ui_only"]


class PluginsSync(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsSyncParams
    renderer: Literal[True]
    result: PluginsOpResult
    tool: Literal["ui_only"]


class RecorderCommitFinish(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderCommitFinishParams
    renderer: Literal[True]
    result: EmptyResult
    tool: Literal["ui_only"]


class RecorderTargetMaterialize(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderMaterializeParams
    renderer: Literal[True]
    result: RecorderWrittenTarget
    tool: Literal["ui_only"]


class RunArtifact(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunArtifactParams
    renderer: Literal[False]
    result: RunArtifactResult
    tool: Literal["kb_run_artifact_get"]


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


class RunDiff(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunDiffParams
    renderer: Literal[False]
    result: RunDiffResult
    tool: Literal["kb_run_compare"]


class RunEvents(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunEventsParams
    renderer: Literal[False]
    result: RunEventsResult
    tool: Literal["kb_run_events"]


class RunExport(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunExportParams
    renderer: Literal[False]
    result: RunExportResult
    tool: Literal["ui_only"]


class RunFailure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunIdParams
    renderer: Literal[False]
    result: RunFailureResult
    tool: Literal["kb_run_status"]


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


class ScreensGet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ScreensGetParams
    renderer: Literal[False]
    result: ScreensGetResult
    tool: Literal["kb_screen_get"]


class ScreensList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: ScreensListParams
    renderer: Literal[False]
    result: ScreensListResult
    tool: Literal["kb_screen_list"]


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


class PluginsChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsChangedParams


class PluginsDone(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: PluginsDoneParams


class RecorderChanged(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderChangedParams


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
    agent_connections_changed: Annotated[
        AgentConnectionsChanged, Field(alias="agent.connections.changed")
    ]
    approval_requested: Annotated[ApprovalRequested, Field(alias="approval.requested")]
    approval_resolved: Annotated[ApprovalResolved, Field(alias="approval.resolved")]
    debug_breakpoints_changed: Annotated[
        DebugBreakpointsChanged, Field(alias="debug.breakpoints.changed")
    ]
    graph_changed: Annotated[GraphChanged, Field(alias="graph.changed")]
    lease_changed: Annotated[LeaseChanged, Field(alias="lease.changed")]
    plugins_changed: Annotated[PluginsChanged, Field(alias="plugins.changed")]
    plugins_done: Annotated[PluginsDone, Field(alias="plugins.done")]
    plugins_progress: Annotated[PluginsProgress, Field(alias="plugins.progress")]
    recorder_changed: Annotated[RecorderChanged, Field(alias="recorder.changed")]
    run_ended: Annotated[RunEnded, Field(alias="run.ended")]
    run_event: Annotated[RunEvent, Field(alias="run.event")]
    run_lagged: Annotated[RunLagged, Field(alias="run.lagged")]
    workspace_changed: Annotated[WorkspaceChanged, Field(alias="workspace.changed")]


class PermissionsGetResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    layers: Annotated[
        list[PermissionsLayer] | None,
        Field(description="계층별 파일 값 (ui 연결만. agent 연결에는 자기 판정 요약 tools만)"),
    ] = None
    principal: Principal
    tools: Annotated[
        list[PermissionsToolDecision],
        Field(
            description="도구별 실효 판정. agent 연결은 자기 주체, ui 연결은 사람이 지켜보는 에이전트(attended) 기준"
        ),
    ]


class RecorderCommitPrepareResult(BaseModel):
    """
    조각과 토큰 (세션 committing). 같은 요청을 다시 부르면 같은 조각(같은 로컬 ID·경로)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    fragment: Annotated[Any, Field(description="urn:kookabug:recorder-fragment:0")]
    targets: list[RecorderWrittenTarget]
    token: RecorderCommitToken


class RecorderFrameResult(BaseModel):
    """
    정지 화면과 그 프레임에서 유효한 보호 영역(비밀값·판정 대기·확인 필요 입력 칸 상자, 클라이언트 물리 픽셀 — 편집기가 빗금으로 보이고 그 영역과 겹치는 저장은 secret_region_overlap)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frame: Frame
    protected: list[Rect]
    which: RecorderFrameWhich


class RecorderStateResult(BaseModel):
    """
    녹화 상태. owned = 부른 연결이 세션을 연 연결인가. 다른 연결(owned false)에는 상태·시작 시각·경과만 준다 (스텝·창 제목 없음 — '다른 창에서 녹화 중'). options = 세션 변환 옵션(recorder.start에서 받은 값, 없는 값은 켬) — 커밋 때 바꾸려면 commit_prepare의 options
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    counts: RecorderCounts | None = None
    elapsed_ms: Annotated[int | None, Field(ge=0, le=9007199254740991)] = None
    foreground: Annotated[
        bool | None,
        Field(
            description="대상 창이 앞에 있는가 (false면 '게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중')"
        ),
    ] = None
    launched: Annotated[
        bool | None, Field(description="게임을 띄워서 녹화 (그래프가 core.app.launch로 시작)")
    ] = None
    options: RecorderOptions | None = None
    owned: bool
    session: RecorderSessionId | None = None
    started_at: Timestamp | None = None
    state: RecorderState
    stop_reason: RecorderStopReason | None = None
    warnings: list[RecorderWarning] | None = None
    window: RecorderWindow | None = None


class RecorderStepPatch(BaseModel):
    """
    스텝 고치기 (비어 있으면 아무것도 바꾸지 않음). text_state를 ordinary로 바꾸려면 confirm_reveal이 있어야 한다 (원문을 처음 보이는 순간). text(일반 글자 고치기)는 ordinary 스텝만, target은 REC 탭의 초안 사양 고치기(RecorderTargetDraft.spec과 같은 모양 — 준 필드만 바꾼다, 보호 영역과 겹치면 secret_region_overlap), keep은 확인 필요 입력을 그대로 남기기. 자를 프레임은 둘 중 하나로 고른다: frame(이 스텝이 붙잡은 프레임 종류) 또는 frame_id(이 세션이 recorder.frame으로 편집기 캐시에 올린 프레임 — live도 조회한 그 순간의 프레임이 고정된다. 다른 세션·다른 연결이 올린 프레임이면 not_owner, 캐시에서 사라졌으면 frame_expired, 그 프레임의 보호 영역 검사를 거친다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    confirm_reveal: Literal[True] | None = None
    delete: Literal[True] | None = None
    equals: Annotated[
        str | None,
        Field(
            description="값 확인(check_text) 스텝의 기댓값 고치기 (사람 수정·글자 읽기 결과). 세션의 비밀값·판정 대기·확인 필요 원문을 담으면 secret_region_overlap"
        ),
    ] = None
    frame: Literal["pre_click", "pre_hover", "pre_next"] | None = None
    frame_id: Annotated[str | None, Field(min_length=1)] = None
    keep: Literal[True] | None = None
    node_type: Annotated[
        str | None,
        Field(
            description="노드 종류 바꾸기 (이미지 클릭 ↔ 좌표 클릭, 대기 종류)",
            pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$",
        ),
    ] = None
    secret_key: SecretKey | None = None
    target: RecorderTargetSpec | None = None
    text: str | None = None
    text_state: Literal["ordinary", "secret"] | None = None
    timeout_ms: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None


class RecorderStepUpdateParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    patch: RecorderStepPatch
    step: RecorderStepId


class RecorderTargetDraft(BaseModel):
    """
    스텝의 찾기 대상: draft(이 세션 초안, 커밋 때 파일로) · file(기존 또는 이미 쓴 target 파일 재사용) · none(아직 없음 — 커밋 target_missing). draft는 spec(daemon이 든 초안 사양 전체 — REC 편집기가 이것으로 상태를 만들고, 고친 값은 recorder.step.update patch.target으로 같은 모양을 보낸다)이 있다. frame은 자른 프레임: 스텝이 붙잡은 프레임 종류, 또는 live(편집기에서 고른 지금 프레임 — 그때 고정된 frame_id가 함께 온다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frame: Literal["live", "pre_click", "pre_hover", "pre_next"] | None = None
    frame_id: Annotated[
        str | None,
        Field(
            description="자른 프레임의 편집기 캐시 ID (recorder.frame·patch.frame_id로 고른 프레임)",
            min_length=1,
        ),
    ] = None
    path: WorkspacePath | None = None
    peaks: Annotated[
        int | None,
        Field(
            description="같은 프레임에서 임계값 이상인 자리 수 (자기 자리 포함, '같은 모양 N곳')",
            ge=0,
            le=9007199254740991,
        ),
    ] = None
    reused: bool | None = None
    source: Literal["draft", "file", "none"]
    spec: RecorderTargetSpec | None = None


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


class PermissionsGet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: PermissionsGetResult
    tool: Literal["kb_project_info"]


class RecorderCommitPrepare(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderCommitPrepareParams
    renderer: Literal[True]
    result: RecorderCommitPrepareResult
    tool: Literal["ui_only"]


class RecorderDiscard(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: RecorderStateResult
    tool: Literal["ui_only"]


class RecorderFrame(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderFrameParams
    renderer: Literal[True]
    result: RecorderFrameResult
    tool: Literal["ui_only"]


class RecorderPause(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: RecorderStateResult
    tool: Literal["ui_only"]


class RecorderResume(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: RecorderStateResult
    tool: Literal["ui_only"]


class RecorderStart(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderStartParams
    renderer: Literal[True]
    result: RecorderStateResult
    tool: Literal["ui_only"]


class RecorderStateModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: RecorderStateResult
    tool: Literal["ui_only"]


class RecorderStop(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: EmptyParams
    renderer: Literal[True]
    result: RecorderStateResult
    tool: Literal["ui_only"]


class RunList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RunListParams
    renderer: Literal[True]
    result: RunListResult
    tool: Literal["kb_run_status"]


class RecorderStep(BaseModel):
    """
    녹화된 스텝 하나 = 재생 동작 하나 (노드는 하나 이상). 글자 규칙(M4 계획 2.8): text는 text_state가 ordinary일 때만(근거로 일반 글자로 판정됐거나 사람이 확인 — 그때 reveal_confirmed) 있다. pending·secret·needs_review는 text_len만. secret_key는 secret에만. node.title·badges에는 비밀값·판정 대기·확인 필요 원문을 넣지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    badges: list[RecorderBadge]
    equals: Annotated[
        str | None,
        Field(
            description="값 확인(check_text) 스텝의 기댓값 (영역 OCR 제안 또는 사람이 고친 값). 비밀값 원문과 겹치면 daemon이 비운다"
        ),
    ] = None
    frames: Annotated[
        list[RecorderFrameWhich] | None,
        Field(description="recorder.frame으로 열 수 있는 이 스텝의 프레임"),
    ] = None
    input: RecorderStepInput | None = None
    kind: Literal[
        "check_text", "check_visible", "click", "delay", "drag", "key", "scroll", "text", "wait"
    ]
    needs_review: list[RecorderNeedsReviewReason]
    node: Annotated[Node, Field(description="노드 초안 요약 (시안 '이미지 클릭 \"강화\"')")]
    reveal_confirmed: Annotated[
        Literal[True] | None, Field(description="사람이 '글자를 보이고 일반 글자로'를 확인했다")
    ] = None
    secret_key: Annotated[
        SecretKey | None,
        Field(description="고른 비밀값 키 (아직 안 골랐으면 null → 커밋 secret_unresolved)"),
    ] = None
    step: RecorderStepId
    t_ms: Annotated[
        int,
        Field(
            description="녹화 시작부터 그 입력까지 (일시정지 시간 포함)", ge=0, le=9007199254740991
        ),
    ]
    target: RecorderTargetDraft | None = None
    text: str | None = None
    text_len: Annotated[
        int | None,
        Field(description="글자 수 (UI는 비밀값이면 이 길이만큼 ●)", ge=0, le=9007199254740991),
    ] = None
    text_state: RecorderTextState | None = None


class RecorderStepResult(BaseModel):
    """
    바뀐(또는 새) 스텝과 스텝 목록 판. 지운 스텝이면 step은 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rev: Annotated[int, Field(ge=0, le=9007199254740991)]
    step: RecorderStep | None


class RecorderStepsResult(BaseModel):
    """
    스텝 목록 (녹화 차례). 원문 글자를 주는 유일한 곳 — ordinary 스텝의 text만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rev: Annotated[int, Field(ge=0, le=9007199254740991)]
    steps: list[RecorderStep]


class DaemonRpcMessage(RootModel[Request | Notification | SuccessResponse | DaemonErrorResponse]):
    root: Annotated[
        Request | Notification | SuccessResponse | DaemonErrorResponse,
        Field(
            description="UI·에이전트 ↔ daemon JSON-RPC 2.0 메시지 하나 (WebSocket 텍스트 프레임 하나, UTF-8 JSON, 최대 16 MiB). 값 규칙은 M0b와 같다: NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단. 메서드·알림 모양은 $defs의 Methods·Notifications 표",
            title="DaemonRpcMessage",
        ),
    ]


class RecorderInsertCheck(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderInsertCheckParams
    renderer: Literal[True]
    result: RecorderStepResult
    tool: Literal["ui_only"]


class RecorderStepUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderStepUpdateParams
    renderer: Literal[True]
    result: RecorderStepResult
    tool: Literal["ui_only"]


class RecorderSteps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    params: RecorderStepsParams
    renderer: Literal[True]
    result: RecorderStepsResult
    tool: Literal["ui_only"]


class Methods(BaseModel):
    """
    메서드 표 (단일 출처). 메시지가 아니라 타입 표다: params·result 모양, 권한 도구, 렌더러 표면에 내놓는지(false = Electron 주 프로세스 내부용)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent_connections: Annotated[AgentConnections, Field(alias="agent.connections")]
    agent_toolsets_enable: Annotated[AgentToolsetsEnable, Field(alias="agent.toolsets.enable")]
    agent_toolsets_get: Annotated[AgentToolsetsGet, Field(alias="agent.toolsets.get")]
    agents_detect: Annotated[AgentsDetect, Field(alias="agents.detect")]
    agents_get: Annotated[AgentsGet, Field(alias="agents.get")]
    agents_set: Annotated[AgentsSet, Field(alias="agents.set")]
    app_launch: Annotated[AppLaunch, Field(alias="app.launch")]
    approval_list: Annotated[ApprovalList, Field(alias="approval.list")]
    approval_preview: Annotated[ApprovalPreview, Field(alias="approval.preview")]
    approval_respond: Annotated[ApprovalRespond, Field(alias="approval.respond")]
    control_click: Annotated[ControlClick, Field(alias="control.click")]
    control_key: Annotated[ControlKey, Field(alias="control.key")]
    control_type: Annotated[ControlType, Field(alias="control.type")]
    daemon_shutdown: Annotated[DaemonShutdown, Field(alias="daemon.shutdown")]
    debug_breakpoints_get: Annotated[DebugBreakpointsGet, Field(alias="debug.breakpoints.get")]
    debug_breakpoints_set: Annotated[DebugBreakpointsSet, Field(alias="debug.breakpoints.set")]
    graph_check: Annotated[GraphCheck, Field(alias="graph.check")]
    graph_close: Annotated[GraphClose, Field(alias="graph.close")]
    graph_create: Annotated[GraphCreate, Field(alias="graph.create")]
    graph_list: Annotated[GraphList, Field(alias="graph.list")]
    graph_open: Annotated[GraphOpen, Field(alias="graph.open")]
    graph_patch: Annotated[GraphPatch, Field(alias="graph.patch")]
    graph_save: Annotated[GraphSave, Field(alias="graph.save")]
    graph_validate: Annotated[GraphValidate, Field(alias="graph.validate")]
    nodes_list: Annotated[NodesList, Field(alias="nodes.list")]
    permissions_get: Annotated[PermissionsGet, Field(alias="permissions.get")]
    permissions_set: Annotated[PermissionsSet, Field(alias="permissions.set")]
    plugins_cancel: Annotated[PluginsCancel, Field(alias="plugins.cancel")]
    plugins_gc: Annotated[PluginsGc, Field(alias="plugins.gc")]
    plugins_install: Annotated[PluginsInstall, Field(alias="plugins.install")]
    plugins_list: Annotated[PluginsList, Field(alias="plugins.list")]
    plugins_preview: Annotated[PluginsPreview, Field(alias="plugins.preview")]
    plugins_relock: Annotated[PluginsRelock, Field(alias="plugins.relock")]
    plugins_remove: Annotated[PluginsRemove, Field(alias="plugins.remove")]
    plugins_sync: Annotated[PluginsSync, Field(alias="plugins.sync")]
    plugins_upgrade: Annotated[PluginsUpgrade, Field(alias="plugins.upgrade")]
    recorder_commit_abort: Annotated[RecorderCommitAbort, Field(alias="recorder.commit_abort")]
    recorder_commit_finish: Annotated[RecorderCommitFinish, Field(alias="recorder.commit_finish")]
    recorder_commit_prepare: Annotated[
        RecorderCommitPrepare, Field(alias="recorder.commit_prepare")
    ]
    recorder_discard: Annotated[RecorderDiscard, Field(alias="recorder.discard")]
    recorder_frame: Annotated[RecorderFrame, Field(alias="recorder.frame")]
    recorder_insert_check: Annotated[RecorderInsertCheck, Field(alias="recorder.insert_check")]
    recorder_pause: Annotated[RecorderPause, Field(alias="recorder.pause")]
    recorder_resume: Annotated[RecorderResume, Field(alias="recorder.resume")]
    recorder_start: Annotated[RecorderStart, Field(alias="recorder.start")]
    recorder_state: Annotated[RecorderStateModel, Field(alias="recorder.state")]
    recorder_step_update: Annotated[RecorderStepUpdate, Field(alias="recorder.step.update")]
    recorder_steps: Annotated[RecorderSteps, Field(alias="recorder.steps")]
    recorder_stop: Annotated[RecorderStop, Field(alias="recorder.stop")]
    recorder_target_materialize: Annotated[
        RecorderTargetMaterialize, Field(alias="recorder.target.materialize")
    ]
    run_artifact: Annotated[RunArtifact, Field(alias="run.artifact")]
    run_cancel: Annotated[RunCancel, Field(alias="run.cancel")]
    run_children: Annotated[RunChildren, Field(alias="run.children")]
    run_compare: Annotated[RunCompare, Field(alias="run.compare")]
    run_diff: Annotated[RunDiff, Field(alias="run.diff")]
    run_events: Annotated[RunEvents, Field(alias="run.events")]
    run_export: Annotated[RunExport, Field(alias="run.export")]
    run_failure: Annotated[RunFailure, Field(alias="run.failure")]
    run_file: Annotated[RunFile, Field(alias="run.file")]
    run_index: Annotated[RunIndex, Field(alias="run.index")]
    run_list: Annotated[RunList, Field(alias="run.list")]
    run_pause: Annotated[RunPause, Field(alias="run.pause")]
    run_restart: Annotated[RunRestart, Field(alias="run.restart")]
    run_resume: Annotated[RunResume, Field(alias="run.resume")]
    run_search: Annotated[RunSearch, Field(alias="run.search")]
    run_start: Annotated[RunStart, Field(alias="run.start")]
    run_status: Annotated[RunStatus, Field(alias="run.status")]
    run_step: Annotated[RunStep, Field(alias="run.step")]
    run_subscribe: Annotated[RunSubscribe, Field(alias="run.subscribe")]
    run_unsubscribe: Annotated[RunUnsubscribe, Field(alias="run.unsubscribe")]
    screen_read_text: Annotated[ScreenReadText, Field(alias="screen.read_text")]
    screens_get: Annotated[ScreensGet, Field(alias="screens.get")]
    screens_list: Annotated[ScreensList, Field(alias="screens.list")]
    secrets_create: Annotated[SecretsCreate, Field(alias="secrets.create")]
    secrets_list: Annotated[SecretsList, Field(alias="secrets.list")]
    session_hello: Annotated[SessionHello, Field(alias="session.hello")]
    target_capture: Annotated[TargetCapture, Field(alias="target.capture")]
    target_load_image: Annotated[TargetLoadImage, Field(alias="target.load_image")]
    target_open: Annotated[TargetOpen, Field(alias="target.open")]
    target_preview: Annotated[TargetPreview, Field(alias="target.preview")]
    target_read_text: Annotated[TargetReadText, Field(alias="target.read_text")]
    target_save: Annotated[TargetSave, Field(alias="target.save")]
    windows_list: Annotated[WindowsList, Field(alias="windows.list")]
    workspace_info: Annotated[WorkspaceInfo, Field(alias="workspace.info")]
    workspace_read: Annotated[WorkspaceRead, Field(alias="workspace.read")]
    workspace_tree: Annotated[WorkspaceTree, Field(alias="workspace.tree")]

# 생성물 (packages/schema/run-index.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CallPath(RootModel[list[str]]):
    """
    호출 경로: 테스트부터의 호출 노드들 + 노드
    """

    root: Annotated[
        list[str],
        Field(
            description="호출 경로: 테스트부터의 호출 노드들 + 노드", min_length=1, title="CallPath"
        ),
    ]


class CompareEnvDiff(BaseModel):
    """
    환경 차이 한 줄 (같은 값은 넣지 않는다). key는 observed.dpi·conditions.profile·conditions.settings.<키>·packages.<이름>·plugins.<ID>·game_build 같은 점 경로. 비밀값 설정은 값 없이 키만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Annotated[Any, Field(description="기준 실행의 값 (없으면 null)")]
    key: Annotated[str, Field(min_length=1)]
    run: Annotated[Any, Field(description="이 실행의 값 (없으면 null)")]


class ChangedItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    change: Literal["added", "modified", "removed"]
    path: Annotated[str, Field(description="스냅샷 안 경로 (워크스페이스 기준)", min_length=1)]


class Node(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline_count: Annotated[int, Field(ge=0)]
    baseline_mean_ms: Annotated[float | None, Field(ge=0.0)]
    count: Annotated[int, Field(ge=0)]
    graph: str
    mean_ms: Annotated[float | None, Field(ge=0.0)]
    node: str


class RectItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class Rect(RootModel[list[RectItem]]):
    """
    [x, y, w, h] 픽셀
    """

    root: Annotated[
        list[RectItem],
        Field(description="[x, y, w, h] 픽셀", max_length=4, min_length=4, title="Rect"),
    ]


class RunId(RootModel[str]):
    root: Annotated[
        str,
        Field(description="실행 ID: 소문자·숫자 8자", pattern="^[a-z0-9]{8}$", title="RunId"),
    ]


class Sha256(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$", title="Sha256")]


class StepId(RootModel[str]):
    root: Annotated[str, Field(pattern="^s[1-9][0-9]*$", title="StepId")]


class StepStatus(RootModel[Literal["aborted", "cancelled", "error", "fail", "running", "success"]]):
    root: Annotated[
        Literal["aborted", "cancelled", "error", "fail", "running", "success"],
        Field(
            description="step.end의 status, 또는 step.end가 없는 스텝: running(진행 중 실행), aborted(끝난 실행에서 중단)",
            title="StepStatus",
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


class VideoView(BaseModel):
    """
    뷰어가 쓰는 영상 정보: video/index.json이 있으면 그 내용, 없으면 segments.jsonl에서 읽은 조각·빈 구간 (finalized false)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    finalized: Annotated[bool, Field(description="index.json(마무리 결과)에서 읽었다")]
    gaps: list[Any]
    reason: Annotated[
        Any | None, Field(description="urn:kookabug:video-index:0#/$defs/VideoReason")
    ] = None
    segments: list[Any]
    status: Annotated[Any, Field(description="urn:kookabug:video-index:0#/$defs/VideoStatus")]


class CompareGraph(BaseModel):
    """
    스냅샷 비교. 해시 = 스냅샷 폴더 파일마다 sha256을 내고, 상대 경로('/' 구분) 순으로 '경로\\0파일 sha256\\n' 줄을 이어 낸 sha256. 한쪽이라도 스냅샷 폴더가 없으면(예전 실행) CompareResult에 graph가 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    baseline_hash: Sha256
    changed: list[ChangedItem]
    hash: Sha256
    same: bool


class CompareScreen(BaseModel):
    """
    화면 차이: 실패 스텝(또는 고른 스텝)의 증거와 기준 실행의 같은 호출 경로·같은 노드 썸네일(남은 마지막 회차)을 같은 크기 회색조로 줄여 비교. 호출 스텝이면 그 증거를 캡처한 안쪽 스텝의 경로로 찾고(그 스텝에 기준 썸네일이 없으면 다른 노드로 넘어가지 않고 reason), 안쪽 스텝을 모를 때만 기준 실행에서 그 호출 경로 아래의 마지막 썸네일을 쓴다(baseline_step은 실제로 쓴 스텝). 비교하지 못하면 reason. reason도 diff_ratio도 없으면 이 환경에서 화면 차이를 계산할 수 없다(플랫폼 없음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    baseline_file: Annotated[
        str | None, Field(description="기준 실행 폴더 기준 파일 (thumbs/<스텝>.jpg)")
    ]
    baseline_step: StepId | None
    diff_ratio: Annotated[
        float | None, Field(description="달라진 픽셀 비율 (0~1)", ge=0.0, le=1.0)
    ] = None
    file: Annotated[
        str | None, Field(description="이 실행 폴더 기준 파일 (steps/<스텝>_fail.png 등)")
    ]
    reason: Annotated[
        Literal[
            "image_unreadable", "no_evidence", "no_matching_step", "no_thumbnail", "policy_omitted"
        ]
        | None,
        Field(
            description="비교하지 못한 이유. policy_omitted: 정책으로 남기지 않음, no_thumbnail: 기준 실행에 썸네일 없음, no_evidence: 이 실행에 증거 없음, no_matching_step: 기준 실행에 같은 노드 스텝 없음, image_unreadable: 두 이미지 중 하나를 읽지 못함(파일이 깨졌거나 사라짐)"
        ),
    ] = None
    regions: Annotated[
        list[Rect] | None,
        Field(description="차이 영역 상자 (이 실행 증거 이미지 좌표)", max_length=5),
    ] = None
    step: StepId


class Inflection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after_ms: Annotated[float, Field(description="변곡 회차부터의 회차 경과 중앙값", ge=0.0)]
    before_ms: Annotated[float, Field(description="앞 절반 회차 경과 중앙값", ge=0.0)]
    body_after_ms: Annotated[
        float | None, Field(description="body_node의 변곡 회차부터 평균 경과", ge=0.0)
    ] = None
    body_before_ms: Annotated[
        float | None, Field(description="body_node의 변곡 전 평균 경과", ge=0.0)
    ] = None
    body_node: Annotated[
        str | None, Field(description="본문에서 가장 많이 늦어진 노드 (반복 노드와 같은 그래프)")
    ] = None
    from_iteration: Annotated[int, Field(ge=0)]
    graph: str
    node: str
    step: StepId


class CompareTime(BaseModel):
    """
    시간 비교. 경과는 멈춤을 뺀 값(스텝에 active_duration_ms가 있으면 그것)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    debug_intervened: Annotated[
        bool | None,
        Field(
            description="이 실행이 디버거로 멈췄던 실행: 회차 경과가 벽시계라 변곡을 내지 않는다(inflections는 빈 목록)"
        ),
    ] = None
    inflections: Annotated[
        list[Inflection],
        Field(
            description="반복 스텝(step, 노드는 반복 노드)의 회차 전체 경과에서 앞 절반 중앙값의 2배를 넘는 경과가 3회차(남은 회차가 적으면 남은 전부, 최소 2) 이어지기 시작한 첫 회차. 회차 4개 이상만, 최대 20개. 앞 1/4쯤 안에서 늦어지기 시작하면 앞 절반 중앙값이 이미 늦은 값이라 잡지 못한다. body_*는 그 반복 본문(회차 바로 아래 스텝)에서 변곡 전·후 평균이 가장 많이 는 노드"
        ),
    ]
    nodes: Annotated[
        list[Node], Field(description="노드별 평균 경과 비교 (한쪽에만 있으면 그쪽 값은 null)")
    ]


class IterationSummary(BaseModel):
    """
    반복 스텝의 회차 하나 (회차 안 스텝은 run.children으로 읽는다). status는 회차 안 스텝 중 가장 나쁜 결과 (error > fail > cancelled > aborted > running > success)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    duration_ms: Annotated[int | None, Field(ge=0)]
    iteration: Annotated[int, Field(ge=0)]
    status: StepStatus
    steps: Annotated[int, Field(description="회차 안 스텝 수 (안쪽 호출 포함)", ge=0)]
    t_start: Timestamp


class NodeStat(BaseModel):
    """
    노드별 통계 (그래프·노드마다, 끝난 스텝만)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    count: Annotated[int, Field(ge=0)]
    error: Annotated[int, Field(ge=0)]
    fail: Annotated[int, Field(ge=0)]
    graph: str
    last_failure_step: StepId | None
    max_ms: Annotated[int, Field(ge=0)]
    mean_ms: Annotated[float, Field(ge=0.0)]
    node: str
    p95_ms: Annotated[float, Field(ge=0.0)]
    success: Annotated[int, Field(ge=0)]


class PauseSpan(BaseModel):
    """
    멈춘 구간 (debug.pause ~ debug.resume, 재개 없이 끝났으면 t_end null)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Literal["continue", "step_into", "step_out", "step_over"] | None = None
    reason: Literal["breakpoint", "request", "step"] | None = None
    step: StepId | None
    t_end: Timestamp | None
    t_start: Timestamp
    where: Literal["boundary", "poll"] | None = None


class StepNode(BaseModel):
    """
    색인의 스텝 하나 (events.jsonl의 step.start·attempt.end·step.end를 합친 것). 반복 스텝(iterations가 있음)의 status·exit·t_end·duration_ms·message는 반복 전체다: 반복 노드에 마지막으로 도착한 스텝이 반복을 끝냈으면(done·한도 fail) 그 스텝 것, 본문 실패·중단으로 돌아오지 못했으면 마지막 회차의 가장 나쁜 결과(그 회차가 성공뿐이면 진행 중 실행은 running·t_end null, 끝난 실행은 aborted)와 그 회차 끝 시각, exit null. duration_ms는 첫 도착 시작부터 그 끝까지(벽시계). active_duration_ms는 없다. 노드별 통계(stats)는 도착마다의 실제 스텝 값이다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    active_duration_ms: Annotated[
        int | None, Field(description="멈춘 시간을 뺀 경과 (step.end에 있을 때만)", ge=0)
    ] = None
    artifacts: Annotated[
        list[str] | None, Field(description="실행 폴더 기준 증거 파일 (step.end.artifacts)")
    ] = None
    attempt: Annotated[int, Field(ge=1)]
    calls: Annotated[
        str | None, Field(description="서브그래프 호출이면 부른 그래프 (워크스페이스 기준)")
    ] = None
    children: Annotated[int, Field(description="바로 아래 스텝 수 (반복이면 모든 회차 합)", ge=0)]
    duration_ms: Annotated[int | None, Field(ge=0)]
    evidence: Annotated[bool, Field(description="step.end.evidence가 있다 (run.step으로 읽는다)")]
    exit: str | None
    graph: Annotated[
        str,
        Field(
            description="노드가 든 그래프 (워크스페이스 기준. 실행 때 쓴 스냅샷은 실행 폴더 snapshot/ 아래 같은 경로)"
        ),
    ]
    iteration: Annotated[
        int | None,
        Field(
            description="parent가 반복 스텝일 때 그 회차 (본문 스텝은 events의 iteration, 되돌아옴은 방금 끝난 회차)",
            ge=0,
        ),
    ] = None
    iterations: Annotated[
        list[IterationSummary] | None, Field(description="반복 스텝이면 회차별 요약 (회차 순)")
    ] = None
    message: str | None = None
    node: str
    omitted: list[Any] | None = None
    parent: Annotated[
        StepId | None,
        Field(
            description="색인 부모: 호출 스텝, 또는 반복 스텝(반복 노드에 처음 도착한 스텝). 반복은 실행기에서 깊이를 더하지 않아 events의 parent와 다를 수 있다: 본문 스텝과 본문이 끝나 반복 노드로 되돌아온 스텝이 반복 스텝 아래 회차로 묶인다. 최상위는 null"
        ),
    ]
    path: CallPath
    retried: Annotated[bool | None, Field(description="재시도 끝에 성공 (step.end.retried)")] = None
    status: StepStatus
    step: StepId
    t_end: Timestamp | None
    t_start: Timestamp
    thumbnail: Annotated[
        bool | None, Field(description="썸네일 파일이 있다 (thumbs/<스텝>.jpg, 파일 유무가 기준)")
    ] = None


class RunIndex(BaseModel):
    """
    실행 색인 (run.index 결과). 코어 record/index.py가 events.jsonl을 한 번 훑어 만든다. 최상위 스텝과 실패 사슬의 스텝만 담고, 그 밖의 스텝은 run.children으로 쪽마다 읽는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    failure_chain: Annotated[
        list[StepId],
        Field(
            description="루트부터 실패 스텝(run.end.failure_step)까지의 스텝 (실패가 없으면 빈 목록)"
        ),
    ]
    last_seq: Annotated[
        int,
        Field(
            description="색인에 넣은 마지막 이벤트 seq (진행 중 실행은 구독 커서와 맞춘다)", ge=0
        ),
    ]
    pauses: list[PauseSpan]
    run: Annotated[
        dict[str, Any] | None,
        Field(description="run.json 내용 그대로 (형식은 run.schema.json, 아직 없으면 null)"),
    ]
    run_dir: Annotated[
        str, Field(description="실행 폴더 (워크스페이스 기준, kbimg://ws/<run_dir>/<파일>로 연다)")
    ]
    run_id: RunId
    state: Literal["ended", "running"]
    stats: list[NodeStat]
    steps: Annotated[
        list[StepNode], Field(description="최상위 스텝과 실패 사슬의 스텝 (step 번호 순)")
    ]
    video: Annotated[VideoView | None, Field(description="video/ 폴더가 없으면 null")]


class CompareResult(BaseModel):
    """
    run.compare 결과: 지난 성공(기준 실행)과의 차이. 기준 실행이 없으면 baseline이 null이고 나머지 비교는 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: RunId | None
    baseline_picked: Annotated[
        Literal["auto", "user"] | None,
        Field(
            description="auto: 같은 테스트·같은 프로필·pass·디버거 개입 아님 중 가장 최근, user: 요청이 고름"
        ),
    ] = None
    env: list[CompareEnvDiff] | None = None
    graph: CompareGraph | None = None
    message: Annotated[
        str | None, Field(description="기준 실행이 없을 때의 안내 (예: 비교할 성공 실행 없음)")
    ] = None
    run_id: RunId
    screen: CompareScreen | None = None
    time: CompareTime | None = None

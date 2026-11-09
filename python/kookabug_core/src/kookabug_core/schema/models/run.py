# 생성물 (packages/schema/run.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class Agent(BaseModel):
    """
    에이전트 제어 실행을 낸 에이전트 (source agent_control)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str


class FailurePath(RootModel[list[str]]):
    root: Annotated[list[str], Field(min_length=1)]


class CheatsUsedItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    calls: Annotated[int, Field(ge=1)]
    cheat: str
    digest: str
    rev: Annotated[int, Field(ge=1)]


class Claim(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assertions: list[str]
    executed: list[str]
    id: str
    passed: list[str]
    rev: Annotated[int, Field(ge=1)]


class Qa(BaseModel):
    """
    M8 그래프 qa 결과: 검증 노드가 실제로 실행·통과했나, 쓴 치트, 설정 오류
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    cheats_used: list[CheatsUsedItem]
    claims: list[Claim]
    config_errors: list[str]
    not_applicable: Annotated[
        str | None,
        Field(description="qa.profiles가 이번 프로필을 담지 않아 판정 skipped (qa_not_applicable)"),
    ] = None


class RecordOverride(BaseModel):
    """
    실행별 기록 강제 (M7 R2): 에이전트 제어 실행은 스크린샷·영상을 끄고 비밀값을 가렸다. 그래프·워크스페이스 기록 정책과 별개
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    by: Literal["agent_control"]
    redact_secrets: Literal[True]
    screenshots: Literal["off"]
    video: Literal["off"]


class DebugInfo(BaseModel):
    """
    디버거 개입 정보 (스키마 v0 6장)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    debug_intervened: Annotated[bool | None, Field(description="디버거가 개입한 실행")] = None
    pause_count: Annotated[int | None, Field(ge=0)] = None
    paused_ms: Annotated[
        int | None, Field(description="멈춰 있던 시간 (M3부터 기한에서 뺀다)", ge=0)
    ] = None


class Diagnostic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: str
    file: str | None = None
    message: str
    node: str | None = None
    pointer: str | None = None
    severity: Literal["error", "warning"]


class FinalizedBy(RootModel[Literal["runner", "supervisor"]]):
    root: Annotated[
        Literal["runner", "supervisor"],
        Field(
            description="실행을 마무리한 쪽: runner 자신, 또는 runner가 죽은 뒤 감독자",
            title="FinalizedBy",
        ),
    ]


class ClientSizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class Observed(BaseModel):
    """
    실행에서 처음 관측한 창의 캡처 방식·클라이언트 크기·DPI (지난 성공과 비교의 환경, M3)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    backend: Annotated[str, Field(description="캡처 방식 (wgc·gdi·fake 등)", min_length=1)]
    client_size: Annotated[
        list[ClientSizeItem],
        Field(description="[w, h] 물리 픽셀", max_length=2, min_length=2),
    ]
    dpi: Annotated[int, Field(ge=1)]


class Plugin(BaseModel):
    """
    실행이 쓴 플러그인. 설치 플러그인(kookabug.lock)은 env·wheel_sha256·schema_sha256까지 (M6)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    env: Annotated[
        str | None, Field(description="설치 플러그인이 돈 환경 이름 (shared·iso-<id>)")
    ] = None
    id: str
    schema_sha256: Annotated[str | None, Field(pattern="^[0-9a-f]{64}$")] = None
    version: str
    wheel_sha256: Annotated[str | None, Field(pattern="^[0-9a-f]{64}$")] = None


class RunId(RootModel[str]):
    root: Annotated[
        str,
        Field(description="실행 ID: 소문자·숫자 8자", pattern="^[a-z0-9]{8}$", title="RunId"),
    ]


class RunnerInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pid: Annotated[int, Field(ge=0)]
    python: str
    version: str


class SettingKey(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$", title="SettingKey")]


class SettingUse(BaseModel):
    """
    설정값과 그 값을 준 계층. 비밀값(secret: true)은 값을 남기지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    layer: Literal["local", "options", "profile", "workspace"]
    secret: Literal[True] | None = None
    value: Any | None = None


class Timestamp(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
            title="Timestamp",
        ),
    ]


class Verdict(RootModel[Literal["error", "fail", "pass", "skipped"]]):
    root: Annotated[Literal["error", "fail", "pass", "skipped"], Field(title="Verdict")]


class VideoSummary(BaseModel):
    """
    영상 요약 (video/index.json에서 읽는다, M3). kept·deleted는 조각 수, bytes는 남은 조각 바이트 합. 실행 판정은 바꾸지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int, Field(ge=0)]
    deleted: Annotated[int, Field(ge=0)]
    kept: Annotated[int, Field(ge=0)]
    reason: Annotated[
        Any | None, Field(description="urn:kookabug:video-index:0#/$defs/VideoReason")
    ] = None
    status: Annotated[Any, Field(description="urn:kookabug:video-index:0#/$defs/VideoStatus")]


class Conditions(BaseModel):
    """
    실행 조건
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: Annotated[int, Field(ge=1)]
    platform: Annotated[str, Field(description="플랫폼 종류 (none·fake·windows)")]
    plugin_lock_sha256: Annotated[
        str | None,
        Field(
            description="실행이 읽은 kookabug.lock의 정규 잠금 해시 (설치 플러그인을 쓴 실행, M6)",
            pattern="^[0-9a-f]{64}$",
        ),
    ] = None
    profile: str | None
    settings: Annotated[
        dict[
            Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")],
            SettingUse,
        ],
        Field(description="이 실행이 쓴 $setting 키 → 값·계층. 비밀값은 키만"),
    ]


class Run(BaseModel):
    """
    실행 정보·결과 (실행 폴더의 run.json). 원자적 교체로만 쓴다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    active_duration_ms: Annotated[
        int | None, Field(description="멈춘 시간을 뺀 경과 (M3)", ge=0)
    ] = None
    agent: Annotated[
        Agent | None, Field(description="에이전트 제어 실행을 낸 에이전트 (source agent_control)")
    ] = None
    agent_mask: Annotated[
        Literal[1] | None,
        Field(
            description="에이전트용 비밀값 분류(이벤트 secret_paths·스텝 secret·agent_withhold)를 남긴 기록 (M5 3.8). 없으면 daemon은 에이전트에게 안전 필드(판정·스텝·노드·출구·상태·오류 코드·시각·기간)만 준다"
        ),
    ] = None
    code: str | None = None
    conditions: Conditions | None = None
    debug_intervened: Annotated[bool | None, Field(description="디버거가 개입한 실행")] = None
    diagnostics: list[Diagnostic] | None = None
    ended_at: Timestamp | None = None
    failure_path: FailurePath | None = None
    failure_step: str | None = None
    finalized_by: FinalizedBy | None = None
    format: Literal["kookabug.run/0"]
    game_build: str | None = None
    graph: Annotated[str, Field(description="실행한 테스트 그래프 (워크스페이스 기준)")]
    observed: Observed | None = None
    packages: Annotated[dict[str, str] | None, Field(description="패키지 이름 → 버전")] = None
    pause_count: Annotated[int | None, Field(ge=0)] = None
    paused_ms: Annotated[
        int | None, Field(description="멈춰 있던 시간 (M3부터 기한에서 뺀다)", ge=0)
    ] = None
    plugins: list[Plugin] | None = None
    qa: Annotated[
        Qa | None,
        Field(
            description="M8 그래프 qa 결과: 검증 노드가 실제로 실행·통과했나, 쓴 치트, 설정 오류"
        ),
    ] = None
    reason: str | None = None
    record_override: Annotated[
        RecordOverride | None,
        Field(
            description="실행별 기록 강제 (M7 R2): 에이전트 제어 실행은 스크린샷·영상을 끄고 비밀값을 가렸다. 그래프·워크스페이스 기록 정책과 별개"
        ),
    ] = None
    retried_steps: Annotated[
        int | None,
        Field(
            description='재시도 끝에 성공한 스텝 수 (step.end.retried). pass인데 0보다 크면 "불안정" (M3)',
            ge=0,
        ),
    ] = None
    run_id: RunId
    run_json_repaired: Annotated[
        Literal[True] | None, Field(description="감독자가 run.end에서 다시 만든 파일")
    ] = None
    runner: RunnerInfo | None = None
    runner_exit_code: int | None = None
    secret_paths: Annotated[
        list[str] | None,
        Field(
            description='run.end.secret_paths 그대로 (reason에 비밀값이 있으면 ["/reason"], M5 3.8)',
            min_length=1,
        ),
    ] = None
    source: Annotated[
        Literal["agent_control"] | None,
        Field(
            description="실행 출처 (M5 3.9). agent_control = 에이전트의 게임 조작(kb_input_*)을 daemon이 한 스텝짜리 실행으로 돌린 것. 없으면 일반 실행"
        ),
    ] = None
    started_at: Timestamp
    status: Literal["finished", "running"]
    verdict: Verdict | None = None
    video: VideoSummary | None = None

# 생성물 (packages/schema/run.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class FailurePath(RootModel[list[str]]):
    root: Annotated[list[str], Field(min_length=1)]


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


class Plugin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    version: str


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


class Conditions(BaseModel):
    """
    실행 조건
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: Annotated[int, Field(ge=1)]
    platform: Annotated[str, Field(description="플랫폼 종류 (none·fake·windows)")]
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
    packages: Annotated[dict[str, str] | None, Field(description="패키지 이름 → 버전")] = None
    pause_count: Annotated[int | None, Field(ge=0)] = None
    paused_ms: Annotated[
        int | None, Field(description="멈춰 있던 시간 (M3부터 기한에서 뺀다)", ge=0)
    ] = None
    plugins: list[Plugin] | None = None
    reason: str | None = None
    run_id: RunId
    run_json_repaired: Annotated[
        Literal[True] | None, Field(description="감독자가 run.end에서 다시 만든 파일")
    ] = None
    runner: RunnerInfo | None = None
    runner_exit_code: int | None = None
    started_at: Timestamp
    status: Literal["finished", "running"]
    verdict: Verdict | None = None

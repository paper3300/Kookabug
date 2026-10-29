# 생성물 (packages/schema/workspace.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class PermissionVerdict(RootModel[Literal["allow", "ask", "deny"]]):
    root: Annotated[Literal["allow", "ask", "deny"], Field(title="PermissionVerdict")]


class RecordPolicy(BaseModel):
    """
    기록 정책. 상위(워크스페이스 → 테스트 → 서브그래프 → 노드)에서 끈 것은 하위에서 켤 수 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    screenshots: Literal["off", "on"] | None = None
    video: Literal["failed_only", "off", "on"] | None = None


class Retention(BaseModel):
    """
    실행 기록 보관
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    failed_days: Annotated[int | None, Field(ge=0)] = None
    keep_last: Annotated[int | None, Field(ge=0)] = None
    passed_days: Annotated[int | None, Field(ge=0)] = None


class SettingKey(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$", title="SettingKey")]


class Settings(
    RootModel[
        dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")], Any]
    ]
):
    root: Annotated[
        dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")], Any],
        Field(
            description="설정 키 → 값. null은 사람마다 .kookabug/local.json에 넣어야 하는 값",
            title="Settings",
        ),
    ]


class PermissionRule(BaseModel):
    """
    권한 규칙 하나. rule은 "도구" 또는 "도구(인자 패턴)". 도구·인자 모두 glob(*, ?), 대소문자 구분
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rule: Annotated[str, Field(pattern="^[a-z0-9_*?]+(\\(.*\\))?$")]
    verdict: PermissionVerdict


class Permissions(BaseModel):
    """
    에이전트 권한. 이 파일(kookabug.json)의 툴셋·프리셋 값은 상한이다 (사용자·프로젝트 계층이 더 풀 수 없다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    preset: Literal["full", "graph_author", "read_only", "runner"] | None = None
    rules: list[PermissionRule] | None = None
    toolsets: (
        dict[
            Literal["control", "core", "graph_edit", "observe", "run", "screens"], PermissionVerdict
        ]
        | None
    ) = None


class Profile(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    settings: Settings | None = None


class Workspace(BaseModel):
    """
    팀 공용 워크스페이스 설정 (kookabug.json)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.workspace/0"]
    permissions: Permissions | None = None
    profiles: (
        dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")], Profile] | None
    ) = None
    record: RecordPolicy | None = None
    retention: Retention | None = None
    settings: Settings | None = None

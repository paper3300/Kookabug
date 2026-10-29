# 생성물 (packages/schema/local.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class PermissionVerdict(RootModel[Literal["allow", "ask", "deny"]]):
    root: Annotated[Literal["allow", "ask", "deny"], Field(title="PermissionVerdict")]


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
            description="설정 키 → 값. 여기 있는 키는 프로필·기본값보다 먼저 쓴다 (null도 선택된 값)",
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
    에이전트 권한 (프로젝트 계층). 툴셋·프리셋 값이 사용자 설정보다 먼저다
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


class Local(BaseModel):
    """
    개인 설정 (.kookabug/local.json, Git 제외)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.local/0"]
    permissions: Permissions | None = None
    settings: Settings | None = None

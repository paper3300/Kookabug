# 생성물 (packages/schema/user-settings.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class PermissionVerdict(RootModel[Literal["allow", "ask", "deny"]]):
    root: Annotated[Literal["allow", "ask", "deny"], Field(title="PermissionVerdict")]


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
    에이전트 권한 (사용자 계층). 모든 워크스페이스에 적용되고, 프로젝트 계층 값이 먼저다
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


class UserSettings(BaseModel):
    """
    사용자 설정 (%APPDATA%\\Kookabug\\settings.json, 워크스페이스 밖)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.user-settings/0"]
    permissions: Permissions | None = None

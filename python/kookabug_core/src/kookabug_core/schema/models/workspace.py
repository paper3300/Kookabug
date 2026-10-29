# 생성물 (packages/schema/workspace.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


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
    profiles: (
        dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")], Profile] | None
    ) = None
    record: RecordPolicy | None = None
    retention: Retention | None = None
    settings: Settings | None = None

# 생성물 (packages/schema/local.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


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


class Local(BaseModel):
    """
    개인 설정 (.kookabug/local.json, Git 제외)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.local/0"]
    settings: Settings | None = None

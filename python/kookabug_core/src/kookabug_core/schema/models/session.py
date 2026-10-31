# 생성물 (packages/schema/session.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Timestamp(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
            title="Timestamp",
        ),
    ]


class Session(BaseModel):
    """
    .kookabug/session.json: 워크스페이스 daemon 하나의 접속 정보. daemon이 .kookabug/daemon.lock을 쥔 뒤 임시 파일 + replace로 쓰고, 끝날 때 자기 start_id인 경우에만 지운다. 판단 근거는 잠금이고, pid·process_created는 붙기 전에 보는 빠른 확인이다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    daemon_version: Annotated[str, Field(min_length=1)]
    format: Literal["kookabug.session/0"]
    pid: Annotated[int, Field(ge=1, le=9007199254740991)]
    port: Annotated[int, Field(ge=1, le=65535)]
    process_created: Annotated[
        str,
        Field(
            description="daemon 프로세스 생성 시각: Windows FILETIME(100ns 단위)을 10진 문자열로",
            pattern="^[0-9]+$",
        ),
    ]
    protocol: Annotated[int, Field(ge=1, le=9007199254740991)]
    start_id: Annotated[
        str,
        Field(
            description="daemon이 시작할 때 정한 무작위 ID (16바이트 hex). 바뀌면 daemon이 교체된 것",
            pattern="^[0-9a-f]{32}$",
        ),
    ]
    started_at: Timestamp
    token: Annotated[
        str,
        Field(description="session.hello 인증 토큰 (32바이트 hex)", pattern="^[0-9a-f]{64}$"),
    ]
    workspace: Annotated[str, Field(description="워크스페이스 루트 절대 경로", min_length=1)]

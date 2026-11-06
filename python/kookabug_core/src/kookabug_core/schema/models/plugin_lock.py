# 생성물 (packages/schema/plugin-lock.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Module(RootModel[str]):
    root: Annotated[str, Field(min_length=1)]


class LockManifest(BaseModel):
    """
    설치한 플러그인의 스키마 머리 (id·version 뺀 나머지). modules로 워커를 띄운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    isolation: Literal["auto", "shared", "isolated"] | None = None
    min_core: str | None = None
    modules: Annotated[list[Module], Field(min_length=1)]
    permissions: list[Literal["capture", "input", "process", "filesystem", "network", "secrets"]]
    title: str | None = None
    ui: str | None = None


class Hash(RootModel[str]):
    root: Annotated[str, Field(pattern="^sha256:[0-9a-f]{64}$")]


class LockPackage(BaseModel):
    """
    환경의 의존성 하나 (wheel만, uv pip compile --generate-hashes 결과)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    hashes: Annotated[list[Hash], Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]


class LockSha256(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$", title="LockSha256")]


class LockSource1(BaseModel):
    """
    원천 출처 (재설치·upgrade용, sync는 쓰지 않는다). 사용자 정보(인증)는 지운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    commit: Annotated[str, Field(pattern="^[0-9a-f]{40}$")]
    kind: Literal["git"]
    ref: str | None
    url: str


class LockSource2(BaseModel):
    """
    원천 출처 (재설치·upgrade용, sync는 쓰지 않는다). 사용자 정보(인증)는 지운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["wheel"]
    path: str | None = None
    sha256: LockSha256
    url: str | None = None


class LockSource3(BaseModel):
    """
    원천 출처 (재설치·upgrade용, sync는 쓰지 않는다). 사용자 정보(인증)는 지운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["path"]
    path: str


class LockSource(RootModel[LockSource1 | LockSource2 | LockSource3]):
    root: Annotated[
        LockSource1 | LockSource2 | LockSource3,
        Field(
            description="원천 출처 (재설치·upgrade용, sync는 쓰지 않는다). 사용자 정보(인증)는 지운다",
            title="LockSource",
        ),
    ]


class PluginId(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$", title="PluginId")]


class Sdk(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    version: Annotated[str, Field(min_length=1)]
    wheel_sha256: LockSha256


class LockEnvironment(BaseModel):
    """
    실행 환경 하나. fingerprint = sha256(정규 JSON {python, platform, sdk, packages, 그 환경 플러그인 wheel_sha256 목록}) — 환경 찾기의 근거. digest = 환경 Lib/site-packages 실제 파일 바이트 해시 (재현 판정)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    digest: LockSha256
    fingerprint: LockSha256
    packages: list[LockPackage]
    plugins: list[PluginId]


class LockPlugin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conflicts: Annotated[
        list[str] | None,
        Field(
            description="isolated_because = conflict일 때 공유 환경과 판이 맞지 않는 패키지 이름"
        ),
    ] = None
    dist: Annotated[str, Field(min_length=1)]
    env: Annotated[str, Field(min_length=1)]
    id: PluginId
    isolated_because: Literal["declared", "conflict"] | None
    manifest: LockManifest
    requires: list[str]
    schema_sha256: LockSha256
    source: LockSource
    version: Annotated[str, Field(min_length=1)]
    wheel: Annotated[
        str,
        Field(
            description="plugins/wheels/<wheel_sha256>/<원래 wheel 파일명> (워크스페이스 기준, 커밋)",
            pattern="^plugins/wheels/[0-9a-f]{64}/[^/\\\\]+\\.whl$",
        ),
    ]
    wheel_sha256: LockSha256


class PluginLock(BaseModel):
    """
    kookabug.lock (M6 계획 3.3): 설치한 플러그인과 해결된 의존성 환경. 커밋한다. 다른 PC는 잠금과 커밋된 plugins/wheels/만으로 같은 환경을 다시 만든다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    environments: dict[str, LockEnvironment]
    format: Literal["kookabug.lock/0"]
    index: Annotated[str, Field(description="의존성 인덱스 URL (사용자 정보 없음)")]
    platform: str
    plugins: Annotated[list[LockPlugin], Field(description="id 순")]
    python: Annotated[str, Field(description="Python 소판 (예: 3.14)", pattern="^\\d+\\.\\d+$")]
    python_full: str
    sdk: Sdk

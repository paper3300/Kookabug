# 생성물 (packages/schema/workspace.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class CheatCategory(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Annotated[str | None, Field(max_length=2000)] = None
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    title: Annotated[str, Field(max_length=200, min_length=1)]
    unattended: bool | None = None


class CheatsPolicy(BaseModel):
    """
    M8: 치트 정책. 분류는 사용자 정의(제품 기본 분류 없음). 사람 전용 쓰기
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    categories: list[CheatCategory] | None = None
    enabled: bool | None = None


class Det(BaseModel):
    """
    rapidocr 검출 크기 설정 (없는 값은 기본값)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    limit_side_len: Annotated[
        int | None,
        Field(description="짧은 변이 이보다 작을 때만 검출 입력을 늘린다. 기본 64", ge=32),
    ] = None
    max_side_len: Annotated[
        int | None, Field(description="긴 변이 이보다 크면 줄인다. 기본 4096", ge=256)
    ] = None
    single_max_pixels: Annotated[
        int | None,
        Field(
            description="픽셀 수가 이 이하면 한 번에 검출, 넘으면 타일로 나눈다. 기본 655360",
            ge=65536,
        ),
    ] = None
    tile_overlap: Annotated[
        int | None, Field(description="이웃 타일이 겹치는 픽셀. 기본 128", ge=0)
    ] = None
    tile_side: Annotated[
        int | None, Field(description="타일 한 변 (32의 배수). 기본 640", ge=256)
    ] = None


class OcrSettings(BaseModel):
    """
    OCR 엔진과 그 설정. engine이 없으면 rapidocr
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    det: Annotated[Det | None, Field(description="rapidocr 검출 크기 설정 (없는 값은 기본값)")] = (
        None
    )
    engine: Literal["rapidocr"] | None = None


class PermissionVerdict(RootModel[Literal["allow", "ask", "deny"]]):
    root: Annotated[Literal["allow", "ask", "deny"], Field(title="PermissionVerdict")]


class FindLink(RootModel[str]):
    root: Annotated[str, Field(min_length=1)]


class PluginIndex(BaseModel):
    """
    M6: 플러그인 의존성 인덱스. kookabug.json은 팀 공용, .kookabug/local.json의 같은 키가 개인 덮어쓰기. URL의 사용자 정보는 잠금·로그·화면에 남기지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    find_links: list[FindLink] | None = None
    url: Annotated[str | None, Field(min_length=1)] = None


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


class RunConditions(BaseModel):
    """
    실행 조건 기본값 (시간은 밀리초). CLI 옵션이 이 값보다 우선한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    capture_timeout_ms: Annotated[
        int | None,
        Field(
            description="관측 호출(캡처·찾기·OCR) 하나의 설정 기한. 넘으면 capture_timeout. 없으면 2000",
            ge=1,
        ),
    ] = None
    deadline_ms: Annotated[int | None, Field(description="실행 전체 기한. 없으면 30분", ge=1)] = (
        None
    )
    frame_budget_mib: Annotated[
        int | None,
        Field(
            description="프레임 저장소 바이트 예산 (MiB). 넘으면 스텝 출력으로 나간 프레임부터 버린다. 없으면 512",
            ge=1,
        ),
    ] = None
    frame_output_refs: Annotated[
        int | None,
        Field(
            description="스텝 출력(이미지·찾기 결과)으로 나간 프레임을 남기는 개수. 없으면 32", ge=0
        ),
    ] = None
    shutdown_grace_ms: Annotated[
        int | None,
        Field(
            description="취소·마무리를 시작한 runner가 끝나기를 기다리는 시간. 넘으면 감독자가 끝낸다. 없으면 5000",
            ge=1,
        ),
    ] = None
    worker_cancel_grace_ms: Annotated[
        int | None,
        Field(
            description="취소한 워커 노드가 끝나기를 기다리는 시간. 넘으면 워커를 끝낸다. 없으면 2000",
            ge=1,
        ),
    ] = None
    worker_start_timeout_ms: Annotated[
        int | None, Field(description="워커가 시작 인사에 답하기까지의 기한. 없으면 30000", ge=1)
    ] = None


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


class Source1(BaseModel):
    """
    원본 하나. path·url·local 중 하나. local이면 경로는 .kookabug/local.json#sources.<id>.path
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^[A-Za-z0-9_.-]{1,64}$")]
    kind: Literal["code", "data", "design_doc", "other", "patch_notes", "qa_sheet", "strings"]
    local: Literal[True] | None = None
    path: Annotated[str, Field(max_length=1000, min_length=1)]
    title: Annotated[str, Field(max_length=200, min_length=1)]
    url: Annotated[str | None, Field(max_length=2000, min_length=1, pattern="^https?://")] = None


class Source2(BaseModel):
    """
    원본 하나. path·url·local 중 하나. local이면 경로는 .kookabug/local.json#sources.<id>.path
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^[A-Za-z0-9_.-]{1,64}$")]
    kind: Literal["code", "data", "design_doc", "other", "patch_notes", "qa_sheet", "strings"]
    local: Literal[True] | None = None
    path: Annotated[str | None, Field(max_length=1000, min_length=1)] = None
    title: Annotated[str, Field(max_length=200, min_length=1)]
    url: Annotated[str, Field(max_length=2000, min_length=1, pattern="^https?://")]


class Source3(BaseModel):
    """
    원본 하나. path·url·local 중 하나. local이면 경로는 .kookabug/local.json#sources.<id>.path
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^[A-Za-z0-9_.-]{1,64}$")]
    kind: Literal["code", "data", "design_doc", "other", "patch_notes", "qa_sheet", "strings"]
    local: Literal[True]
    path: Annotated[str | None, Field(max_length=1000, min_length=1)] = None
    title: Annotated[str, Field(max_length=200, min_length=1)]
    url: Annotated[str | None, Field(max_length=2000, min_length=1, pattern="^https?://")] = None


class Source(RootModel[Source1 | Source2 | Source3]):
    root: Annotated[
        Source1 | Source2 | Source3,
        Field(
            description="원본 하나. path·url·local 중 하나. local이면 경로는 .kookabug/local.json#sources.<id>.path",
            title="Source",
        ),
    ]


class WorkspaceRecordPolicy(BaseModel):
    """
    워크스페이스 기록 정책: 그래프 RecordPolicy(screenshots·video)에 비밀값 가림 스위치를 더한 것. 상위에서 끈 것은 하위에서 켤 수 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    redact_secrets: Annotated[
        bool | None,
        Field(
            description="비밀값 가림. true면 비밀값을 받은 스텝의 스크린샷·영상과 민감 target의 OCR 글자를 남기지 않고 이벤트·로그·실행 기록의 비밀값을 ***로 가린다. 없으면 false(개발 환경 도구라 그대로 남긴다)"
        ),
    ] = None
    screenshots: Literal["off", "on"] | None = None
    video: Literal["failed_only", "off", "on"] | None = None


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
    preset: (
        Literal["curator", "explorer", "full", "graph_author", "qa_runner", "read_only", "runner"]
        | None
    ) = None
    rules: list[PermissionRule] | None = None
    toolsets: (
        dict[
            Literal[
                "cases", "control", "core", "graph_edit", "knowledge", "observe", "run", "screens"
            ],
            PermissionVerdict,
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
    automation: Annotated[Any | None, Field(description="urn:kookabug:automation:0")] = None
    cheats: CheatsPolicy | None = None
    format: Literal["kookabug.workspace/0"]
    id: Annotated[
        str | None,
        Field(
            description="워크스페이스 ID (UUID 소문자). 자격 증명 관리자 비밀값 이름 kookabug:<ID>:<키>의 접두라 팀이 같은 값을 쓴다. 없으면 처음 비밀값을 만들 때(secrets.create) 만들어 넣는다 (M4)",
            pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        ),
    ] = None
    name: Annotated[
        str | None,
        Field(
            description="M8: 프로젝트 이름 (마법사 1단계, kookabug workspace new --name)",
            max_length=100,
            min_length=1,
        ),
    ] = None
    ocr: OcrSettings | None = None
    permissions: Permissions | None = None
    plugin_index: PluginIndex | None = None
    profiles: (
        dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")], Profile] | None
    ) = None
    record: WorkspaceRecordPolicy | None = None
    retention: Retention | None = None
    run: RunConditions | None = None
    settings: Settings | None = None
    sources: Annotated[
        list[Source] | None,
        Field(description="M8: 원본 위치 (복사하지 않는다). 사람 전용 쓰기(project.sources.set)"),
    ] = None

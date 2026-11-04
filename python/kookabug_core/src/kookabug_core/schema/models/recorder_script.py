# 생성물 (packages/schema/recorder-script.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class MonoNs(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="녹화 기준 시각부터 잰 단조 시계 ns (recorder-hook MonoNs와 같다)",
            ge=0,
            le=9007199254740991,
            title="MonoNs",
        ),
    ]


class ObserveLine(BaseModel):
    """
    t_ns부터 관측 스레드가 보는 창 상태. fg·point: 대상 창(target)·우리 앱(app)·대상의 소유 팝업(popup)·다른 창(other), null이면 읽지 못함. delay_ms = 이벤트 뒤 즉시 관측까지 걸리는 시간 (50 ms를 넘으면 그 이벤트는 판정 불가)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    delay_ms: Annotated[int | None, Field(ge=0, le=10000)] = None
    fg: Literal["app", "other", "popup", "target"] | None = None
    focus_password: bool | None = None
    hkl: Any = None
    kind: Literal["observe"]
    point: Literal["app", "other", "popup", "target"] | None = None
    t_ns: MonoNs


class PointItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class Point(RootModel[list[PointItem]]):
    """
    [x, y] 물리 픽셀
    """

    root: Annotated[
        list[PointItem],
        Field(description="[x, y] 물리 픽셀", max_length=2, min_length=2, title="Point"),
    ]


class RawInput(BaseModel):
    """
    번호(event_id·crit_seq)·시각을 매기기 전 원시 입력 = recorder-hook HookEvent에서 event_id·crit_seq·t_ns를 뺀 모양. 종류별 필드 규칙은 HookEvent와 같은 BadInputShape를 쓴다 (두 정의의 수용 여부가 같은지는 계약 검사가 본다). x·y는 물리 화면 좌표
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: Literal["left", "middle", "right", "x1", "x2"] | None = None
    delta: Annotated[int | None, Field(ge=-32768, le=32767)] = None
    extended: bool | None = None
    extra_info: Annotated[Any, Field(description="urn:kookabug:recorder-hook:0#/$defs/ExtraInfo")]
    horizontal: bool | None = None
    injected: bool
    injected_lower_il: bool
    kind: Literal["key_down", "key_up", "mouse_down", "mouse_move", "mouse_up", "wheel"]
    scan: Annotated[int | None, Field(ge=0, le=65535)] = None
    vk: Annotated[int | None, Field(ge=0, le=255)] = None
    x: Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)] = None
    y: Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)] = None


class RectItem(RootModel[int]):
    root: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]


class Rect(RootModel[list[RectItem]]):
    """
    [x, y, w, h] 물리 픽셀
    """

    root: Annotated[
        list[RectItem],
        Field(description="[x, y, w, h] 물리 픽셀", max_length=4, min_length=4, title="Rect"),
    ]


class SceneLine(BaseModel):
    """
    게임이 스스로 장면을 바꾼다 (입력 없이, 예: 로딩 뒤 로비). 입력으로 바뀌는 장면은 가짜 사람이 장면 규칙으로 바꾼다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["scene"]
    scene: Annotated[str, Field(min_length=1)]
    t_ns: MonoNs


class SizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=0, le=9007199254740991)]


class Size(RootModel[list[SizeItem]]):
    """
    [w, h] 물리 픽셀
    """

    root: Annotated[
        list[SizeItem],
        Field(description="[w, h] 물리 픽셀", max_length=2, min_length=2, title="Size"),
    ]


class FaultLine(BaseModel):
    """
    가짜 훅 고장: hook_exit(훅 프로세스 종료·파이프 EOF), health_stop(hook.health가 끊김), hook_detached(OS가 훅을 뗌 — 입력은 계속 오지만 훅 이벤트가 없음), overflow(중요 큐가 차서 다음 중요 이벤트 count개를 버림), batch_gap(다음 묶음 하나를 보내지 않음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    count: Annotated[int | None, Field(ge=1, le=4096)] = None
    fault: Literal["batch_gap", "health_stop", "hook_detached", "hook_exit", "overflow"]
    kind: Literal["fault"]
    t_ns: MonoNs


class FrameLine(BaseModel):
    """
    프레임 도착을 정해 둔다 (없으면 가짜 원천이 장면이 바뀔 때마다 낸다). buffer_size를 주면 그 크기 버퍼(기하와 다르면 검증 안 된 프레임)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    arrival_ns: MonoNs
    buffer_size: Size | None = None
    kind: Literal["frame"]


class Geometry(BaseModel):
    """
    대상 창 기하 (물리 화면 좌표). frame_bounds = DWM 프레임 경계(WGC 버퍼 크기), client_origin = 클라이언트 (0,0)의 화면 점
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_origin: Point
    client_size: Size
    dpi: Annotated[int, Field(ge=1, le=9007199254740991)]
    frame_bounds: Rect


class GeometryGeneration(BaseModel):
    """
    기하 세대 시간표의 한 세대 (프레임 원천 공용 모양). 확정 구간 = [from_ns, confirmed_at_ns] (처음 확인 ~ 마지막 확인). 앞 세대의 confirmed_at_ns ~ 이 세대의 from_ns는 불확실 구간 — 그 구간의 입력·프레임은 어느 세대인지 정하지 않는다. 프레임은 도착 시각이 확정 구간 안이고 버퍼 크기 = frame_bounds 크기일 때만 그 세대로 검증된다. 클라이언트 자르기 = buffer[client_origin - frame_bounds 원점 : + client_size]
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_origin: Point
    client_size: Size
    confirmed_at_ns: MonoNs
    dpi: Annotated[int, Field(ge=1, le=9007199254740991)]
    frame_bounds: Rect
    from_ns: MonoNs
    gen: Annotated[int, Field(ge=1, le=9007199254740991)]


class GeometryLine(BaseModel):
    """
    대상 창 기하가 t_ns에 실제로 바뀌고, 가짜 원천은 notify_ns에 알게 된다 (늦은 알림 경합). notify_ns를 빼면 t_ns
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    geometry: Geometry
    kind: Literal["geometry"]
    notify_ns: MonoNs | None = None
    t_ns: MonoNs


class HeaderLine(BaseModel):
    """
    각본 첫 줄: 대상 창(제목·처음 기하)과 처음 장면
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.recorder-script/0"]
    geometry: Geometry
    kind: Literal["header"]
    scene: Annotated[str, Field(min_length=1)]
    title: str


class ImeLine(BaseModel):
    """
    t_ns부터 대상의 IME 상태와 조회 응답. status가 ok가 아니면 그동안의 표본 조회가 그 상태로 끝난다 (respond_ms 뒤)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["ime"]
    mode: Literal["alphanumeric", "native"]
    respond_ms: Annotated[
        int | None,
        Field(
            description="표본 조회가 끝나는 데 걸리는 시간 (기본 0, timeout이면 50)", ge=0, le=1000
        ),
    ] = None
    status: Literal["failed", "no_ime", "ok", "timeout"] | None = None
    t_ns: MonoNs


class InputLine(BaseModel):
    """
    t_ns에 들어온 원시 입력 하나. 가짜 훅 원천이 훅 프로세스 규칙(event_id·우리 표식 제외·crit_seq·이동 합치기·묶음)을 그대로 적용하고, 가짜 사람(FakeHuman)이 같은 시각에 가짜 게임 장면에 적용한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    input: RawInput
    kind: Literal["input"]
    t_ns: MonoNs


class MarkLine(BaseModel):
    """
    검사가 가리키는 표지 (동작 없음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["mark"]
    label: Annotated[str, Field(min_length=1)]
    t_ns: MonoNs


class RingFrame(BaseModel):
    """
    캡처 링 항목의 메타데이터 (프레임 원천 공용 모양). 버퍼는 WGC 원본(창 프레임 경계 전체, 제목 표시줄·테두리 포함)의 BGR 복사본이고 링은 자르지 않는다 — 그래서 기하는 들지 않고 버퍼 크기와 도착 시각만 든다. 기하는 GeometryGeneration 시간표로 따로 정한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    arrival_ns: MonoNs
    buffer_size: Size
    seq: Annotated[int, Field(ge=1, le=9007199254740991)]


class RecorderScriptLine(
    RootModel[
        HeaderLine
        | InputLine
        | ObserveLine
        | ImeLine
        | GeometryLine
        | SceneLine
        | FrameLine
        | FaultLine
        | MarkLine
    ]
):
    root: Annotated[
        HeaderLine
        | InputLine
        | ObserveLine
        | ImeLine
        | GeometryLine
        | SceneLine
        | FrameLine
        | FaultLine
        | MarkLine,
        Field(
            description="가짜 녹화 각본 JSONL의 한 줄 (검사·E2E 공용, M4 계획 2.15). 첫 줄은 header, 나머지는 시각 차례. 가짜 훅 원천(FakeHookSource)·가짜 프레임 원천(FakeFrameSource)·가짜 사람(FakeHuman)이 같은 각본을 읽는다: 입력·관측 상태·IME·기하 시간표·장면 신호·프레임 도착·훅 고장",
            title="RecorderScriptLine",
        ),
    ]

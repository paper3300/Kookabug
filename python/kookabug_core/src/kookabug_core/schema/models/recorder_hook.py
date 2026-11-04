# 생성물 (packages/schema/recorder-hook.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class BadInputShape1(BaseModel):
    """
    입력 종류와 맞지 않는 필드 조합 (이 모양이면 틀린 입력 — HookEvent·RawInput이 not으로 쓴다). 이동은 x·y만, 버튼은 button·x·y, 휠은 delta·x·y(horizontal 선택), 키는 vk·scan·extended (좌표 없음)
    """

    kind: Literal["mouse_move"]


class BadInputShape8(BaseModel):
    """
    입력 종류와 맞지 않는 필드 조합 (이 모양이면 틀린 입력 — HookEvent·RawInput이 not으로 쓴다). 이동은 x·y만, 버튼은 button·x·y, 휠은 delta·x·y(horizontal 선택), 키는 vk·scan·extended (좌표 없음)
    """

    kind: Literal["mouse_down", "mouse_up"]


class BadInputShape14(BaseModel):
    """
    입력 종류와 맞지 않는 필드 조합 (이 모양이면 틀린 입력 — HookEvent·RawInput이 not으로 쓴다). 이동은 x·y만, 버튼은 button·x·y, 휠은 delta·x·y(horizontal 선택), 키는 vk·scan·extended (좌표 없음)
    """

    kind: Literal["wheel"]


class BadInputShape19(BaseModel):
    """
    입력 종류와 맞지 않는 필드 조합 (이 모양이면 틀린 입력 — HookEvent·RawInput이 not으로 쓴다). 이동은 x·y만, 버튼은 button·x·y, 휠은 delta·x·y(horizontal 선택), 키는 vk·scan·extended (좌표 없음)
    """

    kind: Literal["key_down", "key_up"]


class BadInputShape(RootModel[BadInputShape1 | BadInputShape8 | BadInputShape14 | BadInputShape19]):
    root: Annotated[
        BadInputShape1 | BadInputShape8 | BadInputShape14 | BadInputShape19,
        Field(
            description="입력 종류와 맞지 않는 필드 조합 (이 모양이면 틀린 입력 — HookEvent·RawInput이 not으로 쓴다). 이동은 x·y만, 버튼은 button·x·y, 휠은 delta·x·y(horizontal 선택), 키는 vk·scan·extended (좌표 없음)",
            title="BadInputShape",
        ),
    ]


class BatchNo(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="hook.events 묶음 번호. 1부터 묶음마다 1씩 (전송 연속성). 빈 번호가 있으면 묶음을 잃은 것",
            ge=1,
            le=9007199254740991,
            title="BatchNo",
        ),
    ]


class Count(RootModel[int]):
    root: Annotated[
        int,
        Field(description="녹화 시작부터의 누적 개수", ge=0, le=9007199254740991, title="Count"),
    ]


class CritSeq(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="중요 이벤트(버튼·휠·키) 연속 번호. 우리 표식 제외를 통과한 중요 이벤트에만, 큐에 넣기 전에 1부터 매긴다. 큐가 차서 버린 이벤트도 번호를 쓰므로 받는 쪽의 빈 번호 = 실제 유실",
            ge=1,
            le=9007199254740991,
            title="CritSeq",
        ),
    ]


class EventId(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="훅 콜백이 받은 모든 원시 이벤트(이동·우리 표식 제외 포함)에 1부터 오르는 번호. 관측 연계(cause_event_id)·진단용이고 빈 번호가 정상이다 (빈틈 검사 안 함). 한 녹화 안에서 보내는 차례대로 커진다",
            ge=1,
            le=9007199254740991,
            title="EventId",
        ),
    ]


class ExtraInfo1(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="dwExtraInfo (ULONG_PTR). 값 규칙(2^53-1) 안이면 정수, 넘으면 10진 문자열",
            ge=0,
            le=9007199254740991,
            title="ExtraInfo",
        ),
    ]


class ExtraInfo2(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="dwExtraInfo (ULONG_PTR). 값 규칙(2^53-1) 안이면 정수, 넘으면 10진 문자열",
            pattern="^[0-9]+$",
            title="ExtraInfo",
        ),
    ]


class ExtraInfo(RootModel[ExtraInfo1 | ExtraInfo2]):
    root: Annotated[
        ExtraInfo1 | ExtraInfo2,
        Field(
            description="dwExtraInfo (ULONG_PTR). 값 규칙(2^53-1) 안이면 정수, 넘으면 10진 문자열",
            title="ExtraInfo",
        ),
    ]


class Hkl(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="자판 배치 핸들 HKL을 16진 소문자로 (예: 4120412, ffffffffe0010412)",
            pattern="^[0-9a-f]{1,16}$",
            title="Hkl",
        ),
    ]


class Hooks(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    keyboard: bool
    mouse: bool


class HookHelloParams(BaseModel):
    """
    hook.hello (훅 → daemon): 파이프 인증 직후, 훅 둘을 건 뒤. mono_base_ns는 daemon이 띄울 때 준 녹화 기준 시각을 되돌려 준다(다르면 daemon이 거부). dpi_awareness는 진입점에서 켠 결과
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    created: Annotated[
        str, Field(description="프로세스 생성 시각 (FILETIME 10진 문자열)", pattern="^[0-9]+$")
    ]
    dpi_awareness: Literal["per_monitor", "per_monitor_v2", "system", "unaware"]
    hooks: Hooks
    mono_base_ns: Annotated[
        str,
        Field(
            description="녹화 기준 시각 = 그때의 time.monotonic_ns (10진 문자열). 모든 *_ns 값은 여기서 잰다",
            pattern="^[0-9]+$",
        ),
    ]
    pid: Annotated[int, Field(ge=0, le=9007199254740991)]
    protocol: Literal[1]


class HookStopParams(BaseModel):
    """
    hook.stop (daemon → 훅): 훅을 떼고 남은 묶음을 보낸 뒤 끝낸다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    reason: str | None = None


class Hwnd(RootModel[int]):
    root: Annotated[
        int, Field(description="창 핸들 (정수)", ge=0, le=9007199254740991, title="Hwnd")
    ]


class JsonRpcVersion(RootModel[Literal["2.0"]]):
    root: Annotated[Literal["2.0"], Field(title="JsonRpcVersion")]


class MonoNs(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="녹화 기준 시각(hook.hello의 mono_base_ns)부터 잰 단조 시계 ns. 벽시계로 바꾸지 않는다: 같은 PC의 time.monotonic_ns는 프로세스가 달라도 원점이 같아(QPC) 캡처 프레임 도착 시각과 바로 비교한다. 기준을 빼는 까닭은 값 규칙(정수 ±(2^53-1)) — 부팅 뒤 약 104일이면 ns 값이 넘친다",
            ge=0,
            le=9007199254740991,
            title="MonoNs",
        ),
    ]


class HookEvent(BaseModel):
    """
    저수준 훅 이벤트 하나 (MSLLHOOKSTRUCT·KBDLLHOOKSTRUCT 복사). 훅 콜백은 대상 창에 아무것도 묻지 않는다 — 창·자판·IME는 관측(ImmediateObs·ImeSample)으로 따로 온다. 이동(mouse_move)은 crit_seq가 없고 중요 이벤트는 반드시 있다. 종류별 필드는 BadInputShape(가짜 각본 RawInput과 공용)가 정한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: Literal["left", "middle", "right", "x1", "x2"] | None = None
    crit_seq: CritSeq | None = None
    delta: Annotated[
        int | None,
        Field(
            description="휠 한 번의 양 (WHEEL_DELTA 120 단위, 위·오른쪽이 양수)",
            ge=-32768,
            le=32767,
        ),
    ] = None
    event_id: EventId
    extended: bool | None = None
    extra_info: ExtraInfo
    horizontal: Annotated[bool | None, Field(description="가로 휠 (WM_MOUSEHWHEEL)이면 true")] = (
        None
    )
    injected: Annotated[bool, Field(description="LLMHF_INJECTED·LLKHF_INJECTED")]
    injected_lower_il: Annotated[
        bool, Field(description="LLMHF_LOWER_IL_INJECTED·LLKHF_LOWER_IL_INJECTED")
    ]
    kind: Literal["key_down", "key_up", "mouse_down", "mouse_move", "mouse_up", "wheel"]
    scan: Annotated[int | None, Field(ge=0, le=65535)] = None
    t_ns: MonoNs
    vk: Annotated[int | None, Field(ge=0, le=255)] = None
    x: Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)] = None
    y: Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)] = None


class HookEventsParams(BaseModel):
    """
    hook.events (훅 → daemon): 이벤트 묶음 (최대 256개, event_id 차례). crit_first·crit_last = 이 묶음에 든 중요 이벤트의 첫·마지막 crit_seq (중요 이벤트가 없으면 둘 다 null). dropped_marker(우리 표식이라 훅 프로세스에서 버린 수)·coalesced_moves(이동 큐에서 덮어쓴 이동 수)·overflow(중요 큐가 차서 버린 중요 이벤트 수)는 녹화 시작부터의 누적. daemon 검사: batch_no가 이어지고, crit_seq가 묶음 안·사이에서 빈틈 없이 이어지고, overflow가 0. 어기면 녹화를 input_overflow로 멈춘다. event_id 빈틈·dropped_marker·coalesced_moves 증가는 정상
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    batch_no: BatchNo
    coalesced_moves: Count
    crit_first: CritSeq | None
    crit_last: CritSeq | None
    dropped_marker: Count
    events: Annotated[list[HookEvent], Field(max_length=256)]
    overflow: Count


class HookHealthParams(BaseModel):
    """
    hook.health (훅 → daemon, 500 ms마다): 생존 보고. batch_no = 이 보고 전에 보낸 마지막 hook.events 번호(아직 없으면 0) — 같은 파이프로 차례대로 가므로 받은 마지막 묶음보다 크면 묶음을 잃은 것. last_event_ns = 훅 콜백이 마지막으로 받은 이벤트(우리 표식으로 버린 것 포함) 시각. last_input_tick = GetLastInputInfo().dwTime(ms 틱, 세션 전체·합성 포함) — 이것이 앞섰는데 1초 넘게 훅 이벤트가 없으면 OS가 훅을 뗀 것(hook_lost)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    batch_no: Annotated[int, Field(ge=0, le=9007199254740991)]
    last_event_ns: MonoNs | None
    last_input_tick: Annotated[int, Field(ge=0, le=4294967295)]
    sent_at_ns: MonoNs


class HookHelloMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: Literal["hook.hello"]
    params: HookHelloParams


class HookStopMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: Literal["hook.stop"]
    params: Annotated[
        HookStopParams,
        Field(
            description="hook.stop (daemon → 훅): 훅을 떼고 남은 묶음을 보낸 뒤 끝낸다",
            title="HookStopParams",
        ),
    ]


class ImeSample(BaseModel):
    """
    IME 모드 표본. 관측 스레드만 대상 창에 묻는다: ImmGetDefaultIMEWnd → SendMessageTimeoutW(WM_IME_CONTROL, IMC_GETCONVERSIONMODE, SMTO_ABORTIFHUNG|SMTO_BLOCK, 50 ms). 조회는 query_started_ns에 시작해 sampled_at_ns에 끝났다. status가 ok면 mode는 alphanumeric(영문)·native(한글 등 입력기 고유 모드)이고 conversion(원래 비트)이 있다. ok가 아니면(timeout 시간 초과·failed 호출 실패·no_ime 입력기 창 없음) mode는 unknown. 키 시각 t의 모드 정하기 — '사이 변화'는 IME 전환 키·포그라운드·hkl 변경. (1) 앞 표본 S⁻ = t 앞 300 ms 안 마지막 ok 표본 중 S⁻~t 사이 변화 없음, 뒤 표본 S⁺ = t 뒤 300 ms 안 첫 ok 표본 중 t~S⁺ 사이 변화 없음. (2) 실패 표본의 무효화: 실패 표본의 조회 구간 [query_started_ns, sampled_at_ns]가 (S⁻ 시각, 없으면 t-300 ms) ~ (S⁺ 시각, 없으면 t+300 ms) 구간과 겹치면 그 키는 판정 불가 — 조회 실패를 건너뛰고 한쪽 정상 표본으로 확정하지 않는다. (3) 실패 없이 한쪽만 있으면 그 모드, 둘 다 있고 같으면 그 모드, 다르거나 둘 다 없으면 판정 불가. (4) ok 표본이라도 자기 조회 구간 안에 사이 변화가 있으면 어느 키에도 쓰지 않는다. 판정 불가 키가 든 입력 칸 구간은 needs_review(ime_unknown)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    conversion: Annotated[
        int | None,
        Field(description="IMC_GETCONVERSIONMODE 결과 비트 (IME_CMODE_*)", ge=0, le=4294967295),
    ] = None
    fg: Hwnd | None
    fg_thread: Annotated[int | None, Field(ge=0, le=4294967295)]
    hkl: Hkl | None
    mode: Literal["alphanumeric", "native", "unknown"]
    query_started_ns: MonoNs
    sampled_at_ns: MonoNs
    status: Literal["failed", "no_ime", "ok", "timeout"]
    trigger: Annotated[
        Literal["foreground", "hkl", "ime_key", "key", "periodic"],
        Field(
            description="표본을 뜬 까닭: key(키 뒤, 직전 표본이 100 ms보다 오래됨), ime_key(IME 전환 키를 뗀 직후), foreground·hkl(바뀜), periodic(대상이 앞에 있는 동안 250 ms마다)"
        ),
    ]


class ImmediateObs(BaseModel):
    """
    즉시 관측: 중요 이벤트 하나마다 하나(합치지 않음). 관측 스레드가 메시지 없는 API(GetForegroundWindow·GetWindowThreadProcessId·GetGUIThreadInfo·GetKeyboardLayout·GetWindowLongPtrW)와 창 이벤트로 갱신하는 Z 순서 표로 채운다. 읽지 못한 값은 null. table_changed_ns = 관측 시점 Z 순서·포그라운드 표가 마지막으로 바뀐 시각. daemon은 cause_event_id가 그 이벤트이고 |obs_at_ns - t_ns| ≤ 50 ms이고 table_changed_ns ≤ t_ns(이벤트 뒤 표가 바뀌지 않음)일 때만 쓴다 — 아니면 그 이벤트의 창 판정은 undetermined (확인 배지·needs_review, 추측으로 채우지 않음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    cause_event_id: EventId
    fg: Hwnd | None
    fg_owner: Annotated[
        Hwnd | None,
        Field(description="포그라운드 창의 소유 창 (GW_OWNER) — 대상 창의 소유 팝업인지 판정"),
    ] = None
    fg_thread: Annotated[int | None, Field(ge=0, le=4294967295)]
    focus: Annotated[
        Hwnd | None, Field(description="포그라운드 스레드의 포커스 창 (GetGUIThreadInfo)")
    ]
    focus_password: Annotated[
        bool | None,
        Field(
            description="포커스 창이 ES_PASSWORD 스타일 Edit (Win32 비밀번호 칸, 비밀 근거 1). 읽지 못했으면 null"
        ),
    ] = None
    hkl: Hkl | None
    obs_at_ns: MonoNs
    point_owner: Annotated[Hwnd | None, Field(description="point_window의 소유 창 (GW_OWNER)")] = (
        None
    )
    point_window: Annotated[
        Hwnd | None,
        Field(
            description="마우스 이벤트 자리의 최상위 창 (WindowFromPoint가 아니라 Z 순서 표에서). 키 이벤트면 없음"
        ),
    ] = None
    table_changed_ns: MonoNs
    zorder_rev: Annotated[
        int,
        Field(
            description="Z 순서·포그라운드 표 판 번호 (바뀔 때마다 1씩)", ge=0, le=9007199254740991
        ),
    ]


class HookEventsMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: Literal["hook.events"]
    params: HookEventsParams


class HookHealthMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: Literal["hook.health"]
    params: HookHealthParams


class HookImeParams(BaseModel):
    """
    hook.ime (훅 → daemon): IME 모드 표본 묶음 (표본 시각 차례)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    batch: list[ImeSample]


class HookImeMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: Literal["hook.ime"]
    params: Annotated[
        HookImeParams,
        Field(
            description="hook.ime (훅 → daemon): IME 모드 표본 묶음 (표본 시각 차례)",
            title="HookImeParams",
        ),
    ]


class HookObsParams(BaseModel):
    """
    hook.obs (훅 → daemon): 즉시 관측 묶음
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    batch: list[ImmediateObs]


class HookObsMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: Literal["hook.obs"]
    params: Annotated[
        HookObsParams,
        Field(description="hook.obs (훅 → daemon): 즉시 관측 묶음", title="HookObsParams"),
    ]


class RecorderHookMessage(
    RootModel[
        HookHelloMessage
        | HookEventsMessage
        | HookObsMessage
        | HookImeMessage
        | HookHealthMessage
        | HookStopMessage
    ]
):
    root: Annotated[
        HookHelloMessage
        | HookEventsMessage
        | HookObsMessage
        | HookImeMessage
        | HookHealthMessage
        | HookStopMessage,
        Field(
            description="녹화 훅 프로세스 ↔ daemon 메시지 하나 (named pipe + 길이 접두 JSON + 상호 HMAC, 응답 없는 JSON-RPC 2.0 알림). 훅 → daemon: hook.hello·hook.events·hook.obs·hook.ime·hook.health, daemon → 훅: hook.stop (M4 계획 2.1)",
            title="RecorderHookMessage",
        ),
    ]

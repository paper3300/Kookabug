"""에이전트 정지 화면 보호 판정 `frame_guard` (M7 계획 3.5a, 10장 R1·R3, 12장 보완) — 엄격.

에이전트 연결이 만든(또는 에이전트에게 나갈) 정지 화면의 **모든 출구** 앞에서 이 판정 하나를 쓴다.
`Clear`가 아니면 그 출구는 이미지·글자를 내지 않는다. OCR 음성(글자가 안 읽힘)에 기대지 않는다.

판정 (앞에서부터, 하나라도 걸리면 그 결과):
1. **민감 target**: 워크스페이스 `sensitive: true` target이 그 프레임에 보이면 `protected
   (sensitive_visible)`, 확인 못 하면 `unchecked(sensitive_unchecked)` — 상자만이 아니라 이미지 전체
2. **비밀값을 입력한 창**: 에이전트가 `kb_input_type{secret}`을 보낸 창(바인딩 = HWND·PID·프로세스
   생성 시각)에는 보호 기록이 있다. 그 창의 프레임은 기록의 칸마다 녹화기의 칸 없음 확정
   (`FieldPresenceTracker.absent_in` — 네 둘레 조각·칸 안 픽셀·구조 30% 장면 전환)이어야 `clear`.
   칸 상자를 모르거나(근거 4가지 중 하나라도 없음, R3) 기준 프레임이 없으면(daemon 재시작) 창이 살아
   있는 동안 `protected(secret_field_unknown)`. 기준 DPI와 다르면 `protected(secret_field)`
3. 판정 중 예외는 `unchecked(guard_error)`

수명 (R1): 기록은 세션·연결 끝으로 풀리지 않는다. 창 바인딩이 죽으면 그 창에서 만든 원본 프레임을
**먼저** 버리고(`frame_expired`) 기록을 지운다. 프레임은 캡처 시점 판정을 들고 있고, 출구는 그것과
지금 판정 중 나쁜 쪽을 쓴다(기록이 지워져도 옛 프레임은 `clear`로 올라가지 않는다).

`.kookabug/agent-protect.json` (픽셀·값 없음): 창 바인딩·비밀값 키 이름·칸 상자. 기록을 디스크에
쓴 **뒤에만** 비밀값 입력을 보낸다(쓰기 실패면 `protect_record_failed`). 비밀값 키 목록
(`secret_keys`)은 창 수명과 따로 쌓인다(저장 글자 검사, 3.5b). 읽을 때 형식 전부(필드·타입·배열·
바인딩 값 — 생성 시각은 직렬화 규칙 그대로의 양의 10진 정수)를 검사하고, 문법·구조 어느 쪽이든
틀리면 깨진 파일이다. 검사를 통과하기 전에는 어떤 기록도 지우거나 파일을 다시 쓰지 않는다. 깨졌으면
원본은 그대로 두고 `.corrupt.<시각>` 사본만 만들고, 그 daemon 수명 동안 **에이전트의 모든 창
프레임**을 `protected(protect_state_unknown)`로(창 열거·시각 비교에 기대지 않음), 저장 계열은
`secret_unchecked`로 막는다(`save_blocked`). 깨진 동안은 새 기록도 쓰지 않는다(입력 거부). 풀리는
것은 사람이 원본을 고치거나 지우고 daemon을 다시 시작했을 때뿐이다(사람 연결에 알림·로그 한 줄).

에이전트 제어 실행의 창은 daemon이 한 번 정해(`control.*`) 그 바인딩으로 보호 기록을 쓰고 실행
사양으로 넘긴다 — runner는 다시 찾지 않고 그 창에만 붙는다(`runner.spec.BoundWindow`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from kookabug_core.documents import DocumentError, write_atomic
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.screen_source import Grab, ScreenSource, WindowBinding

if TYPE_CHECKING:
    from kookabug_daemon.frames import EditorFrame, FrameCache
    from kookabug_daemon.targets import TargetStore

__all__ = [
    "CLEAR",
    "CLICK_FRESH_S",
    "FILE",
    "FORMAT",
    "HINTS",
    "FrameGuard",
    "Guard",
    "ProtectFileError",
    "parse_protect_file",
]

log = logging.getLogger(__name__)

FILE: Final = ".kookabug/agent-protect.json"
FORMAT: Final = "kookabug.agent-protect/0"
CLICK_FRESH_S: Final = 10.0
"""칸 상자 근거: 클릭 뒤 이 시간 안에 입력해야 한다 (R3 조건 2)."""

type GuardState = Literal["clear", "protected", "unchecked"]
type Box = tuple[int, int, int, int]

HINTS: Final[Mapping[str, str]] = {
    "sensitive_visible": "민감 대상이 보이는 화면이라 이미지를 보내지 않아요",
    "sensitive_unchecked": "민감 대상을 확인하지 못해 이미지를 보내지 않아요",
    "secret_field": "비밀값을 입력한 칸이 아직 보여요 — 다른 화면으로 넘어가면 다시 보여요",
    "secret_field_unknown": (
        "비밀값을 넣은 칸 위치를 몰라 이 창 이미지를 보내지 않아요 — 다음부터는 칸을 "
        "kb_input_click으로 누른 뒤 입력하세요"
    ),
    "protect_state_unknown": (
        "보호 기록 파일이 손상돼 사람 확인 전까지 이미지를 보내지 않아요 "
        "(.kookabug/agent-protect.json)"
    ),
    "window_unknown": "어느 창인지 확인하지 못해 이미지를 보내지 않아요",
    "guard_error": "보호 판정에 실패해 이미지를 보내지 않아요",
}
_SENSITIVE: Final = frozenset({"sensitive_visible", "sensitive_unchecked"})
_RANK: Final[Mapping[str, int]] = {"clear": 0, "unchecked": 1, "protected": 2}


@dataclass(frozen=True, slots=True)
class Guard:
    state: GuardState
    reason: str | None = None
    path: str | None = None
    """민감 target 사유면 그 target 파일 (워크스페이스 기준 — 값이 아니다)."""

    @property
    def clear(self) -> bool:
        return self.state == "clear"

    def worse(self, other: Guard | None) -> Guard:
        """둘 중 나쁜 쪽 (`clear`로 올라가지 않는다)."""
        if other is None or _RANK[self.state] >= _RANK[other.state]:
            return self
        return other

    def to_json(self) -> dict[str, str]:
        reason = self.reason or "guard_error"
        return {"reason": reason, "hint": HINTS.get(reason, HINTS["guard_error"])}

    def refusal(self) -> RequestFailed:
        """이 판정으로 출구를 막을 때의 오류. 민감 target 사유는 M5의 `sensitive_region` 그대로."""
        info = self.to_json()
        if info["reason"] in _SENSITIVE and self.path is not None:
            # M5 `screen.read_text`와 같은 오류·문구 (그 target 경로 — 값이 아니다)
            text = (
                f"민감 target을 확인하지 못함 ('{self.path}'을(를) 읽거나 판정할 수 없다) — "
                "읽지 않는다"
                if info["reason"] == "sensitive_unchecked"
                else f"민감 target '{self.path}'이(가) 보이는 화면이라 읽지 않는다"
            )
            return RequestFailed("sensitive_region", text, path=self.path, reason=info["reason"])
        code = "sensitive_region" if info["reason"] in _SENSITIVE else "frame_protected"
        return RequestFailed(code, info["hint"], reason=info["reason"], message=info["hint"])


CLEAR: Final = Guard("clear")

_CREATED: Final = re.compile(r"[1-9][0-9]{0,19}")
"""파일의 프로세스 생성 시각: 양의 10진 정수 그대로 (부호·공백·앞자리 0·비숫자 없음)."""
_MAX_CREATED: Final = (1 << 64) - 1
_MAX_PID: Final = (1 << 32) - 1
_MAX_HWND: Final = (1 << 53) - 1


class ProtectFileError(ValueError):
    """보호 기록 파일이 문법·구조 어느 쪽이든 틀렸다."""


def parse_protect_file(raw: bytes) -> tuple[set[str], dict[WindowBinding, _Record]]:
    """`agent-protect.json`을 엄격하게 읽는다 (비밀값 키 목록, 창 기록). 형식이 하나라도 틀리면
    `ProtectFileError` (R1). daemon 시작과 사람 CLI(`screen protect`)가 같이 쓴다."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtectFileError(f"JSON이 아니다: {exc}") from exc

    def fail(where: str) -> ProtectFileError:
        return ProtectFileError(f"보호 기록 형식이 틀렸다: {where}")

    def is_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def strings(value: object, where: str) -> set[str]:
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise fail(where)
        return set(cast(list[str], value))

    if not isinstance(data, dict) or set(data) != {"format", "windows", "secret_keys"}:
        raise fail("/")
    body = cast(dict[str, Any], data)
    if body["format"] != FORMAT:
        raise fail("/format")
    keys = strings(body["secret_keys"], "/secret_keys")
    windows = body["windows"]
    if not isinstance(windows, list):
        raise fail("/windows")
    records: dict[WindowBinding, _Record] = {}
    for i, item in enumerate(cast(list[Any], windows)):
        where = f"/windows/{i}"
        if not isinstance(item, dict) or set(item) != {"window", "keys", "fields"}:
            raise fail(where)
        entry = cast(dict[str, Any], item)
        window = entry["window"]
        if not isinstance(window, dict) or set(window) != {"hwnd", "pid", "created"}:
            raise fail(f"{where}/window")
        bound = cast(dict[str, Any], window)
        if not (is_int(bound["hwnd"]) and 0 < bound["hwnd"] <= _MAX_HWND):
            raise fail(f"{where}/window/hwnd")
        if not (is_int(bound["pid"]) and 0 < bound["pid"] <= _MAX_PID):
            raise fail(f"{where}/window/pid")
        created = bound["created"]
        if not (
            isinstance(created, str)
            and _CREATED.fullmatch(created) is not None
            and int(created) <= _MAX_CREATED
        ):
            # 직렬화 규칙(WindowBinding.created = 양의 10진 정수) 밖이면 손상 — 다른 프로세스의
            # 창으로 보고 지우지 않는다
            raise fail(f"{where}/window/created")
        record_keys = strings(entry["keys"], f"{where}/keys")
        if not record_keys:
            raise fail(f"{where}/keys")
        fields = entry["fields"]
        if not isinstance(fields, list) or not fields:
            raise fail(f"{where}/fields")
        for j, box in enumerate(cast(list[Any], fields)):
            if box is None:
                continue
            values = cast(list[Any], box) if isinstance(box, list) else []
            if len(values) != 4 or not all(is_int(v) for v in values):
                raise fail(f"{where}/fields/{j}")
            if values[0] < 0 or values[1] < 0 or values[2] <= 0 or values[3] <= 0:
                raise fail(f"{where}/fields/{j}")
        binding = WindowBinding(int(bound["hwnd"]), int(bound["pid"]), str(bound["created"]))
        if binding in records:
            raise fail(f"{where}/window")
        # 기준 프레임은 메모리에만 있으므로 다시 읽은 칸은 모두 위치 모름(창 수명 동안 보호)
        records[binding] = _Record(
            binding, record_keys, [_Field(None, None, None) for _ in cast(list[Any], fields)]
        )
    return keys, records


@dataclass
class _Field:
    box: Box | None
    dpi: int | None
    span: int | None
    """`FieldPresenceTracker` 등록 번호 (기준 프레임이 메모리에 있을 때만)."""


@dataclass
class _Record:
    binding: WindowBinding
    keys: set[str] = field(default_factory=set[str])
    fields: list[_Field] = field(default_factory=list[_Field])


@dataclass
class _LastInput:
    connection: int
    kind: str
    at: float
    point: tuple[int, int] | None = None
    before: Grab | None = None
    after: Grab | None = None


class FrameGuard:
    """보호 기록·판정. 어느 스레드에서 불러도 된다."""

    def __init__(
        self,
        root: Path,
        frames: FrameCache,
        targets: TargetStore,
        source: ScreenSource,
        *,
        clock: Any = time.monotonic,
    ) -> None:
        self.root = root
        self.path = root / FILE
        self.frames = frames
        self.targets = targets
        self.source = source
        self.clock = clock
        self._lock = threading.RLock()
        self._records: dict[WindowBinding, _Record] = {}
        self._last: dict[WindowBinding, _LastInput] = {}
        self.secret_keys: set[str] = set()
        self.save_blocked = False
        """기록 파일이 깨져 비밀값 키를 모른다: 저장 계열은 `secret_unchecked` (R1)."""
        self.corrupt = False
        self.on_corrupt: Callable[[], None] | None = None
        """손상 때문에 처음 막았을 때 한 번 부른다 (daemon이 사람 연결에 알린다)."""
        self._corrupt_reported = False
        self._tracker: Any = None
        self._spans = 0

    # ------------------------------------------------------------ 기록 파일

    def load(self) -> None:
        """daemon 시작: 기록 파일을 읽는다. 죽은 창의 기록은 지운다. 기준 프레임은 없으므로 살아
        있는 창은 `secret_field_unknown`이다."""
        with self._lock:
            try:
                raw = self.path.read_bytes()
            except FileNotFoundError:
                return
            except OSError:
                self._fail_closed(None)
                return
            try:
                keys, records = parse_protect_file(raw)
            except ValueError, UnicodeDecodeError:
                # 문법 오류와 구조 오류(필드 누락·타입·배열·바인딩 값)를 똑같이 다룬다 (R1)
                self._fail_closed(raw)
                return
            self.secret_keys = keys
            self._records = {b: r for b, r in records.items() if self.source.alive(b)}
            if len(self._records) != len(records):
                with contextlib.suppress(RequestFailed):
                    self._write()

    def _fail_closed(self, raw: bytes | None) -> None:
        """깨진 기록 파일 (R1·12장·3라운드): 원본은 그대로, 사본만. 저장 계열은 막고, 깨진 동안 새
        기록을 쓰지 않는다. 이 daemon 수명 동안 에이전트의 **모든** 창 프레임을
        `protect_state_unknown`으로 막는다 (`check` — 창 열거·시각 비교 없음)."""
        self.corrupt = True
        self.save_blocked = True
        log.warning(
            "에이전트 보호 기록 파일 %s이(가) 손상됐다 — 사람이 고치거나 지우고 daemon을 다시 "
            "시작할 때까지 에이전트에게 창 이미지를 보내지 않는다",
            FILE,
        )
        if raw is not None:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            with contextlib.suppress(OSError):
                self.path.with_name(f"{self.path.name}.corrupt.{stamp}").write_bytes(raw)

    def _report_corrupt(self) -> None:
        """손상 때문에 처음 막을 때 사람 연결에 한 번 알린다 (값 없음)."""
        with self._lock:
            if self._corrupt_reported:
                return
            self._corrupt_reported = True
            callback = self.on_corrupt
        if callback is not None:
            with contextlib.suppress(Exception):
                callback()

    def _body(self, records: Iterable[_Record], keys: Iterable[str]) -> bytes:
        windows = [
            {
                "window": r.binding.to_json(),
                "keys": sorted(r.keys),
                "fields": [None if f.box is None else list(f.box) for f in r.fields],
            }
            for r in records
        ]
        body = {"format": FORMAT, "windows": windows, "secret_keys": sorted(keys)}
        return json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8")

    def _write(
        self, records: Iterable[_Record] | None = None, keys: Iterable[str] | None = None
    ) -> None:
        """기록 파일을 원자 교체 + fsync. 실패하면 `protect_record_failed`."""
        if self.corrupt:
            raise RequestFailed(
                "protect_record_failed",
                "보호 기록 파일이 깨져 새 기록을 쓰지 않는다 "
                "(사람이 파일을 고치거나 지운 뒤 daemon을 다시 시작)",
            )
        data = self._body(
            self._records.values() if records is None else records,
            self.secret_keys if keys is None else keys,
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, data)
        except (OSError, DocumentError) as exc:
            raise RequestFailed(
                "protect_record_failed", f"보호 기록을 쓰지 못해 비밀값을 입력하지 않았다: {exc}"
            ) from exc

    # ------------------------------------------------------------ 입력 추적 (R3)

    def before_click(self, bindings: Iterable[WindowBinding]) -> dict[WindowBinding, Grab | None]:
        """클릭 직전 캡처 (칸 상자 근거 — 클릭이 장면을 바꿨는지 본다)."""
        return {b: self._grab(b) for b in bindings}

    def note_input(
        self,
        connection: int,
        bindings: Iterable[WindowBinding],
        kind: str,
        *,
        point: tuple[int, int] | None = None,
        before: Mapping[WindowBinding, Grab | None] | None = None,
    ) -> None:
        """그 창들로 에이전트 입력이 갔다. 점 클릭이면 클릭 직후 캡처를 근거로 둔다."""
        now = self.clock()
        for binding in bindings:
            entry = _LastInput(connection, kind, now)
            if kind == "click" and point is not None:
                entry.point = point
                entry.before = None if before is None else before.get(binding)
                entry.after = self._grab(binding)
            with self._lock:
                self._last[binding] = entry

    def _grab(self, binding: WindowBinding) -> Grab | None:
        try:
            grab = self.source.capture(binding.hwnd)
        except Exception:
            return None
        return grab if grab.binding == binding else None

    def record_secret(self, connection: int, bindings: Iterable[WindowBinding], key: str) -> None:
        """`kb_input_type{secret}` 직전: 그 창들의 보호 기록을 디스크에 쓴다 (실패면 예외 — 입력을
        보내지 않는다). 칸 상자는 근거 4가지가 모두 있을 때만 (R3)."""
        bindings = list(bindings)
        for binding in bindings:
            if _CREATED.fullmatch(binding.created) is None:
                # 프로세스 생성 시각을 읽지 못한 창: 기록 형식(양의 10진 정수)으로 남길 수 없다
                raise RequestFailed(
                    "protect_record_failed",
                    "창의 프로세스 생성 시각을 읽지 못해 보호 기록을 쓸 수 없어 비밀값을 입력하지 "
                    "않았다",
                )
        with self._lock:
            self.sweep()
            planned: dict[WindowBinding, tuple[_Record, _Field, Any]] = {}
            for binding in bindings:
                found, baseline = self._field_for(connection, binding)
                old = self._records.get(binding)
                record = _Record(
                    binding,
                    set(old.keys) if old else set(),
                    list(old.fields) if old else [],
                )
                record.keys.add(key)
                record.fields.append(found)
                planned[binding] = (record, found, baseline)
            records = {**self._records, **{b: r for b, (r, _, _) in planned.items()}}
            self._write(records.values(), self.secret_keys | {key})
            # 디스크에 쓴 뒤에만 메모리에 둔다 (쓰기 실패면 아무것도 바뀌지 않고 입력도 안 나감)
            for binding, (record, found, baseline) in planned.items():
                if found.box is not None and baseline is not None:
                    found.span = self._register(found.box, baseline)
                self._records[binding] = record
            self.secret_keys.add(key)

    def _field_for(self, connection: int, binding: WindowBinding) -> tuple[_Field, Any]:
        """칸 상자 근거 (R3): 바로 앞 입력이 같은 연결의 점 클릭, 10초 안, 클릭 전·후·지금 프레임이
        같은 크기·DPI이고 장면 변화 없음, 경계 추정이 상자를 냄. 아니면 상자 없음."""
        unknown = (_Field(None, None, None), None)
        last = self._last.get(binding)
        now = self.clock()
        if (
            last is None
            or last.kind != "click"
            or last.connection != connection
            or last.point is None
            or last.before is None
            or last.after is None
            or now - last.at > CLICK_FRESH_S
        ):
            return unknown
        baseline = self._grab(binding)
        if baseline is None:
            return unknown
        try:
            from kookabug_platform.recorder.crop import estimate_bounds
            from kookabug_platform.recorder.presence import scene_changed

            frames = (last.before, last.after, baseline)
            shape = last.after.pixels.shape
            if any(g.pixels.shape != shape or g.dpi != baseline.dpi for g in frames):
                return unknown
            box = estimate_bounds(last.after.pixels, last.point)
            if box is None:
                return unknown
            if scene_changed(last.before.pixels, last.after.pixels, box) or scene_changed(
                last.after.pixels, baseline.pixels, box
            ):
                return unknown
        except Exception:
            return unknown
        field_box: Box = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
        return _Field(field_box, baseline.dpi, None), baseline.pixels

    def _register(self, box: Box, baseline: Any) -> int | None:
        try:
            if self._tracker is None:
                from kookabug_platform.recorder.presence import FieldPresenceTracker

                self._tracker = FieldPresenceTracker()
            self._spans += 1
            self._tracker.register(self._spans, box, baseline, 0)
        except Exception:
            return None
        return self._spans

    # ------------------------------------------------------------ 수명 (R1)

    def sweep(self) -> None:
        """기록이 있는 창 중 죽은 바인딩: 그 창의 정지 화면을 먼저 버리고 기록을 지운다."""
        with self._lock:
            dead = [b for b in self._records if not self.source.alive(b)]
            if not dead:
                return
            for binding in dead:
                self.frames.discard_binding(binding)
                self._last.pop(binding, None)
            remaining = [r for b, r in self._records.items() if b not in dead]
            with contextlib.suppress(RequestFailed):
                if not self.corrupt:
                    self._write(remaining)
            for binding in dead:
                del self._records[binding]

    # ------------------------------------------------------------ 판정

    def check(self, frame: EditorFrame) -> Guard:
        """그 정지 화면의 지금 판정."""
        try:
            hit = self.targets.sensitive_visible(frame)
            if hit is not None:
                return (
                    Guard("unchecked", "sensitive_unchecked", hit.path)
                    if hit.failed
                    else Guard("protected", "sensitive_visible", hit.path)
                )
            if not frame.window:
                return CLEAR
            if self.corrupt:
                # 기록 파일 손상 (R1·12장, 3라운드): 사람이 고치고 다시 시작할 때까지 에이전트의
                # 모든 창 프레임을 보호 — 창 열거·시각 비교로 "새 창"을 풀어 주지 않는다
                self._report_corrupt()
                return Guard("protected", "protect_state_unknown")
            with self._lock:
                self.sweep()
                if not self._records:
                    return CLEAR
                if frame.binding is None:
                    return Guard("unchecked", "window_unknown")
                record = self._records.get(frame.binding)
            if record is None:
                return CLEAR
            return self._check_record(record, frame)
        except Exception:
            return Guard("unchecked", "guard_error")

    def _check_record(self, record: _Record, frame: EditorFrame) -> Guard:
        for f in record.fields:
            if f.box is None or f.span is None or f.dpi is None:
                return Guard("protected", "secret_field_unknown")
        for f in record.fields:
            assert f.box is not None
            # DPI는 tracker가 보지 않는다: 픽셀 크기가 같아도 배율이 다르면 비교하지 않는다 (12장)
            if frame.dpi != f.dpi or not self._tracker.absent_in(f.span, f.box, frame.pixels):
                return Guard("protected", "secret_field")
        return CLEAR

    def effective(self, frame: EditorFrame) -> Guard:
        """출구에서 쓰는 판정: 캡처 시점 판정과 지금 판정 중 하나라도 `clear`가 아니면 막는다
        (`clear`로 올라가지 않음). 사유는 지금 판정이 막으면 지금 것(안내가 지금 화면에 맞게)."""
        now = self.check(frame)
        if not now.clear or frame.guard is None:
            return now
        return frame.guard

    def require_clear(self, frame: EditorFrame) -> None:
        guard = self.effective(frame)
        if not guard.clear:
            raise guard.refusal()

    def protection_set(self, frame: EditorFrame) -> Any:
        """그 창의 알려진 칸 상자를 `ProtectionSet`으로 (crop 경계 이중 방어 — 끝난 보호, 자를
        프레임에서 칸이 없다는 근거가 있을 때만 겹침 허용). 기록이 없으면 None."""
        from kookabug_core.recorder.protect import ProtectionSet

        with self._lock:
            record = None if frame.binding is None else self._records.get(frame.binding)
            tracker = self._tracker
        if record is None:
            return None
        fields = [f for f in record.fields if f.box is not None and f.span is not None]
        protection = ProtectionSet(
            None if tracker is None else (lambda span, box, img: tracker.absent_in(span, box, img))
        )
        for f in fields:
            assert f.box is not None and f.span is not None
            protection.add(f.span, f.box, 0)
            protection.end(f.span, 0)
        return protection

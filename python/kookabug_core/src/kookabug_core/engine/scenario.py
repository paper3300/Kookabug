"""장면 전이 가짜 플랫폼 `FakeScenario` (구현 계획 M1 2.7, 계획 검수 8).

사양 `platform.scenario`(JSON 파일, 형식 `kookabug.fake-scenario/0`)로 게임 없이 **같은 예제
그래프**(`app.launch` 포함)를 돌린다. 형식은 예제 게임 `sample_game/scenario.py` 맨 위 설명이고,
그 `Simulator`가 기준 해석이다 — 여기는 그것을 창·프로세스와 함께 옮긴 것이다.

- **띄우기**: `launch(경로, 인수)`마다 가짜 게임 하나(새 PID 4001부터, 창 하나). 갈래는 `launch`
  규칙(인수 하나가 `args_contains`와 같은 첫 규칙, 조건 없는 규칙이 기본)으로 고른다. 경로는 보지
  않는다
- **캡처**: 그 창 게임의 지금 장면 PNG. 캡처 한 번이 `after_frames`의 한 프레임이다
- **입력**: 왼쪽 클릭 = 그 점의 클릭 전이(없으면 입력 칸 선택), 키 = 키 전이(없으면 칸 조작:
  다음 칸·끝 글자 지움·전부 고름), 글자 = 지금 칸에 붙임(골라 뒀으면 갈아 끼움). 누르고 있기는
  누를 때 키 하나로 본다. 드래그·휠·떼기는 장면을 바꾸지 않는다
- **창**: 제목·클래스·클라이언트 크기·DPI는 표의 `window`, 프로세스 이름은 `process.name`.
  닫으면(`close`) 그 창은 `window_gone`. 크기는 바꿀 수 없다(장면 PNG가 한 크기) — 같은 크기로
  맞추기만 참
- **이미 떠 있는 게임**: 표의 `running: true`면 시작할 때 기본 갈래 게임 하나가 떠 있다(띄우지
  않고 창에 붙는 그래프용)
- **상태 파일** (검사 전용, M7 3.12): `state_file`을 주면 첫 게임의 지금 상태 전부(갈래·장면·보인
  프레임·지연 전이·칸 값·포커스·선택·창 PID·열림)를 `kookabug.fake-scenario-state/0`으로 시작 때
  읽고 바뀔 때마다 쓴다 — 제어 실행(runner 프로세스)마다 새로 만들어도 게임이 이어지고, daemon 가짜
  캡처가 같은 상태를 본다. 없거나 깨졌으면 표의 `start`

SDK `fake_context(scenario=)`에도 그대로 넣는다(`kookabug_sdk.testing.Scenario`: `capture`·
`on_input`·`launch`). 그때는 가장 나중에 띄운 게임이 화면·입력을 받는다.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core.canonical import loads_strict
from kookabug_core.engine.errors import EngineError
from kookabug_core.inputs.actor import ClientPoint
from kookabug_core.inputs.service import InputService, InputSink
from kookabug_core.record.artifacts import FindEvidence, StagedFrame, find_with_report
from kookabug_core.record.video import VideoFrame
from kookabug_sdk.context import InputApi, Where
from kookabug_sdk.errors import ObservationTimeout
from kookabug_sdk.testing import FakeWindow, FakeWindows, InputCall
from kookabug_sdk.types import (
    Image,
    Match,
    OcrResult,
    Point,
    ProcessRef,
    Rect,
    Secret,
    Target,
    WindowInfo,
    WindowRef,
)

__all__ = [
    "FORMAT",
    "STATE_FORMAT",
    "FakeScenario",
    "ScenarioError",
    "ScenarioPlatform",
    "ScenarioState",
]

FORMAT: Final = "kookabug.fake-scenario/0"
STATE_FORMAT: Final = "kookabug.fake-scenario-state/0"
"""검사 전용 상태 파일 형식 (M7 3.12)."""
FIRST_PID: Final = 4001
FIRST_HWND: Final = 0x10010
_WINDOW_GONE: Final = "window_gone"
# 실제 플랫폼(`kookabug_platform.sendinput`·`platform`)과 같은 문구
NO_INPUT_WINDOW: Final = "입력 대상 창이 정해지지 않았다 (앱 실행·창 붙기로 대상 창을 먼저 정한다)"
NO_CAPTURE_WINDOW: Final = (
    "캡처할 대상 창이 정해지지 않았다 (앱 실행·창 붙기로 대상 창을 먼저 정한다)"
)

type _Edge = Mapping[str, Any]


class ScenarioError(ValueError):
    """장면 전이 표의 형식이 틀렸다."""


# ---------------------------------------------------------------- 표 검사


def _fail(where: str, message: str) -> ScenarioError:
    return ScenarioError(f"장면 표 {where}: {message}")


def _obj(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(where, "객체여야 한다")
    return cast(dict[str, Any], value)


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _fail(where, "목록이어야 한다")
    return cast(list[Any], value)


def _str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(where, "빈 문자열이 아닌 문자열이어야 한다")
    return value


def _int(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail(where, f"{minimum} 이상의 정수여야 한다")
    return value


def _rect(value: Any, where: str) -> tuple[int, int, int, int]:
    items = _list(value, where)
    if len(items) != 4:
        raise _fail(where, "[x, y, 너비, 높이]여야 한다")
    x, y, w, h = (_int(v, where) for v in items)
    if w == 0 or h == 0:
        raise _fail(where, "너비·높이는 양수다")
    return x, y, w, h


def _check(data: Any, folder: Path) -> dict[str, Any]:
    spec = _obj(data, "/")
    if spec.get("format") != FORMAT:
        raise _fail("/format", f"{FORMAT!r}이어야 한다 (지금 {spec.get('format')!r})")
    allowed = {
        "format",
        "forms",
        "launch",
        "process",
        "running",
        "scenes",
        "start",
        "transitions",
        "variants",
        "window",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise _fail("/", f"모르는 키 {unknown}")
    scenes = _obj(spec.get("scenes"), "/scenes")
    if not scenes:
        raise _fail("/scenes", "장면이 하나도 없다")
    for name, file in scenes.items():
        path = folder / _str(file, f"/scenes/{name}")
        if not path.is_file():
            raise _fail(f"/scenes/{name}", f"PNG {path}이(가) 없다")
    start = _str(spec.get("start"), "/start")
    if start not in scenes:
        raise _fail("/start", f"없는 장면 {start!r}")
    variants = [_str(v, "/variants") for v in _list(spec.get("variants"), "/variants")]
    if not variants:
        raise _fail("/variants", "갈래가 하나도 없다")
    window = _obj(spec.get("window"), "/window")
    _str(window.get("title"), "/window/title")
    size = _list(window.get("client_size"), "/window/client_size")
    if len(size) != 2:
        raise _fail("/window/client_size", "[너비, 높이]여야 한다")
    for v in size:
        _int(v, "/window/client_size", minimum=1)
    _int(window.get("dpi", 96), "/window/dpi", minimum=1)
    _str(_obj(spec.get("process"), "/process").get("name"), "/process/name")
    if not isinstance(spec.get("running", False), bool):
        raise _fail("/running", "true·false여야 한다")
    rules = _list(spec.get("launch"), "/launch")
    if not any("args_contains" not in _obj(r, "/launch") for r in rules):
        raise _fail("/launch", "조건 없는 기본 규칙이 없다")
    for i, rule in enumerate(rules):
        if rule.get("variant") not in variants:
            raise _fail(f"/launch/{i}/variant", f"없는 갈래 {rule.get('variant')!r}")
    forms = _obj(spec.get("forms", {}), "/forms")
    for name, form in forms.items():
        where = f"/forms/{name}"
        form = _obj(form, where)
        for scene in _list(form.get("scenes"), f"{where}/scenes"):
            if scene not in scenes:
                raise _fail(f"{where}/scenes", f"없는 장면 {scene!r}")
        if form.get("input_scene") not in scenes:
            raise _fail(f"{where}/input_scene", "없는 장면")
        fields = _list(form.get("fields"), f"{where}/fields")
        names = [_str(_obj(f, f"{where}/fields").get("name"), f"{where}/fields") for f in fields]
        for f in fields:
            _rect(f.get("rect"), f"{where}/fields/{f['name']}/rect")
        if form.get("focus") not in names:
            raise _fail(f"{where}/focus", "없는 칸")
        _int(form.get("max_length"), f"{where}/max_length", minimum=1)
        _str(form.get("next_key"), f"{where}/next_key")
        _str(form.get("erase_key"), f"{where}/erase_key")
        if "select_key" in form:
            _str(form["select_key"], f"{where}/select_key")
        expect = _obj(form.get("expect"), f"{where}/expect")
        if sorted(expect) != sorted(names):
            raise _fail(f"{where}/expect", "칸 이름이 fields와 다르다")
    for i, edge in enumerate(_list(spec.get("transitions"), "/transitions")):
        where = f"/transitions/{i}"
        edge = _obj(edge, where)
        for key in ("from", "to"):
            if edge.get(key) not in scenes:
                raise _fail(f"{where}/{key}", f"없는 장면 {edge.get(key)!r}")
        _int(edge.get("after_frames", 0), f"{where}/after_frames")
        on = edge.get("on")
        if on is not None:
            on = _obj(on, f"{where}/on")
            if on.get("kind") == "click":
                _rect(on.get("rect"), f"{where}/on/rect")
            elif on.get("kind") == "key":
                _str(on.get("key"), f"{where}/on/key")
            else:
                raise _fail(f"{where}/on/kind", "click 또는 key")
        when = edge.get("when")
        if when is not None and _obj(when, f"{where}/when").get("form") not in forms:
            raise _fail(f"{where}/when/form", "없는 폼")
        for variant in edge.get("variants", []):
            if variant not in variants:
                raise _fail(f"{where}/variants", f"없는 갈래 {variant!r}")
    return spec


# ---------------------------------------------------------------- 게임 하나


class ScenarioState:
    """가짜 게임 하나의 장면 상태 (갈래 하나). 예제 게임 `Simulator`와 같은 해석이다."""

    def __init__(self, spec: Mapping[str, Any], args: Sequence[str] = ()) -> None:
        self.s = spec
        self.variant: str = next(
            rule["variant"]
            for rule in spec["launch"]
            if "args_contains" not in rule or rule["args_contains"] in args
        )
        self.scene: str = spec["start"]
        self.forms: dict[str, dict[str, Any]] = {}
        self.captures = 0
        self._shown = 0
        self._pending: tuple[_Edge, int] | None = None
        self._enter(self.scene, None)

    def _forms(self) -> Mapping[str, Any]:
        return self.s.get("forms", {})

    def _form_of(self, scene: str) -> str | None:
        return next((n for n, f in self._forms().items() if scene in f["scenes"]), None)

    def _input_form(self) -> tuple[str, Mapping[str, Any]] | None:
        for name, spec in self._forms().items():
            if spec["input_scene"] == self.scene:
                return name, spec
        return None

    def form_valid(self, name: str) -> bool:
        spec = self._forms()[name]
        return all(self.forms[name]["values"][k] == v for k, v in spec["expect"].items())

    def _reset_form(self, name: str) -> None:
        spec = self._forms()[name]
        self.forms[name] = {
            "values": {f["name"]: "" for f in spec["fields"]},
            "focus": spec["focus"],
            "selected": False,
        }

    def _candidates(self, match: Callable[[Any], bool]) -> list[_Edge]:
        found: list[_Edge] = []
        for t in self.s["transitions"]:
            if t["from"] != self.scene or self.variant not in t.get("variants", [self.variant]):
                continue
            if not match(t.get("on")):
                continue
            when = t.get("when")
            if when is not None and self.form_valid(when["form"]) != when["valid"]:
                continue
            found.append(t)
        if len(found) > 1:
            raise EngineError("scenario_ambiguous", f"한 입력에 맞는 장면 전이가 여럿이다: {found}")
        return found

    def _enter(self, scene: str, edge: _Edge | None) -> None:
        old_form = self._form_of(self.scene) if edge is not None else None
        self.scene, self._shown = scene, 0
        new_form = self._form_of(scene)
        if new_form is not None and new_form != old_form:
            self._reset_form(new_form)
        if new_form is not None:
            self.forms[new_form]["selected"] = False
        effects = (edge or {}).get("effects")
        if effects:
            form = self.forms[effects["form"]]
            for name in effects.get("clear", []):
                form["values"][name] = ""
            if "focus" in effects:
                form["focus"] = effects["focus"]

    def _take(self, edge: _Edge) -> None:
        form = self._form_of(self.scene)
        if form is not None:
            self.forms[form]["selected"] = False  # 입력이 전이를 타면 늦게 넘어가도 바로 풀린다
        if edge.get("after_frames", 0) > 0 and "on" in edge:
            self._pending = (edge, edge["after_frames"])
        else:
            self._enter(edge["to"], edge)

    def click(self, x: int, y: int) -> None:
        def inside(rect: Sequence[int]) -> bool:
            rx, ry, rw, rh = rect
            return rx <= x < rx + rw and ry <= y < ry + rh

        found = self._candidates(
            lambda on: bool(on) and on["kind"] == "click" and inside(on["rect"])
        )
        if found:
            self._take(found[0])
            return
        form = self._input_form()
        if form is not None:
            name, spec = form
            for f in spec["fields"]:
                if inside(f["rect"]):
                    self.forms[name]["focus"] = f["name"]
                    self.forms[name]["selected"] = False

    def key(self, key: str) -> None:
        key = key.lower()
        found = self._candidates(lambda on: on == {"kind": "key", "key": key})
        if found:
            self._take(found[0])
            return
        form = self._input_form()
        if form is None:
            return
        name, spec = form
        state = self.forms[name]
        order = [f["name"] for f in spec["fields"]]
        if key == spec["next_key"]:
            state["focus"] = order[(order.index(state["focus"]) + 1) % len(order)]
            state["selected"] = False
        elif key == spec["erase_key"]:
            value = state["values"][state["focus"]]
            state["values"][state["focus"]] = "" if state["selected"] else value[:-1]
            state["selected"] = False
        elif key == spec.get("select_key"):
            state["selected"] = True

    def text(self, chars: str) -> None:
        form = self._input_form()
        if form is None:
            return
        name, spec = form
        state = self.forms[name]
        for ch in chars:
            if not ch.isprintable():
                continue
            if state["selected"]:
                state["values"][state["focus"]] = ""
                state["selected"] = False
            value = state["values"][state["focus"]]
            if len(value) < spec["max_length"]:
                state["values"][state["focus"]] = value + ch

    # ------------------------------------------------------------ 상태 파일 (검사 전용, M7 3.12)

    def to_json(self) -> dict[str, Any]:
        """지금 상태 전부 (`kookabug.fake-scenario-state/0`의 게임 부분)."""
        pending: list[dict[str, Any]] = []
        if self._pending is not None:
            edge, left = self._pending
            index = next(i for i, t in enumerate(self.s["transitions"]) if t is edge)
            pending.append({"transition": index, "to": edge["to"], "after_frames_left": left})
        return {
            "variant": self.variant,
            "scene": self.scene,
            "shown": self._shown,
            "captures": self.captures,
            "pending": pending,
            "forms": {
                name: {
                    "values": dict(form["values"]),
                    "focus": form["focus"],
                    "selected": form["selected"],
                }
                for name, form in self.forms.items()
            },
        }

    def restore(self, data: Mapping[str, Any]) -> bool:
        """`to_json`이 쓴 상태로 되돌린다. 표와 맞지 않으면 아무것도 바꾸지 않고 False."""
        try:
            variant, scene = str(data["variant"]), str(data["scene"])
            if variant not in self.s["variants"] or scene not in self.s["scenes"]:
                return False
            transitions = self.s["transitions"]
            pending: tuple[_Edge, int] | None = None
            for item in data.get("pending", []):
                edge = transitions[int(item["transition"])]
                pending = (edge, int(item["after_frames_left"]))
            forms: dict[str, dict[str, Any]] = {}
            for name, form in dict(data.get("forms", {})).items():
                spec = self._forms()[name]
                names = {f["name"] for f in spec["fields"]}
                values = {str(k): str(v) for k, v in dict(form["values"]).items()}
                if set(values) != names or form["focus"] not in names:
                    return False
                forms[name] = {
                    "values": values,
                    "focus": str(form["focus"]),
                    "selected": bool(form["selected"]),
                }
            shown, captures = int(data.get("shown", 0)), int(data.get("captures", 0))
        except KeyError, IndexError, TypeError, ValueError, AttributeError:
            return False
        self.variant, self.scene, self._shown, self.captures = variant, scene, shown, captures
        self._pending, self.forms = pending, forms
        return True

    def peek(self) -> str:
        """다음 캡처에 보일 장면 (상태·캡처 차례를 바꾸지 않는다 — M8 금지 동작 판정용: 실제 창에서
        입력 직전 "지금 화면"에 해당한다)."""
        if self._pending is not None:
            edge, remaining = self._pending
            return str(edge["to"]) if remaining <= 0 else self.scene
        auto = self._candidates(lambda on: on is None)
        if auto and self._shown >= auto[0].get("after_frames", 0):
            return str(auto[0]["to"])
        return self.scene

    def capture(self) -> str:
        """캡처 한 번. 이 캡처에 보이는 장면."""
        if self._pending is not None:
            edge, remaining = self._pending
            if remaining <= 0:
                self._pending = None
                self._enter(edge["to"], edge)
            else:
                self._pending = (edge, remaining - 1)
        else:
            auto = self._candidates(lambda on: on is None)
            if auto and self._shown >= auto[0].get("after_frames", 0):
                self._enter(auto[0]["to"], auto[0])
        self._shown += 1
        self.captures += 1
        return self.scene


@dataclass(eq=False)
class _Game:
    state: ScenarioState
    window: WindowRef
    process: ProcessRef
    path: str
    args: tuple[str, ...]
    open: bool = True


def _where_point(at: Where) -> Point:
    if isinstance(at, Point):
        return at
    if isinstance(at, Rect):
        return at.center
    return at.click_point


# ---------------------------------------------------------------- 장면 표


class FakeScenario:
    """장면 전이 표 하나와 거기서 띄운 가짜 게임들."""

    def __init__(
        self, spec: Mapping[str, Any], folder: Path, *, state_file: str | Path | None = None
    ) -> None:
        self.spec = _check(dict(spec), folder)
        self.folder = folder
        self._scenes = {name: folder / file for name, file in self.spec["scenes"].items()}
        self._index = {name: i for i, name in enumerate(self.spec["scenes"])}
        self._games: list[_Game] = []
        self._pids = itertools.count(FIRST_PID)
        self._hwnds = itertools.count(FIRST_HWND, 0x10)
        self.inputs: list[tuple[int, str, tuple[Any, ...]]] = []
        """장면에 닿은 입력 (창 HWND, 종류, 인수) — 검사용."""
        self.state_file = None if state_file is None else Path(state_file)
        """검사 전용 상태 파일 (M7 3.12): 첫 게임의 상태를 실행·프로세스 사이에 잇는다."""
        if self.spec.get("running", False):
            # 이미 떠 있는 게임 하나 (띄우지 않고 창에 붙는 그래프·에이전트 제어 실행 검사, M5)
            self.launch_game("", ())

    @classmethod
    def load(cls, path: str | Path, *, state_file: str | Path | None = None) -> FakeScenario:
        path = Path(path)
        try:
            data = loads_strict(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ScenarioError(f"장면 표 {path}을(를) 읽을 수 없다: {exc}") from exc
        return cls(_obj(data, "/"), path.parent, state_file=state_file)

    # ------------------------------------------------------------ 상태 파일 (검사 전용)

    def _read_state(self) -> dict[str, Any] | None:
        if self.state_file is None:
            return None
        try:
            data = loads_strict(self.state_file.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError, ValueError:
            return None  # 없음·깨짐 = 표의 start
        if not isinstance(data, dict) or data.get("format") != STATE_FORMAT:
            return None
        return cast(dict[str, Any], data)

    def save_state(self) -> None:
        """첫 게임의 지금 상태를 상태 파일에 쓴다 (임시 파일 → 바꾸기). 없으면 아무것도 안 한다."""
        if self.state_file is None or not self._games:
            return
        game = self._games[0]
        body = {
            "format": STATE_FORMAT,
            **game.state.to_json(),
            "window": {
                "pid": game.window.pid,
                "created": game.window.process_created,
                "open": game.open,
            },
        }
        tmp = self.state_file.with_name(f"{self.state_file.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_file)

    def _stateful(self, game: _Game) -> bool:
        return self.state_file is not None and bool(self._games) and game is self._games[0]

    # ------------------------------------------------------------ 창·프로세스

    @property
    def window_spec(self) -> Mapping[str, Any]:
        return self.spec["window"]

    @property
    def process_name(self) -> str:
        return str(self.spec["process"]["name"])

    @property
    def client_size(self) -> tuple[int, int]:
        w, h = self.window_spec["client_size"]
        return int(w), int(h)

    @property
    def dpi(self) -> int:
        return int(self.window_spec.get("dpi", 96))

    def scene_path(self, scene: str) -> Path:
        return self._scenes[scene]

    def scene_index(self, scene: str) -> int:
        return self._index[scene]

    def launch_game(self, path: str, args: Sequence[str] = ()) -> _Game:
        pid = next(self._pids)
        hwnd = next(self._hwnds)
        state = ScenarioState(self.spec, args)
        is_open = True
        created = str(pid)
        saved = self._read_state() if not self._games else None
        if saved is not None and state.restore(saved):
            # 상태 파일의 창(같은 HWND를 다른 PID가 쓰는 경우·닫힌 창·프로세스 생성 시각 — 검사가
            # 바꾼다)
            window_state = saved.get("window")
            if isinstance(window_state, dict):
                found = cast(dict[str, Any], window_state)
                if isinstance(found.get("pid"), int):
                    pid = int(found["pid"])
                    created = str(pid)
                if isinstance(found.get("created"), str) and found["created"]:
                    created = str(found["created"])
                is_open = found.get("open", True) is not False
        window = WindowRef(
            handle=hwnd,
            title=str(self.window_spec["title"]),
            pid=pid,
            process_created=created,
            binding=f"fake-{hwnd:x}",
        )
        game = _Game(state, window, ProcessRef(pid, self.process_name), path, tuple(args), is_open)
        self._games.append(game)
        return game

    def games(self) -> list[_Game]:
        return [g for g in self._games if g.open]

    def game_of(self, window: WindowRef) -> _Game:
        for game in self._games:
            if game.window.handle == window.handle and window.pid in (0, game.window.pid):
                if not game.open:
                    raise EngineError(_WINDOW_GONE, f"가짜 창 {window.handle:#x}이(가) 닫혔다")
                return game
        raise EngineError(_WINDOW_GONE, f"가짜 창 {window.handle:#x}이(가) 없다")

    def game_of_process(self, process: ProcessRef) -> _Game | None:
        return next((g for g in self._games if g.process.pid == process.pid), None)

    def latest(self) -> _Game:
        games = self.games()
        if not games:
            raise EngineError("platform_unavailable", "가짜 장면에 띄운 게임이 없다")
        return games[-1]

    def info(self, window: WindowRef) -> WindowInfo:
        game = self.game_of(window)
        return WindowInfo(
            window=game.window,
            title=game.window.title,
            process_name=self.process_name,
            class_name=str(self.window_spec.get("class", "")),
            client_size=self.client_size,
            client_origin=(0, 0),
            dpi=self.dpi,
        )

    def find(
        self, title: str | None = None, process_name: str | None = None, *, owned: bool = False
    ) -> WindowRef | None:
        """띄운 게임의 창 (나중에 띄운 것이 Z 순서 앞). 찾기 규칙은 가짜 ctx와 같다."""
        windows = FakeWindows(self.fake_window(g) for g in reversed(self.games()))
        return windows.find(title, process_name, owned=owned)

    def fake_window(self, game: _Game) -> FakeWindow:
        return FakeWindow(
            ref=game.window,
            process_name=self.process_name,
            class_name=str(self.window_spec.get("class", "")),
            client_size=self.client_size,
            dpi=self.dpi,
        )

    def close_process(self, process: ProcessRef) -> bool:
        game = self.game_of_process(process)
        if game is not None:
            game.open = False
            if self._stateful(game):
                self.save_state()
        return True

    # ------------------------------------------------------------ 화면·입력

    def frame(self, game: _Game) -> Image:
        """캡처 한 번: 지금 장면 PNG (프레임 번호는 그 게임의 캡처 차례)."""
        scene = game.state.capture()
        if self._stateful(game):
            self.save_state()
        return Image(*self.client_size, path=self.scene_path(scene), frame=game.state.captures)

    def apply(self, game: _Game, kind: str, *args: Any) -> None:
        self.inputs.append((game.window.handle, kind, args))
        match kind:
            case "click":
                x, y, button = args
                if button == "left":
                    game.state.click(x, y)
            case "key":
                game.state.key(args[0])
            case "text":
                game.state.text(args[0])
            case _:
                pass
        if self._stateful(game):
            self.save_state()

    def field_values(self, game: _Game) -> dict[str, tuple[tuple[int, int, int, int], str]]:
        """지금 장면이 입력 장면인 폼의 칸 → (칸 상자, 지금 값). 검사 전용 그리기(daemon 가짜
        캡처의 `draw_fields`)가 쓴다."""
        state = game.state
        out: dict[str, tuple[tuple[int, int, int, int], str]] = {}
        for name, form in self.spec.get("forms", {}).items():
            if form["input_scene"] != state.scene or name not in state.forms:
                continue
            values = state.forms[name]["values"]
            for f in form["fields"]:
                x, y, w, h = (int(v) for v in f["rect"])
                out[f"{name}.{f['name']}"] = ((x, y, w, h), str(values.get(f["name"], "")))
        return out

    # ------------------------------------------------------------ SDK `testing.Scenario`

    def capture(self, region: Rect | None) -> Image:
        return self.frame(self.latest())

    def on_input(self, call: InputCall) -> None:
        game = self.latest()
        match call.method:
            case "click":
                point = _where_point(call.args[0])
                for _ in range(int(call.kwargs.get("count", 1))):
                    self.apply(game, "click", point.x, point.y, call.kwargs.get("button", "left"))
            case "key":
                self.apply(game, "key", call.args[0])
            case "type_text":
                text = call.args[0]
                self.apply(game, "text", text.reveal() if isinstance(text, Secret) else text)
            case _:
                self.apply(game, call.method)

    def launch(self, path: str, args: Sequence[str]) -> Sequence[FakeWindow]:
        return [self.fake_window(self.launch_game(path, args))]


# ---------------------------------------------------------------- 입력 싱크


class ScenarioSink:
    """공용 입력 서비스의 싱크: 요청의 대상 창(가짜 게임)에 장면 입력으로 넣는다. `then`이 있으면
    먼저 그쪽(runner의 입력 액터)에 넣고, 성공하면 장면에 넣는다."""

    def __init__(self, scenario: FakeScenario, then: InputSink | None = None) -> None:
        self._scenario = scenario
        self._then = then

    def _game(self, target: object | None) -> _Game:
        # 실제 `WindowInputGuard`처럼 대상 창 없는 입력은 거부한다 (최근 게임으로 보내면 현재 창을
        # 정하지 않은 그래프가 헤드리스에서만 통과한다)
        if target is None:
            raise EngineError("platform_unavailable", NO_INPUT_WINDOW)
        return cast(_Game, target)

    def click(
        self,
        at: ClientPoint,
        *,
        button: str = "left",
        count: int = 1,
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        game = self._game(target)
        if self._then is not None:
            self._then.click(at, button=button, count=count, target=target, step=step)
        for _ in range(count):
            self._scenario.apply(game, "click", at.x, at.y, button)

    def drag(
        self,
        start: ClientPoint,
        end: ClientPoint,
        *,
        button: str = "left",
        duration_ms: int = 0,
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        game = self._game(target)
        if self._then is not None:
            self._then.drag(
                start, end, button=button, duration_ms=duration_ms, target=target, step=step
            )
        self._scenario.apply(game, "drag", start, end)

    def scroll(
        self,
        at: ClientPoint,
        amount: int,
        *,
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        game = self._game(target)
        if self._then is not None:
            self._then.scroll(at, amount, target=target, step=step)
        self._scenario.apply(game, "scroll", at, amount)

    def key(self, key: str, *, target: object | None = None, step: str | None = None) -> None:
        game = self._game(target)
        if self._then is not None:
            self._then.key(key, target=target, step=step)
        self._scenario.apply(game, "key", key)

    def press(self, key: str, *, target: object | None = None, step: str | None = None) -> None:
        game = self._game(target)
        if self._then is not None:
            self._then.press(key, target=target, step=step)
        self._scenario.apply(game, "key", key)

    def release(self, key: str, *, target: object | None = None, step: str | None = None) -> None:
        # 떼기는 실제 입력 액터도 창을 확인하지 않는다 (복구가 막히지 않게).
        # 대상이 없으면 장면에만 넣지 않는다
        if self._then is not None:
            self._then.release(key, target=target, step=step)
        if target is not None:
            self._scenario.apply(self._game(target), "release", key)

    def type_text(
        self, text: str | Secret, *, target: object | None = None, step: str | None = None
    ) -> None:
        game = self._game(target)
        if self._then is not None:
            self._then.type_text(text, target=target, step=step)
        raw = text.reveal() if isinstance(text, Secret) else text
        self._scenario.apply(game, "text", raw)


@dataclass(frozen=True, slots=True)
class _State:
    backend: str
    client_size: tuple[int, int]
    dpi: int


# ---------------------------------------------------------------- 플랫폼


class ScenarioPlatform:
    """`FakeScenario`를 실행기 플랫폼으로 (캡처·창·프로세스·공용 입력 서비스).

    `decode`(이미지 바이트 → 픽셀)를 주면 프레임 저장소용 캡처(`capture_staged`)를 하고, `engines`
    (찾기·비교·OCR, `kookabug_platform.engines.RunEngines`)를 주면 `ctx.vision`·`ctx.ocr`가 실제로
    돈다. `sink`를 주면 입력은 그쪽을 먼저 거친다(runner의 입력 액터).
    """

    def __init__(
        self,
        scenario: FakeScenario,
        *,
        decode: Callable[[bytes], Any] | None = None,
        engines: Any = None,
        sink: InputSink | None = None,
    ) -> None:
        self.scenario = scenario
        self.decode = decode
        self.engines = engines
        self._decoded: dict[int, Any] = {}
        self._video_decoded: dict[str, Any] = {}
        self._video_lock = threading.Lock()
        self.service = InputService(ScenarioSink(scenario, sink), self)

    def attach_input(self, sink: InputSink) -> None:
        """입력이 장면보다 먼저 거칠 싱크 (runner의 입력 액터 — 기록·임대권·복구)."""
        self.service.sink = ScenarioSink(self.scenario, sink)

    # ------------------------------------------------------------ 입력 (공용 입력 서비스)

    @property
    def input(self) -> InputApi:
        raise EngineError("platform_unavailable", "가짜 장면의 입력은 스텝 ctx로만 보낸다")

    def input_for(
        self,
        step: str,
        window: WindowRef | None,
        observer: Any,
        sleep: Callable[[int], None],
    ) -> InputApi:
        return self.service.for_step(step, window, observer, sleep=sleep)

    def bind(self, window: WindowRef) -> object:
        return self.scenario.game_of(window)

    def identify(self, window: WindowRef) -> WindowRef:
        return self.scenario.game_of(window).window

    def state(self, window: WindowRef) -> _State:
        self.scenario.game_of(window)
        return _State("fake", self.scenario.client_size, self.scenario.dpi)

    # ------------------------------------------------------------ 캡처

    def _game(self, window: WindowRef | None) -> _Game:
        # 실제 플랫폼처럼 대상 창 없는 캡처는 거부한다
        if window is None:
            raise EngineError("platform_unavailable", NO_CAPTURE_WINDOW)
        return self.scenario.game_of(window)

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        return self.scenario.frame(self._game(window))

    def peek_frame(self, window: WindowRef | None) -> Image:
        """지금 장면 PNG (캡처 차례·지연 전이를 넘기지 않는다 — M8 금지 동작 판정용)."""
        game = self._game(window)
        return Image(*self.scenario.client_size, path=self.scenario.scene_path(game.state.peek()))

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None, limits: Any = None
    ) -> tuple[Image, StagedFrame]:
        from kookabug_core.engine.platform_fake import stage_frame

        if self.decode is None:
            raise RuntimeError("ScenarioPlatform에 decode가 없어 프레임을 저장소에 둘 수 없다")
        game = self._game(window)
        frame = self.scenario.frame(game)
        assert frame.path is not None
        scene = game.state.scene
        return stage_frame(
            ("scenario", id(self.scenario), scene),
            frame,
            self._decoded,
            self.scenario.scene_index(scene),
            self.decode,
            region,
            window=game.window,
            dpi=self.scenario.dpi,
        )

    def video_frame(self, window: WindowRef, timeout_ms: int) -> VideoFrame:
        """녹화 프레임 (M3 2.5, 녹화 스레드): 그 창 게임의 지금 장면. 캡처 차례(`after_frames`)를
        세지 않는다 — 녹화가 장면 전이를 바꾸지 않게. `marker`는 장면 이름(검사용)."""
        game = self.scenario.game_of(window)
        scene = game.state.scene
        pixels: Any = None
        if self.decode is not None:
            with self._video_lock:
                pixels = self._video_decoded.get(scene)
                if pixels is None:
                    data = self.scenario.scene_path(scene).read_bytes()
                    pixels = self._video_decoded[scene] = self.decode(data)
        return VideoFrame(pixels, self.scenario.client_size, time.time(), marker=scene)

    # ------------------------------------------------------------ 찾기·비교·OCR

    def _engines(self) -> Any:
        if self.engines is None:
            raise EngineError(
                "platform_unavailable", "이 가짜 장면에는 비전·OCR 엔진이 없다 (kookabug-platform)"
            )
        return self.engines

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: Any
    ) -> Match | None:
        return self._engines().find(image, target, region=region, limits=limits)

    def find_report(
        self, image: Image, target: Target, *, region: Rect | None, limits: Any
    ) -> tuple[Match | None, FindEvidence | None]:
        """찾기 + 매칭 후보 (엔진이 주면, M3 2.6)."""
        return find_with_report(self._engines(), image, target, region=region, limits=limits)

    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float:
        return self._engines().diff(a, b, region=region)

    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: Any
    ) -> OcrResult:
        return self._engines().read_text(image, region=region, sensitive=sensitive, limits=limits)

    def before_node(self, node_type: str, check: Callable[[], None]) -> None:
        """노드 함수를 부르기 전: 엔진 준비(OCR)를 기다린다 (`PreparingPlatform`)."""
        prepare = getattr(self.engines, "before_node", None)
        if callable(prepare):
            prepare(node_type, check)

    # ------------------------------------------------------------ 창·프로세스

    def find_window(
        self, title: str | None, process_name: str | None, owned: bool
    ) -> WindowRef | None:
        return self.scenario.find(title, process_name, owned=owned)

    def window_info(self, window: WindowRef) -> WindowInfo:
        return self.scenario.info(window)

    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool:
        self.scenario.game_of(window)
        return (width, height) == self.scenario.client_size

    def activate(self, window: WindowRef) -> bool:
        self.scenario.game_of(window)
        return True

    def launch(self, path: str, args: Sequence[str], cwd: str | None) -> ProcessRef:
        return self.scenario.launch_game(path, args).process

    def close_process(self, process: ProcessRef, force_after_ms: int) -> bool:
        return self.scenario.close_process(process)

    def process_window(
        self, process: ProcessRef, title: str | None, limits: Any
    ) -> WindowRef | None:
        game = self.scenario.game_of_process(process)
        if game is not None and game.open:
            found = FakeWindows([self.scenario.fake_window(game)]).find(title)
            if found is not None:
                return found
        if limits is not None:
            # 가짜 창은 기다려도 뜨지 않는다: 노드 기한까지 기다린 것으로 본다
            raise ObservationTimeout(f"프로세스 {process.pid}의 창이 기한 안에 뜨지 않았다")
        return None

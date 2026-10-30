"""헤드리스용 장면 전이 표(`frames/scenario.json`)를 상태 기계와 버튼 배치에서 만든다.

가짜 플랫폼(`FakeScenario`, 구현 계획 M1 2.7)이 이 표로 같은 예제 그래프를 창 없이 돌린다.
`Simulator`가 이 형식의 실행 가능한 기준 해석이다(검사가 실제 `Game`과 무작위 입력으로 대조한다).

형식 `kookabug.fake-scenario/0`:

- `window`: 가짜 창 (`title`, `class`, `client_size`, `dpi`), `process`: 가짜 프로세스 (`name`)
- `scenes`: 장면 이름 → 이 파일 옆 PNG, `start`: 시작 장면
- `variants`: 실행 옵션이 만드는 갈래 이름. `launch`: 띄우는 인수에 따라 갈래를 고르는 규칙 —
  앞에서부터 `args_contains`(인수 하나가 그 값과 같음)가 맞는 첫 규칙, 조건 없는 규칙이 기본
- `forms`: 입력 칸 상태. 이름 → `{scenes, input_scene, fields, focus, max_length, next_key,
  erase_key, expect}`
  - 상태(칸 값·지금 칸)는 `scenes` 안에서 이어지고, 밖에서 `scenes`로 들어오면 빈 칸·`focus`로
    초기화된다
  - `input_scene`에서만: `fields`의 `rect`(클라이언트 픽셀) 왼쪽 클릭 = 그 칸 선택, 글자 입력 = 지금
    칸 끝에 출력 가능한 글자를 붙임(`max_length`까지), `next_key` = 다음 칸(끝이면 처음),
    `erase_key` = 지금 칸 끝 글자 지움. 전이가 맞는 입력이면 전이가 먼저다
  - `expect`: 모든 칸이 이 값과 같으면 "맞음"(`when.valid`)
- `transitions`: `{from, on, to, after_frames, when?, effects?, variants?}`
  - `on`: `{kind: "click", rect: [x, y, w, h]}`(사각형 안 왼쪽 클릭) 또는 `{kind: "key", key}`
    (kookabug 키 이름). `on`이 없으면 그 장면을 `after_frames`번 캡처한 다음 캡처부터 `to`
  - `after_frames`: `on`이 있으면 입력 뒤 몇 번 캡처한 다음 `to`가 보이는가 (0 = 바로)
  - `when`: `{form, valid}` — 그 폼이 맞음/틀림일 때만
  - `effects`: `{form, clear?: [칸], focus?: 칸}` — 폼 상태가 이어지는 전이에서 칸 비우기·칸 옮기기
  - `variants`: 그 갈래에서만 쓰는 전이. 없으면 모든 갈래
  - 한 입력에 맞는 전이(갈래·`when` 포함)는 많아야 하나다
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Final

from sample_game import BASE_SIZE, DEFAULT_TITLE
from sample_game.flow import FIELD_MAX, FORM_FIELDS, Game, GameConfig, Scene, keys_for
from sample_game.layout import Viewport, buttons_for

__all__ = ["FORMAT", "LOADING_FRAMES", "VARIANTS", "Simulator", "generate"]

FORMAT: Final = "kookabug.fake-scenario/0"
# 로딩 화면이 몇 번의 캡처 동안 보이는가 (wait_gone 같은 노드가 로딩을 실제로 보게)
LOADING_FRAMES: Final = 3
# 갈래 이름 → 실행 옵션 (앞이 우선: 점검이면 로그인까지 가지 않는다)
VARIANTS: Final[dict[str, tuple[str | None, dict[str, bool]]]] = {
    "maintenance": ("--maintenance", {"maintenance": True}),
    "login_fail": ("--login-fail", {"login_fail": True}),
    "default": (None, {}),
}
FORM: Final = "login"
FORM_INPUT_SCENE: Final = Scene.LOGIN
# 폼 상태가 이어지는 장면 (오류 팝업이 떠도 계정 칸은 남는다)
FORM_SCENES: Final = (Scene.LOGIN, Scene.LOGIN_ERROR)
# 로그인 화면의 칸 조작 키 (flow의 _KEYS와 같다 — 대조 검사가 확인)
NEXT_KEY: Final = "tab"
ERASE_KEY: Final = "backspace"

type _On = dict[str, Any] | None
type _Edge = dict[str, Any]


def _expected(config: GameConfig) -> dict[str, str]:
    return {name: getattr(config, name) for name in FORM_FIELDS}


def _values(game: Game) -> dict[str, str]:
    return {name: getattr(game, name) for name in FORM_FIELDS}


def _representatives(state: Game) -> list[tuple[bool | None, Game]]:
    """입력 칸이 있는 장면은 맞는 값·틀린 값 두 대표 상태로 시험한다."""
    if state.scene is not FORM_INPUT_SCENE:
        return [(None, state)]
    good = _expected(state.config)
    bad = dict(good)
    bad[FORM_FIELDS[-1]] += "!"  # 비어 있지 않은 틀린 값 (비우기 효과가 보이게)
    return [(True, replace(state, **good)), (False, replace(state, **bad))]


def _effects(before: Game, after: Game) -> dict[str, Any] | None:
    if after.scene not in FORM_SCENES:
        return None
    if before.scene not in FORM_SCENES:
        if _values(after) != dict.fromkeys(FORM_FIELDS, "") or after.focus != FORM_FIELDS[0]:
            raise AssertionError(f"{after.scene}에 들어올 때 폼이 초기화되지 않는다")
        return None
    old, new = _values(before), _values(after)
    clear = [name for name in FORM_FIELDS if old[name] and not new[name]]
    changed = [name for name in FORM_FIELDS if old[name] != new[name] and name not in clear]
    if changed:
        raise AssertionError(f"표 형식으로 나타낼 수 없는 칸 변화: {changed}")
    effects: dict[str, Any] = {}
    if clear:
        effects["clear"] = clear
    if after.focus != before.focus:
        effects["focus"] = after.focus
    return {"form": FORM, **effects} if effects else None


def _actions(state: Game, viewport: Viewport) -> list[tuple[_On, Callable[[Game], None]]]:
    # 입력 칸 장면의 칸 클릭·칸 조작 키는 폼 규칙(`forms`)이 맡으므로 전이로 만들지 않는다
    form_inputs = state.scene is FORM_INPUT_SCENE
    field_buttons = {f"{name}_field" for name in FORM_FIELDS}
    actions: list[tuple[_On, Callable[[Game], None]]] = []
    for button in buttons_for(state.scene):
        if form_inputs and button.id in field_buttons:
            continue
        on = {"kind": "click", "rect": list(viewport.rect(button.rect))}
        actions.append((on, lambda g, b=button.id: g.press(b)))
    for name in keys_for(state.scene):
        if form_inputs and name in (NEXT_KEY, ERASE_KEY):
            continue
        actions.append(({"kind": "key", "key": name}, lambda g, k=name: g.key(k)))
    if state.timer is not None:
        token = state.timer.token
        actions.append((None, lambda g: g.fire(token)))
    return actions


def _on_key(on: _On) -> str:
    if on is None:
        return "auto"
    if on["kind"] == "click":
        return "click:" + ",".join(f"{v:05d}" for v in on["rect"])
    return f"key:{on['key']}"


def _explore(
    config: GameConfig, viewport: Viewport
) -> tuple[set[str], dict[tuple[str, str], list[_Edge]]]:
    """한 갈래의 장면 그래프를 넓이 우선으로 훑는다. 장면마다 처음 닿은 상태를 대표로 쓴다."""
    edges: dict[tuple[str, str], list[_Edge]] = {}
    start = Game(config)
    queue = [start]
    seen = {start.scene}
    while queue:
        state = queue.pop(0)
        scene = state.scene
        for on, act in _actions(state, viewport):
            results: list[tuple[bool | None, Game, dict[str, Any] | None]] = []
            for valid, rep in _representatives(state):
                nxt = replace(rep)
                act(nxt)
                results.append((valid, nxt, _effects(rep, nxt)))
            same = len({(n.scene, repr(e)) for _v, n, e in results}) == 1
            found: list[_Edge] = []
            for valid, nxt, effects in results[:1] if same else results:
                if nxt.scene is scene and effects is None:
                    continue  # 장면도 폼도 그대로 (칸 클릭·글자 입력은 폼 규칙이 맡는다)
                edge: _Edge = {
                    "after_frames": LOADING_FRAMES if on is None else 0,
                    "from": scene.value,
                    "to": nxt.scene.value,
                }
                if on is not None:
                    edge["on"] = on
                if not same:
                    edge["when"] = {"form": FORM, "valid": valid}
                if effects is not None:
                    edge["effects"] = effects
                found.append(edge)
                if nxt.scene not in seen:
                    seen.add(nxt.scene)
                    queue.append(nxt)
            if found:
                edges[scene.value, _on_key(on)] = found
    return {s.value for s in seen}, edges


def _when_order(edge: _Edge) -> int:
    when = edge.get("when")
    return 0 if when is None else (1 if when["valid"] else 2)


def generate(size: tuple[int, int] = BASE_SIZE, title: str = DEFAULT_TITLE) -> dict[str, Any]:
    viewport = Viewport(*size)
    config = GameConfig()
    explored = {
        name: _explore(replace(config, **flags), viewport)
        for name, (_arg, flags) in VARIANTS.items()
    }
    order = {scene.value: i for i, scene in enumerate(Scene)}
    keys = sorted(
        {k for _reached, edges in explored.values() for k in edges},
        key=lambda k: (order[k[0]], k[1]),
    )
    transitions: list[_Edge] = []
    for key in keys:
        # 그 장면에 닿는 갈래만 본다. 닿는데 전이가 없으면(제자리) 빈 목록
        groups: dict[str, list[str]] = {}
        lists: dict[str, list[_Edge]] = {}
        for name, (reached, edges) in explored.items():
            if key[0] not in reached:
                continue
            found = sorted(edges.get(key, []), key=_when_order)
            sig = repr(found)
            groups.setdefault(sig, []).append(name)
            lists[sig] = found
        for sig in sorted(groups, key=lambda s: sorted(groups[s])):
            for edge in lists[sig]:
                entry = dict(edge)
                if len(groups) > 1:
                    entry["variants"] = sorted(groups[sig])
                transitions.append(entry)
    fields = {b.id: b for b in buttons_for(FORM_INPUT_SCENE)}
    launch: list[dict[str, Any]] = []
    for name, (arg, _flags) in VARIANTS.items():
        launch.append({"args_contains": arg, "variant": name} if arg else {"variant": name})
    return {
        "format": FORMAT,
        "forms": {
            FORM: {
                "erase_key": ERASE_KEY,
                "expect": _expected(config),
                "fields": [
                    {"name": name, "rect": list(viewport.rect(fields[f"{name}_field"].rect))}
                    for name in FORM_FIELDS
                ],
                "focus": FORM_FIELDS[0],
                "input_scene": FORM_INPUT_SCENE.value,
                "max_length": FIELD_MAX,
                "next_key": NEXT_KEY,
                "scenes": [s.value for s in FORM_SCENES],
            }
        },
        "launch": launch,
        "process": {"name": "python.exe"},
        "scenes": {scene.value: f"{scene.value}.png" for scene in Scene},
        "start": Scene.TITLE.value,
        "transitions": transitions,
        "variants": sorted(VARIANTS),
        "window": {
            "class": "TkTopLevel",
            "client_size": list(size),
            "dpi": 96,
            "title": title,
        },
    }


# ---------------------------------------------------------------- 기준 해석


class Simulator:
    """장면 전이 표의 기준 해석 (갈래 하나, 창 하나). 가짜 플랫폼 구현의 대조용이다."""

    def __init__(self, scenario: Mapping[str, Any], args: Sequence[str] = ()) -> None:
        self.s = scenario
        self.variant: str = next(
            rule["variant"]
            for rule in scenario["launch"]
            if "args_contains" not in rule or rule["args_contains"] in args
        )
        self.scene: str = scenario["start"]
        self.forms: dict[str, dict[str, Any]] = {}
        self._shown = 0  # 지금 장면을 캡처한 횟수
        self._pending: tuple[_Edge, int] | None = None
        self._enter(self.scene, None)

    # ---- 폼

    def _form_of(self, scene: str) -> str | None:
        return next((n for n, f in self.s["forms"].items() if scene in f["scenes"]), None)

    def _input_form(self) -> tuple[str, dict[str, Any]] | None:
        for name, spec in self.s["forms"].items():
            if spec["input_scene"] == self.scene:
                return name, spec
        return None

    def form_valid(self, name: str) -> bool:
        spec = self.s["forms"][name]
        return all(self.forms[name]["values"][k] == v for k, v in spec["expect"].items())

    def _reset_form(self, name: str) -> None:
        spec = self.s["forms"][name]
        self.forms[name] = {
            "values": {f["name"]: "" for f in spec["fields"]},
            "focus": spec["focus"],
        }

    # ---- 전이

    def _candidates(self, match: Callable[[_On], bool]) -> list[_Edge]:
        found = []
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
            raise AssertionError(f"한 입력에 전이가 여럿: {found}")
        return found

    def _enter(self, scene: str, edge: _Edge | None) -> None:
        old_form = self._form_of(self.scene) if edge is not None else None
        self.scene, self._shown = scene, 0
        new_form = self._form_of(scene)
        if new_form is not None and new_form != old_form:
            self._reset_form(new_form)
        effects = (edge or {}).get("effects")
        if effects:
            form = self.forms[effects["form"]]
            for name in effects.get("clear", []):
                form["values"][name] = ""
            if "focus" in effects:
                form["focus"] = effects["focus"]

    def _take(self, edge: _Edge) -> None:
        if edge["after_frames"] > 0 and "on" in edge:
            self._pending = (edge, edge["after_frames"])
        else:
            self._enter(edge["to"], edge)

    # ---- 입력·캡처

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

    def key(self, key: str) -> None:
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
        elif key == spec["erase_key"]:
            state["values"][state["focus"]] = state["values"][state["focus"]][:-1]

    def text(self, chars: str) -> None:
        form = self._input_form()
        if form is None:
            return
        name, spec = form
        state = self.forms[name]
        for ch in chars:
            value = state["values"][state["focus"]]
            if ch.isprintable() and len(value) < spec["max_length"]:
                state["values"][state["focus"]] = value + ch

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
            if auto and self._shown >= auto[0]["after_frames"]:
                self._enter(auto[0]["to"], auto[0])
        self._shown += 1
        return self.scene

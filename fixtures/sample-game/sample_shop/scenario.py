"""상점 헤드리스 표(`frames/shop/scenario.json`, `kookabug.fake-scenario/0`)를 상태 기계에서 만든다.

형식은 예제 게임 `sample_game/scenario.py` 맨 위 설명과 같다. 상점은:

- 시작 장면 `boot`(입장 중) → 첫 캡처에 갈래의 상점 장면(`shop`·`shop_moved`·`shop_missing`)
- 콘솔 입력은 폼 `console`(칸 하나, `expect` = 치트 명령) — Enter가 맞으면 `shop_rich`,
  아니면 `shop`
- 장면 이름 = `Shop.scene` (같은 장면 = 같은 그림 — 콘솔 글자는 그림에 넣지 않는다)

`frames(…)`는 장면마다 대표 상태를 준다 (PNG를 그 상태로 그린다).
"""

from __future__ import annotations

from typing import Any, Final

from sample_shop import CLIENT_SIZE, TITLE
from sample_shop.flow import (
    BUTTONS,
    CHEAT_COMMAND,
    CONSOLE_FIELD,
    CONSOLE_MAX,
    LAYOUTS,
    Shop,
    buttons_for,
    keys_for,
)

__all__ = ["BOOT", "FORMAT", "VARIANT_ARGS", "generate", "representatives"]

FORMAT: Final = "kookabug.fake-scenario/0"
BOOT: Final = "boot"
VARIANT_ARGS: Final[dict[str, str | None]] = {
    "moved": "--buy-moved",
    "missing": "--buy-missing",
    "default": None,
}


def _explore(layout: str) -> dict[str, Shop]:
    """그 갈래에서 닿는 장면 → 처음 닿은 대표 상태."""
    start = Shop(layout=layout)  # type: ignore[arg-type]
    seen = {start.scene: start}
    queue = [start]
    while queue:
        state = queue.pop(0)
        nexts = [state.press(b) for b in buttons_for(state)]
        nexts += [state.key(k) for k in keys_for(state)]
        if state.overlay == "console":
            nexts.append(state.type(CHEAT_COMMAND).key("enter"))
        for nxt in nexts:
            if nxt.scene not in seen:
                seen[nxt.scene] = nxt
                queue.append(nxt)
    return seen


def representatives() -> dict[str, Shop]:
    """장면 이름 → 대표 상태 (모든 갈래)."""
    out: dict[str, Shop] = {}
    for layout in LAYOUTS:
        for scene, state in _explore(layout).items():
            out.setdefault(scene, state)
    return out


def _edges(layout: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for scene, state in _explore(layout).items():
        for button in buttons_for(state):
            nxt = state.press(button)
            if nxt.scene != scene:
                on = {"kind": "click", "rect": list(BUTTONS[button])}
                edges.append({"after_frames": 0, "from": scene, "on": on, "to": nxt.scene})
        if state.overlay == "console":
            good = state.type(CHEAT_COMMAND).key("enter")
            bad = state.key("enter")
            for valid, nxt in ((True, good), (False, bad)):
                edges.append(
                    {
                        "after_frames": 0,
                        "from": scene,
                        "on": {"key": "enter", "kind": "key"},
                        "to": nxt.scene,
                        "when": {"form": "console", "valid": valid},
                    }
                )
            esc = state.key("esc")
            edges.append(
                {
                    "after_frames": 0,
                    "from": scene,
                    "on": {"key": "esc", "kind": "key"},
                    "to": esc.scene,
                }
            )
            continue
        for key in keys_for(state):
            nxt = state.key(key)
            if nxt.scene != scene:
                edges.append(
                    {
                        "after_frames": 0,
                        "from": scene,
                        "on": {"key": key, "kind": "key"},
                        "to": nxt.scene,
                    }
                )
    return edges


def _sort_key(edge: dict[str, Any]) -> tuple[str, str, int]:
    on = edge.get("on") or {}
    when = edge.get("when")
    return (
        edge["from"],
        repr(sorted(on.items())),
        0 if when is None else (1 if when["valid"] else 2),
    )


def generate() -> dict[str, Any]:
    transitions: list[dict[str, Any]] = []
    merged: dict[str, dict[str, Any]] = {}
    for layout in LAYOUTS:
        for edge in _edges(layout):
            key = repr(sorted(edge.items()))
            if key in merged:
                merged[key]["variants"].append(layout)
            else:
                merged[key] = {**edge, "variants": [layout]}
    for edge in merged.values():
        if len(edge["variants"]) == len(LAYOUTS):
            del edge["variants"]  # 모든 갈래
        else:
            edge["variants"] = sorted(edge["variants"])
        transitions.append(edge)
    for layout in LAYOUTS:
        start = Shop(layout=layout).scene  # type: ignore[arg-type]
        transitions.append({"after_frames": 0, "from": BOOT, "to": start, "variants": [layout]})
    transitions.sort(key=_sort_key)
    scenes = sorted({*representatives(), BOOT})
    return {
        "format": FORMAT,
        "forms": {
            "console": {
                "erase_key": "backspace",
                "expect": {"command": CHEAT_COMMAND},
                "fields": [{"name": "command", "rect": list(CONSOLE_FIELD)}],
                "focus": "command",
                "input_scene": "console",
                "max_length": CONSOLE_MAX,
                "next_key": "tab",
                "scenes": ["console"],
            }
        },
        "launch": [
            {"args_contains": arg, "variant": name} if arg else {"variant": name}
            for name, arg in VARIANT_ARGS.items()
        ],
        "process": {"name": "python.exe"},
        "scenes": {name: f"{name}.png" for name in scenes},
        "start": BOOT,
        "transitions": transitions,
        "variants": sorted(LAYOUTS),
        "window": {
            "class": "TkTopLevel",
            "client_size": list(CLIENT_SIZE),
            "dpi": 96,
            "title": TITLE,
        },
    }

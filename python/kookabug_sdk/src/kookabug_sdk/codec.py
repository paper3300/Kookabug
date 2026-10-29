"""값 인코딩: runner ↔ 워커 경계에서 노드 입력·출력·`ctx` 값을 JSON 값으로 (구현 계획 M0b 2.5).

- JSON 값(None·bool·int·float·str·list·문자열 키 dict)은 그대로. tuple은 list가 된다
- SDK 타입은 `{"$kb": "<태그>", ...}`: `secret`, `rect`, `point`, `window`, `process`, `image`,
  `match`, `target`
- `$kb` 키를 가진 사용자 dict는 `{"$kb": "dict", "value": {...}}`로 감싼다 (태그와 헷갈리지 않게)
- `Secret`은 경계 너머에서도 `Secret`이다. 원문은 인증된 로컬 파이프로만 가고, 인코딩한 값을
  `repr()`·`str()`로 찍어도(로그) 가린 값만 나온다

숫자 범위·NaN·중첩 한도는 RPC 피어가 보내기 전에 검사한다 (`kookabug_sdk.rpc`).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_sdk.types import Image, Match, Point, ProcessRef, Rect, Secret, Target, WindowRef

__all__ = ["TAG", "CodecError", "decode", "encode"]

TAG: Final = "$kb"


class CodecError(ValueError):
    """인코딩할 수 없는 값이거나 읽을 수 없는 인코딩 (모르는 태그·틀린 모양)."""


class _SecretWire(dict[str, Any]):
    """인코딩한 비밀값. JSON으로는 원문이 나가고 `repr()`·`str()`에는 가린 값만 나온다."""

    def __repr__(self) -> str:
        return f"{{'{TAG}': 'secret', 'value': '{Secret.MASK}'}}"

    __str__ = __repr__


def encode(value: Any) -> Any:
    """값 → JSON 값."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Secret):
        return _SecretWire({TAG: "secret", "value": value.reveal()})
    if isinstance(value, list | tuple):
        items: list[Any] | tuple[Any, ...] = value
        return [encode(v) for v in items]
    if isinstance(value, Mapping):
        mapping: Mapping[Any, Any] = value
        out: dict[str, Any] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise CodecError(f"dict 키는 문자열이어야 한다: {key!r}")
            out[key] = encode(item)
        return {TAG: "dict", "value": out} if TAG in out else out
    if isinstance(value, Rect):
        return _rect(value)
    if isinstance(value, Point):
        return {TAG: "point", "x": value.x, "y": value.y}
    if isinstance(value, WindowRef):
        return _window(value)
    if isinstance(value, ProcessRef):
        return {TAG: "process", "pid": value.pid, "name": value.name}
    if isinstance(value, Image):
        return _image(value)
    if isinstance(value, Match):
        return {
            TAG: "match",
            "rect": _rect(value.rect),
            "score": value.score,
            "window": None if value.window is None else _window(value.window),
            "frame": value.frame,
        }
    if isinstance(value, Target):
        return {
            TAG: "target",
            "name": value.name,
            "path": None if value.path is None else value.path.as_posix(),
            "spec": encode(dict(value.spec)),
        }
    raise CodecError(f"경계 너머로 보낼 수 없는 값: {type(value).__name__}")


def _rect(value: Rect) -> dict[str, Any]:
    return {TAG: "rect", "x": value.x, "y": value.y, "width": value.width, "height": value.height}


def _window(value: WindowRef) -> dict[str, Any]:
    return {TAG: "window", "handle": value.handle, "title": value.title}


def _image(value: Image) -> dict[str, Any]:
    return {
        TAG: "image",
        "width": value.width,
        "height": value.height,
        "path": None if value.path is None else value.path.as_posix(),
        "frame": value.frame,
        "data": None if value.data is None else base64.b64encode(value.data).decode("ascii"),
        "capture_id": value.capture_id,
    }


def decode(value: Any) -> Any:
    """JSON 값 → 값. 모르는 태그·틀린 모양은 `CodecError`."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        items: list[Any] = value
        return [decode(v) for v in items]
    if not isinstance(value, dict):
        raise CodecError(f"JSON 값이 아니다: {type(value).__name__}")
    data: dict[str, Any] = value
    if TAG not in data:
        return {k: decode(v) for k, v in data.items()}
    tag = data[TAG]
    try:
        return _decode_tagged(tag, data)
    except CodecError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CodecError(f"'{tag}' 값의 모양이 틀렸다: {exc!r}") from exc


def _fields(data: dict[str, Any], *names: str) -> None:
    extra = sorted(set(data) - {TAG, *names})
    missing = sorted(set(names) - set(data))
    if extra or missing:
        raise CodecError(f"'{data[TAG]}' 값의 필드가 틀렸다 (모르는 필드 {extra}, 빠짐 {missing})")


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CodecError(f"정수가 아니다: {value!r}")
    return value


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise CodecError(f"문자열이 아니다: {value!r}")
    return value


def _opt_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _opt_path(value: Any) -> Path | None:
    return None if value is None else Path(_str(value))


def _decode_rect(data: Any) -> Rect:
    if not isinstance(data, dict) or data.get(TAG) != "rect":  # pyright: ignore[reportUnknownMemberType]
        raise CodecError(f"rect가 아니다: {data!r}")
    rect: dict[str, Any] = data
    _fields(rect, "x", "y", "width", "height")
    return Rect(_int(rect["x"]), _int(rect["y"]), _int(rect["width"]), _int(rect["height"]))


def _decode_window(data: Any) -> WindowRef:
    if not isinstance(data, dict) or data.get(TAG) != "window":  # pyright: ignore[reportUnknownMemberType]
        raise CodecError(f"window가 아니다: {data!r}")
    window: dict[str, Any] = data
    _fields(window, "handle", "title")
    return WindowRef(_int(window["handle"]), _str(window["title"]))


def _decode_tagged(tag: Any, data: dict[str, Any]) -> Any:
    match tag:
        case "dict":
            _fields(data, "value")
            inner = data["value"]
            if not isinstance(inner, dict):
                raise CodecError("'dict' 값의 value는 객체다")
            mapping: dict[str, Any] = inner
            return {k: decode(v) for k, v in mapping.items()}
        case "secret":
            _fields(data, "value")
            return Secret(_str(data["value"]))
        case "rect":
            return _decode_rect(data)
        case "point":
            _fields(data, "x", "y")
            return Point(_int(data["x"]), _int(data["y"]))
        case "window":
            return _decode_window(data)
        case "process":
            _fields(data, "pid", "name")
            return ProcessRef(_int(data["pid"]), _str(data["name"]))
        case "image":
            _fields(data, "width", "height", "path", "frame", "data", "capture_id")
            raw = data["data"]
            return Image(
                width=_int(data["width"]),
                height=_int(data["height"]),
                path=_opt_path(data["path"]),
                frame=_opt_int(data["frame"]),
                data=None if raw is None else base64.b64decode(_str(raw), validate=True),
                capture_id=_opt_int(data["capture_id"]),
            )
        case "match":
            _fields(data, "rect", "score", "window", "frame")
            score = data["score"]
            if isinstance(score, bool) or not isinstance(score, int | float):
                raise CodecError(f"score는 수다: {score!r}")
            window = data["window"]
            return Match(
                _decode_rect(data["rect"]),
                float(score),
                None if window is None else _decode_window(window),
                _opt_int(data["frame"]),
            )
        case "target":
            _fields(data, "name", "path", "spec")
            spec = decode(data["spec"])
            if not isinstance(spec, dict):
                raise CodecError("target의 spec은 객체다")
            return Target(_str(data["name"]), _opt_path(data["path"]), spec)
        case _:
            raise CodecError(f"모르는 값 태그 {tag!r}")

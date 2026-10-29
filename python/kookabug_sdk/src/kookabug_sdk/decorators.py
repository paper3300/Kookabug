"""노드 선언: `@node`와 출구·설정·재시도 선언.

선언 오류는 데코레이터가 바로 `NodeDeclarationError`로 낸다
(모듈 import 때 = `kookabug-sdk build` 때).
"""

from __future__ import annotations

import functools
import inspect
import math
import re
import typing
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from kookabug_sdk.context import EFFECTS, Context, EffectContext, GuardedContext
from kookabug_sdk.pure import PureContext
from kookabug_sdk.result import ExitKind, NodeContractError, Result
from kookabug_sdk.types import PinTypeDeclError, describe

__all__ = [
    "CORE_PLUGIN",
    "MISSING",
    "Config",
    "DynamicExits",
    "Exit",
    "FromInterface",
    "Input",
    "NodeDeclarationError",
    "NodeFunction",
    "NodeSpec",
    "Output",
    "Retry",
    "guard",
    "node",
]

CORE_PLUGIN: Final = "core"
MAX_SAFE_INTEGER: Final = 2**53 - 1
_NODE_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
_ENGINE = re.compile(r"^[a-z][a-z0-9_]*$")


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final[Any] = _Missing()


class NodeDeclarationError(ValueError):
    """노드 선언이 규칙에 맞지 않는다 (빌드 오류)."""


# ---------------------------------------------------------------- 선언 객체


@dataclass(frozen=True, slots=True)
class Exit:
    """출구. `outputs`를 생략하면 `ok` 출구는 선언한 출력 전부, `fail` 출구는 출력 없음."""

    name: str
    kind: ExitKind
    outputs: Sequence[str] | None = None


@dataclass(frozen=True, slots=True)
class DynamicExits:
    """config 값(문자열 배열)으로 출구를 만든다. `extra`는 고정 출구."""

    from_config: str
    kind: ExitKind = "ok"
    extra: Sequence[Exit] = ()
    outputs: Sequence[str] | None = None


@dataclass(frozen=True, slots=True)
class FromInterface:
    """핀·출구를 그래프 `interface`에서 만든다 (`core.graph.entry`·`exit`·`call`)."""

    source: Literal["inputs", "outputs", "exits"]


@dataclass(frozen=True, slots=True)
class Config:
    """연결할 수 없는 노드 설정. `default`가 없으면 필수."""

    type: Any
    default: Any = MISSING
    description: str | None = None
    enum: Sequence[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = None


@dataclass(frozen=True, slots=True)
class Input:
    """입력 핀 제약. `Annotated[int, Input(minimum=1)]`처럼 쓴다."""

    description: str | None = None
    enum: Sequence[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = None


@dataclass(frozen=True, slots=True)
class Output:
    """출력 핀. `outputs={"match": Match}` 대신 설명·nullable이 필요할 때 쓴다."""

    type: Any
    nullable: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Retry:
    """노드 타입의 재시도 선언. 생략하면 `never`."""

    mode: Literal["never", "observation"]
    on: tuple[str, ...] = ()

    @classmethod
    def never(cls) -> Retry:
        return cls("never")

    @classmethod
    def observation(cls, on: Sequence[str]) -> Retry:
        """관측 재시도. `on`은 재시도할 수 있는 fail 출구."""
        return cls("observation", tuple(on))


# ---------------------------------------------------------------- 해석된 선언


@dataclass(frozen=True, slots=True)
class PinSpec:
    name: str
    type: str
    nullable: bool = False
    default: Any = MISSING
    description: str | None = None
    enum: tuple[Any, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = None

    @property
    def required(self) -> bool:
        return self.default is MISSING

    def to_json(self, *, with_nullable: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if with_nullable and self.nullable:
            out["nullable"] = True
        if self.default is not MISSING:
            out["default"] = self.default
        if self.description:
            out["description"] = self.description
        if self.enum is not None:
            out["enum"] = list(self.enum)
        for key in ("minimum", "maximum", "min_items"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True, slots=True)
class ExitSpec:
    name: str
    kind: ExitKind
    outputs: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "outputs": list(self.outputs)}


@dataclass(frozen=True, slots=True)
class DynamicExitsSpec:
    from_config: str
    kind: ExitKind
    outputs: tuple[str, ...]
    extra: tuple[ExitSpec, ...]

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "from_config": self.from_config,
            "kind": self.kind,
            "outputs": list(self.outputs),
        }
        if self.extra:
            out["extra"] = [e.to_json() for e in self.extra]
        return out


type Pins = tuple[PinSpec, ...] | FromInterface
type Exits = tuple[ExitSpec, ...] | DynamicExitsSpec | FromInterface | None


@dataclass(frozen=True, slots=True)
class NodeSpec:
    type: str
    version: int
    title: str
    category: str | None
    description: str | None
    pure: bool
    inputs: Pins
    outputs: Pins
    exits: Exits
    config: tuple[PinSpec, ...]
    effects: frozenset[str]
    retry: Retry
    assertion: bool
    engine: str | None

    @property
    def plugin(self) -> str:
        return self.type.split(".", 1)[0]

    def output(self, name: str) -> PinSpec | None:
        if isinstance(self.outputs, FromInterface):
            return None
        return next((p for p in self.outputs if p.name == name), None)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "version": self.version, "title": self.title}
        if self.category:
            out["category"] = self.category
        if self.description:
            out["description"] = self.description
        if self.pure:
            out["pure"] = True
        out["inputs"] = _pins_json(self.inputs)
        out["outputs"] = _pins_json(self.outputs)
        if isinstance(self.exits, tuple):
            out["exits"] = [e.to_json() for e in self.exits]
        elif isinstance(self.exits, DynamicExitsSpec):
            out["exits"] = self.exits.to_json()
        elif isinstance(self.exits, FromInterface):
            out["exits"] = {"from_interface": self.exits.source}
        if self.config:
            out["config"] = {p.name: p.to_json(with_nullable=False) for p in self.config}
        if self.effects:
            out["effects"] = sorted(self.effects)
        if self.retry.mode == "observation":
            out["retry"] = {"mode": "observation", "on": list(self.retry.on)}
        if self.assertion:
            out["assertion"] = True
        if self.engine:
            out["engine"] = self.engine
        return out


def _pins_json(pins: Pins) -> dict[str, Any]:
    if isinstance(pins, FromInterface):
        return {"from_interface": pins.source}
    return {p.name: p.to_json() for p in pins}


# ---------------------------------------------------------------- 실행 래퍼


def guard(ctx: Context, spec: NodeSpec) -> GuardedContext:
    """노드에 넘길 ctx. 순수 노드는 `PureContext`, exec 노드는 `EffectContext`(선언한 효과만)."""
    if spec.pure:
        return PureContext(ctx)
    return EffectContext(ctx, spec.effects)


class NodeFunction:
    """`@node`가 만든 노드. 부르면 ctx를 제한해 함수를 실행하고 결과를 선언과 대조한다.

    선언과 다른 결과·막힌 ctx 사용은 예외가 되고, 실행기는 그것을 `error`로 본다.
    """

    def __init__(self, fn: Callable[..., Any], spec: NodeSpec) -> None:
        functools.update_wrapper(self, fn)
        self.__wrapped__ = fn
        self.spec = spec
        self._signature = inspect.signature(fn)

    def __repr__(self) -> str:
        return f"<node {self.spec.type} v{self.spec.version}>"

    def __call__(self, ctx: Context, /, *args: Any, **kwargs: Any) -> Result:
        return self._run(ctx, args, kwargs)

    def invoke(self, ctx: Context, inputs: Mapping[str, Any]) -> Result:
        """실행기용: 입력 이름 → 값으로 부른다."""
        return self._run(ctx, (), dict(inputs))

    def schema(self) -> dict[str, Any]:
        return self.spec.to_json()

    def _run(self, ctx: Context, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Result:
        if self.spec.engine:
            raise NodeContractError(f"{self.spec.type}은(는) 실행기가 직접 처리하는 노드다")
        guarded = guard(ctx, self.spec)
        returned = self.__wrapped__(guarded, *args, **kwargs)
        if guarded.violations:
            raise guarded.violations[0]
        return self.check_result(returned, ctx.config)

    def check_result(self, returned: object, config: Mapping[str, Any]) -> Result:
        """반환값을 선언과 대조한다. nullable 출력을 빠뜨렸으면 None으로 채운 결과를 돌려준다."""
        spec = self.spec
        if spec.pure:
            if not isinstance(returned, Mapping):
                raise NodeContractError(f"{spec.type}: 순수 노드는 출력 dict를 반환한다")
            outputs = dict(typing.cast(Mapping[str, Any], returned))
            return Result(None, None, self._check_outputs(outputs, None))
        if not isinstance(returned, Result) or returned.exit is None:
            raise NodeContractError(f"{spec.type}: exec 노드는 Result.ok/fail을 반환한다")
        exit = self._find_exit(returned.exit, config)
        if exit is None:
            return returned
        if exit.kind != returned.kind:
            raise NodeContractError(
                f"{spec.type}: 출구 '{exit.name}'은(는) {exit.kind} 출구다 "
                f"(Result.{returned.kind}로 반환함)"
            )
        outputs = self._check_outputs(dict(returned.outputs), exit)
        return Result(returned.exit, returned.kind, outputs, returned.message)

    def _find_exit(self, name: str, config: Mapping[str, Any]) -> ExitSpec | None:
        exits = self.spec.exits
        if isinstance(exits, FromInterface):
            # FromInterface는 engine 노드에만 있고, engine 노드는 여기까지 오지 않는다 (방어)
            raise NodeContractError(f"{self.spec.type}: interface 출구는 실행기가 해석한다")
        if exits is None:
            raise NodeContractError(f"{self.spec.type}: 출구가 없는 노드다")
        found: ExitSpec | None = None
        if isinstance(exits, tuple):
            found = next((e for e in exits if e.name == name), None)
        else:
            found = next((e for e in exits.extra if e.name == name), None)
            dynamic = config.get(exits.from_config)
            if found is None and isinstance(dynamic, list) and name in dynamic:
                found = ExitSpec(name, exits.kind, exits.outputs)
        if found is None:
            raise NodeContractError(f"{self.spec.type}: 선언하지 않은 출구 '{name}'")
        return found

    def _check_outputs(self, outputs: dict[str, Any], exit: ExitSpec | None) -> dict[str, Any]:
        spec = self.spec
        if isinstance(spec.outputs, FromInterface):
            return outputs
        declared = {p.name: p for p in spec.outputs}
        allowed = declared.keys() if exit is None else set(exit.outputs)
        where = "" if exit is None else f" (출구 '{exit.name}')"
        for name in outputs:
            if name not in declared:
                raise NodeContractError(f"{spec.type}: 선언하지 않은 출력 '{name}'")
            if name not in allowed:
                raise NodeContractError(
                    f"{spec.type}: 출력 '{name}'은(는) 이 출구가 주지 않는다{where}"
                )
        for name in allowed:
            if name in outputs:
                continue
            if not declared[name].nullable:
                raise NodeContractError(f"{spec.type}: 출력 '{name}'이(가) 빠졌다{where}")
            outputs[name] = None
        return outputs


# ---------------------------------------------------------------- @node


def node(
    *,
    type: str,
    version: int,
    title: str,
    category: str | None = None,
    exits: Sequence[Exit] | DynamicExits | FromInterface | None = None,
    outputs: Mapping[str, Any] | FromInterface | None = None,
    config: Mapping[str, Config] | None = None,
    inputs: FromInterface | None = None,
    pure: bool = False,
    retry: Retry | None = None,
    effects: Collection[str] = (),
    assertion: bool = False,
    engine: str | None = None,
) -> Callable[[Callable[..., Any]], NodeFunction]:
    """노드를 선언한다.

    - 함수 인자(첫 인자 `ctx` 제외) = 입력 핀. 타입 힌트가 핀 타입, 기본값이 핀 기본값
    - docstring = 노드 설명
    - `effects`: 게임에 영향을 주는 동작(`capture`·`input`·`process`).
      선언 안 한 효과를 ctx로 쓰면 error
    - `assertion=True`: 검증 노드 (판정 5행)
    - `engine="<이름>"`: 실행기가 직접 처리 (core 전용, 함수 본문은 호출되지 않음)
    - `inputs`/`outputs`/`exits`에 `FromInterface`: 그래프 interface에서 만든다
    """

    def decorate(fn: Callable[..., Any]) -> NodeFunction:
        spec = _NodeDecl(
            fn=fn,
            node_type=type,
            version=version,
            title=title,
            category=category,
            exits=exits,
            outputs=outputs,
            config=config,
            inputs=inputs,
            pure=pure,
            retry=retry,
            effects=effects,
            assertion=assertion,
            engine=engine,
        ).resolve()
        return NodeFunction(fn, spec)

    return decorate


@dataclass
class _NodeDecl:
    fn: Callable[..., Any]
    node_type: str
    version: int
    title: str
    category: str | None
    exits: Sequence[Exit] | DynamicExits | FromInterface | None
    outputs: Mapping[str, Any] | FromInterface | None
    config: Mapping[str, Config] | None
    inputs: FromInterface | None
    pure: bool
    retry: Retry | None
    effects: Collection[str]
    assertion: bool
    engine: str | None
    _where: str = field(init=False, default="")

    def fail(self, message: str) -> typing.NoReturn:
        raise NodeDeclarationError(f"{self._where}{message}")

    def resolve(self) -> NodeSpec:
        self._where = f"{self.node_type!r} ({self.fn.__module__}.{self.fn.__qualname__}): "
        if not isinstance(self.node_type, str) or not _NODE_TYPE.match(self.node_type):
            self.fail("type은 '<플러그인>.<분류>.<동작>' 형식이다 (소문자·숫자·밑줄)")
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or not 1 <= self.version <= MAX_SAFE_INTEGER
        ):
            self.fail("version은 1 이상의 정수다")
        if not self.title:
            self.fail("title이 비었다")

        effects = frozenset(self.effects)
        if unknown := sorted(effects - EFFECTS):
            self.fail(f"모르는 effects {unknown}. 가능한 값: {sorted(EFFECTS)}")
        engine = self._engine()
        outputs = self._outputs()
        inputs = self._inputs()
        config = self._config()
        exits = self._exits(outputs, config, engine)
        retry = self._retry(exits, effects)

        if self.pure:
            if effects:
                self.fail("순수 노드는 effects를 선언할 수 없다")
            if self.assertion:
                self.fail("검증 노드(assertion)는 exec 노드여야 한다")

        doc = inspect.getdoc(self.fn)
        return NodeSpec(
            type=self.node_type,
            version=self.version,
            title=self.title,
            category=self.category,
            description=doc or None,
            pure=self.pure,
            inputs=inputs,
            outputs=outputs,
            exits=exits,
            config=config,
            effects=effects,
            retry=retry,
            assertion=self.assertion,
            engine=engine,
        )

    def _engine(self) -> str | None:
        if self.engine is None:
            return None
        if not _ENGINE.match(self.engine):
            self.fail(f"engine 이름이 잘못됐다: {self.engine!r}")
        if self.node_type.split(".", 1)[0] != CORE_PLUGIN:
            self.fail("engine=은 core 플러그인 노드만 쓸 수 있다")
        return self.engine

    def _hints(self) -> dict[str, Any]:
        try:
            return typing.get_type_hints(self.fn, include_extras=True)
        except Exception as exc:
            self.fail(f"타입 힌트를 읽을 수 없다: {exc}")

    def _inputs(self) -> Pins:
        params = list(inspect.signature(self.fn).parameters.values())
        positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        if not params or params[0].kind not in positional:
            self.fail("첫 인자는 ctx여야 한다")
        params = params[1:]
        if self.inputs is not None:
            self._check_interface(self.inputs, ("inputs", "outputs"), "inputs")
            if params:
                self.fail("inputs=FromInterface를 쓰면 함수 인자는 ctx 하나뿐이어야 한다")
            return self.inputs

        hints = self._hints()
        pins: list[PinSpec] = []
        for p in params:
            if p.kind not in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                self.fail(f"입력 '{p.name}': *args·**kwargs·위치 전용 인자는 쓸 수 없다")
            if not _NAME.match(p.name):
                self.fail(f"입력 이름 '{p.name}'은(는) 소문자·숫자·밑줄만 쓴다")
            if p.name not in hints:
                self.fail(f"입력 '{p.name}'에 타입 힌트가 없다")
            hint = hints[p.name]
            meta = Input()
            if typing.get_origin(hint) is typing.Annotated:
                hint, *extras = typing.get_args(hint)
                metas = [e for e in extras if isinstance(e, Input)]
                if len(metas) > 1:
                    self.fail(f"입력 '{p.name}': Input(...)은 하나만 쓴다")
                if metas:
                    meta = metas[0]
            pins.append(
                self._pin(
                    f"입력 '{p.name}'",
                    p.name,
                    hint,
                    default=MISSING if p.default is inspect.Parameter.empty else p.default,
                    description=meta.description,
                    enum=meta.enum,
                    minimum=meta.minimum,
                    maximum=meta.maximum,
                    min_items=meta.min_items,
                )
            )
        return tuple(pins)

    def _outputs(self) -> Pins:
        if isinstance(self.outputs, FromInterface):
            self._check_interface(self.outputs, ("inputs", "outputs"), "outputs")
            return self.outputs
        pins: list[PinSpec] = []
        for name, decl in sorted((self.outputs or {}).items()):
            if not isinstance(name, str) or not _NAME.match(name):
                self.fail(f"출력 이름 {name!r}은(는) 소문자·숫자·밑줄만 쓴다")
            out = decl if isinstance(decl, Output) else Output(decl)
            pin = self._pin(f"출력 '{name}'", name, out.type, description=out.description)
            if pin.enum is not None:
                # 노드 스키마의 출력 핀에는 선택지(enum)가 없다. 연결 검사는 타입만 본다
                self.fail(f"출력 '{name}': Literal은 입력·config 핀에서만 쓴다 (출력은 str 등)")
            if out.nullable and not pin.nullable:
                pin = PinSpec(pin.name, pin.type, True, description=pin.description)
            pins.append(pin)
        return tuple(pins)

    def _config(self) -> tuple[PinSpec, ...]:
        pins: list[PinSpec] = []
        for name, decl in sorted((self.config or {}).items()):
            if not isinstance(name, str) or not _NAME.match(name):
                self.fail(f"config 이름 {name!r}은(는) 소문자·숫자·밑줄만 쓴다")
            if not isinstance(decl, Config):
                self.fail(f"config '{name}'은(는) Config(...)로 선언한다")
            pin = self._pin(
                f"config '{name}'",
                name,
                decl.type,
                default=decl.default,
                description=decl.description,
                enum=decl.enum,
                minimum=decl.minimum,
                maximum=decl.maximum,
                min_items=decl.min_items,
            )
            if pin.nullable:
                self.fail(f"config '{name}'은(는) None을 받을 수 없다")
            pins.append(pin)
        return tuple(pins)

    def _pin(
        self,
        what: str,
        name: str,
        hint: Any,
        *,
        default: Any = MISSING,
        description: str | None = None,
        enum: Sequence[Any] | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        min_items: int | None = None,
    ) -> PinSpec:
        try:
            info = describe(hint)
        except PinTypeDeclError as exc:
            self.fail(f"{what}: {exc}")
        if info.enum is not None and enum is not None:
            self.fail(f"{what}: Literal과 enum을 같이 쓸 수 없다")
        values = info.enum if enum is None else tuple(enum)
        if values is not None:
            if not values:
                self.fail(f"{what}: enum이 비었다")
            values = tuple(self._json(f"{what} enum", v) for v in values)
        if default is not MISSING:
            if default is None and not info.nullable:
                self.fail(f"{what}: 기본값 None은 '| None' 타입에만 쓴다")
            default = self._json(f"{what} 기본값", default)
        if description is not None and not isinstance(description, str):
            self.fail(f"{what}: description은 문자열이다")
        minimum = self._number(f"{what} minimum", minimum)
        maximum = self._number(f"{what} maximum", maximum)
        if minimum is not None and maximum is not None and minimum > maximum:
            self.fail(f"{what}: minimum({minimum})이 maximum({maximum})보다 크다")
        if min_items is not None and (
            isinstance(min_items, bool)
            or not isinstance(min_items, int)
            or not 0 <= min_items <= MAX_SAFE_INTEGER
        ):
            self.fail(f"{what}: min_items는 0 이상의 정수다 ({min_items!r})")
        return PinSpec(
            name=name,
            type=info.type,
            nullable=info.nullable,
            default=default,
            description=description,
            enum=values,
            minimum=minimum,
            maximum=maximum,
            min_items=min_items,
        )

    def _number(self, what: str, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.fail(f"{what}: 수여야 한다 ({value!r})")
        return self._json(what, value)

    def _json(self, what: str, value: Any) -> Any:
        """JSON으로 쓸 수 있는 값으로 바꾼다 (튜플 → 리스트).

        정수는 ±(2^53-1) 안, 실수는 유한해야 한다 (제품 형식 검사·에디터와 같은 규칙).
        """
        if value is None or isinstance(value, bool | str):
            return value
        if isinstance(value, int):
            if abs(value) > MAX_SAFE_INTEGER:
                self.fail(f"{what}: 정수는 ±(2^53-1) 안이어야 한다 ({value})")
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                self.fail(f"{what}: 유한한 수여야 한다")
            return value
        if isinstance(value, list | tuple):
            return [self._json(what, v) for v in typing.cast(Sequence[Any], value)]
        if isinstance(value, dict):
            items = typing.cast(dict[Any, Any], value).items()
            if not all(isinstance(k, str) for k, _ in items):
                self.fail(f"{what}: dict 키는 str이어야 한다")
            return {k: self._json(what, v) for k, v in items}
        self.fail(f"{what}: JSON 값이 아니다 ({value!r})")

    def _check_interface(self, value: FromInterface, allowed: tuple[str, ...], where: str) -> None:
        # interface에서 만든 핀·출구는 실행기만 해석할 수 있다. 일반 노드에 허용하면
        # 결과 검사(출구·출력 대조)를 할 수 없다
        if self.engine is None:
            self.fail(f"{where}=FromInterface는 engine= 노드(core)만 쓸 수 있다")
        if value.source not in allowed:
            self.fail(f"{where}=FromInterface({value.source!r}): 가능한 값 {list(allowed)}")

    def _exit(self, decl: Exit, outputs: Pins) -> ExitSpec:
        if not isinstance(decl, Exit):
            self.fail(f"출구는 Exit(...)로 선언한다: {decl!r}")
        if not _NAME.match(decl.name):
            self.fail(f"출구 이름 '{decl.name}'은(는) 소문자·숫자·밑줄만 쓴다")
        if decl.kind not in ("ok", "fail"):
            self.fail(f"출구 '{decl.name}': kind는 'ok' 또는 'fail'")
        names = self._exit_outputs(f"출구 '{decl.name}'", decl.kind, decl.outputs, outputs)
        return ExitSpec(decl.name, decl.kind, names)

    def _exit_outputs(
        self, what: str, kind: ExitKind, given: Sequence[str] | None, outputs: Pins
    ) -> tuple[str, ...]:
        if isinstance(outputs, FromInterface):
            if given is not None:
                self.fail(f"{what}: outputs=FromInterface 노드의 출구는 outputs를 정하지 않는다")
            return ()
        declared = [p.name for p in outputs]
        if given is None:
            names = tuple(declared) if kind == "ok" else ()
        else:
            if isinstance(given, str):
                self.fail(f"{what}: outputs는 이름 목록이다")
            if unknown := [n for n in given if n not in declared]:
                self.fail(f"{what}: 선언하지 않은 출력 {unknown}")
            if len(set(given)) != len(given):
                self.fail(f"{what}: outputs에 같은 이름이 두 번 있다")
            names = tuple(sorted(given))
        if kind == "fail" and "message" in names:
            self.fail(f"{what}: fail 출구는 'message' 출력을 줄 수 없다 (Result.fail의 사유 인자)")
        return names

    def _exits(self, outputs: Pins, config: tuple[PinSpec, ...], engine: str | None) -> Exits:
        if self.pure:
            if self.exits is not None:
                self.fail("순수 노드는 출구가 없다")
            return None
        if self.exits is None:
            self.fail("exec 노드는 exits를 선언한다 (순수 노드면 pure=True)")
        if isinstance(self.exits, FromInterface):
            self._check_interface(self.exits, ("exits",), "exits")
            return self.exits
        if isinstance(self.exits, DynamicExits):
            dyn = self.exits
            source = next((c for c in config if c.name == dyn.from_config), None)
            if source is None or source.type != "list[string]":
                self.fail(f"DynamicExits: config '{dyn.from_config}'(list[str])가 없다")
            if dyn.kind not in ("ok", "fail"):
                self.fail("DynamicExits: kind는 'ok' 또는 'fail'")
            extra = tuple(self._exit(e, outputs) for e in dyn.extra)
            self._unique_exits(extra)
            names = self._exit_outputs("DynamicExits", dyn.kind, dyn.outputs, outputs)
            return DynamicExitsSpec(dyn.from_config, dyn.kind, names, extra)
        if isinstance(self.exits, str | Exit):
            self.fail("exits는 Exit 목록이다")
        exits = tuple(self._exit(e, outputs) for e in self.exits)
        if not exits and engine is None:
            self.fail("출구가 없는 exec 노드(종료 노드)는 실행기가 처리하는 core 노드만 된다")
        self._unique_exits(exits)
        return exits

    def _unique_exits(self, exits: tuple[ExitSpec, ...]) -> None:
        names = [e.name for e in exits]
        if dup := sorted({n for n in names if names.count(n) > 1}):
            self.fail(f"출구 이름이 겹친다: {dup}")

    def _retry(self, exits: Exits, effects: frozenset[str]) -> Retry:
        retry = self.retry or Retry.never()
        if not isinstance(retry, Retry):
            self.fail("retry는 Retry.never() 또는 Retry.observation(on=[...])로 선언한다")
        if retry.mode == "never":
            if retry.on:
                self.fail("retry never에는 on을 쓰지 않는다")
            return retry
        if retry.mode != "observation":
            self.fail(f"모르는 retry mode {retry.mode!r}")
        if self.pure:
            self.fail("순수 노드는 재시도를 선언할 수 없다")
        if blocked := sorted(effects & {"input", "process"}):
            self.fail(f"게임에 영향을 주는 노드(effects {blocked})는 관측 재시도를 선언할 수 없다")
        if not retry.on:
            self.fail("관측 재시도는 재시도할 fail 출구(on)를 하나 이상 정한다")
        if len(set(retry.on)) != len(retry.on):
            self.fail("retry on에 같은 출구가 두 번 있다")
        if isinstance(exits, tuple):
            fixed = exits
        elif isinstance(exits, DynamicExitsSpec):
            fixed = exits.extra
        else:
            self.fail("출구를 interface에서 만드는 노드는 재시도를 선언할 수 없다")
        fail_exits = {e.name for e in fixed if e.kind == "fail"}
        if wrong := [n for n in retry.on if n not in fail_exits]:
            self.fail(
                f"retry on {wrong}은(는) 선언한 fail 출구가 아니다 "
                f"(fail 출구: {sorted(fail_exits)})"
            )
        return retry

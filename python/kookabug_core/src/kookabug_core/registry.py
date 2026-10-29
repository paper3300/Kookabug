"""노드 레지스트리: 노드 타입 → 노드 스키마 선언 + 실행 함수.

선언은 플러그인의 노드 스키마 JSON(`kookabug.schema.json`, 팔레트가 읽는 것과 같은 파일)에서 읽고,
함수는 플러그인 모듈의 `@node`에서 모은다. 둘이 어긋나면(다시 build하지 않음) 등록을 거부한다.
"""

from __future__ import annotations

import copy
import importlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from kookabug_core.schema import check_shape
from kookabug_sdk import NodeFunction
from kookabug_sdk.schema import FORMAT, load_installed

__all__ = [
    "CORE_PACKAGE",
    "ConfigDecl",
    "DynamicExitsDecl",
    "ExitDecl",
    "InputDecl",
    "NodeDef",
    "OutputDecl",
    "Registry",
    "RegistryError",
    "default_registry",
]

CORE_PACKAGE: Final = "kookabug_nodes"

type InterfaceSource = Literal["inputs", "outputs", "exits"]


class RegistryError(Exception):
    """플러그인을 등록할 수 없다 (스키마 형식 오류, 스키마와 함수 불일치, 타입 중복)."""


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final[Any] = _Missing()


@dataclass(frozen=True, slots=True)
class InputDecl:
    """입력 핀 (config 항목도 같은 모양). `default`가 `MISSING`이고 `optional`이 아니면 필수."""

    name: str
    type: str
    nullable: bool = False
    default: Any = MISSING
    optional: bool = False
    enum: tuple[Any, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = None

    @property
    def required(self) -> bool:
        return self.default is MISSING and not self.optional

    @classmethod
    def from_json(cls, name: str, data: Mapping[str, Any]) -> InputDecl:
        enum = data.get("enum")
        return cls(
            name=name,
            type=data["type"],
            nullable=bool(data.get("nullable", False)),
            default=data.get("default", MISSING),
            optional=bool(data.get("optional", False)),
            enum=tuple(enum) if enum is not None else None,
            minimum=data.get("minimum"),
            maximum=data.get("maximum"),
            min_items=data.get("min_items"),
        )


ConfigDecl = InputDecl


@dataclass(frozen=True, slots=True)
class OutputDecl:
    name: str
    type: str
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class ExitDecl:
    name: str
    kind: Literal["ok", "fail"]
    outputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DynamicExitsDecl:
    """config 값(문자열 배열)으로 만드는 출구. `extra`는 고정 출구."""

    from_config: str
    kind: Literal["ok", "fail"]
    outputs: tuple[str, ...]
    extra: tuple[ExitDecl, ...]


@dataclass(frozen=True)
class NodeDef:
    """노드 타입 하나의 선언(노드 스키마 JSON 기준)과 실행 함수.

    `function`이 None이면 원격 노드다: 워커가 hello로 알려 준 선언만 있고, 실행은 워커에서 한다
    (runner는 플러그인 코드를 import하지 않는다).
    """

    type: str
    version: int
    plugin: str
    decl: Mapping[str, Any]
    function: NodeFunction | None
    inputs: tuple[InputDecl, ...] | InterfaceSource
    outputs: tuple[OutputDecl, ...] | InterfaceSource
    exits: tuple[ExitDecl, ...] | DynamicExitsDecl | InterfaceSource | None
    config: tuple[ConfigDecl, ...]

    @property
    def pure(self) -> bool:
        return bool(self.decl.get("pure", False))

    @property
    def engine(self) -> str | None:
        return self.decl.get("engine")

    @property
    def assertion(self) -> bool:
        return bool(self.decl.get("assertion", False))

    @property
    def effects(self) -> frozenset[str]:
        return frozenset(self.decl.get("effects", ()))

    @property
    def retry_mode(self) -> Literal["never", "observation"]:
        retry = self.decl.get("retry")
        return retry["mode"] if isinstance(retry, Mapping) else "never"

    @property
    def retry_on(self) -> tuple[str, ...]:
        retry = self.decl.get("retry")
        return tuple(retry.get("on", ())) if isinstance(retry, Mapping) else ()

    def effective_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """그래프 노드의 `config`에 선언 기본값을 채운 것 (복사본).

        검증(동적 출구 이름)과 실행 ctx(`ctx.config`)가 같이 쓴다. 적힌 값이 기본값보다 앞선다.
        """
        merged = {c.name: copy.deepcopy(c.default) for c in self.config if c.default is not MISSING}
        merged.update(copy.deepcopy(dict(config)))
        return merged

    @property
    def remote(self) -> bool:
        return self.function is None

    @classmethod
    def from_json(
        cls, plugin: str, decl: Mapping[str, Any], function: NodeFunction | None
    ) -> NodeDef:
        return cls(
            type=decl["type"],
            version=decl["version"],
            plugin=plugin,
            decl=decl,
            function=function,
            inputs=_inputs(decl.get("inputs", {})),
            outputs=_outputs(decl.get("outputs", {})),
            exits=_exits(decl.get("exits")),
            config=tuple(
                InputDecl.from_json(k, v) for k, v in sorted(decl.get("config", {}).items())
            ),
        )


def _source(value: Any) -> InterfaceSource | None:
    if isinstance(value, Mapping) and "from_interface" in value:
        return value["from_interface"]
    return None


def _inputs(value: Any) -> tuple[InputDecl, ...] | InterfaceSource:
    if (source := _source(value)) is not None:
        return source
    return tuple(InputDecl.from_json(k, v) for k, v in sorted(value.items()))


def _outputs(value: Any) -> tuple[OutputDecl, ...] | InterfaceSource:
    if (source := _source(value)) is not None:
        return source
    return tuple(
        OutputDecl(k, v["type"], bool(v.get("nullable", False))) for k, v in sorted(value.items())
    )


def _exit(value: Mapping[str, Any]) -> ExitDecl:
    return ExitDecl(value["name"], value["kind"], tuple(value["outputs"]))


def _exits(value: Any) -> tuple[ExitDecl, ...] | DynamicExitsDecl | InterfaceSource | None:
    if value is None:
        return None
    if isinstance(value, list):
        return tuple(_exit(e) for e in value)
    if (source := _source(value)) is not None:
        return source
    return DynamicExitsDecl(
        value["from_config"],
        value["kind"],
        tuple(value["outputs"]),
        tuple(_exit(e) for e in value.get("extra", ())),
    )


class Registry:
    def __init__(self) -> None:
        self._nodes: dict[str, NodeDef] = {}
        self._plugins: dict[str, str] = {}

    def __contains__(self, node_type: object) -> bool:
        return node_type in self._nodes

    def get(self, node_type: str) -> NodeDef | None:
        return self._nodes.get(node_type)

    def types(self) -> frozenset[str]:
        return frozenset(self._nodes)

    @property
    def plugins(self) -> Mapping[str, str]:
        """플러그인 ID → 버전."""
        return dict(self._plugins)

    def _check_document(self, schema: Mapping[str, Any]) -> str:
        problems = check_shape(schema, "node-schema")
        if problems:
            raise RegistryError(
                "노드 스키마 형식 오류: " + "; ".join(f"{d.pointer} {d.message}" for d in problems)
            )
        plugin = schema["plugin"]["id"]
        if plugin in self._plugins:
            raise RegistryError(f"플러그인 '{plugin}'이(가) 이미 등록돼 있다")
        return plugin

    def _check_type(self, plugin: str, node_type: str, defs: Mapping[str, NodeDef]) -> None:
        if node_type.split(".", 1)[0] != plugin:
            raise RegistryError(f"{node_type}: 플러그인 '{plugin}'의 노드 타입이 아니다")
        if node_type in defs or node_type in self._nodes:
            raise RegistryError(f"{node_type}: 같은 노드 타입이 이미 있다")

    def add_remote(self, schema: Mapping[str, Any]) -> None:
        """워커가 hello로 알려 준 플러그인을 원격 노드(`function` 없음)로 등록한다.

        engine 노드는 실행기가 직접 처리하는 core 전용이라 원격 플러그인에는 둘 수 없다.
        """
        plugin = self._check_document(schema)
        defs: dict[str, NodeDef] = {}
        for decl in schema["nodes"]:
            node_type = decl["type"]
            self._check_type(plugin, node_type, defs)
            if "engine" in decl:
                raise RegistryError(f"{node_type}: 원격 노드는 engine을 쓸 수 없다")
            defs[node_type] = NodeDef.from_json(plugin, copy.deepcopy(decl), None)
        self._nodes.update(defs)
        self._plugins[plugin] = schema["plugin"]["version"]

    def add_plugin(self, schema: Mapping[str, Any], functions: Iterable[NodeFunction]) -> None:
        """노드 스키마 문서와 그 플러그인의 `@node` 함수들을 등록한다."""
        plugin = self._check_document(schema)
        by_type: dict[str, NodeFunction] = {}
        for fn in functions:
            if by_type.get(fn.spec.type) is fn:
                continue  # 다른 모듈에서 import해 온 같은 노드
            if fn.spec.type in by_type:
                raise RegistryError(f"{fn.spec.type}: 같은 타입의 함수가 둘 있다")
            by_type[fn.spec.type] = fn

        defs: dict[str, NodeDef] = {}
        for decl in schema["nodes"]:
            node_type = decl["type"]
            self._check_type(plugin, node_type, defs)
            fn = by_type.pop(node_type, None)
            if fn is None:
                raise RegistryError(f"{node_type}: 스키마에 있는데 함수가 없다")
            if fn.schema() != decl:
                raise RegistryError(
                    f"{node_type}: 스키마와 함수 선언이 다르다 (kookabug-sdk build로 다시 만든다)"
                )
            defs[node_type] = NodeDef.from_json(plugin, decl, fn)
        if by_type:
            raise RegistryError(f"함수는 있는데 스키마에 없는 노드: {sorted(by_type)}")
        self._nodes.update(defs)
        self._plugins[plugin] = schema["plugin"]["version"]

    def add_functions(self, plugin: str, version: str, functions: Sequence[NodeFunction]) -> None:
        """빌드한 스키마 파일 없이 함수에서 바로 등록한다 (테스트 전용 플러그인용)."""
        schema = {
            "format": FORMAT,
            "nodes": [f.schema() for f in sorted(functions, key=lambda f: f.spec.type)],
            "plugin": {"id": plugin, "version": version},
        }
        self.add_plugin(schema, functions)

    def add_installed(self, package: str, modules: Iterable[str]) -> None:
        """설치된 패키지의 노드 스키마(`load_installed`)와 `modules`의 `@node` 함수를 등록한다."""
        functions = [
            value
            for name in modules
            for value in vars(importlib.import_module(name)).values()
            if isinstance(value, NodeFunction)
        ]
        self.add_plugin(load_installed(package), functions)


def default_registry() -> Registry:
    """설치된 `kookabug_nodes`(코어 플러그인 `core`)만 든 레지스트리."""
    import kookabug_nodes

    registry = Registry()
    registry.add_installed(CORE_PACKAGE, kookabug_nodes.MODULES)
    return registry

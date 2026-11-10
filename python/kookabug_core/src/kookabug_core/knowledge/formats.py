"""지식 형식 (M8 계획 3.1·3.2): ID 규칙, 파일 이름, 빈 문서, 형식 검사, 글자 검사, 치트 digest.

스키마 원본은 `packages/schema/knowledge/*.schema.json`(형식 검사는 `check_shape`). 여기는 스키마로
표현하지 않는 규칙(ID 접두, 템플릿 자리, 근거 형식 이름)과 공용 오류만 둔다.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets as random
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final, Literal, cast

from kookabug_core.canonical import canonical_dumps
from kookabug_core.schema import check_shape
from kookabug_core.schema.shape import metaschema
from kookabug_core.workspace import SecretProvider

__all__ = [
    "BASIS_TYPES",
    "CLAIM_ID",
    "FEATURE_ID",
    "FILE_FORMATS",
    "OPS_CURSOR",
    "Actor",
    "Cursor",
    "KnowledgeError",
    "SecretCheck",
    "cheat_digest",
    "check_cheat",
    "child_item",
    "child_key",
    "empty_doc",
    "file_kind",
    "file_rel",
    "key_label",
    "mask_pointer",
    "new_id",
    "now",
    "opaque",
    "schema_cursor",
    "secret_checker",
    "shape_problem",
    "strings_of",
]

FEATURE_ID: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CLAIM_ID: Final = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
GENERATED_ID: Final = re.compile(r"^(?P<p>[a-z])-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
ID_PREFIXES: Final = {
    "c": "사건",
    "e": "증거",
    "w": "변경",
    "a": "채택",
    "j": "작업",
    "u": "미지수",
}

BASIS_TYPES: Final = ("source", "evidence", "run", "human")
"""근거 형식. 위키·주장 근거 형식은 없다(자기 인용 차단, 3.2)."""

KNOWLEDGE_DIR: Final = "knowledge"
WIKI_DIR: Final = "wiki"
LOG_FILE: Final = "knowledge/log.jsonl"
WORKING_CLAIMS_DIR: Final = "knowledge/working/claims"
LAYOUT: Final = (
    "knowledge/features",
    "knowledge/cases",
    "knowledge/evidence",
    "knowledge/working",
    "knowledge/adoptions",
    "knowledge/reports",
    "wiki",
)

Kind = Literal["claims", "lessons", "cheats", "unknowns"]
FILE_FORMATS: Final[dict[Kind, str]] = {
    "claims": "kookabug.claims/0",
    "lessons": "kookabug.lessons/0",
    "cheats": "kookabug.cheats/0",
    "unknowns": "kookabug.unknowns/0",
}
ITEMS_KEY: Final[dict[Kind, str]] = {
    "claims": "claims",
    "lessons": "lessons",
    "cheats": "cheats",
    "unknowns": "unknowns",
}


class KnowledgeError(Exception):
    """지식 연산을 거부했다 (아무것도 쓰지 않았다). `code`는 daemon 오류 코드와 같다.

    메시지·필드에는 요청 글자 값을 넣지 않는다 (비밀값이 섞였을 수 있다)."""

    def __init__(self, code: str, message: str, **fields: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.fields}


@dataclass(frozen=True, slots=True)
class Actor:
    """연산 주체 (감사 이력 `agent`). Agent 연결은 `kind="agent"`, 사람은 `human`."""

    kind: Literal["agent", "human", "kookabug"]
    id: str | None = None
    client: str | None = None
    model: str | None = None
    job: str | None = None

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"

    def to_log(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "client": self.client, "model": self.model}

    def texts(self) -> list[tuple[str, str]]:
        """기록·응답에 들어가는 주체 글자 (글자 검사 대상, 위치는 고정 이름)."""
        fields = (("actor/id", self.id), ("actor/client", self.client))
        fields += (("actor/model", self.model), ("actor/job", self.job))
        return [(name, value) for name, value in fields if value]

    def opaque(self) -> Actor:
        """글자 검사에 걸린 주체를 기록할 때: 글자 필드를 값과 무관한 임의 식별자로."""
        return replace(
            self,
            id=opaque(self.id),
            client=opaque(self.client),
            model=opaque(self.model),
            job=opaque(self.job),
        )


def opaque(value: str | None) -> str | None:
    """원문 대신 남기는 식별자: **값과 무관한 임의 값**(uuid4). 해시를 쓰지 않는다 — 짧은 비밀값은
    후보 대입으로 해시에서 되찾을 수 있다."""
    if value is None:
        return None
    return f"x-{uuid.uuid4().hex[:16]}"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str, when: datetime | None = None) -> str:
    """`<접두>-<UTC yyyymmdd-HHMMSS>-<4hex>` (3.1)."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"모르는 ID 접두 {prefix!r}")
    stamp = (when or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{random.token_hex(2)}"


def file_kind(file: object) -> tuple[Kind, str | None] | None:
    """연산의 `file` 값 → (종류, 기능). 쓸 수 없는 값이면 None (경로 차단 — `policy_path`)."""
    if not isinstance(file, str):
        return None
    if file in ("lessons", "cheats", "unknowns"):
        return file, None  # type: ignore[return-value]
    head, sep, feature = file.partition("/")
    if head == "features" and sep and FEATURE_ID.fullmatch(feature):
        return "claims", feature
    return None


def file_rel(file: str) -> str:
    """연산 `file` 값 → 워크스페이스 기준 경로 (`file_kind`를 통과한 값만)."""
    return f"{KNOWLEDGE_DIR}/{file}.json"


def empty_doc(kind: Kind, feature: str | None = None) -> dict[str, Any]:
    doc: dict[str, Any] = {"format": FILE_FORMATS[kind], "revision": 0, ITEMS_KEY[kind]: []}
    if kind == "claims":
        doc["feature"] = feature
    return doc


def shape_problem(data: Any, kind: str, *, ref: str | None = None) -> str | None:
    """형식 검사 첫 문제의 위치와 코드 (값은 넣지 않는다 — 요청자가 정한 키도 스키마 위치 기준으로
    가린다). 문제없으면 None."""
    diags = check_shape(data, kind, ref=ref)  # type: ignore[arg-type]
    if not diags:
        return None
    d = diags[0]
    return f"{mask_pointer(data, d.pointer or '', schema_cursor(kind, ref)) or '/'}: {d.code}"


# ---------------------------------------------------------------- 오류 위치 가리기
#
# 오류 위치(글자 검사 field·형식 검사 pointer)에는 **그 스키마 위치에서** 이름이 정해진
# 필드(`properties`)와 배열 번호만 그대로 쓴다. 자유 JSON(`Claim.value` 등)·이름이 자유로운
# 객체(치트 `args` 등) 안의 키는 이름과 관계없이 `<key#n>`(그 객체 안 n번째 키) — 다른 형식의 필드
# 이름과 같아도 가린다.

#
# 분기(`oneOf`·`anyOf`·`allOf`)는 펼쳐 **후보 잎**(같은 자리에 올 수 있는 객체 모양 하나) 목록으로
# 다룬다. 값으로 고를 수 있으면(판별자 `const`·`type`) 맞지 않는 잎을 빼고, 남은 잎 **모두**의
# `properties`에 있는 키만 고정 이름이다. 하나라도 그 키를 정하지 않으면(자유 JSON·
# `additionalProperties`) 그 키와 그 아래는 전부 가린다.


@dataclass(frozen=True, slots=True)
class _Leaf:
    props: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]]
    items: Any  # (노드, 문서) | _OP_ITEMS | None
    types: frozenset[str] | None
    consts: Mapping[str, Any]


Cursor = tuple[_Leaf, ...] | None
"""같은 자리에 올 수 있는 후보 잎들. None = 모르는 위치(그 아래 키는 전부 가림)."""

_MAX_LEAVES: Final = 64
_URN: Final = re.compile(r"^urn:kookabug:([a-z-]+):0$")
_ITEM_REFS: Final[dict[str, str]] = {
    "claims": "urn:kookabug:claims:0#/$defs/Claim",
    "lessons": "urn:kookabug:lessons:0#/$defs/Lesson",
    "cheats": "urn:kookabug:cheats:0#/$defs/Cheat",
    "unknowns": "urn:kookabug:unknowns:0#/$defs/Unknown",
}
_OP_ITEMS: Final[Mapping[str, Any]] = {"x-kb-op": True}
"""연산 배열 항목 표시: 항목마다 `file`로 `item`·`changes`의 스키마를 고른다."""
_NO_DOC: Final[Mapping[str, Any]] = {}


def _fragment(doc: Mapping[str, Any], fragment: str) -> Mapping[str, Any] | None:
    node: Any = doc
    for raw in fragment.lstrip("/").split("/") if fragment.strip("/") else []:
        seg = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping):
            return None
        node = cast(Mapping[str, Any], node).get(seg)
    return cast(Mapping[str, Any], node) if isinstance(node, Mapping) else None


def _deref(
    node: Mapping[str, Any], doc: Mapping[str, Any]
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node, doc
    base, _, fragment = ref.partition("#")
    if base:
        match = _URN.fullmatch(base)
        if match is None:
            return None
        try:
            doc = metaschema(match.group(1))  # type: ignore[arg-type]
        except Exception:
            return None
    target = _fragment(doc, fragment)
    return None if target is None else (target, doc)


def _own_leaf(node: Mapping[str, Any], doc: Mapping[str, Any]) -> _Leaf:
    props: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    consts: dict[str, Any] = {}
    raw = node.get("properties")
    if isinstance(raw, Mapping):
        for key, sub in cast(Mapping[str, Any], raw).items():
            sub_node = cast(Mapping[str, Any], sub) if isinstance(sub, Mapping) else {}
            props[key] = (sub_node, doc)
            if "const" in sub_node:
                consts[key] = sub_node["const"]
    items = node.get("items")
    if items is not _OP_ITEMS:
        items = (cast(Mapping[str, Any], items), doc) if isinstance(items, Mapping) else None
    kind = node.get("type")
    types = (
        frozenset([kind])
        if isinstance(kind, str)
        else frozenset(cast(list[str], kind))
        if isinstance(kind, list)
        else None
    )
    return _Leaf(props, items, types, consts)


def _merge(a: _Leaf, b: _Leaf) -> _Leaf:
    """두 잎이 함께 적용될 때 (부모의 공통 속성 + 분기 하나)."""
    types = a.types if b.types is None else b.types if a.types is None else a.types & b.types
    return _Leaf(
        {**b.props, **a.props},
        a.items if a.items is not None else b.items,
        types,
        {**b.consts, **a.consts},
    )


def _expand(node: Mapping[str, Any], doc: Mapping[str, Any], depth: int = 0) -> list[_Leaf] | None:
    """노드 → 후보 잎들 (`$ref` 따라감, 분기는 부모 속성과 합친 잎마다). 모르면 None."""
    if depth > 16:
        return None
    if "$ref" in node:
        target = _deref(node, doc)
        return None if target is None else _expand(target[0], target[1], depth + 1)
    leaves = [_own_leaf(node, doc)]
    for key in ("allOf", "oneOf", "anyOf"):
        subs = node.get(key)
        if not isinstance(subs, list):
            continue
        groups: list[list[_Leaf]] = []
        for sub in cast(list[Any], subs):
            if not isinstance(sub, Mapping):
                return None
            found = _expand(cast(Mapping[str, Any], sub), doc, depth + 1)
            if found is None:
                return None
            groups.append(found)
        if key == "allOf":  # 모두 함께 적용
            for group in groups:
                leaves = [_merge(a, b) for a in leaves for b in group]
        else:  # 하나(또는 여럿) — 후보로 늘린다
            leaves = [_merge(a, b) for a in leaves for group in groups for b in group]
        if len(leaves) > _MAX_LEAVES:
            return None
    return leaves


def _cursor(node: Mapping[str, Any], doc: Mapping[str, Any]) -> Cursor:
    found = _expand(node, doc)
    return None if found is None else tuple(found)


def _fits(leaf: _Leaf, value: Any, kind: str) -> bool:
    """값으로 고를 수 있는가: `type`이 이 모양을 받고, 판별자 `const`가 값과 어긋나지 않는다."""
    if leaf.types is not None and kind not in leaf.types:
        return False
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, Any], value)
        for key, const in leaf.consts.items():
            if key in mapping and mapping[key] != const:
                return False
    return True


def _op_cursor(op: Any) -> Cursor:
    """연산 하나의 위치. `item`·`changes`는 `file` 종류의 항목 스키마(모르는 종류면 전부 가림)."""
    parsed = file_kind(op.get("file")) if isinstance(op, Mapping) else None
    item: Mapping[str, Any] = {"$ref": _ITEM_REFS[parsed[0]]} if parsed else {}
    claim_ref = {"$ref": "urn:kookabug:claims:0#/$defs/ClaimRef"}
    node = {
        "properties": {
            **{k: {} for k in ("op", "file", "base_revision", "base_rev", "id", "status")},
            "item": item,
            "changes": item,
            "by": claim_ref,
            "with": {"items": claim_ref},
            "basis": {"$ref": "urn:kookabug:claims:0#/$defs/Basis"},
        }
    }
    return _cursor(node, _NO_DOC)


OPS_CURSOR: Final[Cursor] = _cursor({"items": _OP_ITEMS}, _NO_DOC)
"""`ops` 배열 위치."""


def schema_cursor(kind: str, ref: str | None = None) -> Cursor:
    """형식 검사 대상(`check_shape(kind, ref)`)의 맨 위 위치."""
    if kind == "knowledge-ops" and ref is None:
        return _cursor({"properties": {"request_id": {}, "ops": {"items": _OP_ITEMS}}}, _NO_DOC)
    try:
        doc = metaschema(kind)  # type: ignore[arg-type]
    except Exception:
        return None
    if ref is None:
        return _cursor(doc, doc)
    node = _fragment(doc, ref.partition("#")[2])
    return None if node is None else _cursor(node, doc)


def child_key(cursor: Cursor, key: str, parent: Any = None) -> tuple[Cursor, bool]:
    """객체 `parent`의 키 한 칸 아래: (아래 위치, 이 위치에서 이름이 정해진 키인가). 값으로 고른
    뒤 남은 후보 **모두**가 이 키를 `properties`로 정할 때만 고정 이름이고, 아니면 그 아래까지
    가린다(None)."""
    if not cursor:
        return None, False
    leaves = [leaf for leaf in cursor if _fits(leaf, parent, "object")]
    if not leaves or any(key not in leaf.props for leaf in leaves):
        return None, False
    out: list[_Leaf] = []
    for leaf in leaves:
        found = _expand(*leaf.props[key])
        if found is None:
            return None, True
        out += found
    return (tuple(out) if len(out) <= _MAX_LEAVES else None), True


def child_item(cursor: Cursor, value: Any) -> Cursor:
    """배열 한 칸 아래 (`value` = 그 항목 — 연산 배열이면 항목의 `file`로 고른다). 남은 후보가
    모두 `items`를 정할 때만 이어 가고, 아니면 None(그 아래 전부 가림)."""
    if not cursor:
        return None
    leaves = [leaf for leaf in cursor if leaf.types is None or "array" in leaf.types]
    if not leaves:
        return None
    out: list[_Leaf] = []
    for leaf in leaves:
        if leaf.items is None:
            return None
        if leaf.items is _OP_ITEMS:
            found = _op_cursor(value)
            found = None if found is None else list(found)
        else:
            found = _expand(*cast(tuple[Mapping[str, Any], Mapping[str, Any]], leaf.items))
        if found is None:
            return None
        out += found
    return tuple(out) if len(out) <= _MAX_LEAVES else None


def key_label(fixed: bool, key: object, index: int) -> str:
    return str(key) if fixed else f"<key#{index}>"


def mask_pointer(data: Any, pointer: str, cursor: Cursor = None) -> str:
    """JSON pointer의 객체 키 조각을 스키마 위치 기준으로 가린다 (값을 따라가며 키 번호를
    찾는다)."""
    if not pointer:
        return ""
    out: list[str] = []
    current: Any = data
    for raw in pointer.lstrip("/").split("/"):
        seg = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list) and seg.isdigit():
            out.append(seg)
            items = cast(list[Any], current)
            current = items[int(seg)] if int(seg) < len(items) else None
            cursor = child_item(cursor, current)
            continue
        keys = list(cast(dict[str, Any], current)) if isinstance(current, dict) else []
        index = keys.index(seg) if seg in keys else len(keys)
        cursor, fixed = child_key(cursor, seg, current)
        out.append(key_label(fixed, seg, index))
        current = cast(dict[str, Any], current).get(seg) if isinstance(current, dict) else None
    return "/" + "/".join(out)


# ---------------------------------------------------------------- 글자 검사

SecretCheck = Callable[[Sequence[tuple[str, str]]], None]
"""(필드 이름, 글자) 목록을 검사해 비밀값이 있으면 `KnowledgeError`(`secret_in_text`·
`secret_unchecked`)를 낸다. daemon은 보호 기록의 비밀값 키로 만든 검사기를 넘긴다 (M7 3.5b)."""


def normalize(text: str) -> str:
    """비밀값 비교용 (daemon `explore.normalize`와 같은 규칙): NFKC, 서식 문자·공백 제거, 대소문자
    무시."""
    folded = unicodedata.normalize("NFKC", text)
    plain = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return "".join(plain.split()).casefold()


def secret_checker(
    keys: Iterable[str],
    provider: SecretProvider,
    *,
    blocked: bool = False,
    extra: Callable[[], Iterable[str]] | None = None,
) -> SecretCheck:
    """M7 글자 검사와 같은 규칙의 검사기. 키 값을 하나라도 못 읽거나 `blocked`(보호 기록 손상)면
    `secret_unchecked`(fail closed). 값은 검사 동안만 메모리에 둔다.

    `extra`: 검사할 때마다 부르는 메모리 원문 공급 (M8 R9 — daemon의 살아 있는 작업 토큰 원문)."""
    names = sorted(set(keys))

    def check(texts: Sequence[tuple[str, str]]) -> None:
        pairs = [(name, text) for name, text in texts if text]
        if blocked:
            raise KnowledgeError(
                "secret_unchecked", "보호 기록이 손상돼 비밀값 검사를 할 수 없어 저장하지 않았다"
            )
        if not pairs:
            return
        values: list[str] = [v for v in (normalize(x) for x in (extra() if extra else ())) if v]
        if not names and not values:
            return
        try:
            for key in names:
                try:
                    value = provider.get(key)
                except Exception:
                    value = None
                if value is None:
                    raise KnowledgeError(
                        "secret_unchecked",
                        f"비밀값 '{key}'을(를) 읽지 못해 글자 검사를 할 수 없어 저장하지 않았다",
                        reason=key,
                    )
                found = normalize(value)
                if found:
                    values.append(found)
            for name, text in pairs:
                plain = normalize(text)
                if any(v in plain for v in values):
                    raise KnowledgeError(
                        "secret_in_text",
                        f"'{name}'에 비밀값이 들어 있어 저장하지 않았다",
                        field=name,
                    )
        finally:
            values.clear()

    return check


def strings_of(value: Any, where: str, cursor: Cursor = None) -> Iterator[tuple[str, str]]:
    """값 안의 모든 글자(키 포함)와 스칼라(숫자·불리언 — 저장·렌더 때 글자가 되므로 JSON 표현으로)를
    (위치, 글자)로. 위치의 키는 `cursor`(스키마 위치) 기준으로 이름이 정해진 것만 그대로, 나머지는
    `<key#n>`(오류에 돌려줘도 비밀값이 없게). `cursor`가 None이면 키를 전부 가린다."""
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, bool | int | float):
        # 저장·digest(`canonical_dumps`)와 렌더(`json.dumps`) 표현 둘 다 본다 (예: 1e-06 / 0.000001)
        yield where, json.dumps(value)
        try:
            stored: str | None = canonical_dumps(value).strip()
        except TypeError, ValueError:
            stored = None  # 저장할 수 없는 수 — 요청 digest 계산에서 원문 없는 형식 거부가 된다
        if stored is not None:
            yield where, stored
    elif isinstance(value, Mapping):
        for i, (k, v) in enumerate(cast(Mapping[Any, Any], value).items()):
            sub, fixed = child_key(cursor, str(k), value)
            at = f"{where}/{key_label(fixed, k, i)}"
            yield at, str(k)
            yield from strings_of(v, at, sub)
    elif isinstance(value, list | tuple):
        for i, v in enumerate(cast(list[Any], value)):
            yield from strings_of(v, f"{where}/{i}", child_item(cursor, v))


# ---------------------------------------------------------------- 치트

_PLACEHOLDER: Final = re.compile(r"\{([a-z][a-z0-9_]{0,31})\}")
_FORBIDDEN_TEMPLATE: Final = re.compile(r"[\r\n\x00]")


def check_cheat(cheat: Mapping[str, Any]) -> str | None:
    """스키마 밖 치트 규칙 (3.2). 문제 설명(값 없음) 또는 None.

    - 템플릿 자리 `{이름}`은 정의된 인자만, 자리 밖 `{`·`}`·줄바꿈 없음 (자리 밖 글자는 고정)
    - integer 인자는 min ≤ max
    - `impl.graph`는 워크스페이스 안 상대 경로 (`..`·드라이브 없음)
    """
    args = cheat.get("args") or {}
    for i, (name, spec) in enumerate(args.items()):
        if spec.get("type") == "integer" and spec.get("min", 0) > spec.get("max", 0):
            return f"args/{key_label(False, name, i)}: min이 max보다 크다"  # 인자 이름은 자유
    impl = cheat.get("impl") or {}
    if impl.get("kind") == "console":
        template = str(impl.get("template", ""))
        if _FORBIDDEN_TEMPLATE.search(template):
            return "impl/template: 줄바꿈을 쓸 수 없다"
        rest = _PLACEHOLDER.sub("", template)
        if "{" in rest or "}" in rest:
            return "impl/template: 자리는 {인자 이름} 꼴만 쓴다"
        unknown = sorted({m for m in _PLACEHOLDER.findall(template) if m not in args})
        if unknown:
            return "impl/template: 정의되지 않은 인자 자리가 있다"
        graph = str(impl.get("graph", ""))
        parts = graph.split("/")
        if graph.startswith("/") or any(p in ("", ".", "..") for p in parts):
            return "impl/graph: 워크스페이스 안 상대 경로가 아니다"
    return None


def cheat_digest(
    cheat: Mapping[str, Any], *, closure: str | None, nodes: Mapping[str, str] | None
) -> str:
    """치트 채택 digest (3.2 + 계획 9장 R2): 정의 필드(`id`·`rev`·`impl`·`args`·`env`·`effect`) +
    `impl.graph`의 전이 참조 폐포 바이트 digest(`closure`, `knowledge.cheats.graph_closure`) + 쓰인
    노드 구현 revision(`nodes`: 노드 타입 → revision — B2가 채운다). 무엇이 바뀌어도 채택이 무효가
    된다."""
    body = {
        "args": cheat.get("args") or {},
        "closure": closure,
        "effect": cheat.get("effect"),
        "env": cheat.get("env") or {},
        "id": cheat.get("id"),
        "impl": cheat.get("impl"),
        "nodes": dict(sorted((nodes or {}).items())),
        "rev": cheat.get("rev"),
    }
    return hashlib.sha256(canonical_dumps(body).encode("utf-8")).hexdigest()

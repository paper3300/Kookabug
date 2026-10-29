"""설계 문서의 ```json 예시 형식 검사.

모든 블록은 아래 `HANDLING` 표에 정확히 한 번 나와야 한다. 문서에 블록이 늘거나 순서가 바뀌면
표를 고칠 때까지 실패한다 (검사 없이 지나가는 예시를 막는다).
"""

from dataclasses import dataclass
from typing import Any

import pytest

from kb_testing.doc_examples import DocBlock, json_blocks
from kookabug_core.schema import check_shape
from kookabug_core.schema.shape import SchemaKind


@dataclass(frozen=True)
class Whole:
    kind: SchemaKind


@dataclass(frozen=True)
class Fragment:
    # (블록 안 경로, 메타스키마 종류, $defs 참조)
    parts: tuple[tuple[tuple[str, ...], SchemaKind, str], ...]


@dataclass(frozen=True)
class Unvalidated:
    reason: str


# 블록 id → (최상위 키, 처리)
HANDLING: dict[str, tuple[list[str], Whole | Fragment | Unvalidated]] = {
    "schema#0": (
        ["format", "interface", "kind", "layout", "meta", "nodes", "plugins"],
        Whole("graph"),
    ),
    "schema#1": (["format", "kind", "layout", "meta", "nodes", "plugins"], Whole("graph")),
    "schema#2": (["click", "format", "image", "match", "recorded", "search"], Whole("target")),
    "schema#3": (
        ["config"],
        Fragment(
            (
                (("config",), "graph", "#/$defs/NodeConfig"),
                (("config", "retry"), "graph", "#/$defs/RetryConfig"),
            )
        ),
    ),
    "schema#4": (
        ["retry", "type"],
        Fragment(
            (
                (("retry",), "node-schema", "#/$defs/RetryDecl"),
                (("type",), "node-schema", "#/$defs/NodeType"),
            )
        ),
    ),
    "schema#5": (
        ["debug_intervened", "pause_count", "paused_ms"],
        Unvalidated("run.json 디버그 개입 조각. events·run 메타스키마는 M0b에서 만든다 (G18)"),
    ),
    "schema#6": (["record"], Fragment(((("record",), "graph", "#/$defs/RecordPolicy"),))),
    "workspace#0": (["format", "profiles", "record", "retention", "settings"], Whole("workspace")),
}

BLOCKS = json_blocks()


def _ids(blocks: list[DocBlock]) -> list[str]:
    return [b.id for b in blocks]


def _dig(data: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        data = data[key]
    return data


@pytest.mark.parametrize("block", BLOCKS, ids=_ids(BLOCKS))
def test_doc_json_blocks_parse(block: DocBlock) -> None:
    assert isinstance(block.data, dict)


def _unsorted_objects(value: Any, at: str = "") -> list[str]:
    found = []
    if isinstance(value, dict):
        if list(value) != sorted(value):
            found.append(at or "/")
        for k, v in value.items():
            found += _unsorted_objects(v, f"{at}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += _unsorted_objects(v, f"{at}/{i}")
    return found


@pytest.mark.parametrize("block", BLOCKS, ids=_ids(BLOCKS))
def test_doc_json_blocks_keys_sorted(block: DocBlock) -> None:
    assert _unsorted_objects(block.data) == []


def test_doc_unvalidated_blocks_are_listed() -> None:
    assert sorted(_ids(BLOCKS)) == sorted(HANDLING), "문서 예시 블록과 HANDLING 표가 다르다"
    for block in BLOCKS:
        keys, handling = HANDLING[block.id]
        assert sorted(block.data) == keys, f"{block.id}(줄 {block.line})이 다른 블록으로 바뀌었다"
        if isinstance(handling, Unvalidated):
            assert handling.reason
        if isinstance(handling, Whole):
            assert block.data["format"].startswith("kookabug.")
    unvalidated = [i for i, (_, h) in HANDLING.items() if isinstance(h, Unvalidated)]
    assert unvalidated == ["schema#5"]


WHOLE = [b for b in BLOCKS if isinstance(HANDLING.get(b.id, (None, None))[1], Whole)]


@pytest.mark.parametrize("block", WHOLE, ids=_ids(WHOLE))
def test_doc_blocks_with_format_validate(block: DocBlock) -> None:
    handling = HANDLING[block.id][1]
    assert isinstance(handling, Whole)
    assert check_shape(block.data, file=block.id) == []
    assert check_shape(block.data, handling.kind) == []


def test_doc_blocks_with_format_counts() -> None:
    kinds = [h.kind for _, h in HANDLING.values() if isinstance(h, Whole)]
    assert sorted(kinds) == ["graph", "graph", "target", "workspace"]


def test_doc_fragments_validate_against_defs() -> None:
    checked = []
    for block in BLOCKS:
        handling = HANDLING[block.id][1]
        if not isinstance(handling, Fragment):
            continue
        for path, kind, ref in handling.parts:
            assert check_shape(_dig(block.data, path), kind, ref=ref) == [], (block.id, ref)
            checked.append(ref)
    assert {"#/$defs/RetryConfig", "#/$defs/RetryDecl", "#/$defs/RecordPolicy"} <= set(checked)


def test_fragment_check_rejects_bad_values() -> None:
    # 부분 검사가 실제로 검사한다는 대조
    assert check_shape({"max_attempts": 0}, "graph", ref="#/$defs/RetryConfig")
    assert check_shape({"mode": "observation"}, "node-schema", ref="#/$defs/RetryDecl")
    assert check_shape({"video": "maybe"}, "graph", ref="#/$defs/RecordPolicy")

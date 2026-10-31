"""값 왕복 (M2 계획 2.6, 검수 H1).

Python 값 → JSON → **Node `JSON.parse` → `wireStringify`** → Python.

판정 ① `json_equal` ② M0b 봉투 값 검사(`kookabug_sdk.rpc` 값 디코드) ③ 형식 검사에 새 수 진단 없음
④ `save_text`가 원문을 돌려줌. 코덱은 `packages/schema/src/wire.ts`를 Node가 그대로 불러 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.corpus import CORPUS_DIR, corpus_files, corpus_id, through_js

from kookabug_core import documents
from kookabug_core.canonical import json_equal, loads_strict, save_text
from kookabug_core.documents import NUMBER_CODES, DocumentError
from kookabug_core.schema import check_shape
from kookabug_core.validate import check_graph
from kookabug_core.workspace import WORKSPACE_FILE, Workspace
from kookabug_sdk.rpc import _check_value, _decode  # pyright: ignore[reportPrivateUsage]

FILES = corpus_files()
BIG_FLOATS = ("1e20", "9007199254740992.0", "1.2345678901234567e19")


def number_diags(value: Any) -> set[tuple[str | None, str]]:
    return {(d.pointer, d.code) for d in check_shape(value, "graph") if d.code in NUMBER_CODES}


@pytest.fixture(scope="module")
def wire_results() -> list[dict[str, Any]]:
    texts = [json.dumps(loads_strict(p.read_bytes().decode("utf-8"))) for p in FILES]
    return through_js(texts)


@pytest.mark.parametrize("index", range(len(FILES)), ids=[corpus_id(p) for p in FILES])
def test_json_rpc_roundtrip_corpus_equal(index: int, wire_results: list[dict[str, Any]]) -> None:
    original = FILES[index].read_bytes().decode("utf-8")
    value = loads_strict(original)
    result = wire_results[index]
    assert "ok" in result, result
    sent: str = result["ok"]
    back = _decode(sent.encode("utf-8"))  # ② 봉투 값 검사 (범위 밖 정수·NaN이면 ValueError)
    assert json_equal(value, back)  # ①
    assert number_diags(back) <= number_diags(value)  # ③
    assert save_text(original, back) == original  # ④


def test_corpus_has_required_cases() -> None:
    # H1 필수 세 수·-0·대리 문자·__proto__가 실제로 말뭉치에 있다
    numbers = (CORPUS_DIR / "numbers.graph.json").read_text(encoding="utf-8")
    for token in (*BIG_FLOATS, "-0", "1.0", "1e-7", "1e+20"):
        assert token in numbers
    assert "\\ud800" in (CORPUS_DIR / "strings.graph.json").read_text(encoding="utf-8")
    proto = loads_strict((CORPUS_DIR / "proto-keys.graph.json").read_text(encoding="utf-8"))
    assert {"__proto__", "constructor"} <= set(proto["nodes"])


def test_big_floats_come_back_as_float() -> None:
    texts = [json.dumps({"v": float(t)}) for t in BIG_FLOATS]
    for token, result in zip(BIG_FLOATS, through_js(texts), strict=True):
        back = _decode(result["ok"].encode("utf-8"))
        assert isinstance(back["v"], float) and back["v"] == float(token)
    # 대리 문자·-0·__proto__
    [result] = through_js([json.dumps({"s": "\ud800", "z": -0.0, "__proto__": {"x": 1}})])
    back = _decode(result["ok"].encode("utf-8"))
    assert back == {"s": "\ud800", "z": 0, "__proto__": {"x": 1}}


def test_plain_json_stringify_counterexample() -> None:
    # 코덱 없이 JSON.stringify로 보내면 세 큰 실수가 범위 밖 정수 토큰이 되어 ②·③에서 걸린다
    value = loads_strict((CORPUS_DIR / "numbers.graph.json").read_text(encoding="utf-8"))
    [plain] = through_js([json.dumps(value)], mode="json")
    sent: str = plain["ok"]
    assert "100000000000000000000" in sent
    with pytest.raises(ValueError, match="2\\^53-1"):
        _decode(sent.encode("utf-8"))  # ②
    back = json.loads(sent)
    new = number_diags(back) - number_diags(value)  # ③
    sink = "/nodes/n_sink/in"
    for name in ("big", "big_plus", "two_53_float", "big_digits"):
        assert (f"{sink}/{name}", "number_out_of_range") in new
    for token in BIG_FLOATS:
        [one] = through_js([json.dumps({"v": float(token)})], mode="json")
        with pytest.raises(ValueError):
            _decode(one["ok"].encode("utf-8"))


def test_edit_other_field_keeps_big_floats(tmp_path: Path) -> None:
    path = tmp_path / "numbers.graph.json"
    path.write_bytes((CORPUS_DIR / "numbers.graph.json").read_bytes())
    doc = documents.open(path)
    [result] = through_js([json.dumps(doc.value)])
    value = _decode(result["ok"].encode("utf-8"))
    value["nodes"]["n_sink"]["title"] = "옆 필드만 고침"
    [result] = through_js([json.dumps(value)])  # 저장도 코덱을 거쳐 daemon으로 간다
    saved = documents.save(doc, _decode(result["ok"].encode("utf-8")), doc.revision)
    assert saved.wrote
    text = path.read_text(encoding="utf-8")
    for token in (
        '"big": 1e+20',
        '"two_53_float": 9.007199254740992e+15',
        "1.2345678901234567e+19",
    ):
        assert token in text
    back = loads_strict(text)["nodes"]["n_sink"]["in"]
    for name in ("big", "big_plus", "big_upper", "two_53_float", "big_digits"):
        assert isinstance(back[name], float), name
    assert check_shape(loads_strict(text)) == []


def test_real_out_of_range_int_still_rejected(tmp_path: Path) -> None:
    (tmp_path / WORKSPACE_FILE).write_text('{"format": "kookabug.workspace/0"}\n', encoding="utf-8")
    rel = "tests/big.graph.json"
    path = tmp_path / rel
    path.parent.mkdir()
    text = (CORPUS_DIR / "canonical.graph.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"x": 280', '"x": 9007199254740993'), encoding="utf-8")
    # 파일의 리터럴: 읽기 진단 (실행과 같은 판정)
    _, diags = check_graph(Workspace.open(tmp_path), rel)
    assert ("number_out_of_range", "/layout/nodes/n_log/x") in {(d.code, d.pointer) for d in diags}
    # 그 값은 저장도 거부
    doc = documents.open(path)
    with pytest.raises(DocumentError) as info:
        documents.save(doc, doc.value, doc.revision)
    assert info.value.code == "validation_failed"
    # Python int로 보낸 값·받은 프레임은 봉투 검사에서 거부
    with pytest.raises(ValueError):
        _check_value({"x": 2**53 + 1})
    with pytest.raises(ValueError):
        _decode(b'{"x": 9007199254740993}')

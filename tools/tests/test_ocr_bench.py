"""OCR 측정 스크립트: 표본 형식·정확도·지연·실패 목록 (구현 계획 M1 2.6, T7)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import ocr_bench as ob

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SET = REPO_ROOT / "fixtures" / "sample-game" / "ocr-samples"


def write_set(folder: Path, rows: list[Any], images: tuple[str, ...] = ("a.png", "b.png")) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in images:
        (folder / name).write_bytes(b"png")
    lines = [row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows]
    (folder / ob.TRUTH_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_truth_format_validated(tmp_path: Path) -> None:
    good = write_set(
        tmp_path / "good",
        [
            {"image": "a.png", "text": "Gold 12,345", "region": [1, 2, 3, 4], "tags": ["dpi150"]},
            {"id": "b", "image": "b.png", "text": "인벤토리", "region": None},
            "",
        ],
    )
    samples = ob.load_truth(good)
    assert [s.id for s in samples] == ["1", "b"]
    assert samples[0].region == (1, 2, 3, 4) and samples[0].tags == ("dpi150",)
    assert samples[1].region is None and samples[1].image == good / "b.png"

    bad = write_set(
        tmp_path / "bad",
        [
            "{not json",
            ["list"],
            {"image": "a.png"},
            {"image": "없음.png", "text": "x"},
            {"image": "a.png", "text": "x", "region": [0, 0, 0, 5]},
            {"image": "a.png", "text": "x", "region": [0, 0, 1]},
            {"image": "a.png", "text": "x", "colour": 1},
            {"id": "d", "image": "a.png", "text": "x"},
            {"id": "d", "image": "b.png", "text": "y", "tags": "dpi"},
        ],
    )
    with pytest.raises(ob.TruthError) as info:
        ob.load_truth(bad)
    errors = info.value.errors
    for no, needle in [
        (1, "JSON이 아니다"),
        (2, "객체여야 한다"),
        (3, "text"),
        (4, "이미지가 없다"),
        (5, "region"),
        (6, "region"),
        (7, "모르는 키 colour"),
        (9, "id가 겹친다"),
        (9, "tags"),
    ]:
        assert any(e.startswith(f"truth.jsonl:{no}:") and needle in e for e in errors), (no, errors)
    assert not any(e.startswith("truth.jsonl:8:") for e in errors)

    empty = write_set(tmp_path / "empty", [""])
    with pytest.raises(ob.TruthError, match="표본이 없다"):
        ob.load_truth(empty)
    with pytest.raises(ob.TruthError, match="읽을 수 없다"):
        ob.load_truth(tmp_path / "없는 폴더")


def fake_clock(steps_ms: list[float]) -> Iterator[float]:
    t = 0.0
    for step in steps_ms:
        yield t
        t += step / 1000
        yield t


def test_accuracy_and_latency_computed(tmp_path: Path) -> None:
    folder = write_set(
        tmp_path / "s",
        [
            {"id": "en", "image": "a.png", "text": "Gold 12,345"},
            {"id": "ko", "image": "a.png", "text": "인벤토리", "region": [0, 0, 5, 5]},
            {"id": "ko2", "image": "b.png", "text": "서버  선택\n입장"},
        ],
    )
    answers = {None: "Gold 12,345", (0, 0, 5, 5): "인벤토니"}
    calls: list[Any] = []

    def read(pixels: Any, region: tuple[int, int, int, int] | None) -> str:
        calls.append((pixels, region))
        if pixels == "b":
            return "서버 선택 입장"  # 공백·줄바꿈 차이는 같다고 본다
        return answers[region]

    ticks = fake_clock([10.0, 30.0, 20.0])
    report = ob.run_bench(
        ob.load_truth(folder),
        read,
        clock=lambda: next(ticks),
        load=lambda path: path.stem,
    )
    assert len(calls) == 4  # 첫 표본 앞에 한 번 데움
    s = report.summary()
    assert s["count"] == 3 and s["korean_count"] == 2
    # 편집 거리 합 1 / 정답 글자 수 11 + 4 + 8
    assert s["char_accuracy"] == pytest.approx(1 - 1 / 23)
    assert s["korean_char_accuracy"] == pytest.approx(1 - 1 / 12)
    # 영역 읽기(ko 하나)와 전체 읽기(en·ko2)를 따로 잰다
    assert (s["region_count"], s["full_count"]) == (1, 2)
    assert s["latency_median_ms"] == pytest.approx(30.0)
    assert s["latency_p95_ms"] == pytest.approx(30.0)
    assert s["full_latency_median_ms"] == pytest.approx(15.0)
    assert s["full_latency_p95_ms"] == pytest.approx(20.0)
    by_id = {r.id: r for r in report.samples}
    assert by_id["ko"].distance == 1 and by_id["ko"].accuracy == pytest.approx(0.75)
    assert by_id["ko2"].ok and by_id["en"].ok

    assert ob.edit_distance("kitten", "sitting") == 3
    assert ob.edit_distance("", "abc") == 3
    assert ob.check_criteria(s, min_accuracy=0.9, max_median_ms=35) == []
    misses = ob.check_criteria(s, min_korean_accuracy=0.95, max_p95_ms=10)
    assert len(misses) == 2 and "한국어" in misses[0]


def test_failures_listed(tmp_path: Path) -> None:
    folder = write_set(
        tmp_path / "s",
        [
            {"id": "ok", "image": "a.png", "text": "확인"},
            {"id": "wrong", "image": "a.png", "text": "I: 인벤토리", "region": [1, 1, 1, 1]},
            {"id": "empty", "image": "b.png", "text": "MAP"},
        ],
    )

    def read(pixels: Any, region: tuple[int, int, int, int] | None) -> str:
        if pixels == "b":
            return ""
        return "확인" if region is None else "1: 인벤토리"

    report = ob.run_bench(ob.load_truth(folder), read, load=lambda p: p.stem, warmup=False)
    assert report.summary()["failures"] == ["wrong", "empty"]
    table = ob.render_table(report)
    assert "| wrong ✗ |" in table and "| ok |" in table
    assert "실패 표본 2개: wrong, empty" in table
    data = report.to_json()
    assert [row["ok"] for row in data["samples"]] == [True, False, False]
    json.dumps(data, ensure_ascii=False)


def m1_rows(dpi100: int, dpi150: int, dpi200: int, korean: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tag, count in (("dpi100", dpi100), ("dpi150", dpi150), ("dpi200", dpi200)):
        for i in range(count):
            text = "한글 표본" if len(rows) < korean else "Sample"
            rows.append(
                {"id": f"{tag}-{i}", "image": "a.png", "text": text, "region": [0, 0, 4, 4]}
                | {"tags": [tag]}
            )
    return rows


def test_m1_real_game_sample_rules(tmp_path: Path) -> None:
    """M1 사람 검증 표본 구성: 전체 30·한국어 15·dpi100 20·dpi150 5·dpi200 5, 모두 영역 읽기."""

    def bench(rows: list[dict[str, Any]]) -> ob.BenchReport:
        folder = write_set(tmp_path / str(len(list(tmp_path.iterdir()))), rows)
        samples = ob.load_truth(folder)
        return ob.run_bench(samples, lambda _p, _r: "", load=lambda p: p.stem, warmup=False)

    enough = bench(m1_rows(20, 5, 5, korean=15))
    assert ob.check_m1_samples(enough) == []
    assert enough.summary()["tag_counts"] == {"dpi100": 20, "dpi150": 5, "dpi200": 5}
    assert "태그별 표본 dpi100 20개, dpi150 5개, dpi200 5개" in ob.render_table(enough)

    short = bench(m1_rows(19, 5, 4, korean=14))
    assert ob.check_m1_samples(short) == [
        "표본 28개 — 기준 ≥ 30개",
        "한국어 표본 14개 — 기준 ≥ 15개",
        "dpi100 표본 19개 — 기준 ≥ 20개",
        "dpi200 표본 4개 — 기준 ≥ 5개",
    ]
    rows = m1_rows(20, 5, 5, korean=15)
    rows[0] = {k: v for k, v in rows[0].items() if k != "region"}
    assert ob.check_m1_samples(bench(rows)) == ["region 없는 표본 1개: dpi100-0 — 영역을 적는다"]


def test_m1_real_game_flag_sets_thresholds_and_sample_rules(
    tmp_path: Path,
    ocr_models: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 예제 게임 표본은 DPI 태그가 없어 표본 구성 기준을 못 채운다 → 1, 사유는 표본 구성
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    out = tmp_path / "bench.json"
    assert ob.main([str(SAMPLE_SET), "--m1-real-game", "--json-out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "기준 미달: dpi100 표본 0개 — 기준 ≥ 20개" in err
    assert "기준 미달: 문자 정확도" not in err  # 예제 게임은 수치 기준(0.95)을 넘는다
    # 따로 준 수치 기준이 묶음보다 이긴다
    assert ob.main([str(SAMPLE_SET), "--m1-real-game", "--min-accuracy", "1.01"]) == 1
    assert "기준 미달: 문자 정확도" in capsys.readouterr().err


def test_sample_game_set_is_valid() -> None:
    samples = ob.load_truth(SAMPLE_SET)
    assert len(samples) >= 20
    assert sum(ob.is_korean(s.text) for s in samples) >= 15
    assert all(s.image.is_file() for s in samples)


def test_bench_on_sample_game(
    tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    out = tmp_path / "bench.json"
    code = ob.main([str(SAMPLE_SET), "--json-out", str(out), "--min-accuracy", "0.9"])
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert summary["count"] == len(ob.load_truth(SAMPLE_SET))
    assert summary["char_accuracy"] >= 0.9
    assert summary["max_inference_ms"] > 0
    assert ob.main([str(SAMPLE_SET), "--min-accuracy", "1.01"]) == 1

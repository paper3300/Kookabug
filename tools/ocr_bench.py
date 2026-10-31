"""OCR 정확도·속도 측정 (구현 계획 M1 2.6·2.14).

표본 폴더 = PNG들 + `truth.jsonl`. `truth.jsonl`은 한 줄에 표본 하나:

    {"id": "server1", "image": "lobby.png", "region": [262, 200, 500, 64], "text": "Server 1 원활"}

| 키 | 뜻 |
|---|---|
| `image` | 필수. 이 폴더 기준 상대 경로(PNG) |
| `text` | 필수. 사람이 적은 정답 문자열 |
| `region` | 선택. 이미지 좌표 `[x, y, w, h]`(없거나 null이면 이미지 전체) |
| `id` | 선택. 없으면 `줄번호`. 겹치면 오류 |
| `tags` | 선택. 문자열 목록(`dpi150` 등, 결과에 그대로 싣는다) |

비교는 공백(줄바꿈 포함)을 띄어쓰기 하나로 줄이고 앞뒤를 지운 뒤 한다. 문자 정확도 = 1 - (편집
거리 합 / 정답 글자 수 합). 한국어 표본(정답에 한글 음절이 있음)만의 정확도도 따로 낸다. 지연은
표본마다 읽기 한 번(이미지 읽기 제외, 첫 표본 앞에 한 번 데워 둠)의 중앙값·p95(최근순위)이고,
`region`이 있는 표본(영역 읽기 — 2.14 기준과 `--max-*-ms`가 보는 값)과 없는 표본(전체 읽기)을
따로 낸다. 추론 한 번(`session.run`)의 최댓값도 낸다. 정답과 다른 표본이 실패 표본이다.

    uv run python tools/ocr_bench.py <표본 폴더> [--json-out 결과.json] [--min-accuracy 0.95]
        [--min-korean-accuracy 0.90] [--max-median-ms 200] [--max-p95-ms 500] [--m1-real-game]

`--m1-real-game`은 M1 사람 검증의 실제 게임 OCR 기준(구현 계획 M1 2.14) 묶음이다: 위 네 수치에 더해
표본 수(전체 30개 이상, 한국어 15개 이상, 태그 `dpi100` 20개 이상·`dpi150`·`dpi200` 각 5개 이상)와
모든 표본에 `region`이 있는지를 본다. 따로 준 수치 기준이 있으면 그것이 이긴다.

종료 코드: 0 측정 완료(기준을 주면 기준 통과), 1 기준 미달, 2 표본 형식 오류.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

TRUTH_FILE: Final = "truth.jsonl"
KEYS: Final = frozenset({"id", "image", "region", "text", "tags"})
_SPACE: Final = re.compile(r"\s+")
_HANGUL: Final = re.compile(r"[가-힣]")

M1_REAL_GAME: Final = {
    "min_accuracy": 0.95,
    "min_korean_accuracy": 0.90,
    "max_median_ms": 200.0,
    "max_p95_ms": 500.0,
}
"""M1 실제 게임 OCR 수치 기준 (2.14, 조율자 결정 Q18)."""
M1_SAMPLE_RULES: Final = (
    ("표본", None, 30),
    ("한국어 표본", "korean", 15),
    ("dpi100 표본", "dpi100", 20),
    ("dpi150 표본", "dpi150", 5),
    ("dpi200 표본", "dpi200", 5),
)
"""(이름, 세는 것 — None 전체·`korean` 한국어·그 밖은 태그, 최소 개수)."""

type Reader = Callable[[Any, tuple[int, int, int, int] | None], str]
"""(BGR 픽셀, 영역) → 읽은 글자."""


class TruthError(ValueError):
    """`truth.jsonl` 형식 오류 (모든 오류를 줄 번호와 함께)."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = list(errors)


@dataclass(frozen=True, slots=True)
class Sample:
    id: str
    image: Path
    text: str
    region: tuple[int, int, int, int] | None = None
    tags: tuple[str, ...] = ()


def normalize(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def is_korean(text: str) -> bool:
    return _HANGUL.search(text) is not None


def edit_distance(a: str, b: str) -> int:
    """레벤슈타인 거리 (글자 단위)."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _region(value: Any) -> tuple[int, int, int, int] | str | None:
    if value is None:
        return None
    if (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
        and value[0] >= 0
        and value[1] >= 0
        and value[2] > 0
        and value[3] > 0
    ):
        return value[0], value[1], value[2], value[3]
    return "region은 [x, y, w, h] 정수 넷(x·y ≥ 0, w·h > 0) 또는 null이다"


def load_truth(folder: Path) -> list[Sample]:
    """`truth.jsonl`을 읽고 검사한다. 문제가 하나라도 있으면 전부 모아 `TruthError`."""
    path = folder / TRUTH_FILE
    try:
        raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise TruthError([f"{path}: 읽을 수 없다 ({exc})"]) from exc
    errors: list[str] = []
    samples: list[Sample] = []
    seen: set[str] = set()
    for no, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        where = f"{TRUTH_FILE}:{no}"
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: JSON이 아니다 ({exc.msg})")
            continue
        if not isinstance(item, dict):
            errors.append(f"{where}: 객체여야 한다")
            continue
        problems: list[str] = []
        unknown = sorted(set(item) - KEYS)
        if unknown:
            problems.append(f"모르는 키 {', '.join(unknown)}")
        image, text = item.get("image"), item.get("text")
        if not isinstance(image, str) or not image:
            problems.append("image(문자열)가 있어야 한다")
        elif not (folder / image).is_file():
            problems.append(f"이미지가 없다: {image}")
        if not isinstance(text, str):
            problems.append("text(문자열)가 있어야 한다")
        region = _region(item.get("region"))
        if isinstance(region, str):
            problems.append(region)
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            problems.append("tags는 문자열 목록이다")
        sample_id = item.get("id", str(no))
        if not isinstance(sample_id, str) or not sample_id:
            problems.append("id는 비어 있지 않은 문자열이다")
        elif sample_id in seen:
            problems.append(f"id가 겹친다: {sample_id}")
        if problems:
            errors.extend(f"{where}: {p}" for p in problems)
            continue
        assert isinstance(image, str) and isinstance(text, str) and isinstance(sample_id, str)
        assert not isinstance(region, str)
        seen.add(sample_id)
        samples.append(Sample(sample_id, folder / image, text, region, tuple(tags)))
    if not samples and not errors:
        errors.append(f"{TRUTH_FILE}: 표본이 없다")
    if errors:
        raise TruthError(errors)
    return samples


@dataclass(frozen=True, slots=True)
class SampleResult:
    id: str
    image: str
    region: tuple[int, int, int, int] | None
    tags: tuple[str, ...]
    truth: str
    text: str
    distance: int
    accuracy: float
    latency_ms: float
    korean: bool

    @property
    def ok(self) -> bool:
        return self.distance == 0


@dataclass
class BenchReport:
    samples: list[SampleResult] = field(default_factory=list)
    max_inference_ms: float | None = None

    @staticmethod
    def _accuracy(rows: Sequence[SampleResult]) -> float | None:
        total = sum(len(normalize(r.truth)) for r in rows)
        if total == 0:
            return None
        return 1.0 - sum(r.distance for r in rows) / total

    @staticmethod
    def _latency(rows: Sequence[SampleResult]) -> tuple[float | None, float | None]:
        """(중앙값, p95 최근순위)."""
        values = sorted(r.latency_ms for r in rows)
        if not values:
            return None, None
        return statistics.median(values), values[max(0, math.ceil(0.95 * len(values)) - 1)]

    def summary(self) -> dict[str, Any]:
        korean = [r for r in self.samples if r.korean]
        regions = [r for r in self.samples if r.region is not None]
        full = [r for r in self.samples if r.region is None]
        median, p95 = self._latency(regions)
        full_median, full_p95 = self._latency(full)
        return {
            "count": len(self.samples),
            "char_accuracy": self._accuracy(self.samples),
            "korean_count": len(korean),
            "korean_char_accuracy": self._accuracy(korean),
            "region_count": len(regions),
            "latency_median_ms": median,
            "latency_p95_ms": p95,
            "full_count": len(full),
            "full_latency_median_ms": full_median,
            "full_latency_p95_ms": full_p95,
            "max_inference_ms": self.max_inference_ms,
            "tag_counts": dict(sorted(Counter(t for r in self.samples for t in r.tags).items())),
            "failures": [r.id for r in self.samples if not r.ok],
        }

    def to_json(self) -> dict[str, Any]:
        rows = []
        for r in self.samples:
            row = asdict(r)
            row["ok"] = r.ok
            rows.append(row)
        return {"summary": self.summary(), "samples": rows}


def load_image(path: Path) -> Any:
    import cv2
    import numpy as np

    pixels = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ValueError(f"이미지를 읽을 수 없다: {path}")
    return pixels


def run_bench(
    samples: Sequence[Sample],
    read: Reader,
    *,
    clock: Callable[[], float] = time.perf_counter,
    load: Callable[[Path], Any] = load_image,
    warmup: bool = True,
) -> BenchReport:
    report = BenchReport()
    cache: dict[Path, Any] = {}
    for i, sample in enumerate(samples):
        pixels = cache.get(sample.image)
        if pixels is None:
            pixels = cache[sample.image] = load(sample.image)
        if warmup and i == 0:
            read(pixels, sample.region)  # 첫 추론의 준비 비용을 빼고 잰다
        start = clock()
        text = read(pixels, sample.region)
        latency = (clock() - start) * 1000
        truth, got = normalize(sample.text), normalize(text)
        distance = edit_distance(truth, got)
        accuracy = 1.0 - distance / len(truth) if truth else (1.0 if not got else 0.0)
        report.samples.append(
            SampleResult(
                id=sample.id,
                image=sample.image.name,
                region=sample.region,
                tags=sample.tags,
                truth=sample.text,
                text=text,
                distance=distance,
                accuracy=accuracy,
                latency_ms=latency,
                korean=is_korean(sample.text),
            )
        )
    return report


def _fmt(value: float | None, digits: int = 4) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render_table(report: BenchReport) -> str:
    lines = ["| id | 정답 | 읽음 | 거리 | 지연 ms |", "|---|---|---|---|---|"]
    for r in report.samples:
        mark = "" if r.ok else " ✗"
        lines.append(
            f"| {r.id}{mark} | {normalize(r.truth)} | {normalize(r.text)} | {r.distance} | "
            f"{r.latency_ms:.1f} |"
        )
    s = report.summary()
    lines += [
        "",
        f"표본 {s['count']}개 (한국어 {s['korean_count']}개)",
        f"문자 정확도 {_fmt(s['char_accuracy'])} (한국어만 {_fmt(s['korean_char_accuracy'])})",
        f"영역 읽기 {s['region_count']}개 지연 중앙값 {_fmt(s['latency_median_ms'], 1)} ms, "
        f"p95 {_fmt(s['latency_p95_ms'], 1)} ms",
        f"전체 읽기 {s['full_count']}개 지연 중앙값 {_fmt(s['full_latency_median_ms'], 1)} ms, "
        f"p95 {_fmt(s['full_latency_p95_ms'], 1)} ms",
        f"추론 한 번 최댓값 {_fmt(s['max_inference_ms'], 1)} ms",
        "태그별 표본 " + (", ".join(f"{t} {n}개" for t, n in s["tag_counts"].items()) or "없음"),
        f"실패 표본 {len(s['failures'])}개: {', '.join(s['failures']) or '없음'}",
    ]
    return "\n".join(lines)


def check_criteria(
    summary: dict[str, Any],
    *,
    min_accuracy: float | None = None,
    min_korean_accuracy: float | None = None,
    max_median_ms: float | None = None,
    max_p95_ms: float | None = None,
) -> list[str]:
    """준 기준 중 못 넘은 것."""
    misses: list[str] = []
    checks = [
        ("문자 정확도", summary["char_accuracy"], min_accuracy, True),
        ("한국어 문자 정확도", summary["korean_char_accuracy"], min_korean_accuracy, True),
        ("지연 중앙값", summary["latency_median_ms"], max_median_ms, False),
        ("지연 p95", summary["latency_p95_ms"], max_p95_ms, False),
    ]
    for name, value, limit, at_least in checks:
        if limit is None:
            continue
        if value is None or (value < limit if at_least else value > limit):
            misses.append(f"{name} {_fmt(value)} — 기준 {'≥' if at_least else '≤'} {limit}")
    return misses


def check_m1_samples(report: BenchReport) -> list[str]:
    """M1 실제 게임 표본 구성 (`M1_SAMPLE_RULES`, 모든 표본은 영역 읽기) 중 못 채운 것."""
    misses: list[str] = []
    for name, kind, minimum in M1_SAMPLE_RULES:
        if kind is None:
            count = len(report.samples)
        elif kind == "korean":
            count = sum(r.korean for r in report.samples)
        else:
            count = sum(kind in r.tags for r in report.samples)
        if count < minimum:
            misses.append(f"{name} {count}개 — 기준 ≥ {minimum}개")
    whole = [r.id for r in report.samples if r.region is None]
    if whole:
        misses.append(f"region 없는 표본 {len(whole)}개: {', '.join(whole)} — 영역을 적는다")
    return misses


def main(argv: Sequence[str] | None = None) -> int:
    from kookabug_sdk.console import utf8_stdio

    utf8_stdio()
    parser = argparse.ArgumentParser(description="OCR 정확도·속도 측정")
    parser.add_argument("folder", type=Path, help="표본 폴더 (PNG + truth.jsonl)")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--engine", default="rapidocr")
    parser.add_argument("--min-accuracy", type=float)
    parser.add_argument("--min-korean-accuracy", type=float)
    parser.add_argument("--max-median-ms", type=float)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument(
        "--m1-real-game", action="store_true", help="M1 실제 게임 OCR 기준(수치·표본 구성)"
    )
    args = parser.parse_args(argv)
    if args.m1_real_game:
        for key, value in M1_REAL_GAME.items():
            if getattr(args, key) is None:
                setattr(args, key, value)
    try:
        samples = load_truth(args.folder)
    except TruthError as exc:
        print(f"표본 형식 오류:\n{exc}", file=sys.stderr)
        return 2

    from kookabug_platform.ocr.engine import Ocr, create_engine

    engine = create_engine(args.engine)
    load = getattr(engine, "load", None)
    if callable(load):
        load()
    ocr = Ocr(engine)
    report = run_bench(samples, lambda px, region: ocr.read(px, region=region).text)
    report.max_inference_ms = getattr(engine, "max_run_ms", None)
    print(render_table(report))
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    misses = check_criteria(
        report.summary(),
        min_accuracy=args.min_accuracy,
        min_korean_accuracy=args.min_korean_accuracy,
        max_median_ms=args.max_median_ms,
        max_p95_ms=args.max_p95_ms,
    )
    if args.m1_real_game:
        misses += check_m1_samples(report)
    for miss in misses:
        print(f"기준 미달: {miss}", file=sys.stderr)
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())

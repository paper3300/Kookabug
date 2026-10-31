"""찾기 결과의 JSON 필드 (`kookabug target test --json`과 daemon `target.preview`가 같이 쓴다).

숫자는 사람이 읽기 좋게 줄인다 (점수·배율 4자리, 색 차이 2자리, 시간 0.1 ms).
"""

from __future__ import annotations

from typing import Any

from kookabug_platform.vision import Candidate, FindResult

__all__ = ["candidate_json", "result_json"]


def candidate_json(candidate: Candidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "method": candidate.method,
        "scale": round(candidate.scale, 4),
        "rect": list(candidate.rect),
        "score": round(candidate.score, 4),
        "color_diff": None if candidate.color_diff is None else round(candidate.color_diff, 2),
        "accepted": candidate.accepted,
        "reason": candidate.reason or None,
    }


def result_json(result: FindResult) -> dict[str, Any]:
    match = result.match
    return {
        "found": result.found,
        "match": None
        if match is None
        else {
            "rect": list(match.rect),
            "score": round(match.score, 4),
            "scale": round(match.scale, 4),
            "method": match.method,
            "click": list(match.click),
        },
        "best": candidate_json(result.best),
        "threshold": result.threshold,
        "expected_scale": round(result.expected_scale, 4),
        "search": list(result.search),
        "candidates": [candidate_json(c) for c in result.candidates],
        "elapsed_ms": round(result.elapsed_ms, 1),
    }

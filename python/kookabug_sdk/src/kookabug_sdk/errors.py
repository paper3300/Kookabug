"""관측·입력 경로의 예외 (구현 계획 M1 2.6·2.8).

- `ObservationTimeout`: 관측 호출(캡처·찾기·OCR·창 기다리기)이 노드가 넘긴 `deadline` 안에 끝나지
  않았다. 노드는 잡아서 `timeout` 출구로 간다
- `StaleObservation`: 입력 직전 재검증에서 관측값(`Match`)이 지금 창과 맞지 않고 다시 찾지도
  못했다. 노드는 잡지 않는다. 실행기가 처리되지 않은 fail(`stale_observation`, 출구 없음)로 바꾼다

설정 기한(`run.capture_timeout_ms`)으로 끝나면 `capture_timeout`(`error`), 전체 기한이면
`DeadlineExceeded`라 둘 다 이 예외가 아니다.
"""

from __future__ import annotations

__all__ = ["ObservationTimeout", "StaleObservation"]


class ObservationTimeout(Exception):
    """관측 호출이 노드 기한(`deadline`) 안에 끝나지 않았다. 남은 시간이 0이면 관측을 시작하지 않고
    바로 이 예외다."""


class StaleObservation(BaseException):
    """관측값이 낡았다 (창 크기·DPI·캡처 방식이 바뀌었는데 다시 찾을 수 없다).

    노드가 `except Exception`으로 삼키지 않도록 `BaseException`이다. 노드 고장(`error`)이 아니라
    그 스텝의 처리되지 않은 fail이 되어야 하기 때문이다.
    """

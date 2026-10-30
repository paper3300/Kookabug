"""화면 노드: 화면이 멈출 때까지 대기, 스크린샷 남기기.

`wait_stable`은 연속한 두 관측의 차이(`ctx.vision.diff`, 채널 평균 절대 차이 / 255)가
`tolerance` 이하인 상태가 `stable_ms` 동안 이어지면 `stable`이다. 정지 화면(같은 프레임의
반복)은 차이가 0이다. 기본 `tolerance` 0.001은 1024x640 화면에서 버튼 한 줄의 강조가 바뀌는
정도(약 0.006)도 변화로 보는 값이다 — 작은 깜박임까지 무시하려면 `region`을 좁힌다.

직전 프레임과 지금 프레임 둘만 쥐고 있다 — 프레임 저장소는 열린 스텝의 최근 캡처 두 개를 남긴다
(구현 계획 M1 2.7).
"""

from typing import Annotated

from kookabug_nodes._observe import POLL_MS, check_region, save_last
from kookabug_sdk import Context, Exit, Input, ObservationTimeout, Result, Retry, node
from kookabug_sdk.types import Image, Rect


@node(
    type="core.screen.wait_stable",
    version=1,
    title="화면 멈춤 대기",
    category="screen",
    exits=[Exit("stable", "ok"), Exit("timeout", "fail")],
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def wait_stable(
    ctx: Context,
    region: Rect | None = None,
    stable_ms: Annotated[int, Input(minimum=0)] = 500,
    tolerance: Annotated[float, Input(minimum=0, maximum=1)] = 0.001,
    timeout_ms: Annotated[int, Input(minimum=0)] = 10000,
) -> Result:
    """화면(`region`이 있으면 그 사각형, 클라이언트 픽셀)이 `stable_ms` 동안 멈출 때까지 기다린다
    (애니메이션 끝). 연속한 두 관측의 차이가 `tolerance`(0~1) 이하면 멈춘 것으로 본다. `region`이
    지금 화면과 겹치지 않으면(창 크기가 바뀐 뒤 포함) 멈춘 것으로 보지 않고 `error`(진단)다."""
    deadline = ctx.deadline(timeout_ms)
    clock = deadline.clock
    previous: Image | None = None
    since: int | None = None  # 지금 이어지는 멈춤이 시작된 관측 시각 (ms)
    seen_at = 0
    try:
        while True:
            ctx.check_cancel()
            frame = ctx.capture(deadline=deadline)
            check_region(frame, region)  # 관측마다 (해상도가 바뀌면 영역이 밖으로 나갈 수 있다)
            now = clock.now_ms()
            if previous is not None:
                if ctx.vision.diff(previous, frame, region=region) <= tolerance:
                    since = seen_at if since is None else since
                    if now - since >= stable_ms:
                        return Result.ok("stable")
                else:
                    since = None
            previous, seen_at = frame, now
            if deadline.passed:
                break
            ctx.sleep(min(POLL_MS, deadline.remaining_ms))
    except ObservationTimeout:
        pass
    save_last(ctx, previous, "timeout")
    return Result.fail("timeout", f"화면이 {timeout_ms}ms 안에 {stable_ms}ms 동안 멈추지 않았다")


@node(
    type="core.screen.capture",
    version=1,
    title="스크린샷",
    category="screen",
    exits=[Exit("done", "ok")],
    outputs={"image": Image},
    effects={"capture"},
)
def capture(ctx: Context, region: Rect | None = None, name: str = "capture") -> Result:
    """지금 화면(`region`이 있으면 그 사각형, 클라이언트 픽셀)을 찍어 `steps/<스텝>_<name>.png`로
    남기고 이미지로 내보낸다. 기록 정책(구간 끄기·비밀값 입력)이 막으면 남기지 않는다."""
    image = ctx.capture(region)
    ctx.artifacts.save(image, name)
    return Result.ok("done", image=image)

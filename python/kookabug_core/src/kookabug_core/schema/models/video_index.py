# 생성물 (packages/schema/video-index.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CleanupFailedItem(RootModel[str]):
    root: Annotated[str, Field(min_length=1)]


class GapReason(
    RootModel[
        Literal[
            "capture_missed",
            "interrupted",
            "no_window",
            "paused",
            "policy_off",
            "secret_input",
            "unavailable",
        ]
    ]
):
    root: Annotated[
        Literal[
            "capture_missed",
            "interrupted",
            "no_window",
            "paused",
            "policy_off",
            "secret_input",
            "unavailable",
        ],
        Field(title="GapReason"),
    ]


class SizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class SegmentFile(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="video/ 안 닫은(재생할 수 있는) 조각 파일 이름 seg-NNNN.mp4. 쓰는 중 파일(.part.mp4)은 조각 목록에 올 수 없다",
            pattern="^seg-[0-9]{4,}\\.mp4$",
            title="SegmentFile",
        ),
    ]


class SegmentMode(RootModel[Literal["failed_only", "on"]]):
    root: Annotated[
        Literal["failed_only", "on"],
        Field(
            description="조각의 영상 정책: on은 늘 남기고, failed_only는 판정 fail·error면 남긴다",
            title="SegmentMode",
        ),
    ]


class StepId(RootModel[str]):
    root: Annotated[str, Field(pattern="^s[1-9][0-9]*$", title="StepId")]


class Timestamp(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z). events.jsonl의 t와 같은 시계",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
            title="Timestamp",
        ),
    ]


class VideoReason(
    RootModel[
        Literal[
            "backend_missing", "encoder_open_failed", "encoder_stuck", "mf_missing", "write_failed"
        ]
    ]
):
    root: Annotated[
        Literal[
            "backend_missing", "encoder_open_failed", "encoder_stuck", "mf_missing", "write_failed"
        ],
        Field(
            description="영상이 없거나 멈춘 이유. mf_missing: Media Foundation이 없음, backend_missing: OpenCV MSMF 백엔드 없음, encoder_open_failed: 인코더 열기 실패, write_failed: 녹화 중 쓰기 실패, encoder_stuck: 녹화 스레드가 3초 안에 끝나지 않아 영상을 포기",
            title="VideoReason",
        ),
    ]


class VideoStatus(RootModel[Literal["failed", "none", "omitted", "recorded", "unavailable"]]):
    root: Annotated[
        Literal["failed", "none", "omitted", "recorded", "unavailable"],
        Field(
            description="recorded: 조각을 남김(지웠을 수도 있음), none: 쓸 프레임이 없었음(정책·창 없음), unavailable: 인코더를 쓸 수 없음, failed: 녹화 중 쓰기 실패, omitted: 영상을 포기함",
            title="VideoStatus",
        ),
    ]


class WrittenSegmentFile(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="video/ 안에 녹화 스레드가 쓴 조각 파일 이름: 닫은 조각 seg-NNNN.mp4 또는 쓰는 중 파일 seg-NNNN.part.mp4 (지운 조각 기록에만 쓴다)",
            pattern="^seg-[0-9]{4,}(\\.part)?\\.mp4$",
            title="WrittenSegmentFile",
        ),
    ]


class DeletedSegment(BaseModel):
    """
    마무리에서 지운 조각과 이유. run_pass·run_skipped·run_cancelled: 판정 pass·skipped·사용자 취소라 failed_only 조각을 지움, interrupted: 쓰다 만 조각(.part.mp4, segments.jsonl 줄 없는 .mp4), encoder_stuck: 녹화 스레드가 멈춰 그 실행의 영상을 포기함
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    file: WrittenSegmentFile
    mode: SegmentMode | None = None
    reason: Literal["encoder_stuck", "interrupted", "run_cancelled", "run_pass", "run_skipped"]


class FramesLine(BaseModel):
    """
    video/seg-NNNN.frames.jsonl 한 줄: 격자 칸 하나에 무엇을 썼는지 (검사·사람 확인용. 뷰어 이동은 격자로 한다). pixels_at은 그 칸에 쓴 프레임의 픽셀 시각(반복이면 반복한 프레임의 시각)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    pixels_at: Timestamp
    repeat: Annotated[
        bool,
        Field(description="새 프레임이 없어(캡처 지연·건너뜀·보류 차단) 직전 프레임을 다시 썼다"),
    ]
    slot: Annotated[
        int,
        Field(description="격자 칸 번호 (조각 안에서 0부터). 재생 위치 = slot * frame_ms", ge=0),
    ]


class Gap(BaseModel):
    """
    영상을 쓰지 않은 구간과 이유. policy_off: 기록 끈 구간, secret_input: 비밀값을 받은 스텝(이 열린 동안), paused: 디버거로 멈춤, no_window: 대상 창 없음, capture_missed: 캡처가 2초 넘게 계속 실패, unavailable: 이 PC에서 영상 인코더를 쓸 수 없음, interrupted: 실행이 중단돼 쓰던 조각을 지움. step은 구간을 연 스텝 (policy_off·secret_input·paused)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    gap: GapReason
    step: StepId | None = None
    t_end: Timestamp
    t_start: Timestamp


class Segment(BaseModel):
    """
    닫은 조각 하나 (segments.jsonl 한 줄, index.json의 segments 항목). 조각 하나는 한 모드·한 창·한 크기·최대 60초이고 안에 빈 구간이 없다. t0은 칸 0의 실행 시각, t_end는 닫은 실행 시각(t0 + frames * frame_ms). 실행 시각 t0 + slot * frame_ms = 재생 위치 slot * frame_ms
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int, Field(ge=0)]
    file: SegmentFile
    frame_ms: Annotated[int, Field(description="격자 칸 길이 (초당 5장이면 200)", ge=1)]
    frames: Annotated[int, Field(description="쓴 칸 수 (반복 칸 포함)", ge=1)]
    mode: SegmentMode
    size: Annotated[
        list[SizeItem],
        Field(
            description="[w, h] 쓴 프레임 크기 (긴 변 1920 이하로 줄인 뒤)",
            max_length=2,
            min_length=2,
        ),
    ]
    t0: Timestamp
    t_end: Timestamp
    window: Annotated[
        str,
        Field(
            description="녹화한 창 (가장 안쪽 호출 프레임의 현재 창 바인딩, match.window와 같은 표기)"
        ),
    ]


class SegmentsLine(RootModel[Segment | Gap]):
    root: Annotated[
        Segment | Gap,
        Field(
            description="video/segments.jsonl 한 줄: 닫은 조각 또는 비운 구간. 녹화 스레드만 덧붙인다",
            title="SegmentsLine",
        ),
    ]


class VideoIndex(BaseModel):
    """
    실행 폴더 video/index.json: 마무리(finalize_video)가 최종 run.end 기준으로 공개한 영상 색인. 같은 폴더 임시 파일 + replace로만 쓴다. 이 파일이 없으면 읽는 쪽은 segments.jsonl만 보고 보여 준다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int, Field(description="남은 조각 바이트 합", ge=0)]
    cleanup_failed: Annotated[
        list[CleanupFailedItem] | None,
        Field(description="지워야 하는데 지우지 못한 파일 (다음 마무리가 다시 시도한다)"),
    ] = None
    deleted: list[DeletedSegment]
    format: Literal["kookabug.video-index/0"]
    gaps: list[Gap]
    reason: VideoReason | None = None
    segments: Annotated[list[Segment], Field(description="남은 조각 (실행 시각 순)")]
    status: VideoStatus

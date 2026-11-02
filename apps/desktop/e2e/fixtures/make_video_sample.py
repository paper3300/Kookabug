"""E2E 영상 표본 `video-sample.mp4`를 만든다 (M3 T11 `runviewer2.spec.ts`).

OS Media Foundation H.264(OpenCV MSMF, 앱 녹화와 같은 경로)로 160x96, 초당 5장, 15장(3초)을
쓴다. 칸 0~4는 빨강, 5~9는 초록, 10~14는 파랑이라 탐색한 칸을 색으로 알 수 있다. CI 호스트에
Media Foundation이 없어도 앱 `<video>` 재생·탐색을 검사할 수 있게 만든 파일을 레포에 둔다.

    .venv/Scripts/python.exe -X utf8 apps/desktop/e2e/fixtures/make_video_sample.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).with_name("video-sample.mp4")
SIZE = (160, 96)
COLORS_BGR = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]


def main() -> None:
    fourcc = cv2.VideoWriter.fourcc(*"avc1")
    writer = cv2.VideoWriter(str(OUT), cv2.CAP_MSMF, fourcc, 5.0, SIZE)
    if not writer.isOpened():
        raise SystemExit("MSMF H.264 인코더를 열 수 없다")
    for i in range(15):
        frame = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
        frame[:] = COLORS_BGR[i // 5]
        writer.write(frame)
    writer.release()
    print(f"{OUT} {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()

"""NOTICES의 "OS 구성요소 사용" 절 (구현 계획 M3 2.5·4장): 영상 녹화는 배포하지 않는 OS 구성요소
(Windows Media Foundation H.264 인코더)를 부르고, 설치 트리에 새 네이티브 파일을 더하지 않는다."""

import native_audit as na
from installer import smoke
from kb_testing.audit_fixtures import native_table, policy


def test_notice_sections_end_with_os_components() -> None:
    sections = na.render_notice_sections([], native_table(), policy(), [], None)
    text = sections[-1]
    assert text.splitlines()[1] == f"# {na.OS_COMPONENTS_TITLE}"
    assert "Windows Media Foundation" in text
    assert "opencv_videoio_ffmpeg" in text  # 쓰지 않고 빼는 FFmpeg 백엔드
    assert f"# {na.OS_COMPONENTS_TITLE}" in smoke.NOTICE_SECTIONS

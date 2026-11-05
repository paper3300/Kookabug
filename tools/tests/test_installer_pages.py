"""설치 파일의 첫 화면 (M2 사람 확인 S3 결함: "모든 사용자/나만" 설치 범위 화면이 떴다).

설치 범위 화면은 설치 파일에 아예 넣지 않는다(`apps/desktop/packaging/installer.nsh`·
`no-install-mode-page.nsh`, build.py가 컴파일 표식으로 확인). 이 검사는 실제로 만든 설치
파일(테스트 판, `installer_test_setup`)을 보이지 않는 데스크톱에서 띄워(`installer.pages`,
설치하지 않음) 첫 화면이 사용자별 기본 폴더의 폴더 고르기이고, 범위를 고르는 라디오 단추와
첫 화면에 남는 "뒤로" 단추(누르면 설치 프로그램이 그냥 끝났다)가 없는지 본다.
"""

import os
from pathlib import Path

import pytest

from installer import build, pages

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(1800)]


def test_first_page_is_per_user_folder_without_scope_choice(installer_test_setup: Path) -> None:
    page = pages.first_page(installer_test_setup)
    assert build.TEST.app_name in page.title, page
    assert page.radios == [], page  # 모든 사용자 / 나만
    assert page.by_id(pages.BACK_ID) == [], page  # 첫 화면에 "뒤로"가 없다
    default = Path(os.environ["LOCALAPPDATA"]) / "Programs" / build.TEST.dir_name
    assert [Path(e) for e in page.edits] == [default], page

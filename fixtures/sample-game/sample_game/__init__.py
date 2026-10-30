"""예제 게임 SampleRPG (구현 계획 M1 2.9).

표준 라이브러리(tkinter)만 쓰는 작은 가짜 게임이다. 타이틀 → (점검 팝업) → 로그인 → 로비 →
(로딩) → 월드 → 인벤토리. 화면 상태 기계(`flow`)·버튼 배치(`layout`)·그리기(`render`)·창
껍데기(`app`)를 나눠, 상태 기계와 배치만으로 헤드리스용 장면 전이 표(`scenario`)를 만든다.
"""

from __future__ import annotations

from typing import Final

DEFAULT_TITLE: Final = "SampleRPG"
DEFAULT_FONT: Final = "Malgun Gothic"
DEFAULT_ACCOUNT: Final = "qa_tester_01"
DEFAULT_PASSWORD: Final = "sample-pass-01"
# 배치의 기준 클라이언트 크기. 다른 크기는 비율을 지켜 늘리고 남는 곳은 배경으로 채운다
BASE_SIZE: Final = (1024, 640)
DEFAULT_LOADING_MS: Final = 400
# 글꼴이 없을 때의 종료 코드
EXIT_FONT_MISSING: Final = 3
EXIT_USAGE: Final = 2

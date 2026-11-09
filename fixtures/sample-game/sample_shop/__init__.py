"""예제 상점 SampleRPG 상점 (M8 계획 3.16·E10).

예제 게임 본체(`sample_game`)와 따로 뜨는 작은 창이다. 본체를 바꾸면 본체 화면 PNG 10장을 대화형
데스크톱에서 다시 찍어야 하므로 상점은 자기 패키지·PNG·헤드리스 표를 갖는다.

그림은 Windows GDI 오프스크린 렌더(`render.py`)가 PNG로 만들고, 창(`app.py`)은 그 PNG를 그대로
보여 준다 — 헤드리스 PNG와 실제 창 픽셀이 같은 렌더러에서 나온다(창을 띄우지 않고 PNG를 만든다).
"""

from typing import Final

__all__ = ["CLIENT_SIZE", "TITLE"]

TITLE: Final = "SampleRPG 상점"
CLIENT_SIZE: Final = (1024, 640)

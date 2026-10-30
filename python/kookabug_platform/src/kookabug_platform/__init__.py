"""Kookabug Windows 플랫폼: 창·프로세스·DPI·캡처·입력·비전·OCR (구현 계획 M1 2.1).

`kookabug_core`는 이 패키지를 프로토콜로만 알고 `platform.kind`가 `windows`일 때만 import한다.
그래서 코어 테스트와 `none`·`fake` 실행은 opencv·onnxruntime 없이 돈다.
"""

__version__ = "0.1.0.dev0"

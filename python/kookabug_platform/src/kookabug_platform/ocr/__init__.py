"""OCR (구현 계획 M1 2.6).

| 모듈 | 내용 |
|---|---|
| `models.py` | 모델 표(`models.toml`)·모델 찾기·해시 확인 (opencv·onnxruntime 없이 읽힌다) |
| `engine.py` | 엔진 인터페이스, `RapidOcrEngine`, 결과 묶기, 숫자 파싱, 실행의 `Ocr` |
| `det.py`·`rec.py` | RapidOCR에서 옮긴 검출·인식 전후처리 (`NOTICE`) |

이 패키지를 import해도 무거운 모듈은 읽히지 않는다 — `engine`은 필요한 곳에서 직접 import한다.
"""

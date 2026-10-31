# M1 실제 게임 검증 워크스페이스 (틀)

M1 사람 검증 G절(`../m1-manual.md`)에서 쓰는 워크스페이스다. 특정 게임에 묶이지 않고 설정값과 target 세 개만 바꿔 쓴다. **레포 밖으로 복사해서 쓴다** — target 이미지와 실행 기록은 게임 화면이라 레포에 넣지 않는다.

```
m1-real-game/
├─ kookabug.json               설정 기본값 (게임 창 제목·확인 글자·한글 영역은 null → .kookabug/local.json)
├─ targets/README.md           target 만드는 법. anchor(기준 버튼)·label(확인 글자)·field(입력 칸)는 사람이 만든다
└─ tests/
   ├─ capture.graph.json       화면 찍기 (capture.delay_ms 기다린 뒤)
   ├─ dpi_check.graph.json     붙기 → 이미지 대기 → 클릭 → OCR → 키 → 복귀 확인
   ├─ move_click.graph.json    찾은 뒤 사람이 창 이동 → 찾은 결과로 클릭
   ├─ resize_click.graph.json  찾은 뒤 창 크기 변경 → 찾은 결과로 클릭 (재검증)
   ├─ focus_loss.graph.json    기다리는 동안 사람이 다른 창 클릭 → 글자 입력
   ├─ korean_input.graph.json  입력 칸 클릭 → 한글 입력 → 찍기 → 영역 OCR
   └─ hold_key.graph.json      키 누르고 있기 (강제 종료 키 해제·키 설정 화면 수신)
```

| 설정 | 기본값 | 뜻 |
|---|---|---|
| `game.title` | null | 게임 창 제목(부분 일치, `/정규식/`) |
| `check.text` | null | 확인 글자(부분 일치) |
| `check.key` | `escape` | 확인 화면에서 기준 화면으로 돌아가는 키 |
| `korean.region` | null | 한글 입력 결과를 읽을 영역 `[x, y, w, h]`(클라이언트 픽셀) |
| `korean.text` | `한글 입력 확인` | 입력할 문자열 (`--set korean.text=…`) |
| `capture.delay_ms` | 0 | 화면 찍기 전 기다림 |
| `manual.delay_ms` | 10000 | 사람이 창 이동·다른 창 클릭을 하는 시간 |
| `resize.size` | `[1280, 720]` | 바꿀 클라이언트 크기 |
| `hold.key`·`hold.ms`·`hold.delay_ms` | `up`·60000·2000 | 누를 키·누르고 있을 시간·누르기 전 기다림 |

그래프가 실행 전 검증을 통과하는지는 `tools/tests/test_verification_docs.py`가 본다.

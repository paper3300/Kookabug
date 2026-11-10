# 예제 워크스페이스 (SampleRPG)

예제 게임 SampleRPG(`../sample_game`)를 대상으로 한 Kookabug 워크스페이스다. 그래프는
[그래프 JSON 스키마 v0](../../../Docs/Design/그래프%20JSON%20스키마%20v0.md) 1장·3장 예시 그대로이고,
게임을 띄우는 노드만 설정값(`game.*`)을 쓴다.

```
workspace/
├─ kookabug.json                      설정·프로필 (login_fail·maintenance)
├─ fake-platform.json                 헤드리스용 가짜 플랫폼 사양 (장면 표 ../frames/scenario.json)
├─ subgraphs/enter_world.graph.json   게임 실행 → 로그인 → 서버 선택 → 월드 접속
├─ tests/inventory_open.graph.json    월드 접속 뒤 I 키로 인벤토리가 열리는가
├─ tests/smoke_headless.graph.json    헤드리스 스모크 (가짜 플랫폼 전용, 설치 스모크·doctor가 쓴다)
├─ tests/broken/swapped_target.graph.json          깨뜨린 변형: 타이틀 대기 target 바꿔치기
├─ subgraphs/broken/enter_world_swapped_target.graph.json
├─ targets/                           찾기 대상 (화면 PNG에서 자른 이미지, 1024x640·96 DPI 기준)
└─ screens/                           화면 판정 8종 (title·maintenance·login·login_error·lobby·loading·world_field·inventory)
```

## 처음 한 번: 사람마다 다른 설정

`kookabug.json`의 `game.executable`·`game.cwd`는 `null`이다. `.kookabug/local.json`(Git에서 뺀다)에
예제 게임을 띄울 Python과 예제 게임 폴더(`sample_game` 패키지가 있는 곳)를 적는다.

```json
{
  "format": "kookabug.local/0",
  "settings": {
    "game.cwd": "C:/src/Kookabug/fixtures/sample-game",
    "game.executable": "C:/Python314/python.exe"
  }
}
```

설치본의 예제(`<설치 폴더>\examples\sample-game\workspace`)에는 설치 파일이 동봉 Python과 그 예제 게임
폴더로 이 파일을 써 둔다.

비밀번호(`accounts.qa_tester_01`)는 환경 변수로 넣는다. 예제 게임의 기본 비밀번호는 `sample-pass-01`이다.

```powershell
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
```

## 실행

이 폴더에서:

```powershell
kookabug run tests/inventory_open.graph.json                       # 통과 (종료 코드 0)
kookabug run tests/inventory_open.graph.json --profile login_fail  # 실패: 월드 접속 (login_failed)
kookabug run tests/inventory_open.graph.json --profile maintenance # 건너뜀 (서버 점검 중)
kookabug run tests/broken/swapped_target.graph.json                # 실패: 월드 접속 > 타이틀 대기
```

게임은 `core.app.launch`가 띄우고 실행이 끝나면 정리된다. 실행 중에는 게임 창이 앞에 있어야 한다
(다른 창이 포커스를 가져가면 입력 노드가 `window_not_foreground`로 끝난다).

- `login_fail`·`maintenance` 프로필은 `game.args`에 `--login-fail`·`--maintenance`를 더한다
- `login_fail`의 실패 위치는 `월드 접속`이고 `steps/<그 스텝>_fail.png`에 로그인 오류 팝업이 보인다.
  호출 노드가 비밀번호(비밀값)를 받아도 호출 스텝의 실패 증거는 막지 않는다(안쪽 스텝 프레임). 비밀번호를
  직접 받은 `비밀번호 입력` 스텝은 스크린샷을 남기지 않는다. 오류 문구는 `오류 문구 읽기` 스텝의
  `_ocr.txt`에도 남는다
- 깨뜨린 변형은 타이틀 대기 timeout을 3초로 줄였다. `steps/<타이틀 대기 스텝>_timeout.png`가 남는다

## 헤드리스 (게임 창 없이)

장면 표(`../frames/scenario.json`)로 같은 그래프를 돌린다. 숨은 테스트 옵션이다.

```powershell
kookabug run tests/inventory_open.graph.json --platform-fake fake-platform.json
kookabug run tests/smoke_headless.graph.json --platform-fake fake-platform.json
```

가짜 입력 기록은 `runs/fake-input.jsonl`에 쌓인다. `kookabug doctor`의 스모크(`smoke.fake`)는
`tests/smoke_headless.graph.json`을 이 장면 표로 돌린다.

## 예제 상점 (자기 진화 QA)

예제 상점(`../sample_shop`, `python -m sample_shop [--buy-moved | --buy-missing]`)은 자기 진화 QA의 완료
시나리오용 따로 뜨는 창이다. 팀 기준 테스트 셋은 역할이 다르다.

- `tests/shop/buy_potion.graph.json` — 구매 단추(`targets/shop/buy.target.json`)를 눌러 골드·물약을 판정한다.
  `qa.claims`(`shop.potion.price`)가 있어 locator 자동 수리 대상이다
- `tests/shop/buy_then_close.graph.json` — 같은 구매 target을 쓰는 영향 테스트(자동 채택 조건 6에서 다시 돈다)
- `tests/shop/close_shop.graph.json` — 구매 target과 무관한 테스트(구매 단추가 사라져도 계속 진행하는지 본다)

지식(`knowledge/`)·원본(`sources/items.csv`)·자동화 정책(금지 문구 "결제")·치트 분류(`dev_safe`)는
`kookabug.json`과 같이 사람이 준비한 팀 기준이다. 치트 `give_gold`는 미채택으로 두고 검사가 사람 경로
(`kookabug cheat adopt`)로 채택한다. 프로필 `shop_moved`·`shop_missing`이 상점 변형을 고른다.

## target 다시 만들기

target 이미지는 `../frames/*.png`를 `../tools/cut_targets.py`의 표대로 자른 것이다. 화면 PNG를 다시
찍었으면 `uv run python fixtures/sample-game/tools/cut_targets.py`로 다시 만든다(`--check`는 비교만).

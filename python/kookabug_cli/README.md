# kookabug-cli

Kookabug 명령줄 도구.

```
kookabug run <그래프 경로> [--workspace DIR] [--profile 이름] [--set 키=JSON값]... [--deadline-ms N]
             [--json] [--quiet] [--plugin-module 모듈]...
```

종료 코드: `0` 통과, `1` 실패, `2` 오류(취소·기한·runner 죽음·입력 임대권 거부·기록 마무리 실패 포함), `3` 건너뜀,
`4` 실행 전 검증 오류, `5` 권한 거부·승인 필요, `6` 사용법·환경 오류.

Ctrl+C 한 번은 취소, 두 번은 runner를 바로 끝낸다. 어느 쪽이든 기록은 마무리된다.

```
kookabug target test <target.json> (--window 제목 | --hwnd N | --image PNG) [--out PNG] [--json] [--all-scales]
kookabug screen test <화면 ID|*.screen.json> (--window 제목 | --hwnd N | --image PNG) [--workspace DIR] [--json]
```

`target test`는 target 하나를 창(지금 화면 한 장)이나 이미지에서 찾고 미리보기 PNG(검색 범위 파랑,
최고 후보 초록/빨강·점수·배율·방법, 클릭 지점 십자)를 쓴다. `0` 찾음, `1` 못 찾음, `6` 사용법·환경 오류.
`screen test`는 화면 판정 조건(`detect.all`·`detect.none`)을 조건별로 보여 준다. `0` 그 화면, `1` 아님,
`6` 사용법·환경 오류. 둘 다 Windows 플랫폼 패키지(`kookabug-platform`)가 필요하다.

```
kookabug doctor [--profile headless|desktop] [--json]
```

`doctor`는 설치와 기능을 점검한다. `headless`: Python 위치, 의존성 import, DLL을 읽은 곳, OCR 모델
해시, DPI 인식, 가짜 플랫폼 스모크 그래프(매칭·OCR). `desktop`(기본): 그에 더해 입력 데스크톱, 임시 창
WGC 캡처, 정지 화면 재사용, 포그라운드(입력은 보내지 않는다). `0` 전부 통과, `1` 실패 있음.

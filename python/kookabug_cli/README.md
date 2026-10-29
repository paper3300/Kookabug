# kookabug-cli

Kookabug 명령줄 도구.

```
kookabug run <그래프 경로> [--workspace DIR] [--profile 이름] [--set 키=JSON값]... [--deadline-ms N]
             [--json] [--quiet] [--plugin-module 모듈]...
```

종료 코드: `0` 통과, `1` 실패, `2` 오류(취소·기한·runner 죽음·입력 임대권 거부·기록 마무리 실패 포함), `3` 건너뜀,
`4` 실행 전 검증 오류, `5` 권한 거부·승인 필요, `6` 사용법·환경 오류.

Ctrl+C 한 번은 취소, 두 번은 runner를 바로 끝낸다. 어느 쪽이든 기록은 마무리된다.

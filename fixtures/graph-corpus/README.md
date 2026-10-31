# 그래프 원문 말뭉치

에디터 저장 계약(M2 계획 2.6)을 검사하는 그래프 파일 모음이다. **바이트 그대로** 둔다
(`.gitattributes`에서 줄바꿈 변환을 끈다). 목록은 `corpus.json`이고, 예제 워크스페이스 그래프 전부도
들어 있다.

| 파일 | 보는 것 |
|---|---|
| `canonical` · `crlf` · `indent4` · `no-final-newline` · `shuffled-keys` | 같은 값의 여러 원문 표기 (무수정 저장은 바이트 그대로) |
| `integer-like-keys` | JS 객체가 앞으로 옮기는 정수 같은 키 (`"10"`, `"2"`) |
| `numbers` | `1.0`·`1e-7`·`-0`·`1e20`·`1e+20`·`9007199254740992.0`·`1.2345678901234567e19` (전송 코덱 필수 세 수) |
| `strings` | `"é"` 이스케이프와 원문 한글, 짝 없는 대리 문자 이스케이프, 제어 문자 |
| `proto-keys` | `__proto__`·`constructor`를 노드 ID·핀 이름·config·값 안 키로 |
| `unknown-keys` | 최상위·노드·`in`·`config`·`layout`의 모르는 키 (형식 검사 오류지만 보존) |
| `unknown-node` | 설치되지 않은 플러그인 노드 (대체 모양) |
| `groups-comments` | 접힌 그룹·주석 |
| `special-values` | `$literal` 안의 특수 값 모양, 배열·객체 안 `$link`, `$setting`·`$secret` |
| `empty-containers` | 빈 객체·빈 배열 |
| `doc-enter-world` · `doc-inventory-open` | `Docs/Design/그래프 JSON 스키마 v0.md` 예시 원문 |

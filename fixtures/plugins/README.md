# 플러그인 검사 픽스처 (M6)

`tools/kb_testing/plugin_fixtures.py`가 이 폴더의 프로젝트로 결정적 wheel을 만들고(스키마는
`kookabug-sdk build`로 생성), 로컬 인덱스(`tools/kb_testing/plugin_index.py`)에 의존성 wheel과 함께
올린다. 네트워크를 쓰지 않는다.

| 폴더 | 의존성 | 쓰는 검사 |
|---|---|---|
| `conflict_a` | `kbfix-dep==1.*` | 공유 환경 |
| `conflict_b` | `kbfix-dep>=2` | A와 충돌 → 격리 |
| `compatible_c` | `kbfix-dep>=1,<3` | 공유에 붙음 |
| `build_marker` | SDK만 | 프로젝트 안 빌드 백엔드·모듈 import가 표식을 씀 → 신뢰 확인 전 코드 미실행 (git·폴더 원천) |

git 원천 검사는 `plugin_fixtures.git_repo()`가 이 폴더·예제를 레포 밖 임시 git 레포(`file://`)로
만든다 (전역 git 설정을 쓰지 않음).

깨진 픽스처(`broken_import`·`unresolvable`·`bad_effects`·`id_core`·`sdist_only`·`schema_drift`·
`hang_import`)는 위 프로젝트를 바탕으로 `plugin_fixtures.py`가 만든다.

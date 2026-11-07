# M6 사람 확인 절차서

M6(플러그인) 완료도 두 단계다 ([[구현 계획 v0]] 1장 M6 행).

1. **자동 완료**: CI 자동 검사(로컬 가짜 인덱스 `tools/kb_testing/plugin_index.py`·레포 밖 로컬 git 레포로 실제 uv·venv 설치), 인수 테스트(`python/kookabug_core/tests/acceptance/test_m6.py`, `apps/desktop/e2e/acceptance.m6.spec.ts`), 화면 샷, 설치본 스모크의 플러그인 단계(`cli.plugin` — 설치 트리의 동봉 uv로 예제 플러그인 설치 → 실행 → 잠금 검증 → 제거 → 정리), 이 절차서·결과 양식
2. **최종 완료**: 이 절차서의 결과가 결과 양식(`m6-result-template.md`)에 기록되고 모든 항목이 통과 기준을 만족

> **사람 확인은 M7 끝에 몰아서 한다** (2026-11-05 사용자 결정, 속도 우선). 그 전까지 M6는 "자동 완료"로만 센다. 실제 공개 레포·실제 PyPI·다른 실제 PC·설치본 앱 화면은 CI에서 쓰지 않는다 — 여기서만 본다.

| 절 | 내용 | 누가 | 시간 |
|---|---|---|---|
| D1·D2 | 전체 자동 검사·E2E, 설치본 스모크(플러그인 단계) | 조율자 | 약 1시간 30분 (기다림) |
| H1~H8 | 실제 공개 레포·PyPI·다른 PC·강제 종료·SDK 바뀐 앱·화면·위젯·백신 | 사람 | 약 2시간 |
| U1~U14 | 기본값으로 진행한 사용자 결정 | 사람 | 20분 |

결과 `manual_result.md`와 증거 폴더는 레포 밖 `.orchestration/M6/`(git 제외)에 둔다.

## 0. 준비

[[m4-manual]] 0절의 준비를 `M4` → `M6`로 바꿔 쓴다(`$ev = "$repo\.orchestration\M6\manual_evidence"`, 결과 양식 `m6-result-template.md` 복사, 예제 워크스페이스 사본 `%TEMP%\kb-m6\sample-rpg`, 개발 빌드 앱 띄우기).

- H1·H2용으로 예제 플러그인(`examples/plugins/kookabug-plugin-sample`, MIT)을 **개인 공개 GitHub 레포**로 올려 둔다(태그 `v0.1.0`). 레포 생성·게시는 사람이 한다(U5). 스키마 파일(`kookabug.schema.json`)은 올리지 않는다 — 설치가 승인 뒤에 만든다
- 플러그인 의존성은 인터넷의 PyPI(`kookabug.json`의 `plugin_index`가 없으면 기본 `https://pypi.org/simple`)에서 받는다. 사내 프록시가 있으면 환경 변수(`HTTPS_PROXY`)로만

## 1. 조율자 자동 검사 (D)

### D1 전체 자동 검사

[[m4-manual]] D2와 같은 명령(전체 pytest + 전체 E2E). 인수 `test_m6.py`·`acceptance.m6.spec.ts`와 플러그인 검사(`packaging` 마커, 로컬 인덱스)가 포함된다. 증거 `d1_full.log`, `d1_e2e.log`.

- 기대 결과: 실패 0. 건너뜀은 대화형 데스크톱·실제 입력 조건부 검사만

### D2 설치본 스모크 (플러그인 단계)

```powershell
$env:PYTHONPATH = "tools"
uv run python -m installer.build --out build/installer --test-setup 2>&1 | Tee-Object "$ev\d2_build.log"
uv run python -m installer.smoke --setup (Get-ChildItem build\installer\dist\kookabug-setup-test-*.exe).FullName --json "$ev\d2_smoke.json"
```

- 기대 결과: 모든 단계 `ok`. `cli.plugin`의 내용에 `동봉 uv 사용 True`, `실행 pass`, `gc 뒤 환경 없음`. `env.python_free`가 PATH에 python·uv가 없음을 확인한다
- 설치 트리 `licenses\THIRD_PARTY_NOTICES.txt`에 "uv 0.13.6의 Rust 크레이트 라이선스 원문"과 "플러그인" 절이 있다

## 2. 사람 확인 (H)

### H1 실제 공개 git 레포를 앱으로 설치 → 예제 실행

1. 개발 빌드 앱으로 예제 사본을 연다 → 액티비티 바 "플러그인" → [+ 플러그인 추가] → "Git 주소"에 0절의 공개 레포 `https://github.com/<you>/kookabug-plugin-sample`, 버전 `v0.1.0` → [미리보기]
2. 신뢰 카드: 이름·`sample · 0.1.0`·출처(커밋 7자)·권한 "화면 캡처 — 게임 창 화면을 읽어요"·경고 문구 → [신뢰하고 설치]
3. 끝나면 팔레트 "Sample" 분류에서 "글자 뒤집기"를 놓아 실행(F5) → 통과

- 기대 결과: 설치 성공, `kookabug.lock`과 `plugins/wheels/<sha256>/` 생김, 실행 통과. 미리보기 단계에는 잠금·환경이 생기지 않는다

### H2 PyPI 실제 의존성이 있는 플러그인

H1 레포에 순수 Python wheel이 있는 작은 의존성 하나(예: `tomli-w`)를 `dependencies`에 더하고 노드에서 import하게 한 뒤 태그 `v0.1.1`. 앱에서 그 버전으로 업그레이드하거나 새로 설치한다.

- 기대 결과: 실제 PyPI에서 받아 설치, 잠금 `environments.shared.packages`에 판·해시. sdist만 있는 의존성을 넣으면 `sdist_only_dependency`로 거부되고 기존 플러그인은 그대로

### H3 다른 PC(또는 Windows Sandbox 설치본)에서 잠금 재현

H1·H2의 워크스페이스(잠금·`plugins/wheels/` 포함, `.kookabug/` 빼고)를 Git으로 다른 PC나 Sandbox(D2의 설치본 설치)에 클론한다.

- 기대 결과: 앱 사이드바에 "준비 필요" 띠 → [준비…] → 신뢰 카드(목록·권한 한 번에) → 준비 끝, 같은 그래프가 통과. 원천 레포에 접근하지 않는다(커밋된 wheel만)
- 증거: **두 PC 모두** 워크스페이스에서 아래를 돌려 저장한다. 두 `h3_digests_*.txt`의 환경별 digest가 같아야 하고(잠금이 같다), 두 `h3_verify_*.json`이 `"ok": true`여야 한다(verify가 각 PC의 실제 환경 파일 digest를 다시 계산해 잠금과 대조한다 — 응답에는 digest가 없다)

```powershell
$pc = "pc1"   # 다른 PC에서는 "pc2"
(Get-Content kookabug.lock -Raw | ConvertFrom-Json).environments.PSObject.Properties |
  ForEach-Object { "$($_.Name) $($_.Value.digest)" } | Set-Content "$ev\h3_digests_$pc.txt"
kookabug plugin verify --json | Set-Content "$ev\h3_verify_$pc.json"
```

### H4 설치 중 앱 강제 종료

H2 같은 설치를 시작하고 진행 단계 줄이 "환경 만들기"일 때 작업 관리자로 앱과 `kookabug.exe`(daemon)를 끝낸다.

- 기대 결과: 다시 열면 기존 플러그인·잠금·그래프 실행이 그대로. 남은 임시 폴더는 다음 작업이 지우고, 미완성 환경은 [⋯ 정리]가 지운다

### H5 앱 SDK가 바뀐 뒤 (다음 판 설치본)

SDK 판이 다른 다음 판 설치본(또는 `KOOKABUG_SDK_WHEEL`로 다른 판 SDK wheel)으로 같은 워크스페이스를 연다.

- 기대 결과: "앱의 Python·SDK가 잠금과 달라요" 띠, 실행은 실행 전 검증 오류(`plugin_env_stale`). [다시 잠그기…] → 확인 카드 → 새 잠금(Git 변경으로 보임), 실행 통과. 실패면 잠금 그대로

### H6 신뢰 확인·권한 문구, 플러그인 화면 기본값

플러그인 사이드바·상세 탭·추가 대화 상자·신뢰 카드·준비 카드·진행·실패 결과·제거·정리 확인을 다크·라이트로 본다(샷 `.orchestration/M6/shots/B5/`·`B6/`). 권한 6종 뜻 문구, "권한은 노드가 선언한 범위를 알려 줄 뿐, 운영체제 수준에서 막지는 않아요" 안내, 화면 글에 로컬 절대 경로가 없음.

- 기대 결과: 문구·배치가 U1~U3 기본값 그대로 쓸 만한지(바꿀 것은 결과 양식 "별도 결정")

### H7 위젯 조작감·테마

예제 노드 "색 고르기"를 골라 인스펙터 설정 칸의 색 위젯(색 칸·코드·스와치)으로 고친다. 되돌리기(Ctrl+Z)·저장·실행 중(읽기 전용)·테마 바꾸기(다크·라이트).

- 기대 결과: 고친 값이 그래프에 저장되고 되돌리기가 위젯에 반영, 실행 중에는 위젯이 꺼진다, 테마를 바꾸면 위젯 색도 바뀐다. 위젯이 뜨지 않으면 5초 뒤 기본 편집기와 안내 문구

### H8 백신·SmartScreen과 동봉 uv

D2 설치본을 Windows Defender(실시간 보호 켬)·SmartScreen이 켜진 PC에 설치하고 H1을 설치본 앱으로 한다.

- 기대 결과: `tools\uv\uv.exe`가 격리·차단되지 않고 설치가 끝난다. 경고가 뜨면 문구·조치를 적는다

## 3. 기본값으로 진행한 사용자 결정 (U)

M6 계획 7장. 그대로 둘지 바꿀지 적는다.

| ID | 기본값 |
|---|---|
| U1 | 플러그인 관리 화면: 액티비티 바 "플러그인"·사이드바 목록·상세 탭·추가 대화 상자(Git 주소·wheel·폴더)·신뢰 카드·진행·결과, 상태 바 "플러그인 N" |
| U2 | 클론한 프로젝트는 띠로만 알리고 [준비…]에서 신뢰 확인, 한 번 신뢰한 잠금은 정규 잠금 해시로 기억(잠금이 바뀌면 다시 물음) |
| U3 | 에이전트는 설치·제거·준비·개발 모듈 실행을 사람 확인으로도 못 함(도구 없음) |
| U4 | 플러그인 노드 권한은 표시 + 선언 검사, OS 수준 차단 없음. 에이전트의 플러그인 그래프 실행은 기존 `kb_run_start` 판정 |
| U5 | 외부 레포 샘플은 이 레포 `examples/plugins/kookabug-plugin-sample`(MIT), 공개 GitHub 레포 생성은 사람 |
| U6 | `kookabug-sdk`·`@kookabug/ui-sdk` 이름 선점·게시는 사람(`python/kookabug_sdk/RELEASING.md`), 0.x 동안 소판이 호환 경계 |
| U7 | 격리 기본값 `auto`(충돌하면 그 플러그인만 격리) |
| U8 | UI 확장은 인스펙터 config 값 편집 위젯만 |
| U9 | 설치 원천은 git·wheel·폴더. PyPI 이름·정적 목록·검색 화면은 MVP 뒤 |
| U10 | 동봉 uv 라이선스: 허용 목록 밖 `CDLA-Permissive-2.0`(webpki-root-certs)은 근거와 함께 허용에 더함, MPL-2.0 크레이트 4개는 기존 조건부 규칙으로 |
| U11 | 의존성은 wheel만, sdist만 있는 의존성은 설치 거부 |
| U12 | 플러그인 wheel을 워크스페이스 `plugins/wheels/<sha256>/`에 커밋 |
| U13 | 환경 자동 삭제 없음, 사이드바 "정리"·`kookabug plugin gc`로만 |
| U14 | ssh git 원천은 MVP 뒤(`source_refused`), 비공개 레포는 https 주소의 토큰으로 |

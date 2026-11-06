"""플러그인 설치·잠금·환경 (M6). CLI `kookabug plugin …`와 daemon `plugins.*`가 같이 쓴다.

- `manifest`: wheel 정적 읽기·검사 (코드 실행 없음)
- `uv`·`resolve`: uv 찾기·실행(설치 작업 Job)·의존성 해석
- `envs`: 환경 지문·찾기·digest·완성 표식
- `lockfile`: `kookabug.lock` 형식·정규 해시·원자 쓰기
- `sources`: 원천 받기 (git·wheel·폴더, git 설정 격리·전송·ref 검사·인증 정보 가림)
- `ops`: 설치 거래(3.5, git·폴더는 staging 빌드)·upgrade·제거·목록·검증
- `sync`·`relock`: 잠금 → 환경 (잠금 안 씀) / 앱 조건으로 다시 잠금
- `trust`: 신뢰한 잠금 해시 기억 (`.kookabug/local.json`)
- `gc`: 사람이 부르는 정리(3.6)
"""

from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.layout import LOCK_FILE, Layout
from kookabug_core.plugins.ops import SDK_WHEEL_ENV, STAGES, AppInfo, PluginOps, Preview

__all__ = [
    "LOCK_FILE",
    "SDK_WHEEL_ENV",
    "STAGES",
    "AppInfo",
    "Layout",
    "PluginError",
    "PluginOps",
    "Preview",
]

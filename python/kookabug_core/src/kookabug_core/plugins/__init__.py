"""플러그인 설치·잠금·환경 (M6). CLI `kookabug plugin …`와 daemon `plugins.*`가 같이 쓴다.

- `manifest`: wheel 정적 읽기·검사 (코드 실행 없음)
- `uv`·`resolve`: uv 찾기·실행(설치 작업 Job)·의존성 해석
- `envs`: 환경 지문·찾기·digest·완성 표식
- `lockfile`: `kookabug.lock` 형식·정규 해시·원자 쓰기
- `ops`: 설치 거래(3.5)·제거·목록·검증
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

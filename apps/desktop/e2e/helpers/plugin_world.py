"""플러그인 E2E 준비 (M6 B5): 로컬 인덱스·SDK wheel·레포 밖 git 레포·픽스처 wheel. 네트워크 없음.

    python plugin_world.py serve <폴더>
        폴더에 세계를 만들고 인덱스 서버를 띄운 뒤 `READY <world.json 경로>`를 찍는다. 표준 입력이
        닫힐 때까지 서버를 둔다 (검사 끝에 끈다)
    python plugin_world.py install <world.json> <워크스페이스> <wheel 이름> [--drop-env] [--untrust]
        그 워크스페이스에 픽스처 wheel을 설치한다 (세계의 앱 SDK wheel·uv 캐시로).
        --drop-env면 만든 환경 폴더를 지워 "잠금은 있고 환경은 없음"을 만든다 (클론한 프로젝트).
        --untrust면 이 PC의 신뢰 기억을 지운다
    python plugin_world.py verify <world.json> <워크스페이스>
        실제 PluginOps.verify() (환경 파일이 바뀌었으면 깨짐 기록). 결과 JSON을 찍는다

world.json: index_url · sdk_wheel(앱 SDK) · sdk_wheel_next(다른 판 — 조건 다름) ·
appdata(uv 캐시가 드는 LOCALAPPDATA) · git_repo(예제 플러그인 git 레포 file:// 주소) ·
wheels{이름: 경로}
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

from kb_testing.plugin_fixtures import (  # noqa: E402
    PLUGINS,
    SAMPLE,
    git_repo,
    index_files,
    plugin_wheel,
    sdk_wheel,
)
from kb_testing.plugin_index import IndexServer  # noqa: E402


def _broken_import() -> bytes:
    return b'raise RuntimeError("broken_import fixture")\n'


def serve(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    files = index_files(root / "index")
    sdk = sdk_wheel(root / "sdk")
    sdk_next = sdk_wheel(root / "sdk-next", version="0.1.1")
    appdata = root / "appdata"
    appdata.mkdir(exist_ok=True)
    repo = git_repo(SAMPLE, root / "repos" / "kookabug-plugin-sample")
    wheels = {
        "sample": plugin_wheel(SAMPLE, root / "wheels" / "sample"),
        # 의존성이 충돌하는 둘 (b는 격리된다) — 샷의 목록 줄
        "conflict_a": plugin_wheel(PLUGINS / "conflict_a", root / "wheels" / "conflict_a"),
        "conflict_b": plugin_wheel(PLUGINS / "conflict_b", root / "wheels" / "conflict_b"),
        "broken_import": plugin_wheel(
            PLUGINS / "conflict_a",
            root / "wheels" / "broken_import",
            overrides={"kbfix_conflict_a/nodes.py": _broken_import()},
        ),
        # 위젯 격리 탐침 (B6): 네트워크·다른 플러그인 자원·프레임 이동을 시도한다
        "widget_probe": plugin_wheel(PLUGINS / "widget_probe", root / "wheels" / "widget_probe"),
    }
    with IndexServer(files) as index:
        world = {
            "index_url": index.url,
            "sdk_wheel": str(sdk),
            "sdk_wheel_next": str(sdk_next),
            "appdata": str(appdata),
            "git_repo": repo.as_uri(),
            "wheels": {k: str(v) for k, v in wheels.items()},
        }
        path = root / "world.json"
        path.write_text(json.dumps(world, indent=2), encoding="utf-8")
        print(f"READY {path}", flush=True)
        sys.stdin.read()


def install(world_path: Path, workspace: Path, name: str, *, drop_env: bool, untrust: bool) -> None:
    from kookabug_core.plugins import SDK_WHEEL_ENV, PluginOps

    world = json.loads(world_path.read_text(encoding="utf-8"))
    environ = {k: v for k, v in os.environ.items() if not k.upper().startswith("KOOKABUG_")}
    environ.update({"LOCALAPPDATA": world["appdata"], SDK_WHEEL_ENV: world["sdk_wheel"]})
    ops = PluginOps(workspace, environ=environ)
    ops.add(world["wheels"][name], confirm=lambda _: True)
    if drop_env:
        shutil.rmtree(workspace / ".kookabug" / "plugins", ignore_errors=True)
    if untrust:
        local = workspace / ".kookabug" / "local.json"
        if local.is_file():
            data = json.loads(local.read_text(encoding="utf-8-sig"))
            data.pop("plugin_trust", None)
            local.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("INSTALLED", flush=True)


def verify(world_path: Path, workspace: Path) -> None:
    """실제 `PluginOps.verify()` (digest 재계산 — 바뀐 환경은 깨짐 기록). 결과 JSON을 찍는다."""
    from kookabug_core.plugins import SDK_WHEEL_ENV, PluginOps

    world = json.loads(world_path.read_text(encoding="utf-8"))
    environ = {k: v for k, v in os.environ.items() if not k.upper().startswith("KOOKABUG_")}
    environ.update({"LOCALAPPDATA": world["appdata"], SDK_WHEEL_ENV: world["sdk_wheel"]})
    print(
        json.dumps(PluginOps(workspace, environ=environ).verify(), ensure_ascii=False), flush=True
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["verify"] and len(argv) == 3:
        verify(Path(argv[1]), Path(argv[2]))
        return 0
    if argv[:1] == ["serve"] and len(argv) == 2:
        serve(Path(argv[1]))
        return 0
    if argv[:1] == ["install"] and len(argv) >= 4:
        flags = set(argv[4:])
        install(
            Path(argv[1]),
            Path(argv[2]),
            argv[3],
            drop_env="--drop-env" in flags,
            untrust="--untrust" in flags,
        )
        return 0
    print(__doc__, file=sys.stderr)
    return 6


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""플러그인 검사 헬퍼 (M6 B1). 네트워크 없이 실제 uv·venv를 쓴다.

검사 폴더의 conftest가 `plugin_world`(세션)·`rig`(검사) 픽스처로 쓴다:

- 세션 하나: SDK wheel(레포 소스), 로컬 인덱스 서버(`kbfix-dep` 1·2, sdist만 있는 전이 의존성),
  플러그인 wheel(예제·충돌 픽스처·깨진 것), 임시 uv 캐시(`LOCALAPPDATA`를 임시 폴더로 — 이 PC의
  실제 캐시를 쓰지 않는다)
- 검사 하나: 워크스페이스(`plugin_index` = 로컬 인덱스)와 `PluginOps`
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from helpers.graphs import make_workspace
from kb_testing.plugin_fixtures import PLUGINS, SAMPLE, index_files, plugin_wheel, sdk_wheel
from kb_testing.plugin_index import IndexServer
from kb_testing.proc import direct_env, python_cmd
from kookabug_core.plugins import SDK_WHEEL_ENV, PluginOps, Preview
from kookabug_core.plugins.envs import find_env


@dataclass
class PluginWorld:
    root: Path
    sdk: Path
    index: IndexServer
    environ: dict[str, str]
    wheels: dict[str, Path] = field(default_factory=dict[str, Path])

    def wheel(self, name: str) -> Path:
        """이름 있는 픽스처 wheel (세션에 한 번 만든다)."""
        if name not in self.wheels:
            self.wheels[name] = _build(name, self.root / "wheels" / name)
        return self.wheels[name]


def _broken_import() -> bytes:
    return b'raise RuntimeError("broken_import fixture")\n'


def _schema_drift() -> bytes:
    # 스키마 파일을 만든 뒤 코드의 노드 제목을 바꾼다: 파일 digest ≠ 코드 digest
    source = (PLUGINS / "conflict_a" / "src" / "kbfix_conflict_a" / "nodes.py").read_text("utf-8")
    return source.replace('title="의존성 판"', 'title="바뀐 제목"').encode("utf-8")


def _build(name: str, dest: Path) -> Path:
    project = {"sample": SAMPLE}.get(name)
    if project is not None:
        return plugin_wheel(project, dest)
    if name in ("conflict_a", "conflict_b", "compatible_c"):
        return plugin_wheel(PLUGINS / name, dest)
    a = PLUGINS / "conflict_a"
    if name == "conflict_a_v2":  # 같은 ID의 다른 판
        return plugin_wheel(a, dest, version="0.2.0")
    if name == "broken_import":
        return plugin_wheel(a, dest, overrides={"kbfix_conflict_a/nodes.py": _broken_import()})
    if name == "schema_drift":
        return plugin_wheel(a, dest, overrides={"kbfix_conflict_a/nodes.py": _schema_drift()})
    if name == "unresolvable":
        return plugin_wheel(
            a,
            dest,
            pyproject_edit=lambda d: d["project"]["dependencies"].append("kbfix-missing>=1"),
        )
    if name == "sdist_only":
        return plugin_wheel(
            a, dest, pyproject_edit=lambda d: d["project"]["dependencies"].append("kbfix-mid>=1")
        )
    if name == "sdk_too_new":
        return plugin_wheel(
            a,
            dest,
            pyproject_edit=lambda d: d["project"].update(
                dependencies=["kookabug-sdk>=0.2,<0.3", "kbfix-dep==1.*"]
            ),
        )
    if name == "bad_effects":
        return plugin_wheel(SAMPLE, dest, schema_edit=lambda s: s["plugin"].update(permissions=[]))
    if name == "id_core":

        def to_core(s: dict[str, Any]) -> None:
            s["plugin"]["id"] = "core"
            for node in s["nodes"]:
                node["type"] = "core." + node["type"].split(".", 1)[1]

        return plugin_wheel(a, dest, schema_edit=to_core)
    if name == "shared_declared":
        return plugin_wheel(
            PLUGINS / "compatible_c",
            dest,
            pyproject_edit=lambda d: d["tool"]["kookabug"].update(isolation="shared"),
            version="0.1.1",
        )
    c = PLUGINS / "compatible_c"
    if name in ("sdk_user", "sdk_consumer"):  # 전이 의존성의 SDK 요구 (맞음 / 안 맞음)
        dep = {"sdk_user": "kbfix-sdk-user==1.0.0", "sdk_consumer": "kbfix-sdk-consumer==1.0.0"}

        return plugin_wheel(
            c, dest, pyproject_edit=lambda d: d["project"]["dependencies"].append(dep[name])
        )
    if name == "self_write":  # 검증 import에서 자기 환경의 의존성 파일을 제자리에 쓰고 실패
        return plugin_wheel(c, dest, overrides={"kbfix_compatible_c/nodes.py": _SELF_WRITE})
    raise KeyError(name)


_SELF_WRITE = (
    b"from pathlib import Path\n"
    b"import kbfix_dep\n"
    b"Path(kbfix_dep.__file__).write_text('__version__ = \"damaged\"\\n')\n"
    b"raise RuntimeError('self_write fixture')\n"
)


@pytest.fixture(scope="session")
def plugin_world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PluginWorld]:
    if shutil.which("uv") is None:
        pytest.skip("uv가 없다")
    root = tmp_path_factory.mktemp("plugin-world")
    files = index_files(root / "index")
    sdk = sdk_wheel(root / "sdk")
    appdata = root / "appdata"
    appdata.mkdir()
    environ = {k: v for k, v in os.environ.items() if not k.upper().startswith("KOOKABUG_")}
    environ.update({"LOCALAPPDATA": str(appdata), SDK_WHEEL_ENV: str(sdk)})
    with IndexServer(files) as index:
        yield PluginWorld(root, sdk, index, environ)


@dataclass
class Rig:
    world: PluginWorld
    root: Path
    faults: list[str] = field(default_factory=list[str])
    fail_at: str | None = None

    def ops(self, **kwargs: Any) -> PluginOps:
        def fault(stage: str) -> None:
            self.faults.append(stage)
            if stage == self.fail_at:
                raise RuntimeError(f"fault at {stage}")

        return PluginOps(self.root, environ=self.world.environ, fault=fault, **kwargs)

    def add(self, name: str, **kwargs: Any) -> dict[str, Any]:
        return self.ops().add(str(self.world.wheel(name)), confirm=_yes, **kwargs)

    def lock(self) -> dict[str, Any]:
        return json.loads((self.root / "kookabug.lock").read_text(encoding="utf-8"))

    def lock_bytes(self) -> bytes | None:
        path = self.root / "kookabug.lock"
        return path.read_bytes() if path.is_file() else None

    @property
    def envs(self) -> Path:
        return self.root / ".kookabug" / "plugins" / "envs"

    def env_dir(self, name: str) -> Path:
        """잠금의 그 환경을 runner처럼 찾는다 (`find_env`)."""
        fp = self.lock()["environments"][name]["fingerprint"]
        found = find_env(self.envs, name, fp)
        assert found is not None, name
        return found


def _yes(preview: Preview | dict[str, Any]) -> bool:
    return True


@pytest.fixture
def rig(plugin_world: PluginWorld, tmp_path: Path) -> Rig:
    root = tmp_path / "ws"
    make_workspace(root)
    data = json.loads((root / "kookabug.json").read_text(encoding="utf-8"))
    data["plugin_index"] = {"url": plugin_world.index.url}
    (root / "kookabug.json").write_text(json.dumps(data), encoding="utf-8")
    return Rig(plugin_world, root.resolve())


_RUN_NODE = (
    "import json, sys\n"
    "from kookabug_sdk.testing import fake_context\n"
    "from kookabug_sdk.worker import collect_plugins, functions_of\n"
    "modules = json.loads(sys.argv[1])\n"
    "collect_plugins(modules)\n"
    "fn = functions_of(modules)[sys.argv[2]]\n"
    "result = fn.invoke(fake_context(), json.loads(sys.argv[3]))\n"
    "print(json.dumps({'exit': result.exit, 'outputs': dict(result.outputs)}))\n"
)

_HELLO = (
    "import json, sys\n"
    "from kookabug_sdk.worker import collect_plugins\n"
    "print(json.dumps(collect_plugins(json.loads(sys.argv[1]))))\n"
)


def env_run(env_dir: Path, code: str, *args: str) -> str:
    """환경 인터프리터(`-I`)로 코드를 돌려 stdout을 돌려준다 (실패면 AssertionError)."""
    proc = subprocess.run(
        [str(env_dir / "Scripts" / "python.exe"), "-I", "-c", code, *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def run_node(
    env_dir: Path, modules: list[str], node_type: str, inputs: dict[str, Any] | None = None
) -> dict[str, Any]:
    """설치된 환경에서 노드 하나를 가짜 ctx로 돌린다 (워커와 같은 모음 함수)."""
    out = env_run(env_dir, _RUN_NODE, json.dumps(modules), node_type, json.dumps(inputs or {}))
    return json.loads(out.strip().splitlines()[-1])


def hello(env_dir: Path, modules: list[str]) -> list[dict[str, Any]]:
    """설치된 환경에서 워커 hello의 플러그인 목록 (`collect_plugins`)."""
    return json.loads(env_run(env_dir, _HELLO, json.dumps(modules)).strip().splitlines()[-1])


def cli_env(world: PluginWorld, faults: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """`kookabug plugin …` 하위 프로세스 환경 (세션의 임시 캐시·SDK wheel, 고장 규칙)."""
    env = direct_env(world.environ)
    if faults:
        env["KOOKABUG_FAULTS"] = json.dumps(faults)
    return env


def plugin_cli(
    rig: Rig, *args: str | Path, faults: list[dict[str, Any]] | None = None, **extra: str
) -> subprocess.CompletedProcess[str]:
    env = {**cli_env(rig.world, faults), **extra}
    return subprocess.run(
        python_cmd("-m", "kookabug_cli", "plugin", *args, "--workspace", rig.root),
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=300,
        check=False,
    )


def hang_wheel(world: PluginWorld, dest: Path, pid_file: Path) -> Path:
    """import 중 멈추는 플러그인 (`hang_import`): 실제 인터프리터·런처 PID를 파일에 쓰고 멈춘다."""
    code = (
        "import os, time\n"
        "from pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(f'{{os.getpid()}} {{os.getppid()}}')\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    return plugin_wheel(
        PLUGINS / "conflict_a", dest, overrides={"kbfix_conflict_a/nodes.py": code.encode()}
    )


def write_then_hang_wheel(dest: Path, pid_file: Path) -> Path:
    """`compatible_c` 바탕: 검증 import에서 자기 환경의 `kbfix_dep` 파일을 제자리에 쓴 뒤 PID를
    남기고 멈춘다 (kill 검사용)."""
    code = (
        "import os, time\n"
        "from pathlib import Path\n"
        "import kbfix_dep\n"
        "Path(kbfix_dep.__file__).write_text('__version__ = \"damaged\"\\n')\n"
        f"Path({str(pid_file)!r}).write_text(f'{{os.getpid()}} {{os.getppid()}}')\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    return plugin_wheel(
        PLUGINS / "compatible_c", dest, overrides={"kbfix_compatible_c/nodes.py": code.encode()}
    )


@pytest.fixture
def own_index(rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """이 검사만의 인덱스(세션 인덱스와 같은 묶음 + 검사가 더하는 파일)와 빈 uv 캐시. 인덱스
    파일 폴더를 돌려준다 — 거기에 wheel을 더하면 다음 요청부터 보인다."""
    files = index_files(tmp_path / "own-index")
    with IndexServer(files) as index:
        monkeypatch.setattr(rig.world, "index", index)
        monkeypatch.setitem(rig.world.environ, "LOCALAPPDATA", str(tmp_path / "own-appdata"))
        path = rig.root / "kookabug.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["plugin_index"] = {"url": index.url}
        path.write_text(json.dumps(config), encoding="utf-8")
        yield files


def cache_hashes(environ: dict[str, str]) -> dict[str, str]:
    """임시 uv 캐시(`LOCALAPPDATA\\Kookabug\\uv-cache`)의 모든 `.py` 파일 바이트 해시."""
    cache = Path(environ["LOCALAPPDATA"]) / "Kookabug" / "uv-cache"
    return {
        p.relative_to(cache).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(cache.rglob("*.py"))
        if p.is_file()
    }


def tree_hashes(folder: Path) -> dict[str, str]:
    """폴더 아래 모든 파일의 바이트 해시 (불변 확인용)."""
    if not folder.exists():
        return {}
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def tree_mtimes(folder: Path) -> dict[str, int]:
    return {
        p.relative_to(folder).as_posix(): p.stat().st_mtime_ns
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


YES: Callable[[Any], bool] = _yes


def git_source(repo: Path, ref: str | None = "v0.1.0") -> str:
    """로컬 git 레포의 원천 문자열 `git+file:///…[@ref]`."""
    return f"git+{repo.as_uri()}" + (f"@{ref}" if ref else "")


def calls_with(ops: PluginOps, *needles: str) -> list[tuple[str, ...]]:
    """자식 명령 기록 중 인자에 `needles`가 모두 든 것."""
    return [c for c in ops.calls if all(any(n in a for a in c) for n in needles)]

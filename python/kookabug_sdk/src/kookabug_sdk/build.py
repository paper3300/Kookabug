"""`kookabug-sdk build`: 플러그인 프로젝트의 노드를 읽어 노드 스키마 JSON을 만든다.

- `pyproject.toml`의 `[tool.kookabug].modules`를 import해 `@node` 노드를 모은다
- 출력: `src/<최상위 패키지>/kookabug.schema.json` (최상위 패키지 = `modules` 첫 항목의 첫 이름)
- 같은 코드면 같은 바이트: 키 정렬, 노드는 type 순, 시각·경로 같은 환경 값은 넣지 않는다
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from kookabug_sdk.decorators import NodeDeclarationError, NodeFunction
from kookabug_sdk.schema import FORMAT, SCHEMA_FILE

__all__ = ["BuildError", "BuildOutput", "PluginProject", "build", "dumps", "read_project"]

PERMISSIONS: Final = frozenset({"capture", "input", "process", "filesystem", "network", "secrets"})
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class BuildError(Exception):
    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True, slots=True)
class PluginProject:
    root: Path
    id: str
    title: str | None
    version: str
    modules: tuple[str, ...]
    permissions: frozenset[str]

    @property
    def package(self) -> str:
        return self.modules[0].split(".", 1)[0]

    @property
    def src(self) -> Path:
        return self.root / "src"

    @property
    def output(self) -> Path:
        return self.src / self.package / SCHEMA_FILE


@dataclass(frozen=True, slots=True)
class BuildOutput:
    path: Path
    document: dict[str, Any]
    text: str


def read_project(root: str | Path) -> PluginProject:
    root = Path(root).resolve()
    pyproject = root / "pyproject.toml"
    try:
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
    except OSError as exc:
        raise BuildError([f"{pyproject}을(를) 읽을 수 없다: {exc}"]) from exc
    except tomllib.TOMLDecodeError as exc:
        raise BuildError([f"{pyproject}: {exc}"]) from exc

    problems: list[str] = []
    project = data.get("project", {})
    tool = data.get("tool", {}).get("kookabug")
    if not isinstance(tool, dict):
        raise BuildError([f"{pyproject}에 [tool.kookabug]가 없다"])

    plugin_id = tool.get("id")
    if not isinstance(plugin_id, str) or not _PLUGIN_ID.match(plugin_id):
        problems.append("[tool.kookabug].id는 소문자로 시작하는 소문자·숫자·밑줄 이름이다")
    title = tool.get("title")
    if title is not None and not isinstance(title, str):
        problems.append("[tool.kookabug].title은 문자열이다")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        problems.append("[project].version이 없다 (dynamic version은 아직 지원하지 않는다)")
    modules = tool.get("modules")
    if (
        not isinstance(modules, list)
        or not modules
        or not all(isinstance(m, str) and _MODULE.match(m) for m in modules)
    ):
        problems.append("[tool.kookabug].modules는 import 경로 목록이다 (하나 이상)")
        modules = []
    permissions = tool.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        problems.append("[tool.kookabug].permissions는 문자열 목록이다")
        permissions = []
    elif unknown := sorted(set(permissions) - PERMISSIONS):
        problems.append(f"모르는 permissions {unknown}. 가능한 값: {sorted(PERMISSIONS)}")
    if problems:
        raise BuildError(problems)

    out = PluginProject(
        root=root,
        id=str(plugin_id),
        title=title,
        version=str(version),
        modules=tuple(modules),
        permissions=frozenset(permissions),
    )
    if not (out.src / out.package).is_dir():
        raise BuildError([f"패키지 폴더 {out.src / out.package}가 없다 (src 레이아웃)"])
    return out


def collect_nodes(project: PluginProject) -> list[NodeFunction]:
    """`modules`를 import해 모듈에 있는 노드를 모은다. 끝나면 import한 모듈을 지운다."""
    problems: list[str] = []
    found: dict[int, NodeFunction] = {}
    src = str(project.src)
    before = set(sys.modules)
    sys.path.insert(0, src)
    importlib.invalidate_caches()
    try:
        for name in project.modules:
            try:
                module = importlib.import_module(name)
            except NodeDeclarationError as exc:
                problems.append(f"{name}: {exc}")
                continue
            except Exception as exc:
                problems.append(f"{name}을(를) import할 수 없다: {type(exc).__name__}: {exc}")
                continue
            if not _inside(module, project.src):
                problems.append(f"{name}이(가) 프로젝트 밖({module.__file__})에서 import됐다")
                continue
            for value in vars(module).values():
                if isinstance(value, NodeFunction):
                    found.setdefault(id(value), value)
    finally:
        sys.path.remove(src)
        package = project.package
        for name in set(sys.modules) - before:
            if name == package or name.startswith(package + "."):
                del sys.modules[name]
    if problems:
        raise BuildError(problems)
    return sorted(found.values(), key=lambda n: n.spec.type)


def _inside(module: ModuleType, src: Path) -> bool:
    file = getattr(module, "__file__", None)
    return file is not None and Path(file).resolve().is_relative_to(src.resolve())


def schema_document(project: PluginProject, nodes: Sequence[NodeFunction]) -> dict[str, Any]:
    problems: list[str] = []
    if not nodes:
        problems.append(f"{', '.join(project.modules)}에 @node 노드가 없다")
    seen: dict[str, NodeFunction] = {}
    for n in nodes:
        spec = n.spec
        if spec.plugin != project.id:
            problems.append(f"{spec.type}: 노드 타입은 플러그인 ID '{project.id}.'로 시작해야 한다")
        if spec.type in seen:
            problems.append(f"{spec.type}: 같은 타입의 노드가 둘 있다")
        seen[spec.type] = n
        if missing := sorted(spec.effects - project.permissions):
            problems.append(
                f"{spec.type}: effects {missing}을(를) [tool.kookabug].permissions에 선언해야 한다"
            )
    if problems:
        raise BuildError(problems)

    plugin: dict[str, Any] = {"id": project.id, "version": project.version}
    if project.title:
        plugin["title"] = project.title
    return {
        "format": FORMAT,
        "nodes": [n.schema() for n in sorted(nodes, key=lambda n: n.spec.type)],
        "plugin": plugin,
    }


def dumps(document: dict[str, Any]) -> str:
    # NaN·Infinity는 JSON이 아니다. 선언 검사가 막지만 쓰기에서도 한 번 더 막는다
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def build(root: str | Path, *, write: bool = True) -> BuildOutput:
    project = read_project(root)
    document = schema_document(project, collect_nodes(project))
    try:
        text = dumps(document)
    except (TypeError, ValueError) as exc:
        raise BuildError([f"노드 스키마를 JSON으로 쓸 수 없다: {exc}"]) from exc
    if write:
        project.output.write_text(text, encoding="utf-8", newline="\n")
    return BuildOutput(project.output, document, text)

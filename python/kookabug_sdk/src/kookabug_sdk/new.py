"""`kookabug-sdk new`: 플러그인 프로젝트 틀을 만든다 (M6 계획 D13).

    kookabug-sdk new acme-tools --id acme [--title "Acme Tools"] [--ui]

- `src` 레이아웃, 패키지 `kookabug_plugin_<id>`, 진입 모듈 `<패키지>.nodes`, 순수 노드 하나
- SDK 의존 범위는 이 SDK 판의 소판 (0.x 동안 소판이 호환 경계 — `RELEASING.md`)
- `--ui`면 위젯 노드 하나와 `ui/index.js`·`ui/kookabug-ui.js`(@kookabug/ui-sdk 사본)
- 틀 파일은 `templates/plugin/*.tmpl`. 빈 폴더(또는 없는 폴더)에만 쓴다
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Final

from kookabug_sdk.build import read_project

__all__ = ["RESERVED_IDS", "NewProjectError", "create_project", "sdk_range"]

RESERVED_IDS: Final = frozenset({"core", "kookabug", "testkit"})
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION = re.compile(r"^(\d+)\.(\d+)")
_UI_README = """
## 위젯 (UI 확장)

`ui/index.js`가 인스펙터 설정 칸의 위젯을 그린다 (`Config(..., ui=Widget("이름"))`). 위젯은 샌드박스
iframe에서 돌고 이 폴더 파일만 읽을 수 있다 — 네트워크·파일·앱 RPC에 접근할 수 없다.
`ui/kookabug-ui.js`는 `@kookabug/ui-sdk`의 사본이다.
"""


class NewProjectError(Exception):
    pass


def sdk_range(version: str) -> str:
    """이 SDK 판으로 만든 플러그인의 의존 범위: `>=0.N,<0.N+1` (개발 판이면 하한이 그 판)."""
    m = _VERSION.match(version)
    if m is None:
        raise NewProjectError(f"SDK 판 {version!r}을(를) 읽을 수 없다")
    major, minor = int(m.group(1)), int(m.group(2))
    upper = f"{major}.{minor + 1}" if major == 0 else f"{major + 1}"
    lower = version if re.search(r"(a|b|rc|\.dev)\d+$", version) else f"{major}.{minor}"
    return f">={lower},<{upper}"


def _template(name: str) -> str:
    return (
        resources.files("kookabug_sdk")
        .joinpath("templates", "plugin", name)
        .read_text(encoding="utf-8")
    )


def create_project(
    folder: str | Path, plugin_id: str, *, title: str | None = None, ui: bool = False
) -> list[Path]:
    """틀을 쓰고 쓴 파일 목록을 돌려준다. 만든 프로젝트는 `kookabug-sdk build`가 바로 통과한다."""
    from kookabug_sdk import __version__

    if not _ID.match(plugin_id):
        raise NewProjectError("ID는 소문자로 시작하는 소문자·숫자·밑줄 이름이다 (예: acme_tools)")
    if plugin_id in RESERVED_IDS:
        raise NewProjectError(f"ID {plugin_id!r}은(는) 예약돼 있다")
    root = Path(folder)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise NewProjectError(f"{root}이(가) 비어 있지 않다")
    title = title or plugin_id.replace("_", " ").title()
    if any(c in title for c in '"\\\n'):
        raise NewProjectError("title에 따옴표·역슬래시·줄바꿈은 쓸 수 없다")
    package = f"kookabug_plugin_{plugin_id}"
    values = {
        "__DIST__": f"kookabug-plugin-{plugin_id.replace('_', '-')}",
        "__PKG__": package,
        "__ID__": plugin_id,
        "__TITLE__": title,
        "__SDK_RANGE__": sdk_range(__version__),
        "__UI_LINE__": '# 위젯 폴더 (패키지 안, 진입 index.js)\nui = "ui"\n' if ui else "",
        "__UI_README__": _UI_README if ui else "",
        "__IMPORTS__": ("Config, Context, Exit, Result, Widget, node" if ui else "Context, node"),
        "__UI_NODE__": _template("nodes_ui.py.tmpl") if ui else "",
    }

    def fill(text: str) -> str:
        # __UI_NODE__를 먼저 채운다 (그 안의 자리표시자도 채우게)
        text = text.replace("__UI_NODE__", values["__UI_NODE__"])
        for key, value in values.items():
            text = text.replace(key, value)
        return text

    files = {
        "pyproject.toml": fill(_template("pyproject.toml.tmpl")),
        "README.md": fill(_template("README.md.tmpl")),
        ".gitignore": fill(_template("gitignore.tmpl")),
        f"src/{package}/__init__.py": f'"""{title} — Kookabug 플러그인 `{plugin_id}`."""\n',
        f"src/{package}/nodes.py": fill(_template("nodes.py.tmpl")),
    }
    if ui:
        files[f"src/{package}/ui/index.js"] = fill(_template("ui/index.js.tmpl"))
        files[f"src/{package}/ui/kookabug-ui.js"] = _template("ui/kookabug-ui.js")
    written: list[Path] = []
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    read_project(root)  # 매니페스트가 build 규칙에 맞는지 바로 확인한다
    return written

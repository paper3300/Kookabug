"""메타스키마 → Python 생성물.

`packages/schema/*.schema.json`(단일 출처)에서
- `kookabug_core/schema/json/`에 같은 바이트로 복사 (wheel에 들어가 런타임 형식 검사가 읽는다)
- `kookabug_core/schema/models/<종류>.py`에 pydantic v2 모델 생성 (datamodel-code-generator)

    uv run python tools/gen_schema.py          # 다시 만든다
    uv run python tools/gen_schema.py --check  # 커밋된 생성물과 다르면 실패

메타스키마 파일 자체도 정해진 JSON 형식(canonical_dumps)이어야 한다.
TS 타입은 `pnpm -r run gen`(packages/schema/scripts/gen.mjs)이 만든다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from kookabug_core.canonical import canonical_dumps
from kookabug_sdk.console import utf8_stdio

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "packages" / "schema"
CORE_SCHEMA = REPO_ROOT / "python" / "kookabug_core" / "src" / "kookabug_core" / "schema"
KINDS = ("graph", "target", "workspace", "local", "node-schema", "events", "run")

MODELS_INIT = '''\
"""메타스키마에서 생성한 pydantic v2 모델 (tools/gen_schema.py). 직접 고치지 않는다.

형식 검사는 `kookabug_core.schema.check_shape`가 한다. 모델은 검사를 통과한 값을 타입 있게
읽을 때 쓴다. 저장은 원래 dict를 `canonical_dumps`로 쓴다 (모델은 숫자를 float로 바꿀 수 있다).
"""
'''

HEADER = "# 생성물 (packages/schema/{name} → tools/gen_schema.py). 직접 고치지 않는다."

# in 핀 값(Value)은 재귀·조건부 모양이라 생성기가 표현하지 못한다. 모양은 jsonschema가 검사하고,
# 모델에서는 JSON 값 그대로 둔다
TYPE_OVERRIDES = {"graph": {"Value": "pydantic.JsonValue"}}


def module_name(kind: str) -> str:
    return kind.replace("-", "_")


def schema_path(kind: str) -> Path:
    return SCHEMA_DIR / f"{kind}.schema.json"


def check_sources() -> list[str]:
    """메타스키마 파일이 정해진 JSON 형식인지."""
    problems = []
    for kind in KINDS:
        text = schema_path(kind).read_text(encoding="utf-8")
        if text != canonical_dumps(json.loads(text)):
            problems.append(f"{schema_path(kind).relative_to(REPO_ROOT)}: canonical 형식이 아니다")
    return problems


def _ruff(*args: str | Path) -> None:
    # 레포 밖 임시 폴더의 파일도 레포 설정으로 정리한다. 생성물의 설명 문자열·정규식은 줄이지
    # 않으므로 줄 길이 검사는 뺀다 (레포 설정의 per-file-ignores와 같다)
    config = REPO_ROOT / "pyproject.toml"
    cmd = [sys.executable, "-m", "ruff", *map(str, args), "--config", str(config), "--quiet"]
    if args[0] == "check":
        cmd += ["--extend-ignore", "E501"]
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def generate_models(work: Path) -> dict[str, str]:
    """{models/ 안 파일 이름: 내용}."""
    out: dict[str, str] = {"__init__.py": MODELS_INIT}
    for kind in KINDS:
        target = work / f"{module_name(kind)}.py"
        cmd = [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(schema_path(kind)),
            "--input-file-type",
            "jsonschema",
            "--output",
            str(target),
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.14",
            "--disable-timestamp",
            "--use-standard-collections",
            "--use-union-operator",
            "--use-title-as-name",
            "--use-schema-description",
            "--use-annotated",
            "--use-double-quotes",
            "--enum-field-as-literal",
            "all",
            "--formatters",
            "builtin",
            "--custom-file-header",
            HEADER.format(name=schema_path(kind).name),
        ]
        if kind in TYPE_OVERRIDES:
            cmd += ["--type-overrides", json.dumps(TYPE_OVERRIDES[kind])]
        subprocess.run(cmd, check=True, cwd=REPO_ROOT, capture_output=True)
        out[target.name] = ""
    files = [work / name for name in out if name != "__init__.py"]
    _ruff("check", "--fix", "--unsafe-fixes", *files)
    _ruff("format", *files)
    for name in out:
        if name != "__init__.py":
            out[name] = (work / name).read_text(encoding="utf-8")
    return out


def expected_outputs() -> dict[Path, bytes]:
    """생성물 전체: {레포 안 경로: 내용}."""
    result: dict[Path, bytes] = {}
    for kind in KINDS:
        result[CORE_SCHEMA / "json" / f"{kind}.schema.json"] = schema_path(kind).read_bytes()
    with tempfile.TemporaryDirectory(prefix="kb-gen-") as tmp:
        for name, text in generate_models(Path(tmp)).items():
            result[CORE_SCHEMA / "models" / name] = text.encode("utf-8")
    return result


def stale_outputs(expected: dict[Path, bytes]) -> list[Path]:
    """다시 만든 결과와 다른 파일, 생성물 폴더에 남은 다른 파일."""
    stale = [p for p, data in expected.items() if not p.is_file() or p.read_bytes() != data]
    for folder, pattern in ((CORE_SCHEMA / "json", "*.json"), (CORE_SCHEMA / "models", "*.py")):
        stale += [p for p in folder.glob(pattern) if p not in expected]
    return sorted(stale)


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description="메타스키마 → Python 생성물")
    parser.add_argument("--check", action="store_true", help="쓰지 않고 차이만 확인")
    args = parser.parse_args(argv)

    problems = check_sources()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    expected = expected_outputs()
    stale = stale_outputs(expected)
    if args.check:
        for path in stale:
            print(f"생성물이 다르다: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for path in stale:
        if path in expected:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected[path])
        else:
            path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from kb_testing.packaging import REPO_ROOT
from kookabug_sdk.build import build

PROJECT = REPO_ROOT / "python" / "kookabug_nodes"


def test_schema_json_up_to_date() -> None:
    out = build(PROJECT, write=False)
    assert out.path == PROJECT / "src" / "kookabug_nodes" / "kookabug.schema.json"
    committed = out.path.read_bytes().decode("utf-8")
    assert committed == out.text, "uv run kookabug-sdk build python/kookabug_nodes 로 다시 만든다"

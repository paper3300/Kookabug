from pathlib import Path

from helpers.graphs import GraphBuilder, check_program, make_workspace, only, secret

from kookabug_core.ir import Unresolved
from kookabug_core.workspace import EnvSecrets, MemorySecrets, SecretChain, secret_env_name
from kookabug_sdk import Secret

GRAPH = "tests/secret.graph.json"


def write_graph(tmp_path: Path) -> str:
    ws = make_workspace(tmp_path)
    return (
        GraphBuilder()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": secret("accounts.qa_tester_01")})
        .write(ws, GRAPH)
    )


def test_secret_env_var_name_mapping() -> None:
    assert secret_env_name("accounts.qa_tester_01") == "KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01"
    assert secret_env_name("token") == "KOOKABUG_SECRET_TOKEN"
    env = EnvSecrets({"KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01": "pw"})
    assert env.get("accounts.qa_tester_01") == "pw"
    assert env.get("accounts.other") is None


def test_secret_chain_order() -> None:
    chain = SecretChain(MemorySecrets({"a": "first"}), MemorySecrets({"a": "second", "b": "b"}))
    assert (chain.get("a"), chain.get("b"), chain.get("c")) == ("first", "b", None)


def test_secret_missing_is_error(tmp_path: Path) -> None:
    rel = write_graph(tmp_path)
    ws = make_workspace(tmp_path)
    program, diags = check_program(ws, rel, secrets=EnvSecrets({}))
    (d,) = only(diags, "secret_missing")
    assert (d.severity, d.node, d.pointer) == ("error", "n_log", "/nodes/n_log/in/text")
    assert "accounts.qa_tester_01" in d.message
    value = program.graphs[GRAPH].nodes["n_log"].inputs["text"]
    assert value == Unresolved("$secret", "accounts.qa_tester_01")


def test_secret_value_wrapped(tmp_path: Path) -> None:
    rel = write_graph(tmp_path)
    ws = make_workspace(tmp_path)
    env = EnvSecrets({"KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01": "hunter2"})
    program, diags = check_program(ws, rel, secrets=env)
    assert diags == []
    value = program.graphs[GRAPH].nodes["n_log"].inputs["text"]
    assert isinstance(value, Secret)
    assert value.reveal() == "hunter2"
    assert "hunter2" not in repr(program.graphs[GRAPH].nodes["n_log"])

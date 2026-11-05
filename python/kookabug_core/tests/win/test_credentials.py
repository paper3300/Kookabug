"""Windows 자격 증명 관리자 (M4 계획 2.8, C11, T7). 실제 자격 증명 관리자에 검사용 접두
`kookabug-test:`로 쓰고 끝에 지운다 (데스크톱 세션이 필요 없다)."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator

import pytest

from kookabug_core.win.credentials import CredentialSecrets, CredentialStore
from kookabug_core.workspace import EnvSecrets, SecretChain, secret_env_name

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 자격 증명 관리자")

PREFIX = "kookabug-test:"


@pytest.fixture
def store() -> Iterator[tuple[CredentialStore, str]]:
    s = CredentialStore(PREFIX)
    wid = str(uuid.uuid4())
    yield s, wid
    for key in s.keys(wid):
        s.delete(wid, key)
    assert s.keys(wid) == []


def test_write_list_read_delete_roundtrip(store: tuple[CredentialStore, str]) -> None:
    s, wid = store
    assert s.read(wid, "accounts.qa") is None and s.keys(wid) == []
    s.write(wid, "accounts.qa", "pässwörd-01 한글")
    s.write(wid, "accounts.admin", "x")
    assert s.read(wid, "accounts.qa") == "pässwörd-01 한글"
    assert s.keys(wid) == ["accounts.admin", "accounts.qa"]
    # 다른 워크스페이스 ID의 키는 섞이지 않는다
    assert s.keys(str(uuid.uuid4())) == []
    s.write(wid, "accounts.qa", "changed")
    assert s.read(wid, "accounts.qa") == "changed"
    assert s.delete(wid, "accounts.qa") is True
    assert s.delete(wid, "accounts.qa") is False
    assert s.read(wid, "accounts.qa") is None and s.keys(wid) == ["accounts.admin"]


def test_secret_chain_env_before_credential(store: tuple[CredentialStore, str]) -> None:
    s, wid = store
    s.write(wid, "accounts.qa", "from-credential")
    cred = CredentialSecrets(wid, s)
    env = {secret_env_name("accounts.qa"): "from-env"}
    assert SecretChain(EnvSecrets(env), cred).get("accounts.qa") == "from-env"
    assert SecretChain(EnvSecrets({}), cred).get("accounts.qa") == "from-credential"
    assert SecretChain(EnvSecrets({}), cred).get("accounts.none") is None
    assert "from-credential" not in repr(cred)

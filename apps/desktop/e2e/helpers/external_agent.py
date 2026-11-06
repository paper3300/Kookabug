"""E2E 도우미: 앱이 띄운 daemon에 외부 agent 연결로 붙어 `app.launch`(control)를 요청한다.

사람 확인은 UI가 거부하므로 결과는 늘 오류 종류다 (게임을 띄우지 않는다). 결과를 JSON으로 쓴다."""

import json
import sys
from pathlib import Path

from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.session import read_session

root, destination = map(Path, sys.argv[1:])
session = read_session(root)
assert session is not None
principal = {
    "kind": "agent",
    "name": "외부 검수 에이전트",
    "version": "0",
    "id": "e2e-external",
    "attended": True,
}
with DaemonClient.from_session(session, client=principal) as agent:
    agent.call("agent.toolsets.enable", {"toolsets": ["control"]})
    try:
        agent.call("app.launch", {}, timeout=45)
        result = {"error": "예상과 달리 허용됨"}
    except DaemonError as e:
        result = {"error": e.kind}
    destination.write_text(json.dumps(result), encoding="utf-8")

"""워커 흉내: 파이프에 붙어 인증하고 hello 요청을 받은 뒤 **연결만 끊고** 살아서 기다린다.

runner가 "연결 상실 = 프로세스 종료"로 오인하지 않고 살아 있는 워커를 끝내는지 보는 검사가 쓴다
(`KOOKABUG_RPC_PIPE`·`KOOKABUG_RPC_KEY`는 runner가 준다).
"""

from __future__ import annotations

import os
import threading

from kookabug_sdk.pipe import connect


def main() -> None:
    conn = connect(os.environ["KOOKABUG_RPC_PIPE"], bytes.fromhex(os.environ["KOOKABUG_RPC_KEY"]))
    conn.recv_frame()  # worker.hello
    conn.close()
    threading.Event().wait(60)


if __name__ == "__main__":
    main()

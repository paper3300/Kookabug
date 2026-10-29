"""SDK 테스트 공용 픽스처: 인증된 파이프 한 쌍."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

import pytest

from kookabug_sdk.pipe import (
    BUFFER_SIZE,
    PipeConnection,
    PipeListener,
    connect,
    new_key,
    new_pipe_name,
)

type PairFactory = Callable[..., tuple[PipeConnection, PipeConnection]]


def make_pair(*, buffer_size: int = BUFFER_SIZE) -> tuple[PipeConnection, PipeConnection]:
    """(서버 끝, 클라이언트 끝). 둘 다 인증을 마쳤다."""
    name, key = new_pipe_name("test"), new_key()
    listener = PipeListener(name, buffer_size=buffer_size)
    accepted: list[PipeConnection | BaseException] = []

    def serve() -> None:
        try:
            accepted.append(listener.accept(key, timeout=10))
        except BaseException as e:
            accepted.append(e)

    thread = threading.Thread(target=serve)
    thread.start()
    client = connect(name, key, timeout=10)
    thread.join(10)
    server = accepted[0]
    if isinstance(server, BaseException):
        client.close()
        raise server
    return server, client


@pytest.fixture
def pipe_pair() -> Iterator[PairFactory]:
    made: list[PipeConnection] = []

    def factory(**kwargs: int) -> tuple[PipeConnection, PipeConnection]:
        server, client = make_pair(**kwargs)
        made.extend((server, client))
        return server, client

    yield factory
    for conn in made:
        conn.close()

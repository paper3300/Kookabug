from collections.abc import Iterator

import pytest
from testkit.nodes import COUNTS


@pytest.fixture(autouse=True)
def _reset_counts() -> Iterator[None]:
    COUNTS.clear()
    yield
    COUNTS.clear()

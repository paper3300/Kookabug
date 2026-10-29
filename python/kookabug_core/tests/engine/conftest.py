from collections.abc import Iterator

import pytest
from testkit.nodes import COUNTS, SEEN


@pytest.fixture(autouse=True)
def _reset_counts() -> Iterator[None]:
    COUNTS.clear()
    SEEN.clear()
    yield
    COUNTS.clear()
    SEEN.clear()

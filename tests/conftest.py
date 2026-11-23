import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path():
    # Keep test artifacts away from the shared OS temp tree and real note exports.
    root = Path(__file__).resolve().parents[1] / "output"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-", dir=root) as directory:
        yield Path(directory)

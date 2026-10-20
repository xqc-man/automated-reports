from pathlib import Path

import pytest

from automated_reports.adapters.csv_input import read_input

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def source_paths():
    return FIXTURES / "input.csv", FIXTURES / "source.json"


@pytest.fixture
def sample(source_paths):
    return read_input(*source_paths)

import pytest

from cvforge.config import load_config


@pytest.fixture(scope="session")
def cfg():
    c = load_config()
    if not (c.lualatex or c.xelatex):
        pytest.skip("no LaTeX engine found")
    return c

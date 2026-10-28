import pytest

from cvforge.config import load_config


@pytest.fixture(scope="session")
def cfg():
    c = load_config()
    if not (c.lualatex or c.xelatex):
        pytest.skip("no LaTeX engine found")
    return c


@pytest.fixture
def discover_master():
    return {"skills": [{"id": "sk-web", "name": "Web",
                        "keywords": ["React", "TypeScript", "Node.js", "Next.js", "PostgreSQL",
                                     "React Native"]}],
            "x-preferences": {"markets": ["IE", "BR"],
                              "workRights": {"IE": {"status": "needs-permit",
                                                    "degreeRecognised": "unknown",
                                                    "soc": ["2136", "2137"]},
                                             "BR": {"status": "citizen"}}}}

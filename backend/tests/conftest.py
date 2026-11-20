"""Test setup: fresh temp database + freshly generated synthetic data, mock LLM, no simulator thread."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="inspectiq_test_"))
os.environ.update({"LLM_PROVIDER": "mock", "DB_PATH": str(_tmp / "test.db"), "DATA_DIR": str(_tmp / "data"),
                   "SIMULATOR_ENABLED": "false", "SECRET_KEY": "test-secret"})

import pytest  # noqa: E402

from synthetic.generate import generate  # noqa: E402

generate(days=30, out=_tmp / "data")


@pytest.fixture(scope="session")
def ready():
    import json
    from app.core import config, security
    from app.services import compliance
    security.seed_users(json.loads((config.DATA_DIR / "users.json").read_text()))
    compliance.seed_rules()
    from app.services.inspection_source import get_store
    return get_store()


@pytest.fixture(scope="session")
def users(ready):
    from app.core import security
    return {u: security.authenticate(u, "demo123") for u in ("inspector", "supervisor", "qm", "compliance", "head", "itops")}

import os
import sys
import tempfile
from pathlib import Path

# Settings are read once at import time, so set them before anything imports app.*
_tmp = tempfile.mkdtemp()
os.environ.update({
    "DATA_DIR": _tmp,
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "APP_PASSWORD": "secret",
    "API_TOKEN": "tok",
    "ANTHROPIC_API_KEY": "",
    "NIGHTLY_SCHEDULER": "0",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

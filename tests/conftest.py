import os
import atexit
import shutil
import tempfile

# config.py resolves LOG_DIR at import time and defaults to clutterctrl/logs inside
# the package itself, so without this the test suite would write real run logs into
# the working tree. conftest is imported before any test module, so setting the env
# var here is early enough to be picked up.
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="clutterctrl_test_logs_")
os.environ.setdefault("CLUTTERCTRL_LOG_DIR", _TEST_LOG_DIR)

# Keep the default layout flat regardless of what categories.json ships with, so
# tests that don't opt into subfolders always assert against the same paths.
os.environ.setdefault("CLUTTERCTRL_SUBFOLDERS", "0")

atexit.register(shutil.rmtree, _TEST_LOG_DIR, True)

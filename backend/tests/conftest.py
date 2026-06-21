"""Test isolation: use a dedicated SQLite DB and the offline engine.

Env is set before any app module imports settings, so the test suite never touches
the dev `copilot.db` or makes live model calls.
"""
import os
import tempfile

os.environ["AGENT_ENGINE"] = "offline"
os.environ.pop("ANTHROPIC_API_KEY", None)

_db_path = os.path.join(tempfile.gettempdir(), "copilot_pytest.db")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

import sys
from pathlib import Path


# Ensure repo root is first in sys.path, before tests/ directory
# (necessary for dashboard module imports to work - prevents collision with tests/dashboard/)
ROOT = Path(__file__).parent.resolve()
repo_root_str = str(ROOT)
sys.path[:] = [p for p in sys.path if p != repo_root_str]
sys.path.insert(0, repo_root_str)

from pathlib import Path

from aaosa.config.loader import load_agents
from aaosa.demo.tools import TOOLBOX

DEMO_AGENTS = load_agents(Path(__file__).parent / "agents.yaml", tool_registry=TOOLBOX)

from pathlib import Path

from aaosa.config.loader import load_agents

DEMO_AGENTS = load_agents(Path(__file__).parent / "agents.yaml")

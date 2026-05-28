from aaosa.core.agent import Agent

AGENT_FRONTEND = Agent(
    name="Frontend",
    tags_with_elo={"frontend": 85, "css": 90, "javascript": 80, "testing": 40},
    system_prompt="You are a frontend specialist focused on UI, CSS, and JavaScript.",
)

AGENT_BACKEND = Agent(
    name="Backend",
    tags_with_elo={"backend": 90, "database": 85, "python": 80, "testing": 50},
    system_prompt="You are a backend specialist focused on APIs, databases, Python, and backend performance optimization (middleware, connection pooling, caching, async patterns, query indexing).",
)

AGENT_DEVOPS = Agent(
    name="DevOps",
    tags_with_elo={"infrastructure": 90, "docker": 85, "ci_cd": 80, "backend": 30},
    system_prompt="You are a DevOps specialist focused on infrastructure and CI/CD.",
)

AGENT_FULLSTACK = Agent(
    name="Fullstack",
    tags_with_elo={"frontend": 50, "backend": 55, "javascript": 60, "python": 50, "database": 40},
    system_prompt="You are a fullstack generalist covering frontend and backend.",
)

DEMO_AGENTS = [AGENT_FRONTEND, AGENT_BACKEND, AGENT_DEVOPS, AGENT_FULLSTACK]

from flask import Flask

from dashboard.cache import Cache
from dashboard.config import DashboardConfig


def create_app(config: DashboardConfig | None = None) -> Flask:
    """Factory. Attache config + cache ; aucune route data (réservé Épique 03b)."""
    config = config or DashboardConfig()
    app = Flask(__name__)
    app.config["AAOSA"] = config
    app.config["CACHE"] = Cache()
    return app

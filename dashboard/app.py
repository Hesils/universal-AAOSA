from flask import Flask

from dashboard.api import api
from dashboard.cache import Cache
from dashboard.config import DashboardConfig


def create_app(config: DashboardConfig | None = None) -> Flask:
    """Factory. Attache config + cache et enregistre l'API REST (Épique 03b)."""
    config = config or DashboardConfig()
    app = Flask(__name__)
    app.config["AAOSA"] = config
    app.config["CACHE"] = Cache()
    app.register_blueprint(api)
    return app

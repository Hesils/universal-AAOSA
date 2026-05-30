from dashboard.app import create_app
from dashboard.config import DashboardConfig

if __name__ == "__main__":
    cfg = DashboardConfig()
    create_app(cfg).run(host=cfg.host, port=cfg.port, debug=True)

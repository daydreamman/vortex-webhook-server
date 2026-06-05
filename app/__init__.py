"""Flask application factory for the Vortex webhook server."""

import logging

from flask import Flask


def configure_logging() -> None:
    """Configure process-wide logging once for local and Cloud Run usage."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()],
    )


def create_app() -> Flask:
    """Create and configure the Flask application."""
    configure_logging()
    flask_app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    from app.routes.dashboard import dashboard_bp

    flask_app.register_blueprint(dashboard_bp)
    return flask_app

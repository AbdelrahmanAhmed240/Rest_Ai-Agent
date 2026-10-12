from flask import Flask
from config import config
from app.models.base import db


def create_app():
    """
    Application Factory Pattern:
    Creates and configures the Flask application instance.
    """
    app = Flask(__name__)

    # Load configuration from config.py
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = config.SQLALCHEMY_TRACK_MODIFICATIONS
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Initialize extensions with this app
    db.init_app(app)

    # Register Blueprints (Route modules)
    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    return app

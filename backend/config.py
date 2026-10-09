import os
from datetime import timedelta
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-CHANGE-ME")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(basedir, "instance", "app.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", 120))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    SESSION_COOKIE_HTTPONLY = True
    # 'Lax' still allows same-site fetches (including cross-port localhost
    # during development, since SameSite ignores port) while blocking the
    # cookie from being sent on genuine cross-site requests — this is the
    # primary CSRF defence for this session-cookie API. Set to True when
    # served over HTTPS in production.
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    if SECRET_KEY == "dev-key-CHANGE-ME" and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set SECRET_KEY in production.")

    MAX_LOGIN_ATTEMPTS = int(os.environ.get("MAX_LOGIN_ATTEMPTS", 5))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", 15))

    UPLOAD_FOLDER = os.path.join(basedir, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

    PAGE_SIZE = 12
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', '1') == '1'
    PUBLIC_APP_URL = os.environ.get('PUBLIC_APP_URL', '')
    SOCIAL = {k: os.environ.get('SOCIAL_' + k.upper(), '') for k in ('facebook', 'x', 'linkedin', 'instagram')}

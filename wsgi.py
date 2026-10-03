"""WSGI entry point (gunicorn wsgi:app)."""
import os, sys
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)  # so instance/, .env and uploads resolve correctly
from app import create_app  # noqa: E402  (the package in backend/, not this folder's app.py)
app = create_app()

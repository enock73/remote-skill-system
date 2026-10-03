"""Run in development with:  python app.py   (production: gunicorn wsgi:app)"""
import os
from wsgi import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Remote Skills Exchange running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

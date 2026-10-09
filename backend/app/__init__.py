import os, secrets
from urllib.parse import urlparse
from datetime import date
from flask import Flask, render_template, request, session, abort, redirect, url_for, flash, send_from_directory
from flask_login import current_user
from config import Config
from app.extensions import db, login_manager, migrate, limiter


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app); migrate.init_app(app, db); limiter.init_app(app); login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "warning"

    from app.models import User, Notification

    @login_manager.user_loader
    def load_user(uid):
        u = db.session.get(User, int(uid))
        return u if u and u.is_active_account else None

    from app.routes import main, auth, bookings, provider, admin
    for m in (main, auth, bookings, provider, admin):
        app.register_blueprint(m.bp)

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not sent or sent != session.get("_csrf"):
                abort(400, "Your session expired. Reload the page and try again.")

    @app.context_processor
    def inject():
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(now_date=date.today().isoformat(), csrf_token=csrf_token, unread_count=unread, public_url=app.config["PUBLIC_APP_URL"], social=app.config["SOCIAL"])

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return resp

    def err(code, title, msg):
        return render_template("error.html", code=code, title=title, msg=msg), code

    @app.errorhandler(400)
    def e400(e): return err(400, "Request problem", getattr(e, "description", "Bad request."))
    @app.errorhandler(403)
    def e403(e): return err(403, "Access denied", "You do not have permission to view this page.")
    @app.errorhandler(404)
    def e404(e): return err(404, "Page not found", "That page does not exist or was removed.")
    @app.errorhandler(413)
    def e413(e): return err(413, "File too large", "Uploads are limited to 5 MB.")
    @app.errorhandler(429)
    def e429(e): return err(429, "Too many requests", "Please wait a moment and try again.")
    @app.errorhandler(500)
    def e500(e):
        db.session.rollback(); app.logger.exception(e)
        return err(500, "Something went wrong", "An unexpected error occurred. Please try again.")

    with app.app_context():
        db.create_all()
    return app


def safe_next(target, default):
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    return default

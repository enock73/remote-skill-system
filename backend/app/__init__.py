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
    app.logger.setLevel("INFO")   # so messages such as password-reset links appear in the terminal
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.config["PRIVATE_FOLDER"] = os.environ.get("PRIVATE_FOLDER") or os.path.join(app.instance_path, "private")   # ID photos: never public
    os.makedirs(app.config["PRIVATE_FOLDER"], exist_ok=True)

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

    images_dir = os.environ.get("PUBLIC_IMAGES_DIR") or os.path.abspath(os.path.join(app.root_path, "..", "..", "public", "images"))

    @app.route("/images/<path:filename>")
    def public_image(filename):   # hero photos: <project>/public/images/student-tech-1.jpg ...
        return send_from_directory(images_dir, filename)

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    @app.before_request
    def check_csrf():
        if request.method == "POST" and request.endpoint != "bookings.mpesa_callback":   # called by Safaricom, protected by a secret URL instead
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not sent or sent != session.get("_csrf"):
                abort(400, "Your session expired. Reload the page and try again.")

    @app.context_processor
    def inject():
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(app_name=app.config['APP_NAME'], now_date=date.today().isoformat(), csrf_token=csrf_token, unread_count=unread, public_url=app.config["PUBLIC_APP_URL"], social=app.config["SOCIAL"])

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
        upgrade_database()
    return app


def safe_next(target, default):
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    return default


# Columns added after the first release. Existing databases get them automatically on start.
NEW_COLUMNS = {
    "skill_listings": {"price_unit": "VARCHAR(30) DEFAULT 'per job'", "service_mode": "VARCHAR(10) DEFAULT 'both'",
                       "shop_address": "VARCHAR(255)", "deposit_percent": "INTEGER DEFAULT 30"},
    "users": {"verification_status": "VARCHAR(10) DEFAULT 'none'", "verification_note": "VARCHAR(255)", "verification_report": "TEXT", "verification_submitted_at": "TIMESTAMP",
              "id_number": "VARCHAR(20)", "id_photo": "VARCHAR(255)", "selfie_photo": "VARCHAR(255)", "mpesa_number": "VARCHAR(20)", "notify_email": "BOOLEAN DEFAULT TRUE", "notify_sms": "BOOLEAN DEFAULT TRUE"},
    "bookings": {"work_place": "VARCHAR(10) DEFAULT 'customer'", "customer_phone": "VARCHAR(20)", "customer_address": "VARCHAR(255)",
                 "agreed_price": "FLOAT", "deposit_amount": "FLOAT DEFAULT 0", "deposit_status": "VARCHAR(10) DEFAULT 'none'",
                 "deposit_code": "VARCHAR(20)", "balance_status": "VARCHAR(10) DEFAULT 'none'", "balance_code": "VARCHAR(20)",
                 "proof_note": "VARCHAR(255)", "completed_at": "TIMESTAMP", "customer_confirmed_at": "TIMESTAMP",
                 "payout_status": "VARCHAR(10) DEFAULT 'none'", "payout_amount": "FLOAT DEFAULT 0", "payout_ref": "VARCHAR(40)", "payout_at": "TIMESTAMP"},
    "notifications": {"link": "VARCHAR(200)"},
}


def upgrade_database():
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    for table, cols in NEW_COLUMNS.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols.items():
            if name not in have:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    db.session.commit()

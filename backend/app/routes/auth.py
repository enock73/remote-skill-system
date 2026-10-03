import re, os, uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadData
from app import safe_next
from app.extensions import db, limiter
from app.models import User

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PW_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
PW_MSG = "Password must be at least 8 characters with an uppercase letter, a lowercase letter and a number."


def save_image(file):
    """Return stored filename, or None (flashing the reason) if missing/invalid."""
    if not file or not file.filename: return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        flash("Images must be png, jpg, webp or gif.", "danger"); return None
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return name


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated: return redirect(url_for("main.dashboard"))
    f, errors = request.form, {}
    if request.method == "POST":
        name, email, role = f.get("full_name", "").strip(), f.get("email", "").strip().lower(), f.get("role", "customer")
        if len(name) < 2: errors["full_name"] = "Enter your full name."
        if not EMAIL_RE.match(email): errors["email"] = "Enter a valid email address."
        elif User.query.filter_by(email=email).first(): errors["email"] = "An account with this email already exists."
        if role not in ("customer", "provider"): errors["role"] = "Choose Customer or Service Provider."
        if not PW_RE.match(f.get("password", "")): errors["password"] = PW_MSG
        if f.get("password") != f.get("confirm"): errors["confirm"] = "Passwords do not match."
        if not errors:
            u = User(full_name=name, email=email, phone=f.get("phone", "").strip()[:20], role=role, location=f.get("location", "").strip()[:120])
            u.set_password(f["password"]); db.session.add(u); db.session.commit()
            login_user(u); flash("Welcome to Remote Skills Exchange!", "success")
            return redirect(url_for("provider.listing_new") if role == "provider" else url_for("main.services"))
    return render_template("register.html", errors=errors, f=f or {"role": request.args.get("role", "customer")})


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        pw = request.form.get("password", "")
        if u and u.is_locked: flash("This account is temporarily locked after repeated failed attempts. Try again later.", "danger")
        elif u and not u.is_active_account: flash("This account has been suspended. Contact support.", "danger")
        elif u and u.check_password(pw):
            u.register_successful_login(); db.session.commit(); login_user(u, remember=True)
            return redirect(safe_next(request.args.get("next"), url_for("main.dashboard")))
        else:
            if u: u.register_failed_login(current_app.config["MAX_LOGIN_ATTEMPTS"], current_app.config["LOCKOUT_MINUTES"]); db.session.commit()
            flash("Email or password is incorrect.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user(); flash("You have been signed out.", "info"); return redirect(url_for("main.home"))


def _ser(): return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="pw-reset")


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if u:
            link = url_for("auth.reset", token=_ser().dumps({"id": u.id, "h": u.password_hash[-10:]}), _external=True)
            current_app.logger.info("PASSWORD RESET LINK for %s: %s", u.email, link)  # no SMTP configured
            if current_app.debug: flash(f"Development mode: reset link: {link}", "info")
        flash("If that email is registered, a reset link has been sent.", "success")
        return redirect(url_for("auth.login"))
    return render_template("forgot.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset(token):
    try: data = _ser().loads(token, max_age=3600)
    except BadData: data = None
    u = db.session.get(User, data["id"]) if data else None
    if not u or u.password_hash[-10:] != data["h"]:
        flash("This reset link is invalid or has expired.", "danger"); return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        if not PW_RE.match(request.form.get("password", "")): flash(PW_MSG, "danger")
        elif request.form["password"] != request.form.get("confirm"): flash("Passwords do not match.", "danger")
        else:
            u.set_password(request.form["password"]); db.session.commit()
            flash("Password updated. Please sign in.", "success"); return redirect(url_for("auth.login"))
    return render_template("reset.html")


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        f = request.form
        if f.get("form") == "password":
            if not current_user.check_password(f.get("current_password", "")): flash("Current password is incorrect.", "danger")
            elif not PW_RE.match(f.get("new_password", "")): flash(PW_MSG, "danger")
            else: current_user.set_password(f["new_password"]); db.session.commit(); flash("Password changed.", "success")
        else:
            name = f.get("full_name", "").strip()
            if len(name) < 2: flash("Enter your full name.", "danger"); return redirect(url_for("auth.profile"))
            current_user.full_name, current_user.phone, current_user.location = name, f.get("phone", "").strip()[:20], f.get("location", "").strip()[:120]
            img = save_image(request.files.get("photo"))
            if img: current_user.profile_image = img
            db.session.commit(); flash("Profile saved.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("profile.html")

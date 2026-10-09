from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.decorators import roles_required
from app.extensions import db
from app.models import User, Category, SkillListing, Booking, Review, Notification
from app.services.notifications import notify
from flask_login import current_user

bp = Blueprint("admin", __name__, url_prefix="/admin")


def back(default): return redirect(request.referrer or url_for(default))


@bp.route("/users")
@roles_required("admin")
def users():
    q, role = (request.args.get("q") or "").strip(), request.args.get("role")
    qy = User.query.filter(User.role != "admin")
    if role in ("customer", "provider"): qy = qy.filter_by(role=role)
    if q: qy = qy.filter(User.full_name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    return render_template("admin/users.html", users=qy.order_by(User.created_at.desc()).all(), q=q, role=role, title="Providers" if role == "provider" else "Users")


@bp.route("/providers")
@roles_required("admin")
def providers(): return redirect(url_for("admin.users", role="provider"))


def _target(uid):
    u = db.session.get(User, uid) or abort(404)
    if u.role == "admin": abort(400, "Administrator accounts cannot be changed here.")
    return u


@bp.route("/users/<int:uid>/<action>", methods=["POST"])
@roles_required("admin")
def user_action(uid, action):
    u = _target(uid)
    if action == "suspend": u.is_active_account = not u.is_active_account; flash("Account " + ("activated." if u.is_active_account else "suspended."), "success")
    elif action == "verify" and u.role == "provider":
        u.is_verified = not u.is_verified
        if u.is_verified: notify(u.id, "You're verified!", "An administrator verified your profile. A ✓ Verified Skill badge now shows on your services.")
        flash("Verification " + ("granted." if u.is_verified else "removed."), "success")
    elif action == "edit":
        u.full_name = request.form.get("full_name", u.full_name).strip() or u.full_name
        u.phone, u.location = request.form.get("phone", "").strip()[:20], request.form.get("location", "").strip()[:120]
        flash("User updated.", "success")
    elif action == "delete":
        for b in Booking.query.filter((Booking.customer_id == u.id) | (Booking.provider_id == u.id)).all(): db.session.delete(b)
        db.session.flush(); db.session.delete(u); flash("Account and its data removed.", "success")
    else: abort(404)
    db.session.commit(); return back("admin.users")


@bp.route("/services")
@roles_required("admin")
def services():
    return render_template("admin/services.html", items=SkillListing.query.order_by(SkillListing.created_at.desc()).all())


@bp.route("/services/<int:lid>/<action>", methods=["POST"])
@roles_required("admin")
def service_action(lid, action):
    l = db.session.get(SkillListing, lid) or abort(404)
    if action == "toggle": l.is_active = not l.is_active
    elif action == "delete": db.session.delete(l)
    else: abort(404)
    db.session.commit(); flash("Service updated.", "success"); return redirect(url_for("admin.services"))


@bp.route("/categories", methods=["GET", "POST"])
@roles_required("admin")
def categories():
    if request.method == "POST":
        f, cid = request.form, request.form.get("id", type=int)
        name = f.get("name", "").strip()
        c = db.session.get(Category, cid) if cid else None
        if f.get("delete"):
            if c and c.listings: flash("This category has services. Reassign or remove them first.", "danger")
            elif c: db.session.delete(c); db.session.commit(); flash("Category deleted.", "success")
        elif not name: flash("Category name is required.", "danger")
        elif Category.query.filter(db.func.lower(Category.name) == name.lower(), Category.id != (cid or 0)).first(): flash("That category already exists.", "danger")
        else:
            c = c or Category(); c.name, c.description = name[:80], f.get("description", "").strip()[:255]
            db.session.add(c); db.session.commit(); flash("Category saved.", "success")
        return redirect(url_for("admin.categories"))
    return render_template("admin/categories.html", cats=Category.query.order_by(Category.name).all())


@bp.route("/bookings")
@roles_required("admin")
def bookings():
    st = request.args.get("status"); qy = Booking.query
    if st: qy = qy.filter_by(status=st)
    return render_template("admin/bookings.html", bookings=qy.order_by(Booking.created_at.desc()).all(), status=st)


@bp.route("/reviews", methods=["GET", "POST"])
@roles_required("admin")
def reviews():
    if request.method == "POST":
        r = db.session.get(Review, request.form.get("id", type=int)) or abort(404)
        db.session.delete(r); db.session.commit(); flash("Review removed.", "success"); return redirect(url_for("admin.reviews"))
    return render_template("admin/reviews.html", reviews=Review.query.order_by(Review.created_at.desc()).all())


@bp.route("/settings", methods=["GET", "POST"])
@roles_required("admin")
def settings():
    if request.method == "POST":
        msg, uid = request.form.get("message", "").strip(), request.form.get("user_id", type=int)
        if len(msg) < 3: flash("Write a message first.", "danger")
        else:
            targets = [db.session.get(User, uid)] if uid else User.query.filter(User.role != "admin").all()
            for t in filter(None, targets): db.session.add(Notification(user_id=t.id, title="Announcement", message=msg[:500]))
            db.session.commit(); flash(f"Notification sent to {len(targets)} user(s).", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", users=User.query.filter(User.role != "admin").order_by(User.full_name).all(),
                           sent=Notification.query.filter_by(title="Announcement").order_by(Notification.created_at.desc()).limit(15).all())

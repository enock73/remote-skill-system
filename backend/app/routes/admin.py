import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_from_directory, current_app
from app.decorators import roles_required
from app.extensions import db
from app.models import User, Category, SkillListing, Booking, Review, Notification, Payment
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
        u.verification_status = "approved" if u.is_verified else "none"
        if u.is_verified: notify(u.id, "You're verified!", "An administrator verified your profile. A ✓ Verified Skill badge now shows on your services.")
        flash("Verification " + ("granted." if u.is_verified else "removed."), "success")
    elif action == "edit":
        u.full_name = request.form.get("full_name", u.full_name).strip() or u.full_name
        u.phone, u.location = request.form.get("phone", "").strip()[:20], request.form.get("location", "").strip()[:120]
        flash("User updated.", "success")
    elif action == "delete":
        for b in Booking.query.filter((Booking.customer_id == u.id) | (Booking.provider_id == u.id)).all(): db.session.delete(b)
        from app.services.files import delete_file
        for nm in (u.id_photo, u.selfie_photo): delete_file("PRIVATE_FOLDER", nm)
        for ph in u.portfolio: delete_file("UPLOAD_FOLDER", ph.filename)
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
            for t in filter(None, targets): notify(t.id, "Announcement", msg[:500], sms=False)
            flash(f"Notification sent to {len(targets)} user(s).", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", users=User.query.filter(User.role != "admin").order_by(User.full_name).all(),
                           sent=Notification.query.filter_by(title="Announcement").order_by(Notification.created_at.desc()).limit(15).all())


# ---------------- identity verification review
@bp.route("/verifications")
@roles_required("admin")
def verifications():
    pending = User.query.filter_by(role="provider", verification_status="pending").order_by(User.verification_submitted_at).all()
    done = User.query.filter(User.role == "provider", User.verification_status.in_(("approved", "rejected"))).order_by(User.verification_submitted_at.desc()).limit(30).all()
    return render_template("admin/verifications.html", pending=pending, done=done)


@bp.route("/verifications/<int:uid>/<which>")
@roles_required("admin")
def verification_file(uid, which):
    u = db.session.get(User, uid) or abort(404)
    name = {"id": u.id_photo, "selfie": u.selfie_photo}.get(which) or abort(404)
    resp = send_from_directory(current_app.config["PRIVATE_FOLDER"], os.path.basename(name))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/verifications/<int:uid>/decide", methods=["POST"])
@roles_required("admin")
def verification_decide(uid):
    u = _target(uid)
    if u.role != "provider" or u.verification_status != "pending": abort(400, "Nothing to review for this account.")
    if request.form.get("decision") == "approve":
        u.verification_status, u.is_verified, u.verification_note = "approved", True, None
        notify(u.id, "You're verified!", "Your ID was checked and approved. A Verified badge now shows on your profile and services.", url_for("provider.verification"))
        flash("Provider verified.", "success")
    else:
        reason = request.form.get("reason", "").strip()[:255]
        if len(reason) < 3:
            flash("Write a short reason so the provider can fix it.", "danger"); return redirect(url_for("admin.verifications"))
        u.verification_status, u.is_verified, u.verification_note = "rejected", False, reason
        notify(u.id, "Verification not approved", f"Reason: {reason}. You can submit new documents.", url_for("provider.verification"))
        flash("Rejected. The provider was told why.", "warning")
    db.session.commit()
    return redirect(url_for("admin.verifications"))


# ---------------- payouts: money paid through M-Pesa STK Push is held by the platform until sent to the provider
@bp.route("/payouts")
@roles_required("admin")
def payouts():
    due = Booking.query.filter_by(payout_status="due").order_by(Booking.updated_at).all()
    paid = Booking.query.filter_by(payout_status="paid").order_by(Booking.payout_at.desc()).limit(30).all()
    held = Booking.query.filter(Booking.payout_status == "none", Booking.deposit_status == "confirmed", Booking.status.in_(("pending", "accepted"))).filter(Booking.payments.any(Payment.status == "success")).all()
    refunds = Booking.query.filter_by(deposit_status="refund").order_by(Booking.updated_at).all()
    return render_template("admin/payouts.html", due=due, paid=paid, held=held, refunds=refunds)


@bp.route("/payouts/<int:bid>/refunded", methods=["POST"])
@roles_required("admin")
def refund_done(bid):
    b = db.session.get(Booking, bid) or abort(404)
    if b.deposit_status != "refund": abort(400)
    b.deposit_status = "refunded"; db.session.commit()
    notify(b.customer_id, "Deposit refunded", f"Your deposit for '{b.listing.title}' was refunded to your M-Pesa.", url_for("bookings.detail", bid=b.id))
    flash("Marked as refunded.", "success"); return redirect(url_for("admin.payouts"))


@bp.route("/payouts/<int:bid>/paid", methods=["POST"])
@roles_required("admin")
def payout_paid(bid):
    b = db.session.get(Booking, bid) or abort(404)
    ref = request.form.get("ref", "").strip().upper()[:40]
    if b.payout_status != "due": abort(400, "No payout is due for this booking.")
    if len(ref) < 6:
        flash("Enter the M-Pesa reference of the payout you sent.", "danger"); return redirect(url_for("admin.payouts"))
    b.payout_status, b.payout_ref, b.payout_at = "paid", ref, datetime.utcnow()
    db.session.commit()
    notify(b.provider_id, "Payout sent", f"KSh {b.payout_amount:,.0f} for '{b.listing.title}' was sent to your M-Pesa (ref {ref}).", url_for("bookings.detail", bid=b.id))
    flash("Marked as paid.", "success")
    return redirect(url_for("admin.payouts"))

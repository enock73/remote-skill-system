import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_from_directory
from flask_login import login_required, current_user
from app.decorators import roles_required
from app.extensions import db, limiter
from app.models import Booking, Dispute, DisputeEvidence, User
from app.services.files import save_private_image
from app.services.notifications import notify

bp = Blueprint("disputes", __name__)
MAX_PHOTOS = 4


def _party_booking(bid):
    b = db.session.get(Booking, bid) or abort(404)
    if current_user.id not in (b.customer_id, b.provider_id): abort(403)
    return b


def _link(b): return url_for("bookings.detail", bid=b.id)


def _add_evidence(d, note, files, allow_empty=False):
    """Save a note and up to MAX_PHOTOS private photos. Returns an error text or None."""
    note = (note or "").strip()[:1000]
    files = [f for f in files if f and f.filename][:MAX_PHOTOS]
    if not note and not files: return None if allow_empty else "Write a note or add a photo."
    saved = []
    for f in files:
        name, err = save_private_image(f)
        if err: return err
        saved.append(name)
    if note: db.session.add(DisputeEvidence(dispute_id=d.id, user_id=current_user.id, note=note))
    for n in saved: db.session.add(DisputeEvidence(dispute_id=d.id, user_id=current_user.id, filename=n))
    return None


@bp.route("/bookings/<int:bid>/dispute", methods=["POST"])
@roles_required("customer", "provider")
@limiter.limit("5 per hour", methods=["POST"])
def open_dispute(bid):
    b = _party_booking(bid)
    if b.open_dispute:
        flash("A dispute is already open on this booking. Add your evidence to it.", "warning"); return redirect(_link(b))
    if not (b.status in ("accepted", "completed") or (b.status == "pending" and b.deposit_status == "confirmed")):
        flash("A dispute can only be opened once the booking is active.", "danger"); return redirect(_link(b))
    reason = request.form.get("reason", "").strip()
    if len(reason) < 10:
        flash("Describe what went wrong in at least a few words (10 characters or more).", "danger"); return redirect(_link(b))
    d = Dispute(booking_id=b.id, opened_by_id=current_user.id, reason=reason[:1500])
    db.session.add(d); db.session.flush()
    err = _add_evidence(d, "", request.files.getlist("photos"), allow_empty=True)
    if err:
        db.session.rollback(); flash(err, "danger"); return redirect(_link(b))
    db.session.commit()
    other = b.provider_id if current_user.id == b.customer_id else b.customer_id
    notify(other, "A dispute was opened", f"{current_user.full_name} opened a dispute on '{b.listing.title}'. Open the booking and add your side with notes or photos.", _link(b))
    for a in User.query.filter_by(role="admin").all():
        notify(a.id, "Dispute opened", f"Booking #{b.id} '{b.listing.title}': {current_user.full_name} ({current_user.role}) says: {reason[:200]}", url_for("disputes.admin_view", did=d.id))
    flash("Dispute opened. The other side was told, and an administrator will decide. Add photos or notes any time.", "success")
    return redirect(_link(b))


@bp.route("/bookings/<int:bid>/dispute/evidence", methods=["POST"])
@roles_required("customer", "provider")
@limiter.limit("20 per hour", methods=["POST"])
def add_evidence(bid):
    b = _party_booking(bid); d = b.open_dispute
    if not d:
        flash("There is no open dispute on this booking.", "danger"); return redirect(_link(b))
    err = _add_evidence(d, request.form.get("note"), request.files.getlist("photos"))
    if err:
        db.session.rollback(); flash(err, "danger"); return redirect(_link(b))
    db.session.commit()
    other = b.provider_id if current_user.id == b.customer_id else b.customer_id
    notify(other, "New evidence in the dispute", f"{current_user.full_name} added evidence on '{b.listing.title}'.", _link(b), sms=False)
    flash("Evidence added.", "success"); return redirect(_link(b))


@bp.route("/disputes/evidence/<int:eid>")
@login_required
def evidence_file(eid):
    e = db.session.get(DisputeEvidence, eid) or abort(404)
    b = e.dispute.booking
    if current_user.role != "admin" and current_user.id not in (b.customer_id, b.provider_id): abort(403)
    if not e.filename: abort(404)
    return send_from_directory(current_app.config["PRIVATE_FOLDER"], os.path.basename(e.filename))


# ---------------- administrator
@bp.route("/admin/disputes")
@roles_required("admin")
def admin_list():
    ds = Dispute.query.order_by((Dispute.status == "open").desc(), Dispute.created_at.desc()).all()
    return render_template("admin/disputes.html", disputes=ds)


@bp.route("/admin/disputes/<int:did>")
@roles_required("admin")
def admin_view(did):
    d = db.session.get(Dispute, did) or abort(404)
    return render_template("admin/dispute.html", d=d, b=d.booking, commission=current_app.config["COMMISSION_PERCENT"] or 0)


@bp.route("/admin/disputes/<int:did>/resolve", methods=["POST"])
@roles_required("admin")
def resolve(did):
    d = db.session.get(Dispute, did) or abort(404); b = d.booking
    back = redirect(url_for("disputes.admin_view", did=d.id))
    if d.status != "open":
        flash("This dispute is already decided.", "warning"); return back
    outcome, note = request.form.get("outcome", ""), request.form.get("note", "").strip()
    if outcome not in ("refund_customer", "pay_provider", "split"):
        flash("Choose a decision.", "danger"); return back
    if len(note) < 5:
        flash("Write a short reason. Both sides will read it.", "danger"); return back
    paid = float(b.paid_total)                 # money the platform is holding for this booking
    if outcome != "pay_provider" and b.payout_status == "paid":
        flash("The provider was already paid out for this booking, so the platform cannot refund it. Choose 'Pay the provider' or settle it outside.", "danger"); return back
    fee_pct = current_app.config["COMMISSION_PERCENT"] or 0
    refund = 0.0
    if outcome == "refund_customer": refund = paid
    elif outcome == "split":
        refund = request.form.get("refund_amount", type=float) or 0
        if paid <= 0 or not 0 < refund < paid:
            flash("For a split, the refund must be more than 0 and less than the KSh %s held." % f"{paid:,.0f}", "danger"); return back
        refund = round(refund, 2)
    release = max(0.0, paid - refund)
    if paid > 0:
        if refund > 0: b.refund_amount, b.refund_status = refund, "due"
        if release > 0 and b.payout_status != "paid":
            b.payout_amount, b.payout_status = round(release - release * fee_pct / 100, 2), "due"
        elif release == 0 and b.payout_status != "paid":
            b.payout_amount, b.payout_status = 0.0, "none"
        if outcome == "refund_customer" and b.status in ("pending", "accepted"): b.status = "cancelled"
    d.status, d.outcome, d.refund_amount, d.admin_note, d.resolved_at = "resolved", outcome, refund, note[:1500], datetime.utcnow()
    db.session.commit()
    t = b.listing.title
    text = {"refund_customer": f"The administrator decided in favour of the customer. KSh {refund:,.0f} will be refunded.",
            "pay_provider": "The administrator decided in favour of the provider. The held money will be released to them.",
            "split": f"The administrator split the money: KSh {refund:,.0f} back to the customer, the rest to the provider."}[outcome]
    for uid in (b.customer_id, b.provider_id):
        notify(uid, "Dispute decided", f"'{t}': {text} Reason: {note[:200]}", _link(b))
    if paid > 0 and outcome != "pay_provider":
        flash(f"Decision saved. Refund of KSh {refund:,.0f} is now listed under Payouts. Send it, then press Mark refunded.", "success")
    elif paid > 0:
        flash("Decision saved. The provider's payout is now listed under Payouts.", "success")
    else:
        flash("Decision saved. No M-Pesa money was held for this booking, so nothing moves automatically. Settle it as you decided.", "info")
    return redirect(url_for("disputes.admin_list"))

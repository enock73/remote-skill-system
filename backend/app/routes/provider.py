from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user
from app.decorators import roles_required
from app.extensions import db
from app.models import SkillListing, Category
from app.routes.auth import save_image

bp = Blueprint("provider", __name__, url_prefix="/provider")


def _own(lid):
    l = db.session.get(SkillListing, lid) or abort(404)
    if l.provider_id != current_user.id: abort(403)
    return l


@bp.route("/services")
@roles_required("provider")
def listings():
    return render_template("provider/listings.html", items=SkillListing.query.filter_by(provider_id=current_user.id).order_by(SkillListing.created_at.desc()).all())


def _form(l=None):
    errors, f = {}, request.form
    if request.method == "POST":
        title, desc = f.get("title", "").strip(), f.get("description", "").strip()
        cat = db.session.get(Category, f.get("category_id", type=int)) if f.get("category_id") else None
        try: price = float(f.get("price", "")); assert price >= 0
        except (ValueError, AssertionError): price = None; errors["price"] = "Enter a valid, non-negative price."
        if not title: errors["title"] = "Title is required."
        if not desc: errors["description"] = "Description is required."
        if not cat: errors["category_id"] = "Select a category."
        if not f.get("location", "").strip(): errors["location"] = "Location is required."
        if not errors:
            l = l or SkillListing(provider_id=current_user.id)
            l.title, l.description, l.category_id, l.price = title[:150], desc[:3000], cat.id, price
            l.location, l.availability = f["location"].strip()[:120], f.get("availability", "").strip()[:120]
            l.is_active = f.get("is_active", "1") == "1"
            img = save_image(request.files.get("image"))
            if img: l.image = img
            db.session.add(l); db.session.commit(); flash("Service saved.", "success")
            return redirect(url_for("provider.listings"))
    return render_template("provider/listing_form.html", l=l, errors=errors, f=f if request.method == "POST" else {}, cats=Category.query.order_by(Category.name).all())


@bp.route("/services/new", methods=["GET", "POST"])
@roles_required("provider")
def listing_new(): return _form()


@bp.route("/services/<int:lid>/edit", methods=["GET", "POST"])
@roles_required("provider")
def listing_edit(lid): return _form(_own(lid))


@bp.route("/services/<int:lid>/delete", methods=["POST"])
@roles_required("provider")
def listing_delete(lid):
    db.session.delete(_own(lid)); db.session.commit(); flash("Service deleted.", "success")
    return redirect(url_for("provider.listings"))

"""Provider trust score (0-100). Computed from facts in the database, never typed in by anyone.

  30  ID verified by an administrator
  30  customer reviews (rating, counted fully only after 5 reviews)
  20  finished jobs (counted fully at 10 jobs)
  10  complete profile (photo, phone, location, work photos)
  10  reliability (loses 5 for every dispute decided against the provider)
"""


def _tier(n):
    if n >= 85: return "Top trusted", "success"
    if n >= 65: return "Trusted", "primary"
    if n >= 40: return "Growing", "info"
    return "New", "secondary"


def lost_disputes(user_id):
    from app.models import Dispute, Booking
    return (Dispute.query.join(Booking, Dispute.booking_id == Booking.id)
            .filter(Booking.provider_id == user_id, Dispute.status == "resolved", Dispute.outcome.in_(("refund_customer", "split"))).count())


def score(u):
    from app.models import Booking
    parts = []
    parts.append(("Verified ID", 30 if u.is_verified else 0, 30, "Verified by an administrator" if u.is_verified else "Verify your Kenyan ID to earn 30 points"))
    n, avg = u.review_count, u.average_rating
    pts = round(((avg - 1) / 4) * 30 * min(n, 5) / 5) if n else 0
    parts.append(("Customer reviews", pts, 30, f"{avg} stars from {n} review{'s' if n != 1 else ''}" if n else "No reviews yet. Each good review adds points"))
    done = Booking.query.filter_by(provider_id=u.id, status="completed").count()
    parts.append(("Finished jobs", round(min(done, 10) / 10 * 20), 20, f"{done} job{'s' if done != 1 else ''} finished" if done else "Finish your first job"))
    have = [bool(u.profile_image), bool(u.phone), bool(u.location), bool(u.portfolio)]
    parts.append(("Complete profile", round(sum(have) * 2.5), 10, "Add " + ", ".join(w for w, h in zip(("a profile photo", "a phone number", "a location", "work photos"), have) if not h) if not all(have) else "Profile is complete"))
    lost = lost_disputes(u.id)
    parts.append(("Reliability", max(0, 10 - 5 * lost), 10, f"{lost} dispute{'s' if lost != 1 else ''} decided against this provider" if lost else "No disputes lost"))
    total = sum(p[1] for p in parts)
    tier, color = _tier(total)
    return {"score": total, "tier": tier, "color": color, "parts": parts, "jobs": done, "lost": lost}

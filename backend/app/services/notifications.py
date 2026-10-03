from app.extensions import db
from app.models import Notification


def notify(user_id, title, message):
    """Create a real, database-backed notification. Never raises —
    a notification failure must not break the calling request."""
    try:
        db.session.add(Notification(user_id=user_id, title=title, message=message))
        db.session.commit()
    except Exception:
        db.session.rollback()

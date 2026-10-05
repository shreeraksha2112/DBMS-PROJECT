from repositories.db import db
from repositories.models import User, EcoActivity
from services.wallet_service import credit_wallet
from services.gamification_service import update_user_gamification


def verify_activity(activity_id, method='manual', decision='approved', reviewer_id=None):
    activity = EcoActivity.query.get(activity_id)
    if not activity:
        raise ValueError('Activity not found')

    if decision == 'approved':
        activity.status = 'approved'
        wallet = credit_wallet(activity.user_id, activity.points, activity.record_id, transaction_type='credit')
        if wallet is not None:
            user = User.query.get(activity.user_id)
            if user:
                update_user_gamification(user, activity.points)
    else:
        activity.status = 'rejected'

    db.session.commit()
    return {
        "activity_id": activity.record_id,
        "status": activity.status,
        "method": method,
        "decision": decision,
        "points": float(activity.points),
    }


def verify_qr_event(user_id, qr_token):
    if qr_token and qr_token.lower() in {'eco-qr-demo', 'cycling-qr', 'community-mission'}:
        return {"verified": True, "message": "QR event verified successfully"}
    return {"verified": False, "message": "Invalid QR token"}

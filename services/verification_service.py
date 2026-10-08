from datetime import datetime, timedelta

from repositories.db import db
from repositories.models import User, EcoActivity, Notification, AuditLog
from services.wallet_service import credit_wallet
from services.gamification_service import update_user_gamification


def log_audit_event(actor_id, action, entity_type, entity_id=None, details=None):
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or '',
    )
    db.session.add(log)
    db.session.flush()
    return log


def create_notification(user_id, notification_type, message):
    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        message=message,
    )
    db.session.add(notification)
    db.session.flush()
    return notification


def evaluate_activity_anomaly(user_id, activity_id, quantity, record_id=None):
    recent_activities = EcoActivity.query.filter_by(user_id=user_id).filter(
        EcoActivity.activity_date >= datetime.utcnow() - timedelta(days=1)
    ).all()
    recent_total = sum(float(activity.quantity) for activity in recent_activities if activity.record_id != record_id)
    threshold = 1000 if activity_id == 1 else 500
    risk_score = 0.0
    reasons = []

    if quantity > threshold:
        risk_score += min(70.0, (quantity / threshold) * 45)
        reasons.append('quantity exceeds expected range')
    if recent_total > 2000:
        risk_score += 30.0
        reasons.append('rapid repeat submissions')
    if quantity > 0 and recent_total > 0 and quantity > recent_total * 0.5:
        risk_score += 20.0
        reasons.append('recent activity spike')

    flagged = risk_score >= 50.0
    if flagged:
        create_notification(
            user_id,
            'warning',
            'Your eco activity has been flagged for moderation review.',
        )
        log_audit_event(
            user_id,
            'suspicious_activity_detected',
            'eco_activity',
            record_id,
            '; '.join(reasons) if reasons else 'suspicious submission',
        )
    return {
        'flagged': flagged,
        'risk_score': round(risk_score, 2),
        'reason': '; '.join(reasons) if reasons else 'normal',
    }


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
        log_audit_event(reviewer_id or activity.user_id, 'activity_approved', 'eco_activity', activity.record_id, method)
    else:
        activity.status = 'rejected'
        log_audit_event(reviewer_id or activity.user_id, 'activity_rejected', 'eco_activity', activity.record_id, method)

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
        log_audit_event(user_id, 'qr_verification', 'eco_event', None, qr_token)
        return {"verified": True, "message": "QR event verified successfully"}
    return {"verified": False, "message": "Invalid QR token"}

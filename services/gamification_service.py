from repositories.db import db
from sqlalchemy import func

from repositories.models import Badge, UserBadge, User, UserChallenge, EcoActivity, Challenge


DEFAULT_BADGES = (
    ('Eco Starter', 'eco_score', 100.0),
    ('Impact Maker', 'eco_score', 500.0),
    ('Green Champion', 'eco_score', 1000.0),
    ('First Steps', 'activity_count', 1.0),
    ('Green Regular', 'activity_count', 10.0),
    ('Habit Builder', 'activity_count', 50.0),
    ('Challenge Finisher', 'challenge_count', 1.0),
    ('Challenge Champion', 'challenge_count', 5.0),
)


def ensure_default_badges():
    for name, rule_type, value in DEFAULT_BADGES:
        if not Badge.query.filter_by(name=name).first():
            db.session.add(Badge(name=name, rule_type=rule_type, rule_value=value))
    db.session.flush()


def update_user_gamification(user, points_delta):
    user.eco_score = float(user.eco_score or 0.0) + float(points_delta)
    user.level = max(1, int(user.eco_score // 100) + 1)
    evaluate_badges_for_user(user.user_id)
    return {"eco_score": float(user.eco_score), "level": user.level}


def evaluate_badges_for_user(user_id):
    ensure_default_badges()
    user = User.query.get(user_id)
    if not user:
        return []

    activity_count = db.session.query(func.count(EcoActivity.record_id)).filter_by(
        user_id=user_id,
        status='approved',
    ).scalar() or 0
    challenge_count = UserChallenge.query.filter_by(user_id=user_id, status='completed').count()
    progress_by_type = {
        'eco_score': float(user.eco_score or 0.0),
        'activity_count': float(activity_count),
        'challenge_count': float(challenge_count),
    }
    badges = Badge.query.order_by(Badge.rule_type.asc(), Badge.rule_value.asc()).all()
    unlocked = []
    for badge in badges:
        if progress_by_type.get(badge.rule_type, 0) < badge.rule_value:
            continue
        exists = UserBadge.query.filter_by(user_id=user_id, badge_id=badge.badge_id).first()
        if exists:
            continue
        db.session.add(UserBadge(user_id=user_id, badge_id=badge.badge_id))
        unlocked.append({"badge_id": badge.badge_id, "name": badge.name, "rule_value": badge.rule_value})
        from services.verification_service import create_notification

        create_notification(user_id, 'badge', f'Badge unlocked: {badge.name}!')
    db.session.commit()
    return unlocked


def get_user_badges(user_id):
    user = User.query.get(user_id)
    if not user:
        return []
    activity_count = db.session.query(func.count(EcoActivity.record_id)).filter_by(
        user_id=user_id,
        status='approved',
    ).scalar() or 0
    challenge_count = UserChallenge.query.filter_by(user_id=user_id, status='completed').count()
    progress_by_type = {
        'eco_score': float(user.eco_score or 0.0),
        'activity_count': float(activity_count),
        'challenge_count': float(challenge_count),
    }
    records = {
        record.badge_id: record
        for record in UserBadge.query.filter_by(user_id=user_id).all()
    }
    badges = Badge.query.order_by(Badge.rule_type.asc(), Badge.rule_value.asc()).all()
    return [
        {
            "badge_id": badge.badge_id,
            "name": badge.name,
            "rule_type": badge.rule_type,
            "rule_value": float(badge.rule_value),
            "progress": min(progress_by_type.get(badge.rule_type, 0.0), float(badge.rule_value)),
            "earned": badge.badge_id in records,
            "earned_at": records[badge.badge_id].earned_at.isoformat() if badge.badge_id in records and records[badge.badge_id].earned_at else None,
        }
        for badge in badges
    ]

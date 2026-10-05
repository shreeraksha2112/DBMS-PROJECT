from repositories.db import db
from repositories.models import Badge, UserBadge, User, UserChallenge, Challenge


def ensure_default_badges():
    badge_names = {
        'Eco Starter': 100.0,
        'Impact Maker': 500.0,
        'Green Champion': 1000.0,
    }

    for name, value in badge_names.items():
        if not Badge.query.filter_by(name=name).first():
            db.session.add(Badge(name=name, rule_type='eco_score', rule_value=value))
    db.session.commit()


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

    badges = Badge.query.order_by(Badge.rule_value.asc()).all()
    unlocked = []
    for badge in badges:
        if user.eco_score >= badge.rule_value:
            exists = UserBadge.query.filter_by(user_id=user_id, badge_id=badge.badge_id).first()
            if not exists:
                db.session.add(UserBadge(user_id=user_id, badge_id=badge.badge_id))
            unlocked.append({"badge_id": badge.badge_id, "name": badge.name, "rule_value": badge.rule_value})
    db.session.commit()
    return unlocked


def get_user_badges(user_id):
    records = UserBadge.query.filter_by(user_id=user_id).all()
    return [
        {
            "badge_id": record.badge_id,
            "name": record.badge.name,
            "earned_at": record.earned_at.isoformat() if record.earned_at else None,
        }
        for record in records
    ]

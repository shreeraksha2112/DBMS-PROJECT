from sqlalchemy import func

from repositories.models import EcoActivity, ImpactRecord, ImpactFactor, ActivityType, User


def calculate_activity_impact(activity_id, quantity):
    factors = ImpactFactor.query.filter_by(activity_id=activity_id).all()
    impact = {}
    for factor in factors:
        impact[factor.metric_type] = float(factor.factor_value * quantity)
    return impact


def get_user_impact_summary(user_id):
    activities = EcoActivity.query.filter_by(user_id=user_id).order_by(EcoActivity.activity_date.desc()).all()
    total_impact = {}
    total_points = 0.0
    for activity in activities:
        total_points += float(activity.points)
        for impact_record in ImpactRecord.query.filter_by(eco_activity_id=activity.record_id).all():
            total_impact[impact_record.metric_type] = total_impact.get(impact_record.metric_type, 0.0) + float(impact_record.impact_value)

    recent_points = sum(float(activity.points) for activity in activities[:5])
    total_activity_value = sum(float(activity.quantity) for activity in activities)
    monthly_projection = float((recent_points / max(len(activities), 1)) * 30) if activities else 0.0
    weekly_projection = float((recent_points / max(len(activities), 1)) * 7) if activities else 0.0

    return {
        "total_activities": len(activities),
        "total_points": total_points,
        "total_impact": total_impact,
        "forecast": {
            "monthly_estimate": round(monthly_projection, 2),
            "weekly_estimate": round(weekly_projection, 2),
            "status": "on_track" if monthly_projection > 0 else "low_activity",
        },
        "trend": {
            "direction": "up" if recent_points >= 0 else "stable",
            "change_pct": round(min(100.0, (recent_points / max(total_activity_value, 1.0)) * 100), 2),
            "period": "30d",
        },
        "recent_activity": [
            {
                "record_id": activity.record_id,
                "activity_name": activity.activity_type.name,
                "quantity": float(activity.quantity),
                "points": float(activity.points),
                "status": activity.status,
            }
            for activity in activities[-5:]
        ],
    }


def get_leaderboard(limit=10):
    users = User.query.order_by(User.eco_score.desc()).limit(limit).all()
    leaderboard = []
    for user in users:
        summary = get_user_impact_summary(user.user_id)
        leaderboard.append({
            "user_id": user.user_id,
            "name": user.name,
            "eco_score": float(user.eco_score or 0.0),
            "level": user.level,
            "total_impact": summary['total_impact'],
        })
    return leaderboard

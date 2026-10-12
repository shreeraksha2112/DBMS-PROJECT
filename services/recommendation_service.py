from datetime import datetime

from repositories.models import Challenge, UserChallenge
from services.verification_service import create_notification, log_audit_event
from services.wallet_service import credit_wallet


def get_recommendations_for_user(user_id, limit=3):
    challenges = Challenge.query.all()
    recommendations = []
    for challenge in challenges[:limit]:
        recommendations.append({
            "challenge_id": challenge.challenge_id,
            "title": challenge.title,
            "type": challenge.type,
            "target_value": float(challenge.target_value),
            "reward_points": float(challenge.reward_points),
            "end_date": challenge.end_date.isoformat() if challenge.end_date else None,
        })
    return recommendations


def update_challenge_progress(user_id, activity_id, quantity):
    active_challenges = UserChallenge.query.filter_by(user_id=user_id, status='active').all()
    now = datetime.utcnow()
    for user_challenge in active_challenges:
        challenge = user_challenge.challenge
        if not challenge:
            continue
        if challenge.end_date <= now or (challenge.start_date and challenge.start_date > now):
            continue

        if challenge.type == 'personal' and challenge.title.lower().startswith('cycling') and activity_id == 1:
            user_challenge.progress += float(quantity)
            if user_challenge.progress >= challenge.target_value:
                user_challenge.status = 'completed'
                user_challenge.progress = challenge.target_value
                credit_wallet(
                    user_id,
                    challenge.reward_points,
                    reference_id=challenge.challenge_id,
                    transaction_type='challenge_reward',
                )
                create_notification(
                    user_id,
                    'reward',
                    f"Challenge completed: {challenge.title}. You earned {challenge.reward_points:g} points!",
                )
                log_audit_event(
                    user_id,
                    'challenge_completed',
                    'challenge',
                    challenge.challenge_id,
                    challenge.title,
                )
                from services.gamification_service import evaluate_badges_for_user

                evaluate_badges_for_user(user_id)
    return True

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import desc
from routes.auth import token_required
from repositories.db import db
from repositories.models import Challenge, ChallengeReminder, Notification, User, UserChallenge

challenge_bp = Blueprint('challenge', __name__)

@challenge_bp.route('/', methods=['GET'])
@token_required
def get_challenges(current_user):
    challenges = Challenge.query.order_by(Challenge.end_date.asc()).all()
    now = datetime.utcnow()
    reminders = {
        reminder.challenge_id: reminder
        for reminder in ChallengeReminder.query.filter_by(user_id=current_user.user_id).all()
    }
    notifications_created = False
    result = []
    for c in challenges:
        participation = UserChallenge.query.filter_by(
            user_id=current_user.user_id,
            challenge_id=c.challenge_id,
        ).first()
        status = participation.status if participation else 'available'
        if status == 'active' and c.end_date <= now:
            status = 'expired'
        elif not participation and c.end_date <= now:
            status = 'expired'
        elif not participation and c.start_date and c.start_date > now:
            status = 'upcoming'
        reminder = reminders.get(c.challenge_id)
        reminder_enabled = reminder is not None
        if (
            reminder and c.start_date and not reminder.start_reminder_sent
            and c.start_date - timedelta(hours=24) <= now <= c.start_date + timedelta(hours=24)
            and now < c.end_date
        ):
            message = (
                f"'{c.title}' starts within 24 hours."
                if now < c.start_date
                else f"'{c.title}' has started. Check your progress!"
            )
            db.session.add(Notification(
                user_id=current_user.user_id,
                notification_type='challenge',
                message=message,
            ))
            reminder.start_reminder_sent = True
            notifications_created = True
        if reminder and not reminder.end_reminder_sent and now < c.end_date <= now + timedelta(hours=24):
            db.session.add(Notification(
                user_id=current_user.user_id,
                notification_type='challenge',
                message=f"'{c.title}' ends within 24 hours. Check your progress!",
            ))
            reminder.end_reminder_sent = True
            notifications_created = True
        result.append({
            "challenge_id": c.challenge_id,
            "title": c.title,
            "type": c.type,
            "target_value": float(c.target_value),
            "reward_points": float(c.reward_points),
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "progress": float(participation.progress or 0.0) if participation else 0.0,
            "status": status,
            "joined": participation is not None,
            "reminder_enabled": reminder_enabled,
        })
    if notifications_created:
        db.session.commit()
    return jsonify({"challenges": result}), 200

@challenge_bp.route('/<int:challenge_id>/join', methods=['POST'])
@token_required
def join_challenge(current_user, challenge_id):
    # FR-07: Join a challenge
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    now = datetime.utcnow()
    if challenge.start_date and challenge.start_date > now:
        return jsonify({"error": "This challenge has not started yet"}), 400
    if challenge.end_date <= now:
        return jsonify({"error": "This challenge has ended"}), 400
        
    existing = UserChallenge.query.filter_by(user_id=current_user.user_id, challenge_id=challenge_id).first()
    if existing:
        return jsonify({"error": "Already joined this challenge"}), 400
        
    user_challenge = UserChallenge(
        user_id=current_user.user_id,
        challenge_id=challenge_id,
        progress=0.0,
        status='active'
    )
    db.session.add(user_challenge)
    db.session.commit()
    
    return jsonify({
        "message": f"You joined {challenge.title}. Log eligible activities to make progress!",
        "challenge": {
            "challenge_id": challenge.challenge_id,
            "title": challenge.title,
            "target_value": float(challenge.target_value),
            "reward_points": float(challenge.reward_points),
            "progress": float(user_challenge.progress),
            "status": user_challenge.status,
            "joined": True,
        },
    }), 201


@challenge_bp.route('/<int:challenge_id>/reminder', methods=['PUT', 'DELETE'])
@token_required
def set_challenge_reminder(current_user, challenge_id):
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    reminder = ChallengeReminder.query.filter_by(
        user_id=current_user.user_id,
        challenge_id=challenge_id,
    ).first()
    if request.method == 'DELETE':
        if reminder:
            db.session.delete(reminder)
            db.session.commit()
        return jsonify({"reminder_enabled": False}), 200

    if challenge.end_date <= datetime.utcnow():
        return jsonify({"error": "Reminders are unavailable for ended challenges"}), 400
    if reminder is None:
        db.session.add(ChallengeReminder(user_id=current_user.user_id, challenge_id=challenge_id))
    db.session.commit()
    return jsonify({"reminder_enabled": True}), 200


@challenge_bp.route('/<int:challenge_id>/leaderboard', methods=['GET'])
@token_required
def get_challenge_leaderboard(current_user, challenge_id):
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    rows = db.session.query(UserChallenge, User).join(
        User, User.user_id == UserChallenge.user_id
    ).filter(
        UserChallenge.challenge_id == challenge_id,
        UserChallenge.status.in_(['active', 'completed']),
        User.account_status == 'active',
    ).order_by(
        desc(UserChallenge.progress),
        User.created_at.asc(),
        User.user_id.asc(),
    ).limit(50).all()

    entries = [{
        "rank": index,
        "user_id": user.user_id,
        "name": user.name,
        "progress": float(participation.progress or 0),
        "target_value": float(challenge.target_value),
        "status": participation.status,
        "is_current_user": user.user_id == current_user.user_id,
    } for index, (participation, user) in enumerate(rows, start=1)]
    return jsonify({
        "challenge": {"challenge_id": challenge.challenge_id, "title": challenge.title},
        "leaderboard": entries,
    }), 200

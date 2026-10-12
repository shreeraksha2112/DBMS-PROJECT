from datetime import datetime

from flask import Blueprint, jsonify
from routes.auth import token_required
from repositories.db import db
from repositories.models import Challenge, UserChallenge

challenge_bp = Blueprint('challenge', __name__)

@challenge_bp.route('/', methods=['GET'])
@token_required
def get_challenges(current_user):
    challenges = Challenge.query.order_by(Challenge.end_date.asc()).all()
    now = datetime.utcnow()
    result = []
    for c in challenges:
        participation = UserChallenge.query.filter_by(
            user_id=current_user.user_id,
            challenge_id=c.challenge_id,
        ).first()
        status = participation.status if participation else 'available'
        if not participation and c.end_date <= now:
            status = 'expired'
        elif not participation and c.start_date and c.start_date > now:
            status = 'upcoming'
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
        })
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

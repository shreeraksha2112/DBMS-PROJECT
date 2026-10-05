from flask import Blueprint, request, jsonify
from routes.auth import token_required
from repositories.db import db
from repositories.models import Challenge, UserChallenge

challenge_bp = Blueprint('challenge', __name__)

@challenge_bp.route('/', methods=['GET'])
@token_required
def get_challenges(current_user):
    # FR-07: Return available challenges
    challenges = Challenge.query.all()
    result = []
    for c in challenges:
        result.append({
            "challenge_id": c.challenge_id,
            "title": c.title,
            "type": c.type,
            "target_value": c.target_value,
            "reward_points": c.reward_points,
            "end_date": c.end_date.isoformat()
        })
    return jsonify({"challenges": result}), 200

@challenge_bp.route('/<int:challenge_id>/join', methods=['POST'])
@token_required
def join_challenge(current_user, challenge_id):
    # FR-07: Join a challenge
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404
        
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
    
    return jsonify({"message": "Successfully joined challenge"}), 201

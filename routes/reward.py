from flask import Blueprint, jsonify
from routes.auth import token_required
from repositories.db import db
from repositories.models import Reward, Redemption
from services.wallet_service import debit_wallet

reward_bp = Blueprint('reward', __name__)


@reward_bp.route('/', methods=['GET'])
@token_required
def get_rewards(current_user):
    rewards = Reward.query.filter_by(active=True).all()
    result = []
    for reward in rewards:
        result.append({
            "reward_id": reward.reward_id,
            "name": reward.name,
            "points_required": float(reward.points_required),
            "stock": reward.stock,
            "tier": reward.tier,
        })
    return jsonify({"rewards": result}), 200


@reward_bp.route('/<int:reward_id>/redeem', methods=['POST'])
@token_required
def redeem_reward(current_user, reward_id):
    reward = Reward.query.get(reward_id)
    if not reward or not reward.active:
        return jsonify({"error": "Reward not available"}), 404

    if reward.stock <= 0:
        return jsonify({"error": "Reward out of stock"}), 400

    try:
        debit_wallet(current_user.user_id, reward.points_required, reference_id=reward_id, transaction_type='debit')
    except ValueError:
        return jsonify({"error": "Insufficient points"}), 400

    reward.stock -= 1

    redemption = Redemption(
        user_id=current_user.user_id,
        reward_id=reward_id,
        points_used=reward.points_required,
    )
    db.session.add(redemption)
    db.session.commit()

    return jsonify({"message": "Reward redeemed successfully"}), 200

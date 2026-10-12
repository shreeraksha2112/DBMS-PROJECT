from flask import Blueprint, jsonify
from sqlalchemy import func
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


@reward_bp.route('/history', methods=['GET'])
@token_required
def get_redemption_history(current_user):
    redemptions = db.session.query(Redemption, Reward).join(
        Reward, Reward.reward_id == Redemption.reward_id
    ).filter(
        Redemption.user_id == current_user.user_id
    ).order_by(
        Redemption.redeemed_at.desc()
    ).limit(50).all()
    totals = db.session.query(
        func.count(Redemption.redemption_id),
        func.coalesce(func.sum(Redemption.points_used), 0),
    ).filter(
        Redemption.user_id == current_user.user_id
    ).first()

    return jsonify({
        "total_redemptions": int(totals[0] or 0),
        "total_points_spent": float(totals[1] or 0),
        "redemptions": [{
            "redemption_id": redemption.redemption_id,
            "reward_id": reward.reward_id,
            "reward_name": reward.name,
            "points_used": float(redemption.points_used),
            "status": redemption.status,
            "redeemed_at": redemption.redeemed_at.isoformat() if redemption.redeemed_at else None,
        } for redemption, reward in redemptions],
    }), 200


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

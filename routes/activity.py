from flask import Blueprint, request, jsonify
from routes.auth import token_required
from repositories.db import db
from repositories.models import ActivityType, ImpactFactor, EcoActivity, ImpactRecord, User
from services.impact_service import calculate_activity_impact
from services.wallet_service import credit_wallet
from services.gamification_service import update_user_gamification
from services.recommendation_service import update_challenge_progress
from services.verification_service import evaluate_activity_anomaly, create_notification, log_audit_event

activity_bp = Blueprint('activity', __name__)


@activity_bp.route('/', methods=['POST'])
@token_required
def submit_activity(current_user):
    data = request.get_json(silent=True)

    if not data or not data.get('activity_id') or data.get('quantity') is None:
        return jsonify({"error": "Missing activity_id or quantity"}), 400

    activity_id = int(data['activity_id'])
    quantity = float(data['quantity'])
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than zero"}), 400

    activity_type = ActivityType.query.get(activity_id)
    if not activity_type:
        return jsonify({"error": "Invalid activity_id"}), 404

    points = activity_type.base_points * quantity
    status = 'pending' if activity_type.verification_required else 'approved'

    eco_activity = EcoActivity(
        user_id=current_user.user_id,
        activity_id=activity_id,
        quantity=quantity,
        points=points,
        status=status,
    )
    db.session.add(eco_activity)
    db.session.flush()

    impact_results = []
    factors = ImpactFactor.query.filter_by(activity_id=activity_id).all()
    for factor in factors:
        impact_value = float(factor.factor_value * quantity)
        db.session.add(ImpactRecord(
            eco_activity_id=eco_activity.record_id,
            metric_type=factor.metric_type,
            impact_value=impact_value,
        ))
        impact_results.append({"metric": factor.metric_type, "value": impact_value})

    anomaly = evaluate_activity_anomaly(current_user.user_id, activity_id, quantity, eco_activity.record_id)
    eco_activity.is_flagged = anomaly['flagged']
    eco_activity.risk_score = anomaly['risk_score']
    eco_activity.flag_reason = anomaly['reason']
    if anomaly['flagged']:
        eco_activity.status = 'flagged'
        create_notification(current_user.user_id, 'warning', 'Activity flagged for review by moderation team.')
        log_audit_event(current_user.user_id, 'activity_flagged', 'eco_activity', eco_activity.record_id, anomaly['reason'])

    if status == 'approved' and not anomaly['flagged']:
        credit_wallet(current_user.user_id, points, eco_activity.record_id, transaction_type='credit')
        update_user_gamification(current_user, points)
        update_challenge_progress(current_user.user_id, activity_id, quantity)

    db.session.commit()

    return jsonify({
        "message": "Activity submitted successfully",
        "status": eco_activity.status,
        "points_earned": float(points),
        "impact": impact_results,
        "flagged": anomaly['flagged'],
        "risk_score": anomaly['risk_score'],
    }), 201


@activity_bp.route('/', methods=['GET'])
@token_required
def get_activities(current_user):
    activities = EcoActivity.query.filter_by(user_id=current_user.user_id).order_by(EcoActivity.activity_date.desc()).all()
    result = []
    for activity in activities:
        result.append({
            "record_id": activity.record_id,
            "activity_name": activity.activity_type.name,
            "quantity": float(activity.quantity),
            "points": float(activity.points),
            "status": activity.status,
            "date": activity.activity_date.isoformat() if activity.activity_date else None,
        })
    return jsonify({"activities": result}), 200

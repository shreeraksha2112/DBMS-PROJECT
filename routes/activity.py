from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from sqlalchemy import func
from routes.auth import token_required
from repositories.db import db
from repositories.models import ActivityType, ImpactFactor, EcoActivity, ImpactRecord, User
from services.impact_service import calculate_activity_impact
from services.wallet_service import credit_wallet
from services.gamification_service import update_user_gamification
from services.recommendation_service import update_challenge_progress
from services.verification_service import evaluate_activity_anomaly, create_notification, log_audit_event

activity_bp = Blueprint('activity', __name__)


@activity_bp.route('/types', methods=['GET'])
@token_required
def get_activity_types(current_user):
    activity_types = ActivityType.query.order_by(ActivityType.name.asc()).all()
    return jsonify({
        "activity_types": [{
            "activity_id": item.activity_id,
            "name": item.name,
            "unit": item.unit,
        } for item in activity_types]
    }), 200


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
    query = EcoActivity.query.filter_by(user_id=current_user.user_id)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    activity_id = request.args.get('activity_id')
    status = request.args.get('status')

    try:
        if start_date:
            query = query.filter(EcoActivity.activity_date >= datetime.strptime(start_date, '%Y-%m-%d'))
        if end_date:
            inclusive_end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(EcoActivity.activity_date < inclusive_end)
    except ValueError:
        return jsonify({"error": "Dates must use YYYY-MM-DD format"}), 400

    if activity_id:
        try:
            parsed_activity_id = int(activity_id)
        except ValueError:
            return jsonify({"error": "activity_id must be a valid integer"}), 400
        if not ActivityType.query.get(parsed_activity_id):
            return jsonify({"error": "Unknown activity type"}), 400
        query = query.filter_by(activity_id=parsed_activity_id)
    if status:
        if status not in {'pending', 'approved', 'rejected', 'flagged'}:
            return jsonify({"error": "status must be pending, approved, rejected, or flagged"}), 400
        query = query.filter_by(status=status)

    if start_date and end_date and start_date > end_date:
        return jsonify({"error": "start_date must not be after end_date"}), 400

    activities = query.order_by(EcoActivity.activity_date.desc()).all()
    totals = db.session.query(
        func.count(EcoActivity.record_id),
        func.coalesce(func.sum(EcoActivity.quantity), 0),
        func.coalesce(func.sum(EcoActivity.points), 0),
    ).filter(
        EcoActivity.record_id.in_([item.record_id for item in activities])
    ).first() if activities else (0, 0, 0)
    result = []
    for activity in activities:
        result.append({
            "record_id": activity.record_id,
            "activity_name": activity.activity_type.name,
            "activity_id": activity.activity_id,
            "quantity": float(activity.quantity),
            "points": float(activity.points),
            "status": activity.status,
            "date": activity.activity_date.isoformat() if activity.activity_date else None,
        })
    return jsonify({
        "activities": result,
        "summary": {
            "count": int(totals[0] or 0),
            "total_quantity": float(totals[1] or 0),
            "total_points": float(totals[2] or 0),
        },
    }), 200

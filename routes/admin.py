from flask import Blueprint, jsonify, request

from repositories.db import db
from repositories.models import EcoActivity, User, Role
from routes.auth import token_required
from services.verification_service import verify_activity

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/users', methods=['GET'])
@token_required
def list_users(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({
        "users": [
            {
                "user_id": user.user_id,
                "name": user.name,
                "email": user.email,
                "eco_score": float(user.eco_score or 0.0),
                "level": user.level,
            }
            for user in users
        ]
    }), 200


@admin_bp.route('/activities/pending', methods=['GET'])
@token_required
def list_pending_activities(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    activities = EcoActivity.query.filter_by(status='pending').order_by(EcoActivity.activity_date.desc()).all()
    return jsonify({
        "activities": [
            {
                "record_id": activity.record_id,
                "user_id": activity.user_id,
                "activity_name": activity.activity_type.name,
                "quantity": float(activity.quantity),
                "points": float(activity.points),
                "status": activity.status,
            }
            for activity in activities
        ]
    }), 200


@admin_bp.route('/activities/<int:record_id>/review', methods=['POST'])
@token_required
def review_activity(current_user, record_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    decision = data.get('decision', 'approved').lower()
    method = data.get('method', 'manual')

    if decision not in {'approved', 'rejected'}:
        return jsonify({"error": "decision must be either approved or rejected"}), 400

    try:
        result = verify_activity(record_id, method=method, decision=decision, reviewer_id=current_user.user_id)
        return jsonify({"message": "Verification processed", "result": result}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

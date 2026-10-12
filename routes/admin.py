import csv
from io import StringIO, BytesIO
import math
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import func

from repositories.db import db
from repositories.models import EcoActivity, User, Role, AuditLog, QREvent, QRClaim
from routes.auth import token_required, bcrypt
from services.qr_reward_service import create_qr_image
from services.verification_service import verify_activity, log_audit_event, create_notification

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/analytics', methods=['GET'])
@token_required
def get_admin_analytics(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    try:
        days = int(request.args.get('days', '30'))
    except ValueError:
        return jsonify({"error": "days must be 7, 30, or 90"}), 400
    if days not in {7, 30, 90}:
        return jsonify({"error": "days must be 7, 30, or 90"}), 400

    today = datetime.utcnow().date()
    start_date = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    labels = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    daily_counts = {
        'users': {},
        'activities': {},
        'qr_claims': {},
    }

    user_rows = db.session.query(
        func.date(User.created_at), func.count(User.user_id)
    ).filter(
        User.created_at >= start_date
    ).group_by(func.date(User.created_at)).all()
    activity_rows = db.session.query(
        func.date(EcoActivity.activity_date), func.count(EcoActivity.record_id)
    ).filter(
        EcoActivity.activity_date >= start_date
    ).group_by(func.date(EcoActivity.activity_date)).all()
    claim_rows = db.session.query(
        func.date(QRClaim.claimed_at), func.count(QRClaim.claim_id)
    ).filter(
        QRClaim.claimed_at >= start_date
    ).group_by(func.date(QRClaim.claimed_at)).all()

    for key, rows in (
        ('users', user_rows),
        ('activities', activity_rows),
        ('qr_claims', claim_rows),
    ):
        daily_counts[key] = {str(day)[:10]: count for day, count in rows}

    status_rows = db.session.query(
        EcoActivity.status, func.count(EcoActivity.record_id)
    ).filter(
        EcoActivity.activity_date >= start_date
    ).group_by(EcoActivity.status).all()
    event_rows = db.session.query(
        QREvent.business_name,
        QREvent.event_name,
        func.count(QRClaim.claim_id),
    ).join(
        QRClaim, QRClaim.event_id == QREvent.event_id
    ).filter(
        QRClaim.claimed_at >= start_date
    ).group_by(
        QREvent.event_id, QREvent.business_name, QREvent.event_name
    ).order_by(
        func.count(QRClaim.claim_id).desc(), QREvent.event_id
    ).limit(6).all()

    return jsonify({
        "days": days,
        "labels": labels,
        "daily": {
            key: [daily_counts[key].get(day, 0) for day in labels]
            for key in ('users', 'activities', 'qr_claims')
        },
        "activity_status": [
            {"status": status or "unknown", "count": count}
            for status, count in status_rows
        ],
        "qr_events": [
            {
                "label": f"{business_name}: {event_name}",
                "claims": count,
            }
            for business_name, event_name, count in event_rows
        ],
    }), 200


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
                "role_name": user.role.role_name if user.role else 'User',
                "eco_score": float(user.eco_score or 0.0),
                "level": user.level,
                "account_status": user.account_status,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            for user in users
        ]
    }), 200


@admin_bp.route('/exports/<string:dataset>.csv', methods=['GET'])
@token_required
def export_admin_csv(current_user, dataset):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    output = StringIO()
    writer = csv.writer(output)

    def write_row(values):
        safe_values = [
            "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
            for value in values
        ]
        writer.writerow(safe_values)

    if dataset == 'users':
        write_row(['user_id', 'name', 'email', 'role', 'account_status', 'eco_score', 'level', 'created_at'])
        for user in User.query.order_by(User.created_at.desc()).all():
            write_row([
                user.user_id, user.name, user.email,
                user.role.role_name if user.role else 'User',
                user.account_status, user.eco_score or 0, user.level,
                user.created_at.isoformat() if user.created_at else '',
            ])
        filename = 'ecosphere-users.csv'
    elif dataset == 'activities':
        write_row(['record_id', 'user_id', 'user_name', 'activity', 'quantity', 'points', 'status', 'is_flagged', 'activity_date'])
        activities = EcoActivity.query.join(User, EcoActivity.user_id == User.user_id).order_by(
            EcoActivity.activity_date.desc()
        ).all()
        for activity in activities:
            write_row([
                activity.record_id, activity.user_id, activity.user.name,
                activity.activity_type.name, activity.quantity, activity.points,
                activity.status, bool(activity.is_flagged),
                activity.activity_date.isoformat() if activity.activity_date else '',
            ])
        filename = 'ecosphere-activities.csv'
    elif dataset == 'qr-claims':
        write_row(['claim_id', 'event_id', 'business_name', 'event_name', 'user_id', 'user_name', 'reward_points', 'claimed_at'])
        claims = db.session.query(QRClaim, QREvent, User).join(
            QREvent, QRClaim.event_id == QREvent.event_id
        ).join(
            User, QRClaim.user_id == User.user_id
        ).order_by(QRClaim.claimed_at.desc()).all()
        for claim, event, user in claims:
            write_row([
                claim.claim_id, event.event_id, event.business_name, event.event_name,
                user.user_id, user.name, event.reward_points,
                claim.claimed_at.isoformat() if claim.claimed_at else '',
            ])
        filename = 'ecosphere-qr-claims.csv'
    else:
        return jsonify({"error": "Unknown export. Choose users, activities, or qr-claims."}), 404

    response = send_file(
        BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv; charset=utf-8',
        as_attachment=True,
        download_name=filename,
    )
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.route('/qr-events', methods=['GET'])
@token_required
def list_qr_events(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    events = QREvent.query.order_by(QREvent.created_at.desc()).limit(30).all()
    return jsonify({"qr_events": [{
        "event_id": event.event_id,
        "business_name": event.business_name,
        "event_name": event.event_name,
        "qr_token": event.qr_token,
        "reward_points": float(event.reward_points),
        "expires_at": event.expires_at.isoformat(),
        "active": bool(event.active) and event.expires_at > datetime.utcnow(),
        "claims": QRClaim.query.filter_by(event_id=event.event_id).count(),
        "qr_image_url": f"/api/admin/qr-events/{event.event_id}/qr",
    } for event in events]}), 200


@admin_bp.route('/qr-events', methods=['POST'])
@token_required
def create_qr_event(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    business_name = data.get('business_name')
    event_name = data.get('event_name')
    try:
        reward_points = float(data.get('reward_points'))
        expires_in_hours = int(data.get('expires_in_hours', 24))
    except (TypeError, ValueError):
        return jsonify({"error": "Reward points and expiry must be valid numbers"}), 400

    if not isinstance(business_name, str) or not business_name.strip() or len(business_name.strip()) > 120:
        return jsonify({"error": "Business name is required and must be at most 120 characters"}), 400
    if not isinstance(event_name, str) or not event_name.strip() or len(event_name.strip()) > 150:
        return jsonify({"error": "Event name is required and must be at most 150 characters"}), 400
    if not math.isfinite(reward_points) or not 1 <= reward_points <= 10000:
        return jsonify({"error": "Reward points must be between 1 and 10000"}), 400
    if not 1 <= expires_in_hours <= 720:
        return jsonify({"error": "QR expiry must be between 1 and 720 hours"}), 400

    event = QREvent(
        business_name=business_name.strip(),
        event_name=event_name.strip(),
        qr_token=secrets.token_urlsafe(32),
        reward_points=reward_points,
        expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
        created_by=current_user.user_id,
    )
    db.session.add(event)
    db.session.flush()
    db.session.add(AuditLog(
        actor_id=current_user.user_id,
        action='qr_event_created',
        entity_type='qr_event',
        entity_id=event.event_id,
        details=f'{event.business_name}: {event.event_name}',
    ))
    db.session.commit()

    return jsonify({"qr_event": {
        "event_id": event.event_id,
        "business_name": event.business_name,
        "event_name": event.event_name,
        "qr_token": event.qr_token,
        "reward_points": float(event.reward_points),
        "expires_at": event.expires_at.isoformat(),
        "active": True,
        "claims": 0,
        "qr_image_url": f"/api/admin/qr-events/{event.event_id}/qr",
    }}), 201


@admin_bp.route('/qr-events/<int:event_id>/qr', methods=['GET'])
@token_required
def get_qr_event_image(current_user, event_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    event = QREvent.query.get(event_id)
    if not event:
        return jsonify({"error": "QR event not found"}), 404

    response = send_file(
        create_qr_image(event.qr_token),
        mimetype='image/png',
        download_name=f'ecosphere-event-{event.event_id}.png',
    )
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.route('/qr-events/<int:event_id>', methods=['PATCH'])
@token_required
def update_qr_event(current_user, event_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    event = QREvent.query.get(event_id)
    if not event:
        return jsonify({"error": "QR event not found"}), 404

    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('active'), bool):
        return jsonify({"error": "active must be a boolean"}), 400
    if data['active'] and event.expires_at <= datetime.utcnow():
        return jsonify({"error": "Expired QR events cannot be reactivated"}), 400

    event.active = data['active']
    db.session.add(AuditLog(
        actor_id=current_user.user_id,
        action='qr_event_activated' if event.active else 'qr_event_deactivated',
        entity_type='qr_event',
        entity_id=event.event_id,
        details=event.event_name,
    ))
    db.session.commit()
    return jsonify({"message": "QR event status updated", "active": bool(event.active)}), 200


@admin_bp.route('/users/<int:user_id>/progress', methods=['GET'])
@token_required
def get_user_progress(current_user, user_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    activities = EcoActivity.query.filter_by(user_id=user_id).order_by(EcoActivity.activity_date.desc()).all()
    total_points = sum(float(a.points) for a in activities)
    total_quantity = sum(float(a.quantity) for a in activities)
    return jsonify({
        "user_id": user.user_id,
        "name": user.name,
        "eco_score": float(user.eco_score or 0.0),
        "level": user.level,
        "account_status": user.account_status,
        "progress": {
            "total_activities": len(activities),
            "total_points": total_points,
            "total_quantity": total_quantity,
            "recent_activity": [{
                "record_id": activity.record_id,
                "activity_name": activity.activity_type.name,
                "status": activity.status,
                "quantity": float(activity.quantity),
                "points": float(activity.points),
                "date": activity.activity_date.isoformat() if activity.activity_date else None,
            } for activity in activities[:10]]
        }
    }), 200


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@token_required
def reset_user_password(current_user, user_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    password = data.get('password')
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    user.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    user.account_status = 'active'
    db.session.commit()
    return jsonify({"message": "Password reset successful", "user_id": user.user_id}), 200


@admin_bp.route('/users/<int:user_id>/terminate', methods=['POST'])
@token_required
def terminate_user_account(current_user, user_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if user.user_id == current_user.user_id:
        return jsonify({"error": "Admin cannot terminate own account"}), 400

    user.account_status = 'terminated'
    db.session.commit()
    return jsonify({"message": "User account terminated successfully", "user_id": user.user_id}), 200


@admin_bp.route('/activities/pending', methods=['GET'])
@token_required
def list_pending_activities(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    activities = EcoActivity.query.filter(
        EcoActivity.status.in_(['pending', 'flagged'])
    ).order_by(EcoActivity.activity_date.desc()).all()
    return jsonify({
        "activities": [
            {
                "record_id": activity.record_id,
                "user_id": activity.user_id,
                "activity_name": activity.activity_type.name,
                "quantity": float(activity.quantity),
                "points": float(activity.points),
                "status": activity.status,
                "is_flagged": bool(activity.is_flagged),
                "risk_score": float(activity.risk_score or 0.0),
                "reason": activity.flag_reason or '',
                "activity_date": activity.activity_date.isoformat() if activity.activity_date else None,
            }
            for activity in activities
        ]
    }), 200


@admin_bp.route('/activities/<int:record_id>/flag', methods=['PATCH'])
@token_required
def flag_activity(current_user, record_id):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    activity = EcoActivity.query.get(record_id)
    if not activity:
        return jsonify({"error": "Activity not found"}), 404
    if activity.status not in {'pending', 'flagged'}:
        return jsonify({"error": "Only activities awaiting review can be flagged"}), 409

    data = request.get_json(silent=True) or {}
    flagged = data.get('flagged')
    if not isinstance(flagged, bool):
        return jsonify({"error": "flagged must be a boolean"}), 400

    reason = data.get('reason', '')
    if not isinstance(reason, str) or len(reason.strip()) > 255:
        return jsonify({"error": "reason must be a string of at most 255 characters"}), 400
    if flagged and not reason.strip() and not activity.is_flagged:
        return jsonify({"error": "A reason is required when flagging an activity"}), 400

    activity.is_flagged = flagged
    activity.status = 'flagged' if flagged else 'pending'
    if flagged:
        activity.flag_reason = reason.strip() or activity.flag_reason or 'Flagged for admin review'
    else:
        activity.flag_reason = ''
    action = 'activity_flagged' if flagged else 'activity_unflagged'
    details = activity.flag_reason or 'Flag cleared by administrator'
    log_audit_event(current_user.user_id, action, 'eco_activity', activity.record_id, details)
    if flagged:
        create_notification(
            activity.user_id,
            'warning',
            'Your eco activity has been flagged for administrator review.',
        )
    db.session.commit()
    return jsonify({
        "message": "Activity flag updated",
        "record_id": activity.record_id,
        "is_flagged": bool(activity.is_flagged),
        "status": activity.status,
        "reason": activity.flag_reason,
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
        status_code = 404 if str(exc) == 'Activity not found' else 409
        return jsonify({"error": str(exc)}), status_code


@admin_bp.route('/moderation', methods=['GET'])
@token_required
def list_moderation(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    flagged = EcoActivity.query.filter_by(is_flagged=True).order_by(EcoActivity.activity_date.desc()).all()
    return jsonify({
        "flagged": [{
            "record_id": activity.record_id,
            "user_id": activity.user_id,
            "activity_name": activity.activity_type.name,
            "quantity": float(activity.quantity),
            "risk_score": float(activity.risk_score or 0.0),
            "reason": activity.flag_reason or 'suspicious submission',
            "status": activity.status,
        } for activity in flagged]
    }), 200


@admin_bp.route('/audit-logs', methods=['GET'])
@token_required
def list_audit_logs(current_user):
    if current_user.role.role_name != 'Admin':
        return jsonify({"error": "Admin access required"}), 403

    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(25).all()
    return jsonify({
        "audit_logs": [{
            "log_id": log.log_id,
            "actor_id": log.actor_id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        } for log in logs]
    }), 200

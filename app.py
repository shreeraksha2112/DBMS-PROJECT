from flask import Flask, request, render_template, jsonify
from sqlalchemy import inspect, text
from config import Config
from repositories.db import db
from repositories.models import Notification, QREvent, QRClaim


def ensure_schema_compatibility(engine):
    migrations = {
        'users': {
            'account_status': "VARCHAR(50) NOT NULL DEFAULT 'active'",
        },
        'eco_activities': {
            'is_flagged': 'BOOLEAN NOT NULL DEFAULT FALSE',
            'risk_score': 'FLOAT DEFAULT 0',
            'flag_reason': "VARCHAR(255) DEFAULT ''",
        },
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    for table_name, columns in migrations.items():
        if table_name not in tables:
            continue
        existing_columns = {column['name'] for column in inspector.get_columns(table_name)}
        for column_name, definition in columns.items():
            if column_name not in existing_columns:
                with engine.begin() as connection:
                    connection.execute(text(
                        f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}'
                    ))
                existing_columns.add(column_name)


def seed_default_data():
    from repositories.models import Role, ActivityType, ImpactFactor, Challenge, Reward, Notification
    from datetime import datetime, timedelta

    if not Role.query.filter_by(role_name='User').first():
        db.session.add(Role(role_name='User'))
    if not Role.query.filter_by(role_name='Admin').first():
        db.session.add(Role(role_name='Admin'))

    if not ActivityType.query.filter_by(name='Cycling').first():
        cycling = ActivityType(name='Cycling', unit='km', base_points=10.0, verification_required=False)
        db.session.add(cycling)
        db.session.flush()
        db.session.add(ImpactFactor(activity_id=cycling.activity_id, metric_type='CO2e (kg)', factor_value=0.2))

    if not ActivityType.query.filter_by(name='Recycling Plastic').first():
        recycling = ActivityType(name='Recycling Plastic', unit='kg', base_points=25.0, verification_required=True)
        db.session.add(recycling)
        db.session.flush()
        db.session.add(ImpactFactor(activity_id=recycling.activity_id, metric_type='CO2e (kg)', factor_value=1.5))
        db.session.add(ImpactFactor(activity_id=recycling.activity_id, metric_type='Water (L)', factor_value=30.0))

    if not Challenge.query.filter_by(title='Cycling Century').first():
        db.session.add(Challenge(
            title='Cycling Century',
            type='personal',
            target_value=100.0,
            reward_points=500.0,
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=30),
        ))

    if not Reward.query.filter_by(name='$10 Coffee Shop Gift Card').first():
        db.session.add(Reward(name='$10 Coffee Shop Gift Card', points_required=1000.0, stock=50, tier=1, active=True))
        db.session.add(Reward(name='Eco-Friendly Water Bottle', points_required=2500.0, stock=20, tier=2, active=True))

    db.session.commit()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    with app.app_context():
        from repositories import models
        db.create_all()
        ensure_schema_compatibility(db.engine)
        seed_default_data()

    from routes.auth import auth_bp, token_required
    from routes.activity import activity_bp
    from routes.challenge import challenge_bp
    from routes.reward import reward_bp
    from routes.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(activity_bp, url_prefix='/api/activities')
    app.register_blueprint(challenge_bp, url_prefix='/api/challenges')
    app.register_blueprint(reward_bp, url_prefix='/api/rewards')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    from services.impact_service import get_user_impact_summary, get_leaderboard
    from services.wallet_service import get_wallet_summary
    from services.recommendation_service import get_recommendations_for_user
    from services.verification_service import verify_qr_event
    from services.qr_reward_service import QRRewardError, claim_qr_reward

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/admin/login')
    def admin_login_page():
        return render_template('admin_login.html')

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')

        if request.path == '/admin/login':
            response.headers['Content-Security-Policy'] = (
                "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; "
                "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
            response.headers['Cache-Control'] = 'no-store'
        elif request.path.startswith('/api/auth/'):
            response.headers['Cache-Control'] = 'no-store'

        return response

    @app.route('/api/dashboard')
    @token_required
    def dashboard(current_user):
        wallet = get_wallet_summary(current_user.user_id)
        summary = get_user_impact_summary(current_user.user_id)
        recommendations = get_recommendations_for_user(current_user.user_id)
        return {
            "message": "Welcome to EcoSphere Rewards Dashboard",
            "wallet": {"balance": wallet['balance'], "transactions": wallet['transactions']},
            "impact": summary,
            "recommendations": recommendations,
            "eco_score": float(current_user.eco_score or 0.0),
            "level": current_user.level,
        }, 200

    @app.route('/api/wallet')
    @token_required
    def wallet_endpoint(current_user):
        return jsonify(get_wallet_summary(current_user.user_id)), 200

    @app.route('/api/impact')
    @token_required
    def impact_endpoint(current_user):
        return jsonify(get_user_impact_summary(current_user.user_id)), 200

    @app.route('/api/leaderboard')
    @token_required
    def leaderboard_endpoint(current_user):
        return jsonify({"leaderboard": get_leaderboard(limit=10)}), 200

    @app.route('/api/notifications', methods=['GET'])
    @token_required
    def notifications_endpoint(current_user):
        notifications = Notification.query.filter_by(user_id=current_user.user_id).order_by(Notification.created_at.desc()).limit(50).all()
        unread_count = Notification.query.filter_by(user_id=current_user.user_id, is_read=False).count()
        return jsonify({
            "unread_count": unread_count,
            "notifications": [{
                "notification_id": item.notification_id,
                "type": item.notification_type,
                "message": item.message,
                "is_read": item.is_read,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            } for item in notifications]
        }), 200

    @app.route('/api/notifications/<int:notification_id>/read', methods=['PATCH'])
    @token_required
    def mark_notification_read(current_user, notification_id):
        notification = Notification.query.filter_by(
            notification_id=notification_id,
            user_id=current_user.user_id,
        ).first()
        if not notification:
            return jsonify({"error": "Notification not found"}), 404
        notification.is_read = True
        db.session.commit()
        return jsonify({"notification_id": notification.notification_id, "is_read": True}), 200

    @app.route('/api/notifications/read-all', methods=['PATCH'])
    @token_required
    def mark_all_notifications_read(current_user):
        updated = Notification.query.filter_by(
            user_id=current_user.user_id,
            is_read=False,
        ).update({Notification.is_read: True}, synchronize_session=False)
        db.session.commit()
        return jsonify({"updated": updated}), 200

    @app.route('/api/badges', methods=['GET'])
    @token_required
    def user_badges_endpoint(current_user):
        from services.gamification_service import evaluate_badges_for_user, get_user_badges

        evaluate_badges_for_user(current_user.user_id)
        badges = get_user_badges(current_user.user_id)
        return jsonify({
            "earned_count": sum(1 for badge in badges if badge['earned']),
            "badges": badges,
        }), 200

    @app.route('/api/qr-rewards/history', methods=['GET'])
    @token_required
    def qr_reward_history_endpoint(current_user):
        claims = db.session.query(QRClaim, QREvent).join(
            QREvent, QRClaim.event_id == QREvent.event_id
        ).filter(
            QRClaim.user_id == current_user.user_id
        ).order_by(
            QRClaim.claimed_at.desc()
        ).limit(20).all()
        totals = db.session.query(
            db.func.count(QRClaim.claim_id),
            db.func.coalesce(db.func.sum(QREvent.reward_points), 0),
        ).join(
            QREvent, QRClaim.event_id == QREvent.event_id
        ).filter(
            QRClaim.user_id == current_user.user_id
        ).first()

        return jsonify({
            "total_claims": int(totals[0] or 0),
            "total_points": float(totals[1] or 0),
            "claims": [{
                "event_id": event.event_id,
                "business_name": event.business_name,
                "event_name": event.event_name,
                "points": float(event.reward_points),
                "claimed_at": claim.claimed_at.isoformat() if claim.claimed_at else None,
            } for claim, event in claims],
        }), 200

    @app.route('/api/verify/qr', methods=['POST'])
    @token_required
    def verify_qr_endpoint(current_user):
        data = request.get_json(silent=True) or {}
        qr_token = data.get('qr_token') or data.get('token')
        if not qr_token:
            return jsonify({"error": "Missing QR token"}), 400

        if not isinstance(qr_token, str):
            return jsonify({"error": "QR token must be a string"}), 400
        qr_token = qr_token.strip()
        if QREvent.query.filter_by(qr_token=qr_token).first():
            try:
                return jsonify(claim_qr_reward(current_user.user_id, qr_token)), 200
            except QRRewardError as exc:
                return jsonify({"error": str(exc)}), exc.status_code

        result = verify_qr_event(current_user.user_id, qr_token)
        if result['verified']:
            return jsonify(result), 200
        return jsonify(result), 400

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)

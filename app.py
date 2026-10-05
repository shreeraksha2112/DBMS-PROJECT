from flask import Flask, request, render_template, jsonify
from config import Config
from repositories.db import db


def seed_default_data():
    from repositories.models import Role, ActivityType, ImpactFactor, Challenge, Reward
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

    @app.route('/')
    def index():
        return render_template('index.html')

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

    @app.route('/api/verify/qr', methods=['POST'])
    @token_required
    def verify_qr_endpoint(current_user):
        data = request.get_json(silent=True) or {}
        qr_token = data.get('qr_token') or data.get('token')
        if not qr_token:
            return jsonify({"error": "Missing QR token"}), 400
        result = verify_qr_event(current_user.user_id, qr_token)
        if result['verified']:
            return jsonify(result), 200
        return jsonify(result), 400

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)

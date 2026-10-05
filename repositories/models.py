from repositories.db import db
from datetime import datetime


class Role(db.Model):
    __tablename__ = 'roles'
    role_id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)


class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    eco_score = db.Column(db.Float, default=0.0)
    level = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    role = db.relationship('Role', backref=db.backref('users', lazy=True))
    profile = db.relationship('UserProfile', backref='user', uselist=False)
    wallet = db.relationship('Wallet', backref='user', uselist=False, cascade='all, delete-orphan')
    activities = db.relationship('EcoActivity', backref='user', lazy=True)
    challenge_links = db.relationship('UserChallenge', backref='user', lazy=True)


class UserProfile(db.Model):
    __tablename__ = 'user_profiles'
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), primary_key=True)
    department = db.Column(db.String(100))
    goals = db.Column(db.Text)
    preferences = db.Column(db.JSON)


class ActivityType(db.Model):
    __tablename__ = 'activity_types'
    activity_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    base_points = db.Column(db.Float, nullable=False)
    verification_required = db.Column(db.Boolean, default=False)


class ImpactFactor(db.Model):
    __tablename__ = 'impact_factors'
    factor_id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity_types.activity_id'), nullable=False)
    metric_type = db.Column(db.String(50), nullable=False)
    factor_value = db.Column(db.Float, nullable=False)
    effective_from = db.Column(db.DateTime, default=datetime.utcnow)
    effective_to = db.Column(db.DateTime, nullable=True)


class EcoActivity(db.Model):
    __tablename__ = 'eco_activities'
    record_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity_types.activity_id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    points = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='pending')
    activity_date = db.Column(db.DateTime, default=datetime.utcnow)

    activity_type = db.relationship('ActivityType')
    impact_records = db.relationship('ImpactRecord', backref='eco_activity', lazy=True)


class ImpactRecord(db.Model):
    __tablename__ = 'impact_records'
    record_id = db.Column(db.Integer, primary_key=True)
    eco_activity_id = db.Column(db.Integer, db.ForeignKey('eco_activities.record_id'), nullable=False)
    metric_type = db.Column(db.String(50), nullable=False)
    impact_value = db.Column(db.Float, nullable=False)


class Wallet(db.Model):
    __tablename__ = 'wallets'
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), primary_key=True)
    current_balance = db.Column(db.Float, default=0.0)


class PointTransaction(db.Model):
    __tablename__ = 'point_transactions'
    transaction_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(50), nullable=False)
    reference_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Challenge(db.Model):
    __tablename__ = 'challenges'
    challenge_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    target_value = db.Column(db.Float, nullable=False)
    reward_points = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)

    user_challenges = db.relationship('UserChallenge', back_populates='challenge', cascade='all, delete-orphan')


class UserChallenge(db.Model):
    __tablename__ = 'user_challenges'
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.challenge_id'), primary_key=True)
    progress = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default='active')

    challenge = db.relationship('Challenge', back_populates='user_challenges')


class Badge(db.Model):
    __tablename__ = 'badges'
    badge_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rule_type = db.Column(db.String(50), nullable=False)
    rule_value = db.Column(db.Float, nullable=False)


class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), primary_key=True)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.badge_id'), primary_key=True)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

    badge = db.relationship('Badge', backref='user_badges', lazy=True)


class Reward(db.Model):
    __tablename__ = 'rewards'
    reward_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    points_required = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False)
    tier = db.Column(db.Integer, default=1)
    active = db.Column(db.Boolean, default=True)


class Redemption(db.Model):
    __tablename__ = 'redemptions'
    redemption_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    reward_id = db.Column(db.Integer, db.ForeignKey('rewards.reward_id'), nullable=False)
    points_used = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='completed')
    redeemed_at = db.Column(db.DateTime, default=datetime.utcnow)

from repositories.db import db
from datetime import datetime
from sqlalchemy import UniqueConstraint


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
    account_status = db.Column(db.String(50), default='active')
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
    is_flagged = db.Column(db.Boolean, default=False)
    risk_score = db.Column(db.Float, default=0.0)
    flag_reason = db.Column(db.String(255), default='')
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


class ChallengeReminder(db.Model):
    __tablename__ = 'challenge_reminders'
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.challenge_id'), primary_key=True)
    start_reminder_sent = db.Column(db.Boolean, default=False, nullable=False)
    end_reminder_sent = db.Column(db.Boolean, default=False, nullable=False)


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


class QREvent(db.Model):
    __tablename__ = 'qr_events'
    event_id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(120), nullable=False)
    event_name = db.Column(db.String(150), nullable=False)
    qr_token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    reward_points = db.Column(db.Float, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QRClaim(db.Model):
    __tablename__ = 'qr_claims'
    __table_args__ = (UniqueConstraint('event_id', 'user_id', name='uq_qr_claim_event_user'),)
    claim_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('qr_events.event_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    claimed_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = 'notifications'
    notification_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False, default='info')
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    log_id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

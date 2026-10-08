from flask import Blueprint, request, jsonify, current_app
from repositories.db import db
from repositories.models import User, Role, UserProfile, Wallet
from flask_bcrypt import Bcrypt
from functools import wraps
from threading import Lock
import time
import jwt
import datetime

auth_bp = Blueprint('auth', __name__)
bcrypt = Bcrypt()
_admin_login_attempts = {}
_admin_login_lock = Lock()
_admin_login_limit = 5
_admin_login_window = 300
_admin_login_lockout = 300


def _is_admin_login_locked(client_ip):
    now = time.monotonic()
    with _admin_login_lock:
        attempt = _admin_login_attempts.get(client_ip)
        return bool(attempt and attempt['locked_until'] > now)


def _record_admin_login_failure(client_ip):
    now = time.monotonic()
    with _admin_login_lock:
        attempt = _admin_login_attempts.get(client_ip)
        if not attempt or now - attempt['window_started'] >= _admin_login_window:
            attempt = {'count': 0, 'window_started': now, 'locked_until': 0}
        attempt['count'] += 1
        if attempt['count'] >= _admin_login_limit:
            attempt['locked_until'] = now + _admin_login_lockout
        _admin_login_attempts[client_ip] = attempt


def _clear_admin_login_failures(client_ip):
    with _admin_login_lock:
        _admin_login_attempts.pop(client_ip, None)


def _create_token(user, lifetime_hours):
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode({
        'user_id': user.user_id,
        'role': user.role.role_name,
        'iat': now,
        'exp': now + datetime.timedelta(hours=lifetime_hours),
    }, current_app.config['SECRET_KEY'], algorithm='HS256')

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
            
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = User.query.filter_by(user_id=data['user_id']).first()
        except Exception as e:
            return jsonify({'message': 'Token is invalid!'}), 401

        if (current_user is None or current_user.account_status != 'active'
                or data.get('role') != current_user.role.role_name):
            return jsonify({'message': 'Token is invalid!'}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or not data.get('email') or not data.get('password') or not data.get('name'):
        return jsonify({"error": "Missing required fields"}), 400
        
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"error": "User with that email already exists"}), 409
        
    # Get or create default 'User' role
    role = Role.query.filter_by(role_name='User').first()
    if not role:
        role = Role(role_name='User')
        db.session.add(role)
        db.session.commit()
        
    hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    
    new_user = User(
        name=data['name'],
        email=data['email'],
        password_hash=hashed_password,
        role_id=role.role_id
    )
    
    db.session.add(new_user)
    db.session.commit()
    
    # Create empty user profile
    profile = UserProfile(user_id=new_user.user_id)
    db.session.add(profile)
    
    # Create empty wallet
    wallet = Wallet(user_id=new_user.user_id, current_balance=0.0)
    db.session.add(wallet)
    
    db.session.commit()
    
    return jsonify({"message": "User registered successfully", "user_id": new_user.user_id}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Missing email or password"}), 400
        
    user = User.query.filter_by(email=data['email']).first()
    
    if user and user.account_status == 'terminated':
        return jsonify({"error": "Account terminated by administrator"}), 403

    if user and bcrypt.check_password_hash(user.password_hash, data['password']):
        if user.role.role_name == 'Admin':
            return jsonify({"error": "Unable to sign in with these credentials."}), 401
        token = _create_token(user, 24)
        
        return jsonify({"message": "Login successful", "token": token}), 200
        
    return jsonify({"error": "Invalid credentials"}), 401


@auth_bp.route('/admin-login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    if not isinstance(email, str) or not isinstance(password, str) or not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    client_ip = request.remote_addr or 'unknown'
    if _is_admin_login_locked(client_ip):
        response = jsonify({"error": "Unable to sign in. Try again later."})
        response.headers['Retry-After'] = str(_admin_login_lockout)
        return response, 429

    user = User.query.filter_by(email=email.strip().lower()).first()
    password_matches = user is not None and bcrypt.check_password_hash(user.password_hash, password)
    if (not password_matches or user.account_status != 'active'
            or user.role.role_name != 'Admin'):
        _record_admin_login_failure(client_ip)
        return jsonify({"error": "Unable to sign in with these credentials."}), 401

    _clear_admin_login_failures(client_ip)
    return jsonify({
        "message": "Admin sign-in successful",
        "token": _create_token(user, 1),
    }), 200

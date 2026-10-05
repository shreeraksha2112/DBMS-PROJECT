from flask import Blueprint, request, jsonify, current_app
from repositories.db import db
from repositories.models import User, Role, UserProfile, Wallet
from flask_bcrypt import Bcrypt
import jwt
import datetime

auth_bp = Blueprint('auth', __name__)
bcrypt = Bcrypt()

from functools import wraps

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
    
    if user and bcrypt.check_password_hash(user.password_hash, data['password']):
        token = jwt.encode({
            'user_id': user.user_id,
            'role': user.role.role_name,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, current_app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({"message": "Login successful", "token": token}), 200
        
    return jsonify({"error": "Invalid credentials"}), 401

import jwt
import datetime
from functools import wraps
from flask import request, jsonify
from models import db, User
import os

SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-key')

def register_user(username, password):
    """Register a new user"""
    # Check if user already exists
    if User.query.filter_by(username=username).first():
        raise ValueError('Username already exists')
    
    # Create new user
    user = User(username=username)
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    return user

def login_user(username, password):
    """Authenticate user and return JWT token"""
    user = User.query.filter_by(username=username).first()
    
    if not user or not user.check_password(password):
        raise ValueError('Invalid username or password')
    
    # Generate JWT token
    payload = {
        'user_id': user.id,
        'username': user.username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    return token

def token_required(f):
    """Decorator to require valid JWT token for route"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Decode token
            payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            current_user = User.query.get(payload['user_id'])
            
            if not current_user:
                return jsonify({'error': 'Invalid token'}), 401
                
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated
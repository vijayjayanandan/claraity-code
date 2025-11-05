from flask import Flask, jsonify, request
from flask_cors import CORS
from models import db, User, Task
from auth import register_user, login_user, token_required
import os

def create_app():
    app = Flask(__name__)
    CORS(app)
    
    # Database configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///tasks.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
    
    db.init_app(app)
    
    # Create tables
    with app.app_context():
        db.create_all()
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404
    
    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': 'Unauthorized'}), 401
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({'error': 'Bad request'}), 400
    
    # Routes
    @app.route('/auth/register', methods=['POST'])
    def register():
        data = request.get_json()
        
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'error': 'Username and password required'}), 400
        
        try:
            user = register_user(data['username'], data['password'])
            return jsonify({
                'user_id': user.id,
                'username': user.username
            }), 201
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
    
    @app.route('/auth/login', methods=['POST'])
    def login():
        data = request.get_json()
        
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'error': 'Username and password required'}), 400
        
        try:
            token = login_user(data['username'], data['password'])
            return jsonify({
                'access_token': token,
                'token_type': 'bearer'
            }), 200
        except ValueError as e:
            return jsonify({'error': str(e)}), 401
    
    @app.route('/tasks', methods=['GET'])
    @token_required
    def get_tasks(current_user):
        tasks = Task.query.filter_by(user_id=current_user.id).all()
        return jsonify([{
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'completed': task.completed,
            'created_at': task.created_at.isoformat()
        } for task in tasks]), 200
    
    @app.route('/tasks', methods=['POST'])
    @token_required
    def create_task(current_user):
        data = request.get_json()
        
        if not data or not data.get('title'):
            return jsonify({'error': 'Title is required'}), 400
        
        task = Task(
            title=data['title'],
            description=data.get('description', ''),
            user_id=current_user.id
        )
        
        db.session.add(task)
        db.session.commit()
        
        return jsonify({
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'completed': task.completed,
            'created_at': task.created_at.isoformat()
        }), 201
    
    @app.route('/tasks/<int:task_id>', methods=['PUT'])
    @token_required
    def update_task(current_user, task_id):
        task = Task.query.filter_by(id=task_id, user_id=current_user.id).first()
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        task.title = data.get('title', task.title)
        task.description = data.get('description', task.description)
        task.completed = data.get('completed', task.completed)
        
        db.session.commit()
        
        return jsonify({
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'completed': task.completed,
            'created_at': task.created_at.isoformat()
        }), 200
    
    @app.route('/tasks/<int:task_id>', methods=['DELETE'])
    @token_required
    def delete_task(current_user, task_id):
        task = Task.query.filter_by(id=task_id, user_id=current_user.id).first()
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        db.session.delete(task)
        db.session.commit()
        
        return '', 204
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
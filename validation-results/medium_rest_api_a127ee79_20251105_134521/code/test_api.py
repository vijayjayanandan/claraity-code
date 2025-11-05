import unittest
import json
from app import create_app
from models import db, User, Task

class TaskAPITestCase(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        
        with self.app.app_context():
            db.create_all()
            
            # Create test users
            user1 = User(username='alice')
            user1.set_password('password123')
            
            user2 = User(username='bob')
            user2.set_password('password456')
            
            db.session.add(user1)
            db.session.add(user2)
            db.session.commit()
            
            # Create test tasks
            task1 = Task(title='Buy groceries', description='Milk, eggs, bread', user_id=user1.id)
            task2 = Task(title='Walk the dog', user_id=user1.id)
            task3 = Task(title='Finish project', completed=True, user_id=user2.id)
            
            db.session.add(task1)
            db.session.add(task2)
            db.session.add(task3)
            db.session.commit()
    
    def tearDown(self):
        """Tear down test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_register_user_success(self):
        """Test successful user registration"""
        response = self.client.post('/auth/register',
                                  data=json.dumps({
                                      'username': 'charlie',
                                      'password': 'password789'
                                  }),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data)
        self.assertIn('user_id', data)
        self.assertEqual(data['username'], 'charlie')
    
    def test_register_user_duplicate_username(self):
        """Test registration with duplicate username"""
        response = self.client.post('/auth/register',
                                  data=json.dumps({
                                      'username': 'alice',
                                      'password': 'password789'
                                  }),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Username already exists')
    
    def test_register_user_missing_fields(self):
        """Test registration with missing fields"""
        response = self.client.post('/auth/register',
                                  data=json.dumps({
                                      'username': 'charlie'
                                  }),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Username and password required')
    
    def test_login_success(self):
        """Test successful login"""
        response = self.client.post('/auth/login',
                                  data=json.dumps({
                                      'username': 'alice',
                                      'password': 'password123'
                                  }),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('access_token', data)
        self.assertEqual(data['token_type'], 'bearer')
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = self.client.post('/auth/login',
                                  data=json.dumps({
                                      'username': 'alice',
                                      'password': 'wrongpassword'
                                  }),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Invalid username or password')
    
    def test_login_missing_fields(self):
        """Test login with missing fields"""
        response = self.client.post('/auth/login',
                                  data=json.dumps({
                                      'username': 'alice'
                                  }),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Username and password required')
    
    def test_get_tasks_unauthorized(self):
        """Test getting tasks without token"""
        response = self.client.get('/tasks')
        self.assertEqual(response.status_code, 401)
    
    def test_get_tasks_success(self):
        """Test getting tasks with valid token"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Get tasks
        response = self.client.get('/tasks',
                                 headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data), 2)  # Alice has 2 tasks
        self.assertEqual(data[0]['title'], 'Buy groceries')
        self.assertEqual(data[1]['title'], 'Walk the dog')
    
    def test_create_task_success(self):
        """Test creating task with valid token"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Create task
        response = self.client.post('/tasks',
                                  data=json.dumps({
                                      'title': 'New task',
                                      'description': 'Task description'
                                  }),
                                  content_type='application/json',
                                  headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data)
        self.assertEqual(data['title'], 'New task')
        self.assertEqual(data['description'], 'Task description')
        self.assertFalse(data['completed'])
    
    def test_create_task_missing_title(self):
        """Test creating task without title"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Create task
        response = self.client.post('/tasks',
                                  data=json.dumps({
                                      'description': 'Task description'
                                  }),
                                  content_type='application/json',
                                  headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Title is required')
    
    def test_update_task_success(self):
        """Test updating own task"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Get alice's task
        with self.app.app_context():
            task = Task.query.filter_by(user_id=1).first()
            task_id = task.id
        
        # Update task
        response = self.client.put(f'/tasks/{task_id}',
                                 data=json.dumps({
                                     'title': 'Updated task',
                                     'completed': True
                                 }),
                                 content_type='application/json',
                                 headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['title'], 'Updated task')
        self.assertTrue(data['completed'])
    
    def test_update_task_not_owner(self):
        """Test updating someone else's task"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Try to update bob's task
        with self.app.app_context():
            task = Task.query.filter_by(user_id=2).first()
            task_id = task.id
        
        response = self.client.put(f'/tasks/{task_id}',
                                 data=json.dumps({
                                     'title': 'Hacked task'
                                 }),
                                 content_type='application/json',
                                 headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Task not found')
    
    def test_delete_task_success(self):
        """Test deleting own task"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Get alice's task
        with self.app.app_context():
            task = Task.query.filter_by(user_id=1).first()
            task_id = task.id
        
        # Delete task
        response = self.client.delete(f'/tasks/{task_id}',
                                    headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 204)
    
    def test_delete_task_not_owner(self):
        """Test deleting someone else's task"""
        # First login to get token
        login_response = self.client.post('/auth/login',
                                        data=json.dumps({
                                            'username': 'alice',
                                            'password': 'password123'
                                        }),
                                        content_type='application/json')
        
        token = json.loads(login_response.data)['access_token']
        
        # Try to delete bob's task
        with self.app.app_context():
            task = Task.query.filter_by(user_id=2).first()
            task_id = task.id
        
        response = self.client.delete(f'/tasks/{task_id}',
                                    headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertEqual(data['error'], 'Task not found')

if __name__ == '__main__':
    unittest.main()
import unittest
import json
from app import create_app
from models import db, User, Task

class TaskAPITestCase(unittest.TestCase):
    def setUp(self):
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
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_register_user(self):
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
    
    def test_register_user_existing_username(self):
        response = self.client.post('/auth/register',
                                   data=json.dumps({
                                       'username': 'alice',
                                       'password': 'newpassword'
                                   }),
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_register_user_missing_fields(self):
        response = self.client.post('/auth/register',
                                   data=json.dumps({
                                       'username': 'david'
                                   }),
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_login_user(self):
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
    
    def test_login_user_invalid_credentials(self):
        response = self.client.post('/auth/login',
                                   data=json.dumps({
                                       'username': 'alice',
                                       'password': 'wrongpassword'
                                   }),
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_login_user_missing_fields(self):
        response = self.client.post('/auth/login',
                                   data=json.dumps({
                                       'username': 'alice'
                                   }),
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_get_tasks_unauthorized(self):
        response = self.client.get('/tasks')
        self.assertEqual(response.status_code, 401)
    
    def test_get_tasks(self):
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Get tasks
        response = self.client.get('/tasks',
                                  headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data), 2)  # alice has 2 tasks
        self.assertEqual(data[0]['title'], 'Buy groceries')
        self.assertEqual(data[1]['title'], 'Walk the dog')
    
    def test_create_task(self):
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
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
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Create task without title
        response = self.client.post('/tasks',
                                  data=json.dumps({
                                      'description': 'Task without title'
                                  }),
                                  content_type='application/json',
                                  headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_update_task(self):
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Update task
        response = self.client.put('/tasks/1',
                                 data=json.dumps({
                                     'title': 'Buy groceries and vegetables',
                                     'completed': True
                                 }),
                                 content_type='application/json',
                                 headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['title'], 'Buy groceries and vegetables')
        self.assertTrue(data['completed'])
    
    def test_update_nonexistent_task(self):
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Update nonexistent task
        response = self.client.put('/tasks/999',
                                 data=json.dumps({
                                     'title': 'Nonexistent task'
                                 }),
                                 content_type='application/json',
                                 headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_update_other_user_task(self):
        # Login as bob
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'bob',
                                             'password': 'password456'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Try to update alice's task
        response = self.client.put('/tasks/1',  # This is alice's task
                                 data=json.dumps({
                                     'title': 'Hacked task'
                                 }),
                                 content_type='application/json',
                                 headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_delete_task(self):
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Delete task
        response = self.client.delete('/tasks/1',
                                    headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 204)
    
    def test_delete_nonexistent_task(self):
        # Login first
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'alice',
                                             'password': 'password123'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Delete nonexistent task
        response = self.client.delete('/tasks/999',
                                    headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_delete_other_user_task(self):
        # Login as bob
        login_response = self.client.post('/auth/login',
                                         data=json.dumps({
                                             'username': 'bob',
                                             'password': 'password456'
                                         }),
                                         content_type='application/json')
        
        login_data = json.loads(login_response.data)
        token = login_data['access_token']
        
        # Try to delete alice's task
        response = self.client.delete('/tasks/1',  # This is alice's task
                                    headers={'Authorization': f'Bearer {token}'})
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertIn('error', data)

if __name__ == '__main__':
    unittest.main()
# Task Management API

A RESTful API for task management with user authentication and authorization.

## Features

- User registration and authentication with JWT tokens
- Create, read, update, and delete tasks
- Users can only access their own tasks
- Input validation and proper error handling
- CORS support

## Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd task-management-api
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set environment variables (optional):
   ```bash
   export SECRET_KEY="your-secret-key"
   export DATABASE_URL="sqlite:///tasks.db"
   ```

5. Run the application:
   ```bash
   python app.py
   ```

The API will be available at `http://localhost:5000`.

## API Endpoints

### Authentication

#### Register a new user
```http
POST /auth/register
```

**Request Body:**
```json
{
  "username": "alice",
  "password": "secret123"
}
```

**Response:**
```json
{
  "user_id": 1,
  "username": "alice"
}
```

#### Login
```http
POST /auth/login
```

**Request Body:**
```json
{
  "username": "alice",
  "password": "secret123"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

### Tasks

All task endpoints require a valid JWT token in the Authorization header:
```
Authorization: Bearer <token>
```

#### Get all tasks
```http
GET /tasks
```

**Response:**
```json
[
  {
    "id": 1,
    "title": "Buy groceries",
    "description": "Milk, eggs, bread",
    "completed": false,
    "created_at": "2023-01-01T12:00:00"
  }
]
```

#### Create a new task
```http
POST /tasks
```

**Request Body:**
```json
{
  "title": "Buy groceries",
  "description": "Milk, eggs, bread"
}
```

**Response:**
```json
{
  "id": 1,
  "title": "Buy groceries",
  "description": "Milk, eggs, bread",
  "completed": false,
  "created_at": "2023-01-01T12:00:00"
}
```

#### Update a task
```http
PUT /tasks/{id}
```

**Request Body:**
```json
{
  "title": "Buy groceries and vegetables",
  "completed": true
}
```

**Response:**
```json
{
  "id": 1,
  "title": "Buy groceries and vegetables",
  "description": "Milk, eggs, bread",
  "completed": true,
  "created_at": "2023-01-01T12:00:00"
}
```

#### Delete a task
```http
DELETE /tasks/{id}
```

**Response:**
```
204 No Content
```

## Example Usage with curl

1. Register a user:
   ```bash
   curl -X POST http://localhost:5000/auth/register \
        -H "Content-Type: application/json" \
        -d '{"username": "alice", "password": "secret123"}'
   ```

2. Login:
   ```bash
   curl -X POST http://localhost:5000/auth/login \
        -H "Content-Type: application/json" \
        -d '{"username": "alice", "password": "secret123"}'
   ```

3. Create a task (replace `<token>` with actual token):
   ```bash
   curl -X POST http://localhost:5000/tasks \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer <token>" \
        -d '{"title": "Buy groceries", "description": "Milk, eggs, bread"}'
   ```

4. Get tasks:
   ```bash
   curl -X GET http://localhost:5000/tasks \
        -H "Authorization: Bearer <token>"
   ```

## Environment Variables

- `SECRET_KEY`: Secret key for JWT token signing (default: dev-secret-key-change-in-production)
- `DATABASE_URL`: Database connection string (default: sqlite:///tasks.db)

## Testing

Run the test suite:
```bash
python -m unittest test_api.py
```

## Technologies Used

- Flask: Web framework
- SQLAlchemy: ORM for database operations
- PyJWT: JWT token generation and verification
- bcrypt: Password hashing
- Flask-CORS: Cross-Origin Resource Sharing support

## License

MIT
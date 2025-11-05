# Task Management API

A RESTful API for managing tasks with user authentication and authorization.

## Features

- User registration and authentication with JWT tokens
- CRUD operations for tasks
- Secure password hashing with bcrypt
- Input validation
- Proper HTTP status codes
- CORS support
- Comprehensive test suite

## Setup Instructions

### Prerequisites

- Python 3.7+
- pip (Python package installer)

### Installation

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
export DATABASE_URL="sqlite:///tasks.db"  # Optional, defaults to SQLite
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

**Request body:**
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

**Request body:**
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
    "created_at": "2023-01-01T10:00:00"
  }
]
```

#### Create a new task
```http
POST /tasks
```

**Request body:**
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
  "created_at": "2023-01-01T10:00:00"
}
```

#### Update a task
```http
PUT /tasks/{id}
```

**Request body:**
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
  "created_at": "2023-01-01T10:00:00"
}
```

#### Delete a task
```http
DELETE /tasks/{id}
```

**Response:** 204 No Content

## Example curl commands

### Register a user
```bash
curl -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
```

### Login
```bash
curl -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
```

### Get tasks (replace `<token>` with actual token)
```bash
curl -X GET http://localhost:5000/tasks \
  -H "Authorization: Bearer <token>"
```

### Create a task (replace `<token>` with actual token)
```bash
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"title": "Buy groceries", "description": "Milk, eggs, bread"}'
```

## Running Tests

To run the test suite:
```bash
python -m pytest test_api.py -v
```

Or with unittest:
```bash
python test_api.py
```

## Environment Variables

- `SECRET_KEY`: Secret key for JWT token signing (default: "your-secret-key-here")
- `DATABASE_URL`: Database connection string (default: "sqlite:///tasks.db")

## Dependencies

See `requirements.txt` for a full list of dependencies.

## License

MIT
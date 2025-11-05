
import sys
import os
import json
import traceback
from datetime import datetime

# Set UTF-8 encoding for stdout on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def safe_print(text: str) -> None:
    """Print text, replacing emojis on Windows to avoid encoding issues."""
    if sys.platform == 'win32':
        import re
        # Remove all emoji characters (simplified approach)
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+", flags=re.UNICODE)
        text = emoji_pattern.sub('', text)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', 'replace').decode('ascii'))

# Add project root to path
sys.path.insert(0, r"C:\Vijay\Learning\AI\ai-coding-agent")

try:
    from src.core.agent import CodingAgent

    # Initialize agent in AUTO mode for validation (no approval prompts)
    # Use OpenAI-compatible backend with DashScope API (from .env config)
    safe_print("[AGENT] Initializing CodingAgent...")
    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    agent = CodingAgent(
        model_name="qwen3-coder-plus",  # From .env: LLM_MODEL
        backend="openai",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",  # From .env: LLM_HOST
        api_key=api_key,
        permission_mode="auto",
        enable_clarity=False  # Disable ClarAIty in validation mode
    )

    # Task prompt
    prompt = """
Create a RESTful API for task management with authentication.

**Database Models:**

1. User model:
   - id (primary key)
   - username (unique)
   - password_hash (never store plain passwords!)
   - created_at

2. Task model:
   - id (primary key)
   - title (required)
   - description (optional)
   - completed (boolean, default False)
   - created_at
   - user_id (foreign key to User)

**API Endpoints:**

1. POST /auth/register
   - Body: {"username": "alice", "password": "secret123"}
   - Returns: {"user_id": 1, "username": "alice"}
   - Hash password with bcrypt

2. POST /auth/login
   - Body: {"username": "alice", "password": "secret123"}
   - Returns: {"access_token": "eyJ...", "token_type": "bearer"}
   - Generate JWT token

3. GET /tasks
   - Headers: Authorization: Bearer <token>
   - Returns: List of user's tasks
   - Requires valid JWT token

4. POST /tasks
   - Headers: Authorization: Bearer <token>
   - Body: {"title": "Buy groceries", "description": "Milk, eggs, bread"}
   - Returns: Created task
   - Requires valid JWT token

5. PUT /tasks/{id}
   - Headers: Authorization: Bearer <token>
   - Body: {"title": "...", "completed": true}
   - Returns: Updated task
   - Only owner can update

6. DELETE /tasks/{id}
   - Headers: Authorization: Bearer <token>
   - Returns: 204 No Content
   - Only owner can delete

**Technical Requirements:**
- Use Flask or FastAPI framework
- Use SQLAlchemy ORM for database
- Hash passwords with bcrypt
- Use PyJWT for JWT tokens
- Validate all inputs
- Return proper HTTP status codes
- Include CORS support

**Testing Requirements:**
- Minimum 15 unit/integration tests
- Test authentication flow
- Test authorization (users can only access their tasks)
- Test input validation
- Test error cases (401, 403, 404)

**Documentation:**
- README.md with:
  - Setup instructions
  - API endpoint documentation
  - Example curl commands
  - Environment variables
- requirements.txt with all dependencies

**Bonus (Optional):**
- Docker setup
- Environment variable configuration
- OpenAPI/Swagger documentation

**Deliverables:**
- app.py (main application)
- models.py (database models)
- auth.py (authentication logic)
- test_api.py (comprehensive tests)
- README.md (documentation)
- requirements.txt (dependencies)

Work in the current directory and create all files here.

IMPORTANT:
- Work in the current directory
- Create all files here
- Include comprehensive tests
- Add a README with setup and usage instructions
"""

    safe_print(f"[INFO] Task prompt:\n{prompt}\n")
    safe_print("[START] Starting execution...\n")

    # Execute task
    start_time = datetime.now()

    # Note: We're calling the agent synchronously
    # The agent will use its workflow system for complex tasks
    response = agent.execute_task(prompt)

    duration = (datetime.now() - start_time).total_seconds()

    safe_print(f"\n[OK] Agent completed in {duration:.1f}s")

    # Prepare result
    result = {
        "success": True,
        "response": str(response) if response else "",
        "duration_seconds": duration,
        "tokens_used": 0,  # TODO: Extract from agent
        "cost_usd": 0.0,   # TODO: Calculate
        "tool_calls": {},  # TODO: Extract from agent
        "errors": [],
        "warnings": [],
        "human_interventions": 0
    }

    # Save result
    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)

except Exception as e:
    safe_print(f"\n[FAIL] Agent failed with error: {e}")
    traceback.print_exc()

    result = {
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
        "errors": [str(e)],
        "warnings": [],
        "human_interventions": 0
    }

    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)

    sys.exit(1)

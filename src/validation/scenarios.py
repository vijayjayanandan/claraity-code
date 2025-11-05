"""
Pre-defined Validation Scenarios

Three carefully designed test cases to validate agent capabilities:
- EASY: CLI Weather Tool (1-2 hours)
- MEDIUM: REST API with Auth (3-4 hours)
- HARD: Web Scraper with Analytics (5-8 hours)
"""

from .scenario import (
    ValidationScenario,
    DifficultyLevel,
    ValidationStep,
    StepType,
    SuccessCriteria
)


# ============================================================================
# EASY: CLI Weather Tool
# ============================================================================

EASY_CLI_WEATHER = ValidationScenario(
    id="easy_cli_weather",
    name="CLI Weather Tool with Caching",
    difficulty=DifficultyLevel.EASY,
    estimated_hours=2.0,
    tags=["cli", "api", "caching", "sqlite"],

    prompt="""Build a command-line weather tool with the following features:

**Core Requirements:**
1. Fetch weather data from wttr.in API (no API key needed)
   - Example: curl "wttr.in/London?format=j1"
2. Cache results for 1 hour in a local SQLite database
3. Accept city name as command-line argument
4. Display: temperature, weather condition, humidity
5. Include --clear-cache flag to reset cache
6. Include --help flag with usage examples

**Technical Requirements:**
- Use `requests` library for HTTP calls
- Use `sqlite3` for caching (built-in Python module)
- Use `argparse` for command-line interface
- Handle network errors gracefully (timeout, connection errors)
- Handle invalid city names (404 errors)

**Testing Requirements:**
- Write unit tests with pytest
- Minimum 5 tests covering:
  - Successful API call
  - Cache hit (no API call)
  - Cache expiration
  - Error handling
  - CLI argument parsing

**Documentation:**
- Create README.md with:
  - Installation instructions
  - Usage examples
  - How caching works
  - Dependencies

**Example Usage:**
```bash
python weather.py "San Francisco"
# Output:
# Weather in San Francisco:
# Temperature: 18°C
# Condition: Partly cloudy
# Humidity: 65%

python weather.py "London" --clear-cache
# Clears cache and fetches fresh data
```

**Deliverables:**
- weather.py (main script)
- test_weather.py (unit tests)
- README.md (documentation)
- requirements.txt (dependencies)

Work in the current directory and create all files here.""",

    context_files=[],

    success_criteria=SuccessCriteria(
        required_files=["weather.py", "test_weather.py", "README.md", "requirements.txt"],
        tests_must_pass=True,
        min_test_count=5,
        must_have_readme=True
    ),

    validation_steps=[
        ValidationStep(
            type=StepType.BASH,
            description="Check help text works",
            command="python weather.py --help",
            expected_exit_code=0,
            timeout_seconds=10
        ),
        ValidationStep(
            type=StepType.PYTEST,
            description="Run unit tests",
        ),
        ValidationStep(
            type=StepType.INSPECT,
            description="Verify error handling exists",
            file_path="weather.py",
            check_criteria="has_error_handling"
        ),
    ],

    scoring_weights={
        "completeness": 0.30,
        "correctness": 0.35,
        "quality": 0.20,
        "autonomy": 0.15
    }
)


# ============================================================================
# MEDIUM: REST API with Authentication
# ============================================================================

MEDIUM_REST_API = ValidationScenario(
    id="medium_rest_api",
    name="Task Management REST API",
    difficulty=DifficultyLevel.MEDIUM,
    estimated_hours=4.0,
    tags=["api", "rest", "authentication", "database", "jwt"],

    prompt="""Create a RESTful API for task management with authentication.

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

Work in the current directory and create all files here.""",

    context_files=[],

    success_criteria=SuccessCriteria(
        required_files=["app.py", "models.py", "test_api.py", "README.md", "requirements.txt"],
        tests_must_pass=True,
        min_test_count=15,
        must_have_readme=True
    ),

    validation_steps=[
        ValidationStep(
            type=StepType.PYTEST,
            description="Run comprehensive API tests",
        ),
        ValidationStep(
            type=StepType.INSPECT,
            description="Verify password hashing",
            file_path="auth.py",
            check_criteria="has_error_handling"
        ),
    ],

    scoring_weights={
        "completeness": 0.35,
        "correctness": 0.35,
        "quality": 0.20,
        "autonomy": 0.10
    }
)


# ============================================================================
# HARD: Web Scraper with Analytics
# ============================================================================

HARD_WEB_SCRAPER = ValidationScenario(
    id="hard_web_scraper",
    name="Hacker News Scraper with Analytics",
    difficulty=DifficultyLevel.HARD,
    estimated_hours=6.0,
    tags=["scraping", "database", "analytics", "scheduling", "reporting"],

    prompt="""Build a web scraping system that extracts Hacker News articles and generates analytics.

**Core Features:**

1. **Web Scraper** (scraper.py):
   - Scrape Hacker News front page (https://news.ycombinator.com/)
   - Extract for each article:
     * Title
     * URL
     * Points (score)
     * Author
     * Comment count
     * Timestamp
   - Respect robots.txt
   - Rate limiting: 1 request per 2 seconds
   - Handle network errors gracefully
   - Use BeautifulSoup4 for parsing

2. **Database** (database.py):
   - SQLite database with tables:
     * articles (id, title, url, points, author, comments, scraped_at)
     * authors (username, total_articles, total_points)
   - Use SQLAlchemy ORM
   - Automatic timestamp tracking
   - Prevent duplicate articles (by URL)

3. **Analytics Engine** (analytics.py):
   - Top 10 articles by points
   - Most active authors (by article count)
   - Trending topics (keyword extraction from titles)
   - Average points per article
   - Articles per hour statistics
   - Generate time-series data

4. **Report Generator** (report_generator.py):
   - Generate markdown reports with analytics
   - Generate HTML reports with charts (optional)
   - Export data to CSV/JSON
   - Include summary statistics

5. **CLI Interface** (cli.py):
   - Commands:
     * `python cli.py scrape` - Run scraper once
     * `python cli.py analyze` - Generate analytics
     * `python cli.py report --format md` - Generate report
     * `python cli.py export --format csv` - Export data
   - Use argparse or click for CLI
   - Progress indicators
   - Logging to file

**Technical Requirements:**
- Beautiful error handling (try/except with specific exceptions)
- Comprehensive logging (to file: scraper.log)
- Configuration via config.json or YAML
- Type hints throughout code
- Docstrings for all functions/classes

**Testing Requirements:**
- Minimum 20 unit tests across all modules
- Integration tests for end-to-end flow
- Mock HTTP requests in tests (don't hit real website)
- Test error handling paths
- Test database operations

**Documentation:**
- README.md with:
  - Architecture overview
  - Installation instructions
  - Usage examples for all CLI commands
  - Configuration options
  - Database schema diagram (ASCII art OK)
  - Known limitations
- requirements.txt with all dependencies
- ARCHITECTURE.md (optional) explaining design decisions

**Bonus Features (Optional):**
- Schedule hourly scrapes with APScheduler
- Email report delivery
- Sentiment analysis of titles
- Detect trending topics over time
- Web dashboard with Flask

**Deliverables:**
- scraper.py (web scraping logic)
- database.py (SQLAlchemy models and queries)
- analytics.py (data analysis functions)
- report_generator.py (report generation)
- cli.py (command-line interface)
- test_scraper.py (scraper tests)
- test_analytics.py (analytics tests)
- test_database.py (database tests)
- README.md (comprehensive documentation)
- requirements.txt (all dependencies)
- config.json or config.yaml (configuration)

Work in the current directory and create all files here.""",

    context_files=[],

    success_criteria=SuccessCriteria(
        required_files=[
            "scraper.py",
            "database.py",
            "analytics.py",
            "report_generator.py",
            "cli.py",
            "test_scraper.py",
            "test_analytics.py",
            "README.md",
            "requirements.txt"
        ],
        tests_must_pass=True,
        min_test_count=20,
        must_have_readme=True
    ),

    validation_steps=[
        ValidationStep(
            type=StepType.BASH,
            description="Check CLI help works",
            command="python cli.py --help",
            expected_exit_code=0,
            timeout_seconds=10
        ),
        ValidationStep(
            type=StepType.PYTEST,
            description="Run comprehensive test suite",
        ),
        ValidationStep(
            type=StepType.INSPECT,
            description="Verify logging exists",
            file_path="scraper.py",
            check_criteria="has_error_handling"
        ),
    ],

    scoring_weights={
        "completeness": 0.40,
        "correctness": 0.30,
        "quality": 0.20,
        "autonomy": 0.10
    }
)


# ============================================================================
# Scenario Registry
# ============================================================================

VALIDATION_SCENARIOS = [
    EASY_CLI_WEATHER,
    MEDIUM_REST_API,
    HARD_WEB_SCRAPER,
]


def get_scenario_by_id(scenario_id: str) -> ValidationScenario:
    """Get scenario by ID"""
    for scenario in VALIDATION_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise ValueError(f"Scenario not found: {scenario_id}")


def get_scenarios_by_difficulty(difficulty: DifficultyLevel) -> list:
    """Get all scenarios of a given difficulty"""
    return [s for s in VALIDATION_SCENARIOS if s.difficulty == difficulty]

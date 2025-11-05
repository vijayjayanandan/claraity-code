
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
sys.path.insert(0, r"/home/user/ai-coding-agent")

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
Build a web scraping system that extracts Hacker News articles and generates analytics.

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

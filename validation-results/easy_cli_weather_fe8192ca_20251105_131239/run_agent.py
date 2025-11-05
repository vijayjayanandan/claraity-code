
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
Build a command-line weather tool with the following features:

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

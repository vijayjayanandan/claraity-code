"""
=============================================================================
  Prompt Caching Demo - See the cost savings in real time
=============================================================================

This standalone script demonstrates prompt caching with Claude models via
any OpenAI-compatible API endpoint. It runs the SAME 5-turn conversation
twice - once WITHOUT caching, once WITH - then prints a comparison.

Requirements:
    pip install openai

Usage:
    python prompt_caching_demo.py

You'll be prompted for your API key, base URL, and model name.
Or hardcode them below in the CONFIGURATION section.
"""

import getpass
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

# ============================= CONFIGURATION ================================
# Hardcode these to skip the interactive prompts.
# Leave as None to be prompted at runtime.

API_KEY = None                                      # Your API key (or enter at runtime)
BASE_URL = None                                     # Defaults to FuelIX proxy at runtime
MODEL = None                                        # e.g. "claude-sonnet-4-20250514"

DEFAULT_BASE_URL = "https://proxy.fuelix.ai/v1"    # Default when user presses Enter

MAX_OUTPUT_TOKENS = 300             # Kept small to minimize demo cost
RESPONSE_PREVIEW_CHARS = 180        # How many chars of LLM response to show

# ============================================================================


# ---------------------------------------------------------------------------
# System prompt (~1,500 tokens). Must exceed Anthropic's 1,024-token minimum
# for caching to activate. Real agent prompts are typically 3,000-10,000+.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior software engineer AI assistant working as part of an
AI-powered coding agent. You help users with code review, debugging, architecture design,
writing clean code, performance optimization, and security best practices.

## Core Guidelines

1. Always explain your reasoning before providing code
2. Use type hints in all Python code
3. Follow PEP 8 style guidelines strictly
4. Prefer composition over inheritance
5. Write unit tests for all critical logic paths
6. Handle errors gracefully with specific exception types
7. Use structured logging (not print statements) for production code
8. Keep functions small and focused on a single responsibility
9. Use meaningful variable names that convey intent
10. Document all public APIs with comprehensive docstrings
11. Prefer immutable data structures where possible
12. Use context managers for resource management
13. Validate inputs at system boundaries
14. Prefer explicit over implicit behavior
15. Follow the principle of least surprise in API design

## Code Review Checklist

When reviewing code, systematically check for:

### Correctness
- Logic errors and off-by-one mistakes
- Unhandled edge cases (empty collections, None values, boundary conditions)
- Race conditions in concurrent code
- Incorrect error handling (swallowing exceptions, wrong exception types)

### Security (OWASP Top 10)
- SQL injection via string concatenation
- Cross-site scripting (XSS) in web output
- Command injection in subprocess calls
- Insecure deserialization of untrusted data
- Missing authentication or authorization checks
- Sensitive data exposure in logs or error messages
- Missing CSRF protection on state-changing endpoints

### Performance
- N+1 query patterns in ORM code
- Unnecessary memory allocations in hot paths
- Missing database indexes for frequent queries
- Unbounded collection growth
- Synchronous I/O blocking the event loop
- Missing pagination on list endpoints

### Reliability
- Resource leaks (unclosed files, database connections, HTTP sessions)
- Missing retry logic for transient failures
- Missing circuit breakers for external service calls
- Insufficient timeout configuration
- Missing health check endpoints

### Maintainability
- Functions longer than 30 lines (suggest decomposition)
- Deeply nested conditionals (suggest early returns)
- Magic numbers without named constants
- Duplicate code across modules (suggest extraction)
- Missing or misleading comments

## System Design Guidelines

When designing systems, evaluate and document decisions on:

### Data Layer
- Database selection (PostgreSQL for relational, MongoDB for documents, Redis for cache)
- Schema design with migration strategy
- Read vs write ratio analysis
- Indexing strategy based on query patterns
- Data partitioning and sharding approach

### API Layer
- REST for CRUD resources, GraphQL for flexible queries, gRPC for internal services
- API versioning strategy (URL path vs header)
- Rate limiting and throttling
- Request/response schema validation
- Pagination strategy (cursor-based preferred)

### Infrastructure
- Container orchestration (Kubernetes for production)
- CI/CD pipeline design
- Blue-green or canary deployment strategy
- Auto-scaling policies based on metrics
- Disaster recovery and backup procedures

### Observability
- Structured logging with correlation IDs
- Distributed tracing (OpenTelemetry)
- Custom metrics and SLO dashboards
- Alerting thresholds and escalation procedures
- Error tracking and aggregation

### Security Architecture
- Authentication (OAuth 2.0 / OIDC with PKCE)
- Authorization (RBAC or ABAC based on requirements)
- Secrets management (HashiCorp Vault or cloud-native)
- Network security (mTLS for service-to-service)
- Audit logging for compliance

Always respond concisely and precisely. Avoid unnecessary verbosity. Structure responses
with clear headings when covering multiple topics. Provide code examples that are
production-ready, not just illustrative."""


# ---------------------------------------------------------------------------
# Simulated multi-turn conversation (builds up like a real coding session)
# ---------------------------------------------------------------------------
CONVERSATION_TURNS = [
    "I have a Python Flask API that handles user authentication. "
    "The login endpoint accepts username and password, queries the "
    "database, and returns a JWT token. Can you review this approach?",

    "Good points. Now I want to add rate limiting to prevent brute "
    "force attacks. What's the best approach for Flask? Should I use "
    "an in-memory store or Redis?",

    "Let's go with Redis. Can you write the rate limiting middleware? "
    "I want 5 attempts per minute per IP for the login endpoint, and "
    "100 requests per minute per user for other authenticated endpoints.",

    "Now I need to add refresh token rotation. When a client uses a "
    "refresh token, I want to invalidate the old one and issue a new "
    "pair. How should I store and track refresh tokens?",

    "One more thing - I need to add audit logging for all auth events. "
    "Login success, login failure, token refresh, logout. What's a good "
    "pattern that won't slow down the auth endpoints?",
]


# ---------------------------------------------------------------------------
# Cache breakpoint logic (the two-breakpoint strategy)
# ---------------------------------------------------------------------------

def apply_cache_control(messages: list[dict]) -> list[dict]:
    """Apply the two-breakpoint strategy to a message list.

    BP1: System prompt (first message) - static across all calls.
    BP2: Last message with content before the new user input -
         caches the conversation history prefix.

    This is the core of prompt caching. These ~30 lines save 40-50% on
    input costs for multi-turn conversations with Claude.
    """
    if len(messages) < 2:
        return messages

    result = [{**m} for m in messages]  # shallow copy - never mutate originals

    # BP1: Mark the system prompt
    if result[0].get("role") == "system":
        result[0] = _add_cache_marker(result[0])

    # BP2: Walk backwards from second-to-last, find last message with content.
    # We skip the final message (new user input) since it changes every turn.
    if len(result) >= 3:
        for i in range(len(result) - 2, 0, -1):
            if result[i].get("content") is not None:
                result[i] = _add_cache_marker(result[i])
                break

    return result


def _add_cache_marker(msg: dict) -> dict:
    """Add cache_control: {"type": "ephemeral"} to a message."""
    msg = {**msg}
    content = msg.get("content")

    if content is None:
        return msg

    # Tool role: add as sibling field (required for litellm/proxy compatibility)
    if msg.get("role") == "tool":
        msg["cache_control"] = {"type": "ephemeral"}
        return msg

    # String content: convert to Anthropic content-blocks format
    if isinstance(content, str):
        msg["content"] = [{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"},
        }]
    # List content: mark the last block
    elif isinstance(content, list) and content:
        content = [{**block} for block in content]
        content[-1]["cache_control"] = {"type": "ephemeral"}
        msg["content"] = content

    return msg


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class TurnMetrics:
    turn: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: float = 0.0
    context_messages: int = 0  # how many messages sent to LLM this turn

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    @property
    def cache_pct(self) -> float:
        if self.input_tokens == 0:
            return 0.0
        return self.cache_read_tokens / self.input_tokens * 100


@dataclass
class SessionMetrics:
    turns: list[TurnMetrics] = field(default_factory=list)

    @property
    def total_input(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def total_output(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def total_cache_read(self) -> int:
        return sum(t.cache_read_tokens for t in self.turns)

    @property
    def total_cache_write(self) -> int:
        return sum(t.cache_write_tokens for t in self.turns)

    @property
    def cache_hits(self) -> int:
        return sum(1 for t in self.turns if t.cache_hit)

    @property
    def total_latency_ms(self) -> float:
        return sum(t.latency_ms for t in self.turns)

    def effective_cost_units(self) -> float:
        """Relative cost with caching (1.0 = full price per token)."""
        uncached = self.total_input - self.total_cache_read - self.total_cache_write
        return (
            self.total_cache_read * 0.1       # 90% discount on cache reads
            + self.total_cache_write * 1.25   # 25% surcharge on first write
            + max(0, uncached) * 1.0          # full price for uncached
        )

    def baseline_cost_units(self) -> float:
        return float(self.total_input)


# ---------------------------------------------------------------------------
# Usage extraction
# ---------------------------------------------------------------------------

def extract_usage(usage) -> dict:
    """Extract token counts from an OpenAI SDK usage object."""
    if usage is None:
        return {"input": 0, "output": 0, "cached": 0, "cache_write": 0}

    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0

    # Cache data may come from prompt_tokens_details (OpenAI format)
    # or directly on the usage object (Anthropic-via-proxy format)
    cached = 0
    cache_write = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details:
        cached = getattr(details, "cached_tokens", 0) or 0

    cached = max(cached, getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_write = max(cache_write, getattr(usage, "cache_creation_input_tokens", 0) or 0)

    return {"input": input_tokens, "output": output_tokens,
            "cached": cached, "cache_write": cache_write}


# ---------------------------------------------------------------------------
# Transaction logger (plain text)
# ---------------------------------------------------------------------------

class TransactionLogger:
    """Logs every API call to a readable plain text file.

    Shows the exact messages array sent to the LLM so users can see
    how cache breakpoints are placed and how context grows each turn.
    """

    def __init__(self, model: str, base_url: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = f"prompt_caching_demo_{timestamp}.log"
        self.lines: list[str] = []
        self._write_header(model, base_url)

    def _write_header(self, model: str, base_url: str):
        self.lines.append("=" * 80)
        self.lines.append("  PROMPT CACHING DEMO - TRANSACTION LOG")
        self.lines.append("=" * 80)
        self.lines.append(f"  Timestamp:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.lines.append(f"  Model:        {model}")
        self.lines.append(f"  Base URL:     {base_url}")
        self.lines.append(f"  Max output:   {MAX_OUTPUT_TOKENS} tokens/turn")
        self.lines.append(f"  Turns:        {len(CONVERSATION_TURNS)}")
        self.lines.append("")

    def log_run_start(self, run_mode: str):
        label = "WITH CACHING" if run_mode == "with" else "WITHOUT CACHING"
        self.lines.append("")
        self.lines.append("#" * 80)
        self.lines.append(f"#  RUN: {label}")
        self.lines.append("#" * 80)

    def _format_message_for_log(self, msg: dict, max_text: int = 200) -> dict:
        """Create a log-friendly copy of a message, truncating long text."""
        result = {}
        for key, value in msg.items():
            if key == "content":
                if isinstance(value, str):
                    if len(value) > max_text:
                        result["content"] = value[:max_text] + f"...({len(value)} chars)"
                    else:
                        result["content"] = value
                elif isinstance(value, list):
                    blocks = []
                    for block in value:
                        if isinstance(block, dict):
                            b = dict(block)
                            text = b.get("text", "")
                            if len(text) > max_text:
                                b["text"] = text[:max_text] + f"...({len(text)} chars)"
                            blocks.append(b)
                        else:
                            blocks.append(block)
                    result["content"] = blocks
                else:
                    result["content"] = value
            else:
                result[key] = value
        return result

    def _indent(self, text: str, prefix: str = "        ") -> list[str]:
        """Indent each line of text."""
        return [prefix + line for line in text.split("\n")]

    def log_turn(self, run_mode: str, turn: int, user_msg: str,
                 messages_sent: list[dict], llm_response: str,
                 usage: dict, latency_ms: float, context_messages: int,
                 model: str = ""):
        """Log a single API call showing the exact call with cache_control fields."""
        import json

        self.lines.append("")
        self.lines.append("-" * 80)
        self.lines.append(f"  TURN {turn}/{len(CONVERSATION_TURNS)}  "
                          f"[{context_messages} messages in context]")
        self.lines.append("-" * 80)

        # --- Show the exact API call with cache_control visible ---
        self.lines.append("")
        self.lines.append("  EXACT API CALL:")
        self.lines.append("  " + "~" * 40)

        # Build a readable representation of the messages array
        log_messages = [self._format_message_for_log(m) for m in messages_sent]
        messages_json = json.dumps(log_messages, indent=4)

        self.lines.append("  client.chat.completions.create(")
        self.lines.append(f"      model=\"{model}\",")
        self.lines.append(f"      max_tokens={MAX_OUTPUT_TOKENS},")
        self.lines.append("      messages=")
        self.lines.extend(self._indent(messages_json, "      "))
        self.lines.append("  )")

        self.lines.append("  " + "~" * 40)

        # --- LLM Response ---
        self.lines.append("")
        self.lines.append("  LLM RESPONSE:")
        response_preview = llm_response.replace("\n", "\n       ")
        if len(response_preview) > 500:
            response_preview = response_preview[:497] + "..."
        self.lines.append(f"       {response_preview}")

        # --- Usage ---
        self.lines.append("")
        self.lines.append(f"  USAGE:")
        self.lines.append(f"    Input tokens:        {usage['input']:,}")
        self.lines.append(f"    Output tokens:       {usage['output']:,}")
        self.lines.append(f"    Cache read tokens:   {usage['cached']:,}")
        self.lines.append(f"    Cache write tokens:  {usage['cache_write']:,}")
        self.lines.append(f"    Latency:             {latency_ms:,.0f}ms")

        if usage['cached'] > 0:
            pct = usage['cached'] / usage['input'] * 100
            self.lines.append(f"    Cache hit:           {pct:.0f}% of input served from cache")

    def log_summary(self, without: "SessionMetrics" = None,
                    with_cache: "SessionMetrics" = None):
        """Log the final comparison."""
        self.lines.append("")
        self.lines.append("=" * 80)
        self.lines.append("  COMPARISON SUMMARY")
        self.lines.append("=" * 80)

        if without:
            self.lines.append("")
            self.lines.append("  WITHOUT CACHING:")
            self.lines.append(f"    Total input tokens:  {without.total_input:,}")
            self.lines.append(f"    Total output tokens: {without.total_output:,}")
            self.lines.append(f"    Total latency:       {without.total_latency_ms:,.0f}ms")

        if with_cache:
            self.lines.append("")
            self.lines.append("  WITH CACHING:")
            self.lines.append(f"    Total input tokens:  {with_cache.total_input:,}")
            self.lines.append(f"    Total output tokens: {with_cache.total_output:,}")
            self.lines.append(f"    Cache read tokens:   {with_cache.total_cache_read:,}")
            self.lines.append(f"    Cache write tokens:  {with_cache.total_cache_write:,}")
            self.lines.append(f"    Cache hits:          "
                              f"{with_cache.cache_hits}/{len(with_cache.turns)} turns")
            self.lines.append(f"    Total latency:       {with_cache.total_latency_ms:,.0f}ms")

        if without and with_cache:
            has_data = with_cache.total_cache_read > 0 or with_cache.total_cache_write > 0
            if has_data:
                baseline = without.baseline_cost_units()
                effective = with_cache.effective_cost_units()
                savings_pct = ((baseline - effective) / baseline * 100) if baseline > 0 else 0

                cost_without = without.total_input / 1_000_000 * 3.0
                cost_read = with_cache.total_cache_read / 1_000_000 * 0.30
                cost_write = with_cache.total_cache_write / 1_000_000 * 3.75
                uncached = max(0, with_cache.total_input
                               - with_cache.total_cache_read
                               - with_cache.total_cache_write)
                cost_with = cost_read + cost_write + (uncached / 1_000_000 * 3.0)

                self.lines.append("")
                self.lines.append("  SAVINGS:")
                self.lines.append(f"    Input cost reduction: ~{savings_pct:.1f}%")
                self.lines.append(f"    Without caching:      ${cost_without:.4f}")
                self.lines.append(f"    With caching:         ${cost_with:.4f}")
                self.lines.append(f"    Saved:                ${cost_without - cost_with:.4f}")

        self.lines.append("")

    def save(self):
        """Write the log file."""
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))
        log_path = os.path.abspath(self.log_file)
        print(f"\n  Log saved to: {log_path}")
        print(f"\n  >> Open the log file to see the EXACT API calls made to the LLM,")
        print(f"     including how cache_control breakpoints are placed on messages.")
        print(f"     This shows you exactly how to implement prompt caching in your own code.")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def safe_str(text: str) -> str:
    """Remove characters that can't be printed on Windows cp1252 console."""
    return text.encode("ascii", errors="replace").decode("ascii")


def truncate(text: str, max_chars: int) -> str:
    """Truncate text with ellipsis, safe for Windows console."""
    text = safe_str(text.replace("\n", " ").strip())
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3].rstrip() + "..."


def print_turn(turn_num: int, total: int, user_msg: str, llm_response: str,
               metrics: TurnMetrics, caching_enabled: bool):
    """Print a single turn with conversation preview and metrics."""
    # Header
    cache_label = ""
    if caching_enabled:
        if metrics.cache_hit:
            cache_label = f" | CACHE HIT: {metrics.cache_pct:.0f}% of input cached"
        elif metrics.cache_write_tokens > 0:
            cache_label = f" | CACHE WRITE: {metrics.cache_write_tokens:,} tokens stored"

    print(f"\n  Turn {turn_num}/{total}  "
          f"[{metrics.context_messages} messages, "
          f"{metrics.input_tokens:,} tokens in context]")

    # Conversation preview
    print(f"  USER: {truncate(user_msg, RESPONSE_PREVIEW_CHARS)}")
    print(f"  LLM:  {truncate(llm_response, RESPONSE_PREVIEW_CHARS)}")

    # Metrics line
    print(f"  >>> {metrics.input_tokens:,} input | "
          f"{metrics.output_tokens:,} output | "
          f"{metrics.latency_ms:,.0f}ms{cache_label}")


# ---------------------------------------------------------------------------
# Run one full conversation
# ---------------------------------------------------------------------------

def run_conversation(client, model: str, caching_enabled: bool,
                     logger: TransactionLogger = None) -> SessionMetrics:
    """Run the 5-turn conversation and display each turn."""
    metrics = SessionMetrics()
    history: list[dict] = []
    run_mode = "with" if caching_enabled else "without"

    label = "WITH CACHING" if caching_enabled else "WITHOUT CACHING"
    print(f"\n{'=' * 70}")
    print(f"  Run: {label}")
    print(f"{'=' * 70}")

    if logger:
        logger.log_run_start(run_mode)

    for turn_idx, user_msg in enumerate(CONVERSATION_TURNS):
        turn_num = turn_idx + 1

        # Build conversation: system prompt + growing history + new user message
        history.append({"role": "user", "content": user_msg})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history)

        # Apply cache markers if enabled
        if caching_enabled:
            messages = apply_cache_control(messages)

        msg_count = len(messages)

        # --- LLM API Call ---
        start = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=messages,
        )
        latency = (time.perf_counter() - start) * 1000

        # Extract response text
        llm_response = ""
        if response.choices and response.choices[0].message:
            llm_response = response.choices[0].message.content or ""

        # Extract usage metrics
        usage = extract_usage(response.usage)
        tm = TurnMetrics(
            turn=turn_num,
            input_tokens=usage["input"],
            output_tokens=usage["output"],
            cache_read_tokens=usage["cached"],
            cache_write_tokens=usage["cache_write"],
            latency_ms=latency,
            context_messages=msg_count,
        )
        metrics.turns.append(tm)

        # Display this turn
        print_turn(turn_num, len(CONVERSATION_TURNS), user_msg, llm_response,
                   tm, caching_enabled)

        # Log this turn (includes the exact messages array with cache markers)
        if logger:
            logger.log_turn(run_mode, turn_num, user_msg, messages,
                            llm_response, usage, latency, msg_count,
                            model=model)

        # Add assistant response to history for next turn
        history.append({"role": "assistant", "content": llm_response})

    return metrics


# ---------------------------------------------------------------------------
# Final comparison report
# ---------------------------------------------------------------------------

def print_comparison(without: SessionMetrics, with_cache: SessionMetrics, model: str = ""):
    """Print the side-by-side savings report."""

    print(f"\n{'=' * 70}")
    print(f"  COMPARISON: WITHOUT vs WITH CACHING")
    print(f"{'=' * 70}")

    # Per-turn table
    print(f"\n  {'Turn':<6} {'-- No Cache --':>20}   {'-- With Cache --':>32}")
    print(f"  {'':6} {'Input':>8} {'Latency':>10}   "
          f"{'Input':>8} {'Cached':>8} {'Hit%':>6} {'Latency':>10}")
    print(f"  {'-'*6} {'-'*8} {'-'*10}   {'-'*8} {'-'*8} {'-'*6} {'-'*10}")

    for w, c in zip(without.turns, with_cache.turns):
        hit_pct = f"{c.cache_pct:.0f}%" if c.cache_hit else "-"
        print(f"  {w.turn:<6} {w.input_tokens:>8,} {w.latency_ms:>8,.0f}ms   "
              f"{c.input_tokens:>8,} {c.cache_read_tokens:>8,} {hit_pct:>6} "
              f"{c.latency_ms:>8,.0f}ms")

    # Totals row
    overall_hit_pct = (with_cache.total_cache_read / with_cache.total_input * 100
                       if with_cache.total_input > 0 else 0)
    print(f"\n  {'TOTAL':<6} {without.total_input:>8,} "
          f"{without.total_latency_ms:>8,.0f}ms   "
          f"{with_cache.total_input:>8,} {with_cache.total_cache_read:>8,} "
          f"{overall_hit_pct:>5.0f}% {with_cache.total_latency_ms:>8,.0f}ms")

    # Summary stats
    has_cache_data = with_cache.total_cache_read > 0 or with_cache.total_cache_write > 0

    if has_cache_data:
        baseline = without.baseline_cost_units()
        cached = with_cache.effective_cost_units()
        savings_pct = ((baseline - cached) / baseline * 100) if baseline > 0 else 0
        latency_diff = without.total_latency_ms - with_cache.total_latency_ms

        print(f"\n  {'=' * 64}")
        print(f"  SAVINGS SUMMARY")
        print(f"  {'=' * 64}")
        print(f"  Cache hit rate:           "
              f"{with_cache.cache_hits}/{len(with_cache.turns)} turns")
        print(f"  Tokens served from cache: {with_cache.total_cache_read:,} "
              f"/ {with_cache.total_input:,}")
        print(f"  Input cost reduction:     ~{savings_pct:.1f}%")

        latency_label = "faster" if latency_diff > 0 else "slower"
        print(f"  Latency difference:       {abs(latency_diff):,.0f}ms {latency_label}")
        print(f"                            (latency varies with network/proxy;"
              f" cost savings are the reliable metric)")

        # Dollar estimate (Claude Sonnet pricing)
        print(f"\n  --- Dollar Estimate ({model or 'Claude Sonnet'}: $3/MTok input) ---")
        cost_without = without.total_input / 1_000_000 * 3.0
        cost_read = with_cache.total_cache_read / 1_000_000 * 0.30
        cost_write = with_cache.total_cache_write / 1_000_000 * 3.75
        uncached = max(0, with_cache.total_input
                       - with_cache.total_cache_read
                       - with_cache.total_cache_write)
        cost_with = cost_read + cost_write + (uncached / 1_000_000 * 3.0)

        print(f"  Without caching:  ${cost_without:.4f}")
        print(f"  With caching:     ${cost_with:.4f}")
        print(f"  Saved:            ${cost_without - cost_with:.4f}")

        # Extrapolation
        print(f"\n  --- At Scale ---")
        print(f"  If your agent averages 15 turns/task and 100 tasks/day:")
        daily_without = cost_without / 5 * 15 * 100
        daily_with = cost_with / 5 * 15 * 100
        print(f"    Daily cost without caching: ${daily_without:,.2f}")
        print(f"    Daily cost with caching:    ${daily_with:,.2f}")
        print(f"    Daily savings:              ${daily_without - daily_with:,.2f}")
        print(f"    Monthly savings:            ${(daily_without - daily_with) * 30:,.2f}")
    else:
        print(f"\n  NOTE: Your proxy did not return cache token counts.")
        print(f"  The cache markers ARE being sent - check your proxy logs.")
        print(f"  For full metrics, use the Anthropic SDK directly or a")
        print(f"  proxy that forwards cache usage fields.")

    print(f"\n  TIP: Savings grow with system prompt size and conversation")
    print(f"  length. Production agents with 5K+ token system prompts and")
    print(f"  20+ turns see 50-70% input cost reduction.\n")


# ---------------------------------------------------------------------------
# Single-run report (for "without only" or "with only" modes)
# ---------------------------------------------------------------------------

def print_single_run(metrics: SessionMetrics, caching_enabled: bool):
    """Print summary for a single run."""
    label = "WITH" if caching_enabled else "WITHOUT"
    print(f"\n  {'=' * 64}")
    print(f"  SUMMARY ({label} CACHING)")
    print(f"  {'=' * 64}")
    print(f"  Total input tokens:  {metrics.total_input:,}")
    print(f"  Total output tokens: {metrics.total_output:,}")
    print(f"  Total latency:       {metrics.total_latency_ms:,.0f}ms")
    if caching_enabled and metrics.total_cache_read > 0:
        print(f"  Cache hits:          {metrics.cache_hits}/{len(metrics.turns)} turns")
        print(f"  Tokens from cache:   {metrics.total_cache_read:,}")
        savings = ((metrics.baseline_cost_units() - metrics.effective_cost_units())
                   / metrics.baseline_cost_units() * 100)
        print(f"  Cost reduction:      ~{savings:.1f}%")
    elif caching_enabled:
        print(f"  Cache data:          Not reported by proxy")
        print(f"  (Cache markers were sent - check proxy logs)")
    print()


# ---------------------------------------------------------------------------
# Interactive setup
# ---------------------------------------------------------------------------

def get_config():
    """Prompt user for API key, base URL, model, and run mode."""
    print("\n  ========================================")
    print("    Prompt Caching Demo")
    print("    See the cost savings in real time")
    print("  ========================================")

    # --- Step 1: Base URL ---
    base_url = BASE_URL
    if not base_url:
        print(f"\n  STEP 1: Base URL")
        print(f"  This is your OpenAI-compatible API endpoint.")
        print(f"  Default: {DEFAULT_BASE_URL}\n")
        base_url = input(f"  Base URL (press Enter for default): ").strip()
        if not base_url:
            base_url = DEFAULT_BASE_URL
    else:
        print(f"  Base URL:   {base_url} (from CONFIGURATION)")

    # --- Step 2: API Key ---
    api_key = API_KEY
    if not api_key:
        print("\n  STEP 2: API Key")
        print("  (Tip: hardcode it in the CONFIGURATION section at top of this file)\n")
        api_key = getpass.getpass("  API Key (hidden): ").strip()
        if not api_key:
            print("  ERROR: API key is required.")
            return None, None, None, None
    else:
        print(f"\n  API Key:    ****...{api_key[-4:]} (from CONFIGURATION)")

    # --- Step 3: Model ---
    model = MODEL
    if not model:
        print("\n  STEP 3: Model")
        print("  Must be a Claude model for caching demo (e.g. claude-3-7-sonnet-20250219).\n")
        model = input("  Model (press Enter for claude-3-7-sonnet-20250219): ").strip()
        if not model:
            model = "claude-3-7-sonnet-20250219"
    else:
        print(f"  Model:      {model} (from CONFIGURATION)")

    # --- Step 4: Run mode ---
    print("\n  STEP 4: What would you like to run?")
    print()
    print("  [1] Compare (recommended)")
    print("      Runs the same 5-turn conversation TWICE - first without caching,")
    print("      then with caching - and shows a side-by-side cost comparison.")
    print()
    print("  [2] Without caching only")
    print("      Runs the conversation without any cache markers.")
    print("      Shows the baseline cost of a normal multi-turn session.")
    print()
    print("  [3] With caching only")
    print("      Runs the conversation with cache breakpoints enabled.")
    print("      Shows cache hit rate and per-turn savings.")
    print()
    choice = input("  Your choice [1/2/3] (press Enter for 1): ").strip()
    if choice == "2":
        mode = "without"
    elif choice == "3":
        mode = "with"
    else:
        mode = "both"

    return api_key, base_url, model, mode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    result = get_config()
    if result[0] is None:
        return
    api_key, base_url, model, mode = result

    # Create OpenAI-compatible client
    from openai import OpenAI
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    print(f"\n  Configuration:")
    print(f"    Model:      {model}")
    print(f"    Base URL:   {base_url or 'default (api.openai.com)'}")
    print(f"    Turns:      {len(CONVERSATION_TURNS)}")
    print(f"    Max output: {MAX_OUTPUT_TOKENS} tokens/turn")
    print(f"    Mode:       {mode}")

    mode_descriptions = {
        "both": "Running same conversation WITHOUT then WITH caching...",
        "without": "Running conversation WITHOUT caching (baseline)...",
        "with": "Running conversation WITH caching enabled...",
    }
    print(f"\n  {mode_descriptions[mode]}")

    # Create transaction logger
    logger = TransactionLogger(model, base_url or "default")

    without_metrics = None
    with_metrics = None

    if mode in ("without", "both"):
        try:
            without_metrics = run_conversation(
                client, model, caching_enabled=False, logger=logger)
        except Exception as e:
            print(f"\n  ERROR: {e}")
            print(f"  Check your API key, base URL, and model name.")
            return

    if mode in ("with", "both"):
        try:
            with_metrics = run_conversation(
                client, model, caching_enabled=True, logger=logger)
        except Exception as e:
            print(f"\n  ERROR: {e}")
            return

    # --- Report ---
    if mode == "both" and without_metrics and with_metrics:
        print_comparison(without_metrics, with_metrics, model=model)
        logger.log_summary(without_metrics, with_metrics)
    elif without_metrics:
        print_single_run(without_metrics, caching_enabled=False)
        logger.log_summary(without=without_metrics)
    elif with_metrics:
        print_single_run(with_metrics, caching_enabled=True)
        logger.log_summary(with_cache=with_metrics)

    # Save the log
    logger.save()


if __name__ == "__main__":
    main()

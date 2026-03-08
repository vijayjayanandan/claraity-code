
/*
=============================================================================
  Prompt Caching Demo - See the cost savings in real time
=============================================================================

This standalone script demonstrates prompt caching with Claude models via
any OpenAI-compatible API endpoint. It runs the SAME 5-turn conversation
twice - once WITHOUT caching, once WITH - then prints a comparison.

Requirements:
    Java 11+ (uses java.net.http.HttpClient). No external dependencies.

Usage:
    java PromptCachingDemo.java

You'll be prompted for your API key, base URL, and model name.
Or hardcode them below in the CONFIGURATION section.
*/

import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

public class PromptCachingDemo {

    // ============================= CONFIGURATION ================================
    // Hardcode these to skip the interactive prompts.
    // Leave as null to be prompted at runtime.

    static String API_KEY = null;                           // Your API key (or enter at runtime)
    static String BASE_URL = null;                          // Defaults to FuelIX proxy at runtime
    static String MODEL = null;                             // e.g. "claude-3-7-sonnet-20250219"

    static String DEFAULT_BASE_URL = "https://proxy.fuelix.ai/v1"; // Default when user presses Enter

    static int MAX_OUTPUT_TOKENS = 300;                     // Kept small to minimize demo cost
    static int RESPONSE_PREVIEW_CHARS = 180;                // How many chars of LLM response to show

    // ============================================================================
    // System prompt (~1,500 tokens). Must exceed Anthropic's 1,024-token minimum
    // for caching to activate. Real agent prompts are typically 3,000-10,000+.
    // ============================================================================
    static String SYSTEM_PROMPT = """
You are a senior software engineer AI assistant working as part of an
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
production-ready, not just illustrative.
""";

    // ---------------------------------------------------------------------------
    // Simulated multi-turn conversation (builds up like a real coding session)
    // ---------------------------------------------------------------------------
    static String[] CONVERSATION_TURNS = new String[] {
        "I have a Python Flask API that handles user authentication. " +
        "The login endpoint accepts username and password, queries the " +
        "database, and returns a JWT token. Can you review this approach?",

        "Good points. Now I want to add rate limiting to prevent brute " +
        "force attacks. What's the best approach for Flask? Should I use " +
        "an in-memory store or Redis?",

        "Let's go with Redis. Can you write the rate limiting middleware? " +
        "I want 5 attempts per minute per IP for the login endpoint, and " +
        "100 requests per minute per user for other authenticated endpoints.",

        "Now I need to add refresh token rotation. When a client uses a " +
        "refresh token, I want to invalidate the old one and issue a new " +
        "pair. How should I store and track refresh tokens?",

        "One more thing - I need to add audit logging for all auth events. " +
        "Login success, login failure, token refresh, logout. What's a good " +
        "pattern that won't slow down the auth endpoints?"
    };

    // ---------------------------------------------------------------------------
    // Cache breakpoint logic (the two-breakpoint strategy)
    // ---------------------------------------------------------------------------

    static List<Map<String, Object>> apply_cache_control(List<Map<String, Object>> messages) {
        /* Apply the two-breakpoint strategy to a message list.

         BP1: System prompt (first message) - static across all calls.
         BP2: Last message with content before the new user input -
              caches the conversation history prefix.

         This is the core of prompt caching. These ~30 lines save 40-50% on
         input costs for multi-turn conversations with Claude.
        */
        if (messages.size() < 2) return messages;

        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> m : messages) result.add(new LinkedHashMap<>(m)); // shallow copy

        // BP1: Mark the system prompt
        if ("system".equals(String.valueOf(result.get(0).get("role")))) {
            result.set(0, _add_cache_marker(result.get(0)));
        }

        // BP2: Walk backwards from second-to-last, find last message with content.
        // We skip the final message (new user input) since it changes every turn.
        if (result.size() >= 3) {
            for (int i = result.size() - 2; i >= 1; i--) {
                if (result.get(i).get("content") != null) {
                    result.set(i, _add_cache_marker(result.get(i)));
                    break;
                }
            }
        }

        return result;
    }

    static Map<String, Object> _add_cache_marker(Map<String, Object> msgIn) {
        /* Add cache_control: {"type": "ephemeral"} to a message. */
        Map<String, Object> msg = new LinkedHashMap<>(msgIn);
        Object content = msg.get("content");

        if (content == null) return msg;

        // Tool role: add as sibling field (required for litellm/proxy compatibility)
        if ("tool".equals(String.valueOf(msg.get("role")))) {
            msg.put("cache_control", Map.of("type", "ephemeral"));
            return msg;
        }

        // String content: convert to Anthropic content-blocks format
        if (content instanceof String) {
            List<Object> blocks = new ArrayList<>();
            Map<String, Object> block = new LinkedHashMap<>();
            block.put("type", "text");
            block.put("text", content);
            block.put("cache_control", Map.of("type", "ephemeral"));
            blocks.add(block);
            msg.put("content", blocks);
        }
        // List content: mark the last block
        else if (content instanceof List<?> list && !list.isEmpty()) {
            List<Object> newBlocks = new ArrayList<>();
            for (Object o : list) {
                if (o instanceof Map<?, ?> m) {
                    Map<String, Object> copy = new LinkedHashMap<>();
                    for (Map.Entry<?, ?> e : m.entrySet()) copy.put(String.valueOf(e.getKey()), e.getValue());
                    newBlocks.add(copy);
                } else {
                    newBlocks.add(o);
                }
            }
            Object last = newBlocks.get(newBlocks.size() - 1);
            if (last instanceof Map<?, ?> m) {
                @SuppressWarnings("unchecked")
                Map<String, Object> lm = (Map<String, Object>) last;
                lm.put("cache_control", Map.of("type", "ephemeral"));
            }
            msg.put("content", newBlocks);
        }

        return msg;
    }

    // ---------------------------------------------------------------------------
    // Metrics
    // ---------------------------------------------------------------------------

    static class TurnMetrics {
        int turn = 0;
        int input_tokens = 0;
        int output_tokens = 0;
        int cache_read_tokens = 0;
        int cache_write_tokens = 0;
        double latency_ms = 0.0;
        int context_messages = 0; // how many messages sent to LLM this turn

        boolean cache_hit() { return cache_read_tokens > 0; }

        double cache_pct() {
            if (input_tokens == 0) return 0.0;
            return (double) cache_read_tokens / (double) input_tokens * 100.0;
        }
    }

    static class SessionMetrics {
        List<TurnMetrics> turns = new ArrayList<>();

        int total_input() {
            int s = 0;
            for (TurnMetrics t : turns) s += t.input_tokens;
            return s;
        }

        int total_output() {
            int s = 0;
            for (TurnMetrics t : turns) s += t.output_tokens;
            return s;
        }

        int total_cache_read() {
            int s = 0;
            for (TurnMetrics t : turns) s += t.cache_read_tokens;
            return s;
        }

        int total_cache_write() {
            int s = 0;
            for (TurnMetrics t : turns) s += t.cache_write_tokens;
            return s;
        }

        int cache_hits() {
            int s = 0;
            for (TurnMetrics t : turns) if (t.cache_hit()) s += 1;
            return s;
        }

        double total_latency_ms() {
            double s = 0.0;
            for (TurnMetrics t : turns) s += t.latency_ms;
            return s;
        }

        double effective_cost_units() {
            // Relative cost with caching (1.0 = full price per token).
            int uncached = total_input() - total_cache_read() - total_cache_write();
            return (double) total_cache_read() * 0.1
                + (double) total_cache_write() * 1.25
                + (double) Math.max(0, uncached) * 1.0;
        }

        double baseline_cost_units() {
            return (double) total_input();
        }
    }

    // ---------------------------------------------------------------------------
    // Usage extraction
    // ---------------------------------------------------------------------------

    static Map<String, Integer> extract_usage(Map<String, Object> usage) {
        // Extract token counts from an OpenAI SDK usage object.
        if (usage == null) return Map.of("input", 0, "output", 0, "cached", 0, "cache_write", 0);

        int input_tokens = getInt(usage.get("prompt_tokens"));
        int output_tokens = getInt(usage.get("completion_tokens"));

        // Cache data may come from prompt_tokens_details (OpenAI format)
        // or directly on the usage object (Anthropic-via-proxy format)
        int cached = 0;
        int cache_write = 0;

        Object detailsObj = usage.get("prompt_tokens_details");
        if (detailsObj instanceof Map<?, ?> details) {
            Object ct = ((Map<?, ?>) details).get("cached_tokens");
            cached = Math.max(cached, getInt(ct));
        }

        cached = Math.max(cached, getInt(usage.get("cache_read_input_tokens")));
        cache_write = Math.max(cache_write, getInt(usage.get("cache_creation_input_tokens")));

        Map<String, Integer> out = new LinkedHashMap<>();
        out.put("input", input_tokens);
        out.put("output", output_tokens);
        out.put("cached", cached);
        out.put("cache_write", cache_write);
        return out;
    }

    static int getInt(Object o) {
        if (o == null) return 0;
        if (o instanceof Number n) return n.intValue();
        try { return Integer.parseInt(String.valueOf(o)); } catch (Exception e) { return 0; }
    }

    // ---------------------------------------------------------------------------
    // Transaction logger (plain text)
    // ---------------------------------------------------------------------------

    static class TransactionLogger {
        /* Logs every API call to a readable plain text file.

         Shows the exact messages array sent to the LLM so users can see
         how cache breakpoints are placed and how context grows each turn.
        */
        String log_file;
        List<String> lines = new ArrayList<>();

        TransactionLogger(String model, String base_url) {
            String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
            this.log_file = "prompt_caching_demo_" + timestamp + ".log";
            _write_header(model, base_url);
        }

        void _write_header(String model, String base_url) {
            lines.add("=".repeat(80));
            lines.add("  PROMPT CACHING DEMO - TRANSACTION LOG");
            lines.add("=".repeat(80));
            lines.add("  Timestamp:    " + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
            lines.add("  Model:        " + model);
            lines.add("  Base URL:     " + base_url);
            lines.add("  Max output:   " + MAX_OUTPUT_TOKENS + " tokens/turn");
            lines.add("  Turns:        " + CONVERSATION_TURNS.length);
            lines.add("");
        }

        void log_run_start(String run_mode) {
            String label = "with".equals(run_mode) ? "WITH CACHING" : "WITHOUT CACHING";
            lines.add("");
            lines.add("#".repeat(80));
            lines.add("#  RUN: " + label);
            lines.add("#".repeat(80));
        }

        Map<String, Object> _format_message_for_log(Map<String, Object> msg, int max_text) {
            // Create a log-friendly copy of a message, truncating long text.
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : msg.entrySet()) {
                String key = e.getKey();
                Object value = e.getValue();
                if ("content".equals(key)) {
                    if (value instanceof String s) {
                        if (s.length() > max_text) result.put("content", s.substring(0, max_text) + "...(" + s.length() + " chars)");
                        else result.put("content", s);
                    } else if (value instanceof List<?> list) {
                        List<Object> blocks = new ArrayList<>();
                        for (Object block : list) {
                            if (block instanceof Map<?, ?> bm) {
                                Map<String, Object> b = new LinkedHashMap<>();
                                for (Map.Entry<?, ?> be : bm.entrySet()) b.put(String.valueOf(be.getKey()), be.getValue());
                                Object text = b.get("text");
                                if (text instanceof String ts && ts.length() > max_text) {
                                    b.put("text", ts.substring(0, max_text) + "...(" + ts.length() + " chars)");
                                }
                                blocks.add(b);
                            } else {
                                blocks.add(block);
                            }
                        }
                        result.put("content", blocks);
                    } else {
                        result.put("content", value);
                    }
                } else {
                    result.put(key, value);
                }
            }
            return result;
        }

        List<String> _indent(String text, String prefix) {
            List<String> out = new ArrayList<>();
            for (String line : text.split("\n", -1)) out.add(prefix + line);
            return out;
        }

        void log_turn(String run_mode, int turn, String user_msg,
                      List<Map<String, Object>> messages_sent, String llm_response,
                      Map<String, Integer> usage, double latency_ms, int context_messages,
                      String model) {
            lines.add("");
            lines.add("-".repeat(80));
            lines.add(String.format("  TURN %d/%d  [%d messages in context]", turn, CONVERSATION_TURNS.length, context_messages));
            lines.add("-".repeat(80));

            lines.add("");
            lines.add("  EXACT API CALL:");
            lines.add("  " + "~".repeat(40));

            List<Object> log_messages = new ArrayList<>();
            for (Map<String, Object> m : messages_sent) log_messages.add(_format_message_for_log(m, 200));
            String messages_json = Json.toJson(log_messages, 4);

            lines.add("  client.chat.completions.create(");
            lines.add("      model=\"" + model + "\",");
            lines.add("      max_tokens=" + MAX_OUTPUT_TOKENS + ",");
            lines.add("      messages=");
            lines.addAll(_indent(messages_json, "      "));
            lines.add("  )");
            lines.add("  " + "~".repeat(40));

            lines.add("");
            lines.add("  LLM RESPONSE:");
            String response_preview = llm_response.replace("\n", "\n       ");
            if (response_preview.length() > 500) response_preview = response_preview.substring(0, 497) + "...";
            lines.add("       " + response_preview);

            lines.add("");
            lines.add("  USAGE:");
            lines.add(String.format("    Input tokens:        %,d", usage.getOrDefault("input", 0)));
            lines.add(String.format("    Output tokens:       %,d", usage.getOrDefault("output", 0)));
            lines.add(String.format("    Cache read tokens:   %,d", usage.getOrDefault("cached", 0)));
            lines.add(String.format("    Cache write tokens:  %,d", usage.getOrDefault("cache_write", 0)));
            lines.add(String.format("    Latency:             %,.0fms", latency_ms));

            if (usage.getOrDefault("cached", 0) > 0 && usage.getOrDefault("input", 0) > 0) {
                double pct = (double) usage.get("cached") / (double) usage.get("input") * 100.0;
                lines.add(String.format("    Cache hit:           %.0f%% of input served from cache", pct));
            }
        }

        void log_summary(SessionMetrics without, SessionMetrics with_cache) {
            lines.add("");
            lines.add("=".repeat(80));
            lines.add("  COMPARISON SUMMARY");
            lines.add("=".repeat(80));

            if (without != null) {
                lines.add("");
                lines.add("  WITHOUT CACHING:");
                lines.add(String.format("    Total input tokens:  %,d", without.total_input()));
                lines.add(String.format("    Total output tokens: %,d", without.total_output()));
                lines.add(String.format("    Total latency:       %,.0fms", without.total_latency_ms()));
            }

            if (with_cache != null) {
                lines.add("");
                lines.add("  WITH CACHING:");
                lines.add(String.format("    Total input tokens:  %,d", with_cache.total_input()));
                lines.add(String.format("    Total output tokens: %,d", with_cache.total_output()));
                lines.add(String.format("    Cache read tokens:   %,d", with_cache.total_cache_read()));
                lines.add(String.format("    Cache write tokens:  %,d", with_cache.total_cache_write()));
                lines.add(String.format("    Cache hits:          %d/%d turns", with_cache.cache_hits(), with_cache.turns.size()));
                lines.add(String.format("    Total latency:       %,.0fms", with_cache.total_latency_ms()));
            }

            if (without != null && with_cache != null) {
                boolean has_data = with_cache.total_cache_read() > 0 || with_cache.total_cache_write() > 0;
                if (has_data) {
                    double baseline = without.baseline_cost_units();
                    double effective = with_cache.effective_cost_units();
                    double savings_pct = baseline > 0 ? ((baseline - effective) / baseline * 100.0) : 0.0;

                    double cost_without = without.total_input() / 1_000_000.0 * 3.0;
                    double cost_read = with_cache.total_cache_read() / 1_000_000.0 * 0.30;
                    double cost_write = with_cache.total_cache_write() / 1_000_000.0 * 3.75;
                    int uncached = Math.max(0, with_cache.total_input() - with_cache.total_cache_read() - with_cache.total_cache_write());
                    double cost_with = cost_read + cost_write + (uncached / 1_000_000.0 * 3.0);

                    lines.add("");
                    lines.add("  SAVINGS:");
                    lines.add(String.format("    Input cost reduction: ~%.1f%%", savings_pct));
                    lines.add(String.format("    Without caching:      $%.4f", cost_without));
                    lines.add(String.format("    With caching:         $%.4f", cost_with));
                    lines.add(String.format("    Saved:                $%.4f", (cost_without - cost_with)));
                }
            }

            lines.add("");
        }

        void save() {
            try {
                Files.writeString(Path.of(log_file), String.join("\n", lines), StandardCharsets.UTF_8);
                String log_path = Path.of(log_file).toAbsolutePath().toString();
                System.out.println("\n  Log saved to: " + log_path);
                System.out.println("\n  >> Open the log file to see the EXACT API calls made to the LLM,");
                System.out.println("     including how cache_control breakpoints are placed on messages.");
                System.out.println("     This shows you exactly how to implement prompt caching in your own code.");
            } catch (Exception e) {
                System.out.println("\n  ERROR: Failed to save log: " + e.getMessage());
            }
        }
    }

    // ---------------------------------------------------------------------------
    // Display helpers
    // ---------------------------------------------------------------------------

    static String safe_str(String text) {
        // Remove characters that can't be printed on Windows cp1252 console.
        // Java will generally handle UTF-8 terminals fine, but we match Python behaviour.
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c <= 0x7F) sb.append(c);
            else sb.append('?');
        }
        return sb.toString();
    }

    static String truncate(String text, int max_chars) {
        // Truncate text with ellipsis, safe for Windows console.
        text = safe_str(text.replace("\n", " ").trim());
        if (text.length() <= max_chars) return text;
        String cut = text.substring(0, Math.max(0, max_chars - 3)).stripTrailing();
        return cut + "...";
    }

    static void print_turn(int turn_num, int total, String user_msg, String llm_response,
                           TurnMetrics metrics, boolean caching_enabled) {
        // Print a single turn with conversation preview and metrics.
        String cache_label = "";
        if (caching_enabled) {
            if (metrics.cache_hit()) {
                cache_label = String.format(" | CACHE HIT: %.0f%% of input cached", metrics.cache_pct());
            } else if (metrics.cache_write_tokens > 0) {
                cache_label = String.format(" | CACHE WRITE: %,d tokens stored", metrics.cache_write_tokens);
            }
        }

        System.out.println(String.format("\n  Turn %d/%d  [%d messages, %,d tokens in context]",
                turn_num, total, metrics.context_messages, metrics.input_tokens));

        System.out.println("  USER: " + truncate(user_msg, RESPONSE_PREVIEW_CHARS));
        System.out.println("  LLM:  " + truncate(llm_response, RESPONSE_PREVIEW_CHARS));

        System.out.println(String.format("  >>> %,d input | %,d output | %,.0fms%s",
                metrics.input_tokens, metrics.output_tokens, metrics.latency_ms, cache_label));
    }

    // ---------------------------------------------------------------------------
    // Run one full conversation
    // ---------------------------------------------------------------------------

    static SessionMetrics run_conversation(OpenAICompatClient client, String model, boolean caching_enabled,
                                          TransactionLogger logger) throws Exception {
        // Run the 5-turn conversation and display each turn.
        SessionMetrics metrics = new SessionMetrics();
        List<Map<String, Object>> history = new ArrayList<>();
        String run_mode = caching_enabled ? "with" : "without";

        String label = caching_enabled ? "WITH CACHING" : "WITHOUT CACHING";
        System.out.println("\n" + "=".repeat(70));
        System.out.println("  Run: " + label);
        System.out.println("=".repeat(70));

        if (logger != null) logger.log_run_start(run_mode);

        for (int turn_idx = 0; turn_idx < CONVERSATION_TURNS.length; turn_idx++) {
            int turn_num = turn_idx + 1;
            String user_msg = CONVERSATION_TURNS[turn_idx];

            // Build conversation: system prompt + growing history + new user message
            history.add(mapOf("role", "user", "content", user_msg));
            List<Map<String, Object>> messages = new ArrayList<>();
            messages.add(mapOf("role", "system", "content", SYSTEM_PROMPT));
            messages.addAll(history);

            // Apply cache markers if enabled
            if (caching_enabled) messages = apply_cache_control(messages);

            int msg_count = messages.size();

            // --- LLM API Call ---
            long start = System.nanoTime();
            OpenAICompatClient.ChatCompletionResponse response = client.chat_completions_create(model, MAX_OUTPUT_TOKENS, messages);
            double latency = (System.nanoTime() - start) / 1_000_000.0;

            String llm_response = response.text != null ? response.text : "";

            Map<String, Integer> usage = extract_usage(response.usage);

            TurnMetrics tm = new TurnMetrics();
            tm.turn = turn_num;
            tm.input_tokens = usage.getOrDefault("input", 0);
            tm.output_tokens = usage.getOrDefault("output", 0);
            tm.cache_read_tokens = usage.getOrDefault("cached", 0);
            tm.cache_write_tokens = usage.getOrDefault("cache_write", 0);
            tm.latency_ms = latency;
            tm.context_messages = msg_count;
            metrics.turns.add(tm);

            print_turn(turn_num, CONVERSATION_TURNS.length, user_msg, llm_response, tm, caching_enabled);

            if (logger != null) {
                logger.log_turn(run_mode, turn_num, user_msg, messages, llm_response, usage, latency, msg_count, model);
            }

            history.add(mapOf("role", "assistant", "content", llm_response));
        }

        return metrics;
    }

    // ---------------------------------------------------------------------------
    // Final comparison report
    // ---------------------------------------------------------------------------

    static void print_comparison(SessionMetrics without, SessionMetrics with_cache) {
        // Print the side-by-side savings report.
        System.out.println("\n" + "=".repeat(70));
        System.out.println("  COMPARISON: WITHOUT vs WITH CACHING");
        System.out.println("=".repeat(70));

        System.out.println(String.format("\n  %-6s %20s   %32s", "Turn", "-- No Cache --", "-- With Cache --"));
        System.out.println(String.format("  %-6s %8s %10s   %8s %8s %6s %10s", "", "Input", "Latency", "Input", "Cached", "Hit%", "Latency"));
        System.out.println(String.format("  %-6s %8s %10s   %8s %8s %6s %10s",
                "-".repeat(6), "-".repeat(8), "-".repeat(10), "-".repeat(8), "-".repeat(8), "-".repeat(6), "-".repeat(10)));

        for (int i = 0; i < without.turns.size() && i < with_cache.turns.size(); i++) {
            TurnMetrics w = without.turns.get(i);
            TurnMetrics c = with_cache.turns.get(i);
            String hit_pct = c.cache_hit() ? String.format("%.0f%%", c.cache_pct()) : "-";
            System.out.println(String.format("  %-6d %8s %8sms   %8s %8s %6s %8sms",
                    w.turn,
                    fmtInt(w.input_tokens),
                    fmtMs(w.latency_ms),
                    fmtInt(c.input_tokens),
                    fmtInt(c.cache_read_tokens),
                    hit_pct,
                    fmtMs(c.latency_ms)
            ));
        }

        double overall_hit_pct = with_cache.total_input() > 0
                ? (double) with_cache.total_cache_read() / (double) with_cache.total_input() * 100.0
                : 0.0;

        System.out.println(String.format("\n  %-6s %8s %8sms   %8s %8s %5.0f%% %8sms",
                "TOTAL",
                fmtInt(without.total_input()),
                fmtMs(without.total_latency_ms()),
                fmtInt(with_cache.total_input()),
                fmtInt(with_cache.total_cache_read()),
                overall_hit_pct,
                fmtMs(with_cache.total_latency_ms())
        ));

        boolean has_cache_data = with_cache.total_cache_read() > 0 || with_cache.total_cache_write() > 0;
        if (has_cache_data) {
            double baseline = without.baseline_cost_units();
            double cached = with_cache.effective_cost_units();
            double savings_pct = baseline > 0 ? ((baseline - cached) / baseline * 100.0) : 0.0;
            double latency_diff = without.total_latency_ms() - with_cache.total_latency_ms();

            System.out.println("\n  " + "=".repeat(64));
            System.out.println("  SAVINGS SUMMARY");
            System.out.println("  " + "=".repeat(64));
            System.out.println(String.format("  Cache hit rate:           %d/%d turns", with_cache.cache_hits(), with_cache.turns.size()));
            System.out.println(String.format("  Tokens served from cache: %,d / %,d", with_cache.total_cache_read(), with_cache.total_input()));
            System.out.println(String.format("  Input cost reduction:     ~%.1f%%", savings_pct));

            String latency_label = latency_diff > 0 ? "faster" : "slower";
            System.out.println(String.format("  Latency difference:       %,.0fms %s", Math.abs(latency_diff), latency_label));
            System.out.println("                            (latency varies with network/proxy; cost savings are the reliable metric)");

            System.out.println("\n  --- Dollar Estimate (Claude Sonnet: $3/MTok input) ---");
            double cost_without = without.total_input() / 1_000_000.0 * 3.0;
            double cost_read = with_cache.total_cache_read() / 1_000_000.0 * 0.30;
            double cost_write = with_cache.total_cache_write() / 1_000_000.0 * 3.75;
            int uncached_input = Math.max(0, with_cache.total_input() - with_cache.total_cache_read() - with_cache.total_cache_write());
            double cost_with = cost_read + cost_write + (uncached_input / 1_000_000.0 * 3.0);

            System.out.println(String.format("  Without caching:  $%.4f", cost_without));
            System.out.println(String.format("  With caching:     $%.4f", cost_with));
            System.out.println(String.format("  Saved:            $%.4f", (cost_without - cost_with)));

            System.out.println("\n  --- At Scale ---");
            System.out.println("  If your agent averages 15 turns/task and 100 tasks/day:");
            double daily_without = cost_without / 5.0 * 15.0 * 100.0;
            double daily_with = cost_with / 5.0 * 15.0 * 100.0;
            System.out.println(String.format("    Daily cost without caching: $%,.2f", daily_without));
            System.out.println(String.format("    Daily cost with caching:    $%,.2f", daily_with));
            System.out.println(String.format("    Daily savings:              $%,.2f", (daily_without - daily_with)));
            System.out.println(String.format("    Monthly savings:            $%,.2f", (daily_without - daily_with) * 30.0));
        } else {
            System.out.println("\n  NOTE: Your proxy did not return cache token counts.");
            System.out.println("  The cache markers ARE being sent - check your proxy logs.");
            System.out.println("  For full metrics, use the Anthropic SDK directly or a");
            System.out.println("  proxy that forwards cache usage fields.");
        }

        System.out.println("\n  TIP: Savings grow with system prompt size and conversation");
        System.out.println("  length. Production agents with 5K+ token system prompts and");
        System.out.println("  20+ turns see 50-70% input cost reduction.\n");
    }

    // ---------------------------------------------------------------------------
    // Single-run report (for "without only" or "with only" modes)
    // ---------------------------------------------------------------------------

    static void print_single_run(SessionMetrics metrics, boolean caching_enabled) {
        // Print summary for a single run.
        String label = caching_enabled ? "WITH" : "WITHOUT";
        System.out.println("\n  " + "=".repeat(64));
        System.out.println("  SUMMARY (" + label + " CACHING)");
        System.out.println("  " + "=".repeat(64));
        System.out.println(String.format("  Total input tokens:  %,d", metrics.total_input()));
        System.out.println(String.format("  Total output tokens: %,d", metrics.total_output()));
        System.out.println(String.format("  Total latency:       %,.0fms", metrics.total_latency_ms()));
        if (caching_enabled && metrics.total_cache_read() > 0) {
            System.out.println(String.format("  Cache hits:          %d/%d turns", metrics.cache_hits(), metrics.turns.size()));
            System.out.println(String.format("  Tokens from cache:   %,d", metrics.total_cache_read()));
            double savings = (metrics.baseline_cost_units() - metrics.effective_cost_units()) / metrics.baseline_cost_units() * 100.0;
            System.out.println(String.format("  Cost reduction:      ~%.1f%%", savings));
        } else if (caching_enabled) {
            System.out.println("  Cache data:          Not reported by proxy");
            System.out.println("  (Cache markers were sent - check proxy logs)");
        }
        System.out.println();
    }

    // ---------------------------------------------------------------------------
    // Interactive setup
    // ---------------------------------------------------------------------------

    static Config get_config() throws IOException {
        // Prompt user for API key, base URL, model, and run mode.
        System.out.println("\n  ========================================");
        System.out.println("    Prompt Caching Demo");
        System.out.println("    See the cost savings in real time");
        System.out.println("  ========================================");

        BufferedReader br = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));

        // --- Step 1: Base URL ---
        String base_url = BASE_URL;
        if (base_url == null || base_url.isBlank()) {
            System.out.println("\n  STEP 1: Base URL");
            System.out.println("  This is your OpenAI-compatible API endpoint.");
            System.out.println("  Default: " + DEFAULT_BASE_URL + "\n");
            System.out.print("  Base URL (press Enter for default): ");
            base_url = br.readLine().trim();
            if (base_url.isBlank()) base_url = DEFAULT_BASE_URL;
        } else {
            System.out.println("  Base URL:   " + base_url + " (from CONFIGURATION)");
        }

        // --- Step 2: API Key ---
        String api_key = API_KEY;
        if (api_key == null || api_key.isBlank()) {
            System.out.println("\n  STEP 2: API Key");
            System.out.println("  (Tip: hardcode it in the CONFIGURATION section at top of this file)\n");
            api_key = readPassword("  API Key (hidden): ", br);
            api_key = api_key.trim();
            if (api_key.isBlank()) {
                System.out.println("  ERROR: API key is required.");
                return new Config(null, null, null, null);
            }
        } else {
            String suffix = api_key.length() >= 4 ? api_key.substring(api_key.length() - 4) : api_key;
            System.out.println("\n  API Key:    ****..." + suffix + " (from CONFIGURATION)");
        }

        // --- Step 3: Model ---
        String model = MODEL;
        if (model == null || model.isBlank()) {
            System.out.println("\n  STEP 3: Model");
            System.out.println("  Must be a Claude model for caching demo (e.g. claude-3-7-sonnet-20250219).\n");
            System.out.print("  Model (press Enter for claude-3-7-sonnet-20250219): ");
            model = br.readLine().trim();
            if (model.isBlank()) model = "claude-3-7-sonnet-20250219";
        } else {
            System.out.println("  Model:      " + model + " (from CONFIGURATION)");
        }

        // --- Step 4: Run mode ---
        System.out.println("\n  STEP 4: What would you like to run?\n");
        System.out.println("  [1] Compare (recommended)");
        System.out.println("      Runs the same 5-turn conversation TWICE - first without caching,");
        System.out.println("      then with caching - and shows a side-by-side cost comparison.\n");
        System.out.println("  [2] Without caching only");
        System.out.println("      Runs the conversation without any cache markers.");
        System.out.println("      Shows the baseline cost of a normal multi-turn session.\n");
        System.out.println("  [3] With caching only");
        System.out.println("      Runs the conversation with cache breakpoints enabled.");
        System.out.println("      Shows cache hit rate and per-turn savings.\n");
        System.out.print("  Your choice [1/2/3] (press Enter for 1): ");
        String choice = br.readLine().trim();
        String mode;
        if ("2".equals(choice)) mode = "without";
        else if ("3".equals(choice)) mode = "with";
        else mode = "both";

        return new Config(api_key, base_url, model, mode);
    }

    static String readPassword(String prompt, BufferedReader fallback) throws IOException {
        Console c = System.console();
        if (c != null) {
            char[] pwd = c.readPassword(prompt);
            return pwd == null ? "" : new String(pwd);
        }
        // Fallback (IDE terminals often return null console): visible input
        System.out.print(prompt);
        return fallback.readLine();
    }

    static class Config {
        String api_key;
        String base_url;
        String model;
        String mode;

        Config(String api_key, String base_url, String model, String mode) {
            this.api_key = api_key;
            this.base_url = base_url;
            this.model = model;
            this.mode = mode;
        }
    }

    // ---------------------------------------------------------------------------
    // Main
    // ---------------------------------------------------------------------------

    public static void main(String[] args) {
        try {
            Config cfg = get_config();
            if (cfg.api_key == null) return;

            // Create OpenAI-compatible client
            OpenAICompatClient client = new OpenAICompatClient(cfg.api_key, cfg.base_url);

            System.out.println("\n  Configuration:");
            System.out.println("    Model:      " + cfg.model);
            System.out.println("    Base URL:   " + (cfg.base_url == null || cfg.base_url.isBlank() ? "default (api.openai.com)" : cfg.base_url));
            System.out.println("    Turns:      " + CONVERSATION_TURNS.length);
            System.out.println("    Max output: " + MAX_OUTPUT_TOKENS + " tokens/turn");
            System.out.println("    Mode:       " + cfg.mode);

            Map<String, String> mode_descriptions = Map.of(
                    "both", "Running same conversation WITHOUT then WITH caching...",
                    "without", "Running conversation WITHOUT caching (baseline)...",
                    "with", "Running conversation WITH caching enabled..."
            );
            System.out.println("\n  " + mode_descriptions.get(cfg.mode));

            // Create transaction logger
            TransactionLogger logger = new TransactionLogger(cfg.model, (cfg.base_url == null || cfg.base_url.isBlank()) ? "default" : cfg.base_url);

            SessionMetrics without_metrics = null;
            SessionMetrics with_metrics = null;

            if ("without".equals(cfg.mode) || "both".equals(cfg.mode)) {
                try {
                    without_metrics = run_conversation(client, cfg.model, false, logger);
                } catch (Exception e) {
                    System.out.println("\n  ERROR: " + e.getMessage());
                    System.out.println("  Check your API key, base URL, and model name.");
                    return;
                }
            }

            if ("with".equals(cfg.mode) || "both".equals(cfg.mode)) {
                try {
                    with_metrics = run_conversation(client, cfg.model, true, logger);
                } catch (Exception e) {
                    System.out.println("\n  ERROR: " + e.getMessage());
                    return;
                }
            }

            // --- Report ---
            if ("both".equals(cfg.mode) && without_metrics != null && with_metrics != null) {
                print_comparison(without_metrics, with_metrics);
                logger.log_summary(without_metrics, with_metrics);
            } else if (without_metrics != null) {
                print_single_run(without_metrics, false);
                logger.log_summary(without_metrics, null);
            } else if (with_metrics != null) {
                print_single_run(with_metrics, true);
                logger.log_summary(null, with_metrics);
            }

            // Save the log
            logger.save();

        } catch (Exception e) {
            System.out.println("\n  ERROR: " + e.getMessage());
        }
    }

    // ---------------------------------------------------------------------------
    // OpenAI-compatible HTTP client (LiteLLM proxy)
    // ---------------------------------------------------------------------------

    static class OpenAICompatClient {
        private final String apiKey;
        private final String baseUrl;
        private final HttpClient http;

        OpenAICompatClient(String apiKey, String baseUrl) {
            this.apiKey = apiKey;
            this.baseUrl = (baseUrl == null || baseUrl.isBlank()) ? "https://api.openai.com/v1" : normalizeBaseUrl(baseUrl);
            this.http = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(30))
                    .build();
        }

        static String normalizeBaseUrl(String b) {
            // Python passes base_url to OpenAI SDK which expects ".../v1".
            // We mimic that: if user already includes /v1, keep; else append /v1.
            String x = b.strip();
            if (x.endsWith("/")) x = x.substring(0, x.length() - 1);
            if (!x.endsWith("/v1")) x = x + "/v1";
            return x;
        }

        ChatCompletionResponse chat_completions_create(String model, int max_tokens, List<Map<String, Object>> messages) throws Exception {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", model);
            payload.put("max_tokens", max_tokens);
            payload.put("messages", messages);

            String body = Json.toJson(payload);

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/chat/completions"))
                    .header("Authorization", "Bearer " + apiKey)
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(120))
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (resp.statusCode() < 200 || resp.statusCode() >= 300) {
                throw new RuntimeException("HTTP " + resp.statusCode() + ": " + resp.body());
            }

            Object parsed = new JsonParser(resp.body()).parseValue();
            if (!(parsed instanceof Map<?, ?> root)) {
                return new ChatCompletionResponse("", null, resp.body());
            }

            @SuppressWarnings("unchecked")
            Map<String, Object> r = (Map<String, Object>) root;

            String text = extractAssistantText(r);

            Map<String, Object> usage = null;
            Object usageObj = r.get("usage");
            if (usageObj instanceof Map<?, ?> um) {
                usage = new LinkedHashMap<>();
                for (Map.Entry<?, ?> e : um.entrySet()) usage.put(String.valueOf(e.getKey()), e.getValue());
            }

            return new ChatCompletionResponse(text, usage, resp.body());
        }

        static String extractAssistantText(Map<String, Object> root) {
            Object choicesObj = root.get("choices");
            if (!(choicesObj instanceof List<?> choices) || choices.isEmpty()) return "";

            Object first = choices.get(0);
            if (!(first instanceof Map<?, ?> fm)) return "";

            Object msgObj = ((Map<?, ?>) fm).get("message");
            if (!(msgObj instanceof Map<?, ?> mm)) return "";

            Object content = ((Map<?, ?>) mm).get("content");
            if (content == null) return "";

            if (content instanceof String s) return s;

            // Sometimes proxies return content blocks
            if (content instanceof List<?> blocks) {
                StringBuilder sb = new StringBuilder();
                for (Object b : blocks) {
                    if (b instanceof Map<?, ?> bm) {
                        Object t = ((Map<?, ?>) bm).get("text");
                        if (t instanceof String ts) sb.append(ts);
                    }
                }
                return sb.toString();
            }

            return String.valueOf(content);
        }

        static class ChatCompletionResponse {
            final String text;
            final Map<String, Object> usage;
            final String raw_json;

            ChatCompletionResponse(String text, Map<String, Object> usage, String raw_json) {
                this.text = text;
                this.usage = usage;
                this.raw_json = raw_json;
            }
        }
    }

    // ---------------------------------------------------------------------------
    // Tiny JSON utils (serializer + parser) - no external dependencies
    // ---------------------------------------------------------------------------

    static class Json {
        static String toJson(Object value) {
            return toJson(value, 0);
        }

        static String toJson(Object value, int indent) {
            StringBuilder sb = new StringBuilder();
            writeJson(sb, value, indent, 0);
            return sb.toString();
        }

        private static void writeJson(StringBuilder sb, Object v, int indent, int depth) {
            if (v == null) {
                sb.append("null");
                return;
            }
            if (v instanceof String s) {
                sb.append('"').append(escape(s)).append('"');
                return;
            }
            if (v instanceof Number || v instanceof Boolean) {
                sb.append(String.valueOf(v));
                return;
            }
            if (v instanceof Map<?, ?> map) {
                sb.append("{");
                boolean first = true;
                for (Map.Entry<?, ?> e : map.entrySet()) {
                    if (!first) sb.append(",");
                    first = false;
                    if (indent > 0) sb.append("\n").append(" ".repeat((depth + 1) * indent));
                    sb.append('"').append(escape(String.valueOf(e.getKey()))).append('"').append(":");
                    if (indent > 0) sb.append(" ");
                    writeJson(sb, e.getValue(), indent, depth + 1);
                }
                if (indent > 0 && !map.isEmpty()) sb.append("\n").append(" ".repeat(depth * indent));
                sb.append("}");
                return;
            }
            if (v instanceof List<?> list) {
                sb.append("[");
                boolean first = true;
                for (Object o : list) {
                    if (!first) sb.append(",");
                    first = false;
                    if (indent > 0) sb.append("\n").append(" ".repeat((depth + 1) * indent));
                    writeJson(sb, o, indent, depth + 1);
                }
                if (indent > 0 && !list.isEmpty()) sb.append("\n").append(" ".repeat(depth * indent));
                sb.append("]");
                return;
            }
            // Fallback
            sb.append('"').append(escape(String.valueOf(v))).append('"');
        }

        private static String escape(String s) {
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '\\' -> out.append("\\\\");
                    case '"' -> out.append("\\\"");
                    case '\n' -> out.append("\\n");
                    case '\r' -> out.append("\\r");
                    case '\t' -> out.append("\\t");
                    default -> {
                        if (c < 0x20) out.append(String.format("\\u%04x", (int) c));
                        else out.append(c);
                    }
                }
            }
            return out.toString();
        }
    }

    static class JsonParser {
        private final String s;
        private int i = 0;

        JsonParser(String s) { this.s = s; }

        Object parseValue() {
            skipWs();
            if (i >= s.length()) return null;
            char c = s.charAt(i);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't' || c == 'f') return parseBoolean();
            if (c == 'n') return parseNull();
            return parseNumber();
        }

        private Map<String, Object> parseObject() {
            expect('{');
            Map<String, Object> obj = new LinkedHashMap<>();
            skipWs();
            if (peek('}')) { expect('}'); return obj; }
            while (true) {
                skipWs();
                String key = parseString();
                skipWs();
                expect(':');
                Object val = parseValue();
                obj.put(key, val);
                skipWs();
                if (peek('}')) { expect('}'); break; }
                expect(',');
            }
            return obj;
        }

        private List<Object> parseArray() {
            expect('[');
            List<Object> arr = new ArrayList<>();
            skipWs();
            if (peek(']')) { expect(']'); return arr; }
            while (true) {
                Object val = parseValue();
                arr.add(val);
                skipWs();
                if (peek(']')) { expect(']'); break; }
                expect(',');
            }
            return arr;
        }

        private String parseString() {
            expect('"');
            StringBuilder out = new StringBuilder();
            while (i < s.length()) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    if (i >= s.length()) break;
                    char e = s.charAt(i++);
                    switch (e) {
                        case '"' -> out.append('"');
                        case '\\' -> out.append('\\');
                        case '/' -> out.append('/');
                        case 'b' -> out.append('\b');
                        case 'f' -> out.append('\f');
                        case 'n' -> out.append('\n');
                        case 'r' -> out.append('\r');
                        case 't' -> out.append('\t');
                        case 'u' -> {
                            String hex = s.substring(i, Math.min(i + 4, s.length()));
                            i += 4;
                            try { out.append((char) Integer.parseInt(hex, 16)); } catch (Exception ex) { out.append('?'); }
                        }
                        default -> out.append(e);
                    }
                } else {
                    out.append(c);
                }
            }
            return out.toString();
        }

        private Boolean parseBoolean() {
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            return Boolean.FALSE;
        }

        private Object parseNull() {
            if (s.startsWith("null", i)) { i += 4; return null; }
            return null;
        }

        private Number parseNumber() {
            int start = i;
            if (peek('-')) i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            if (i < s.length() && s.charAt(i) == '.') {
                i++;
                while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            }
            if (i < s.length() && (s.charAt(i) == 'e' || s.charAt(i) == 'E')) {
                i++;
                if (peek('+') || peek('-')) i++;
                while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            }
            String num = s.substring(start, i);
            try {
                if (num.contains(".") || num.contains("e") || num.contains("E")) return Double.parseDouble(num);
                long lv = Long.parseLong(num);
                if (lv >= Integer.MIN_VALUE && lv <= Integer.MAX_VALUE) return (int) lv;
                return lv;
            } catch (Exception e) {
                return 0;
            }
        }

        private void skipWs() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\n' || c == '\r' || c == '\t') i++;
                else break;
            }
        }

        private boolean peek(char c) {
            return i < s.length() && s.charAt(i) == c;
        }

        private void expect(char c) {
            skipWs();
            if (i >= s.length() || s.charAt(i) != c) {
                throw new RuntimeException("JSON parse error: expected '" + c + "' at pos " + i);
            }
            i++;
        }
    }

    // ---------------------------------------------------------------------------
    // Small helpers
    // ---------------------------------------------------------------------------

    static Map<String, Object> mapOf(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int j = 0; j + 1 < kv.length; j += 2) {
            m.put(String.valueOf(kv[j]), kv[j + 1]);
        }
        return m;
    }

    static String fmtInt(int n) {
        return String.format("%,d", n);
    }

    static String fmtMs(double ms) {
        return String.format("%,.0f", ms);
    }
}

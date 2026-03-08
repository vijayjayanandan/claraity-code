# Prompt Caching for LLM Applications: A Complete Guide

## What Is the Problem?

Every time your application calls an LLM API, the provider processes your entire prompt from scratch. This includes the system prompt, the full conversation history, tool definitions, and the new user message. The provider reads every single token, computes attention across all of them, and charges you for the full input.

Now here's the thing that most people miss: in a multi-turn conversation, over 90 percent of that input is identical between calls. Your system prompt doesn't change. Your conversation history only grows by one or two messages each turn. The tool definitions are exactly the same. Yet you're paying full price to reprocess all of it, every single time.

In an agentic coding tool, where the LLM might make 10 to 20 calls per task, reading files, editing code, running tests, this means you're paying to reprocess the same system prompt 10 to 20 times. The same conversation history gets reprocessed over and over, each time with just a tiny bit more added at the end.

This is where prompt caching comes in. Prompt caching tells the provider: you've already seen this prefix, don't reprocess it, just start from where it changes. The provider stores the processed tokens in a cache, and on the next call, if the prefix matches, it serves the cached result instead of recomputing everything from scratch.

## How Much Does It Actually Save?

We ran a controlled experiment to measure this precisely. We took the same 5-turn conversation about building authentication for a Flask API, and ran it twice through Claude Sonnet via our FuelIX proxy. First without any caching, then with our caching strategy enabled.

The results were dramatic.

Without caching, the five turns consumed a total of 8,141 input tokens. Every token was processed at full price.

With caching enabled, the same conversation used roughly the same total input tokens, but 4,747 of those tokens, which is 58 percent of all input, were served from cache at a 90 percent discount.

By the third turn, 76 percent of the input was cached. By the fourth turn, 80 percent. By the fifth turn, 83 percent. The pattern is clear: as the conversation grows, the percentage of cached tokens keeps climbing because more and more of the context is "old" content that's already been seen.

The effective input cost reduction was 45.5 percent across just five turns.

Now extrapolate that to a real workload. If your team runs an AI coding agent that averages 15 turns per task and handles 100 tasks per day, the savings add up to roughly 100 dollars per month. With a larger system prompt, say 5,000 tokens instead of our demo's 1,500, and longer conversations of 20 or more turns, you'd see 50 to 70 percent cost reduction. That's thousands of dollars per month at enterprise scale.

And the cost savings aren't the only benefit. Cached tokens don't need to be reprocessed by the model, which means the time-to-first-token, the delay before the LLM starts responding, is significantly reduced for the cached portion of the prompt. In practice, this translates to snappier responses, especially as conversations get longer.

## The Two-Breakpoint Strategy

The core of our implementation is what we call the two-breakpoint strategy. You place exactly two cache markers in your message list. Not one, not five. Two. Here's why those two specific positions matter.

Breakpoint one goes on the system prompt. This is the first message in your messages array, typically with the role set to system. The system prompt contains your agent's instructions, tool definitions, behavioral guidelines, and all that boilerplate that is absolutely identical on every single API call throughout the entire session. It never changes. This is the lowest-hanging fruit for caching. You mark it once, and it stays cached for the entire session.

Breakpoint two goes on the second-to-last message in your conversation history. Here's the reasoning: the conversation history grows by one or two messages each turn, one new user message and one new assistant response. Everything before the latest exchange is identical to what you sent in the previous API call. By placing a breakpoint on the second-to-last message, you're caching the maximum possible prefix of the conversation. The only uncached content is the brand new user message at the end, which is typically a small fraction of the total.

Why not the last message? Because the last message is the new user input. It changes every turn, so caching it provides zero benefit.

Why not more breakpoints? Anthropic allows up to four, so why not use all of them? Because each breakpoint creates a separate cache entry with its own time-to-live. Scattered breakpoints fragment the cache and reduce hit rates. Two well-placed breakpoints capture the system prompt and the entire conversation prefix, which covers over 90 percent of the cacheable content. The remaining gains from additional breakpoints are marginal.

Here's how the caching plays out across a real conversation:

On the first call, there's no cached content. The system prompt is processed and written to cache. This incurs a 25 percent write surcharge on those tokens, so the first call is actually slightly more expensive than without caching.

On the second call, the system prompt is served from cache at a 90 percent discount. The conversation history from turn one is written to cache with the 25 percent surcharge. The new user message is processed at full price.

From the third call onwards, both the system prompt and the conversation prefix hit the cache. Only the newest messages are processed at full price. By turn five in our demo, 83 percent of all input tokens were cached.

The key insight is that caching is an investment. You pay a small premium on the first write (25 percent surcharge), but every subsequent read of that content costs only 10 percent of the original price. The break-even point is typically reached by the second or third turn.

## How the Cache Markers Work Technically

When you're calling Claude through an OpenAI-compatible proxy like FuelIX, you send your messages in the standard OpenAI format with roles like system, user, and assistant. To enable caching, you add a special field called cache_control to the content of the messages you want to cache.

For a regular text message, you convert the string content into Anthropic's content blocks format. Instead of the content being a plain string, it becomes a list containing a single object with the type set to text, the actual text content, and a cache_control field set to ephemeral. The word ephemeral tells Anthropic to cache this content with a time-to-live of 5 minutes, which resets every time the cache is hit.

The proxy translation layer, whether it's FuelIX or litellm, takes these markers and converts them into the correct format for Anthropic's native API.

There's an important subtlety with tool result messages. For messages with the role set to tool, you must add the cache_control as a sibling field on the message object itself, not inside the content. This is because the proxy's translation layer reads it from the top level when converting tool results to Anthropic's format. If you put it inside the content blocks, the translation breaks and caching silently fails.

## How Cache Breakpoints Work with Tool Calls

In a real agentic coding tool, the LLM doesn't just chat back and forth with the user. It also calls tools. It reads files, edits code, runs commands, searches the codebase. Each tool call adds two messages to the conversation: an assistant message that contains the tool call request, and a tool message that contains the result.

This creates an interesting situation for breakpoint placement. Let's walk through a concrete example.

Imagine the user says: read the auth module and check for SQL injection. The LLM decides it needs to read a file first, so it responds with a tool call to read_file, pointing at src/auth/login.py. That tool call gets executed, and the file contents come back as a tool result message. Now the user says: fix the vulnerability you found.

At this point, the messages array has five messages. Message zero is the system prompt. Message one is the user's original request. Message two is the assistant's tool call, and here's the key detail: this message has its content set to None because it only contains tool calls, no text. Message three is the tool result with the file contents. Message four is the user's follow-up asking for the fix.

Now let's apply the two-breakpoint strategy. Breakpoint one goes on message zero, the system prompt. That's straightforward, same as always. For breakpoint two, we walk backwards from the second-to-last message, which is message three, the tool result. Does it have content? Yes, it has the file contents. So breakpoint two lands on the tool result.

But notice what happened. The backward walk skipped right over message two, the assistant's tool call message, because its content was None. The marker function checks for None content and skips those messages. This is exactly the right behavior. The tool call message has no cacheable text content, so there's nothing to mark. The tool result, on the other hand, might contain hundreds of lines of source code. That's expensive to reprocess, so caching it makes perfect sense.

And here's where the tool message special handling comes in. When we add the cache marker to a regular user or assistant message, we convert its string content into a content blocks array with the cache_control field inside the block. But for tool messages, we cannot do that. The proxy's translation layer expects tool result content as a plain string, not as content blocks. If we convert it to blocks, the translation breaks silently. So instead, we add cache_control as a sibling field directly on the message object, right next to the role and content fields. The content stays as a plain string, untouched.

The beautiful thing is that the same cache marking function handles all of this automatically. It checks the role, and if it's a tool message, it takes the sibling field path. If it's any other role with string content, it converts to content blocks. If the content is None, it skips the message entirely. One function, three paths, all handled correctly.

## Practical Gotchas We Discovered

After implementing prompt caching in production, we ran into several issues that aren't obvious from the documentation.

First, never mutate your original message objects when adding cache markers. Always make copies first. In an agent that maintains a conversation history, the same message objects get reused across multiple API calls. If you add cache_control markers directly to the originals, you corrupt them. Subsequent calls might send messages with stale or duplicate markers. Always copy before modifying.

Second, if you're using streaming responses, you won't see cache token counts in the usage data unless you explicitly opt in by passing stream_options with include_usage set to true. Without this, the API still caches your tokens, but you have no way to verify it's working. You'd be flying blind.

Third, Anthropic requires a minimum token count for caching to activate. For Claude Sonnet, the minimum is 1,024 tokens. For Haiku, it's 2,048. If your system prompt is below this threshold, caching won't kick in at all. In our first demo attempt, we used an 800-token system prompt and got almost no cache hits. Once we increased it to 1,500 tokens, caching activated immediately.

Fourth, the cache time-to-live is 5 minutes, but it resets every time the cache is hit. In an active agent session where API calls happen every 10 to 30 seconds, the cache stays warm indefinitely. But if there's a long gap, say the user walks away for 10 minutes, the cache expires and the next call incurs a full cache write again. This is usually fine because the write surcharge is only 25 percent and subsequent calls immediately benefit from cache reads at the 90 percent discount.

## The Difference Between Anthropic and OpenAI Caching

An important distinction: OpenAI and Anthropic handle caching very differently.

For OpenAI models like GPT-4o and GPT-4.1, prompt caching is completely automatic. You don't need to add any markers. The server detects repeated prefixes and caches them transparently. The discount is 50 percent on cached tokens, with no write surcharge. You literally don't have to change any code. Just make sure you enable usage reporting in streaming mode so you can monitor the cache hit rate.

For Anthropic models like Claude Sonnet and Haiku, caching requires explicit markers. You must add the cache_control field to the specific messages you want cached. However, the discount is more aggressive: 90 percent on cache reads, compared to OpenAI's 50 percent. The trade-off is a 25 percent surcharge on the initial cache write.

If you use both providers, the recommended approach is to gate the marker injection on the model name. Check if the model contains the word claude. If it does, apply cache markers. If it's an OpenAI model, skip the markers entirely since caching is automatic.

## Our Real Demo Results

To make this tangible, here are the exact numbers from our controlled test. We ran a 5-turn conversation about building Flask authentication through Claude Sonnet via FuelIX.

In the without caching run, the input tokens per turn were: turn one 938 tokens, turn two 1,280 tokens, turn three 1,629 tokens, turn four 1,975 tokens, and turn five 2,321 tokens. Every token was processed at full price. Total input: 8,141 tokens.

In the with caching run, the input tokens were nearly identical, but the cache behavior was: turn one had no cache data as it was the first call. Turn two wrote 1,238 tokens to cache, which is the system prompt getting stored. Turn three had a cache hit of 1,238 tokens, which is 76 percent of its input. Turn four had a cache hit of 1,580 tokens, 80 percent of input. Turn five had a cache hit of 1,929 tokens, 83 percent of input.

The comparison: without caching the total cost was proportional to 8,141 token-units. With caching, the effective cost was proportional to just 4,440 token-units, a 45.5 percent reduction in input cost.

In dollar terms using Claude Sonnet pricing of 3 dollars per million input tokens: the five turns without caching cost about 2.4 cents. With caching, about 1.3 cents. That's a saving of 1.1 cents on just five turns.

Scale that to 15 turns per task, 100 tasks per day, and you're saving about 100 dollars per month. With longer prompts and more turns, which is typical for production agents, the savings are substantially higher.

## Actionable Takeaways for Your Team

Here's what you should do based on your situation.

If your team only uses OpenAI models, you already have caching for free. No code changes needed. Just make sure you're reporting usage with stream_options set to include_usage true, so you can monitor your cache hit rate. If it's below 50 percent, investigate whether your message ordering is stable.

If your team uses Claude models through FuelIX or any OpenAI-compatible proxy, implement the two-breakpoint strategy. It's roughly 50 lines of code. Mark the system prompt as breakpoint one, mark the second-to-last message as breakpoint two, and copy messages before modifying them. That's it. You'll see 40 to 50 percent input cost reduction immediately.

If your team uses both providers, add a model name check. If the model name contains claude, apply the markers. Otherwise, skip them.

Regardless of provider, always add a cache tracker to your application. Log the cache hit rate, the number of tokens served from cache, and the effective cost reduction at the end of each session. If your hit rate is below 60 percent, your breakpoint placement needs work.

Finally, remember that the return on investment is massive for agentic applications. A coding agent that makes 15 LLM calls per task with a 5,000-token system prompt saves roughly 400,000 tokens of reprocessing per task. At Anthropic's Sonnet pricing, that's about 1 dollar and 20 cents saved per task. Multiply by the number of tasks your team runs daily, and the annual savings can easily reach tens of thousands of dollars.

The implementation takes an afternoon. The savings last forever.

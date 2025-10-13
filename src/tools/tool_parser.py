"""
Tool call parser for extracting and validating tool calls from LLM responses.
Supports JSON format optimized for Qwen3-Coder 30B.
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ToolCall:
    """Represents a single tool call."""
    tool: str
    arguments: Dict[str, Any]

    def __repr__(self) -> str:
        return f"ToolCall(tool='{self.tool}', arguments={self.arguments})"


@dataclass
class ParsedResponse:
    """Result of parsing an LLM response for tool calls."""
    has_tool_calls: bool
    tool_calls: List[ToolCall]
    thoughts: Optional[str] = None
    raw_text: Optional[str] = None
    error: Optional[str] = None

    def __repr__(self) -> str:
        if self.has_tool_calls:
            return f"ParsedResponse(tools={len(self.tool_calls)}, thoughts='{self.thoughts[:50]}...')"
        return f"ParsedResponse(no_tools, text='{self.raw_text[:50] if self.raw_text else 'None'}...')"


class ToolCallParser:
    """
    Parser for extracting tool calls from LLM responses.

    Supports JSON format with the structure:
    {
      "thoughts": "explanation",
      "tool_calls": [
        {"tool": "tool_name", "arguments": {...}}
      ]
    }
    """

    def __init__(self):
        """Initialize the tool call parser."""
        # Pattern to extract JSON from markdown code blocks
        self.json_pattern = re.compile(r'```json\s*\n(.*?)\n```', re.DOTALL)

        # Pattern to find standalone JSON objects
        self.json_object_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL)

    def parse(self, llm_response: str) -> ParsedResponse:
        """
        Parse an LLM response to extract tool calls.

        Args:
            llm_response: The raw response from the LLM

        Returns:
            ParsedResponse object containing tool calls or error information
        """
        if not llm_response or not llm_response.strip():
            return ParsedResponse(
                has_tool_calls=False,
                tool_calls=[],
                error="Empty response"
            )

        # Try to extract JSON from the response
        json_text = self._extract_json(llm_response)

        if not json_text:
            # No JSON found - this is a regular text response
            return ParsedResponse(
                has_tool_calls=False,
                tool_calls=[],
                raw_text=llm_response
            )

        # Try to parse the JSON
        try:
            data = json.loads(json_text)
            return self._parse_json_response(data, llm_response)
        except json.JSONDecodeError as e:
            return ParsedResponse(
                has_tool_calls=False,
                tool_calls=[],
                error=f"Invalid JSON: {str(e)}",
                raw_text=llm_response
            )

    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extract JSON from text, trying multiple strategies.

        Args:
            text: Text that may contain JSON

        Returns:
            Extracted JSON string or None
        """
        # Strategy 1: Look for ```json code blocks
        matches = self.json_pattern.findall(text)
        if matches:
            return matches[0]  # Return first match

        # Strategy 2: Look for raw JSON objects
        matches = self.json_object_pattern.findall(text)
        if matches:
            # Try each match to see if it's valid JSON with our expected structure
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, dict) and ("tool_calls" in data or "thoughts" in data):
                        return match
                except:
                    continue

        # Strategy 3: Try to find JSON between { and } manually
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end > start:
                potential_json = text[start:end]
                # Validate it's parseable
                json.loads(potential_json)
                return potential_json
        except:
            pass

        return None

    def _parse_json_response(self, data: Dict[str, Any], original_text: str) -> ParsedResponse:
        """
        Parse a JSON response object into a ParsedResponse.

        Args:
            data: Parsed JSON dictionary
            original_text: Original response text

        Returns:
            ParsedResponse object
        """
        # Extract thoughts
        thoughts = data.get("thoughts", "")

        # Extract tool calls
        tool_calls_data = data.get("tool_calls", [])

        if not tool_calls_data or not isinstance(tool_calls_data, list):
            # No tool calls in response
            return ParsedResponse(
                has_tool_calls=False,
                tool_calls=[],
                thoughts=thoughts,
                raw_text=original_text
            )

        # Parse each tool call
        tool_calls = []
        errors = []

        for i, call_data in enumerate(tool_calls_data):
            try:
                tool_call = self._parse_tool_call(call_data, i)
                tool_calls.append(tool_call)
            except ValueError as e:
                errors.append(str(e))

        if errors:
            error_msg = "; ".join(errors)
            return ParsedResponse(
                has_tool_calls=False,
                tool_calls=[],
                error=f"Tool call parsing errors: {error_msg}",
                raw_text=original_text
            )

        return ParsedResponse(
            has_tool_calls=True,
            tool_calls=tool_calls,
            thoughts=thoughts
        )

    def _parse_tool_call(self, call_data: Dict[str, Any], index: int) -> ToolCall:
        """
        Parse a single tool call from JSON data.

        Args:
            call_data: Dictionary containing tool call data
            index: Index of this tool call (for error messages)

        Returns:
            ToolCall object

        Raises:
            ValueError: If tool call is invalid
        """
        if not isinstance(call_data, dict):
            raise ValueError(f"Tool call {index} is not a dictionary")

        tool_name = call_data.get("tool")
        if not tool_name:
            raise ValueError(f"Tool call {index} missing 'tool' field")

        if not isinstance(tool_name, str):
            raise ValueError(f"Tool call {index} 'tool' field must be a string")

        arguments = call_data.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError(f"Tool call {index} 'arguments' field must be a dictionary")

        return ToolCall(tool=tool_name, arguments=arguments)

    def validate_tool_call(self, tool_call: ToolCall, available_tools: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Validate that a tool call is valid and the tool exists.

        Args:
            tool_call: The ToolCall to validate
            available_tools: List of available tool names

        Returns:
            Tuple of (is_valid, error_message)
        """
        if tool_call.tool not in available_tools:
            return False, f"Unknown tool: '{tool_call.tool}'. Available tools: {', '.join(available_tools)}"

        return True, None


def parse_tool_calls(llm_response: str) -> ParsedResponse:
    """
    Convenience function to parse tool calls from an LLM response.

    Args:
        llm_response: The LLM's response text

    Returns:
        ParsedResponse object
    """
    parser = ToolCallParser()
    return parser.parse(llm_response)


# Example usage and testing
if __name__ == "__main__":
    # Test cases
    test_responses = [
        # Test 1: Valid tool call
        '''```json
{
  "thoughts": "I need to read the file first",
  "tool_calls": [
    {
      "tool": "read_file",
      "arguments": {"file_path": "agent.py"}
    }
  ]
}
```''',

        # Test 2: Multiple tool calls
        '''```json
{
  "thoughts": "I'll search first, then read the results",
  "tool_calls": [
    {"tool": "search_code", "arguments": {"query": "MemoryManager"}},
    {"tool": "read_file", "arguments": {"file_path": "src/core/agent.py"}}
  ]
}
```''',

        # Test 3: No tool calls (regular response)
        "Here's what the code does: It implements a coding agent that...",

        # Test 4: Invalid JSON
        "```json\n{invalid json}\n```",
    ]

    parser = ToolCallParser()

    for i, response in enumerate(test_responses, 1):
        print(f"\n{'='*80}")
        print(f"Test {i}:")
        print(f"{'='*80}")
        print(f"Input: {response[:100]}...")

        result = parser.parse(response)
        print(f"\nResult: {result}")

        if result.has_tool_calls:
            print(f"Tool calls: {len(result.tool_calls)}")
            for j, call in enumerate(result.tool_calls, 1):
                print(f"  {j}. {call.tool}({call.arguments})")
        elif result.error:
            print(f"Error: {result.error}")
        else:
            print("No tool calls - regular text response")

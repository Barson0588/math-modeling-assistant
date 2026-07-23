import time
import os
from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError

MAX_RETRIES = 3
RETRY_DELAY = 2.0
DEFAULT_BASE_URL = "https://api.deepseek.com"


def _make_client(api_key):
    return OpenAI(
        api_key=api_key,
        base_url=DEFAULT_BASE_URL,
        timeout=90.0,
    )


def generate_response(system_prompt, user_prompt, max_tokens=8000, api_key=None):
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DeepSeek API Key is not configured")
    client = _make_client(key)
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
        except APIError as e:
            raise RuntimeError(f"DeepSeek API error: {e}") from e

    raise RuntimeError(f"请求失败（已重试 {MAX_RETRIES} 次）: {last_error}")


def generate_stream(system_prompt, user_prompt, max_tokens=8000, api_key=None):
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DeepSeek API Key is not configured")
    client = _make_client(key)
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
        except APIError as e:
            raise RuntimeError(f"DeepSeek API error: {e}") from e

    raise RuntimeError(f"请求失败（已重试 {MAX_RETRIES} 次）: {last_error}")


# ── Function Calling (Tools) Support ──────────────────────────────────

def generate_with_tools(
    system_prompt,
    user_prompt,
    tools,
    max_tokens=4000,
    api_key=None,
    temperature=0.3,
):
    """Send a request to DeepSeek with function/tool definitions.

    DeepSeek's API supports OpenAI-compatible tool calling. This function
    returns the full message response, which may include tool_calls.

    Args:
        system_prompt: System message content.
        user_prompt: User message content.
        tools: List of tool definitions in OpenAI format.
        max_tokens: Max completion tokens.
        api_key: DeepSeek API key.
        temperature: Sampling temperature.

    Returns:
        The full ChatCompletionMessage with optional .tool_calls attribute.
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DeepSeek API Key is not configured")

    client = _make_client(key)
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=tools,
                tool_choice="auto",
            )
            return response.choices[0].message
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
        except APIError as e:
            raise RuntimeError(f"DeepSeek API error: {e}") from e

    raise RuntimeError(f"请求失败（已重试 {MAX_RETRIES} 次）: {last_error}")


def run_tool_loop(system_prompt, user_prompt, tools, tool_executors, max_turns=5, api_key=None):
    """Run a multi-turn tool-use conversation with DeepSeek.

    The LLM can call tools, receive results, and continue reasoning.

    Args:
        system_prompt: System message.
        user_prompt: Initial user message.
        tools: Tool definitions in OpenAI format.
        tool_executors: dict mapping tool name → callable(**kwargs) → str result.
        max_turns: Maximum number of tool-call round-trips.
        api_key: DeepSeek API key.

    Returns:
        The final assistant message (as plain text), after all tool calls
        have been resolved.
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DeepSeek API Key is not configured")

    client = _make_client(key)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for turn in range(max_turns):
        last_error = None
        message = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    max_tokens=4000,
                    temperature=0.3,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                message = response.choices[0].message
                break
            except (APIConnectionError, APITimeoutError, RateLimitError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY * (2 ** attempt)
                    time.sleep(delay)
            except APIError as e:
                raise RuntimeError(f"DeepSeek API error: {e}") from e

        if message is None:
            raise RuntimeError(f"请求失败（已重试 {MAX_RETRIES} 次）: {last_error}")

        # If the model wants to call tools
        if message.tool_calls:
            # Add assistant message (with tool_calls) to history
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            # Execute each tool call and add results
            for tc in message.tool_calls:
                fn_name = tc.function.name
                fn_args = {}
                try:
                    import json
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}

                executor = tool_executors.get(fn_name)
                if executor:
                    try:
                        result = executor(**fn_args)
                    except Exception as e:
                        result = f"Tool error: {e}"
                else:
                    result = f"Unknown tool: {fn_name}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

            # Continue loop — model can make more tool calls
            continue

        # No tool calls — final response
        return message.content or ""

    return "Max tool-call turns exceeded."

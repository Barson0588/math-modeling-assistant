import time
from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError
import config

_client = OpenAI(
    api_key=config.DEEPSEEK_API_KEY,
    base_url=config.DEEPSEEK_BASE_URL,
    timeout=90.0,
)

MAX_RETRIES = 3
RETRY_DELAY = 2.0


def generate_response(system_prompt, user_prompt, max_tokens=8000):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = _client.chat.completions.create(
                model=config.MODEL,
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


def generate_stream(system_prompt, user_prompt, max_tokens=8000):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            stream = _client.chat.completions.create(
                model=config.MODEL,
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

import anthropic
import config


def get_client():
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def generate_response(system_prompt, user_prompt, max_tokens=8000):
    client = get_client()
    message = client.messages.create(
        model=config.MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text

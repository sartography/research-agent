"""One function: send a prompt to a model, get text back.

Kept provider-agnostic in shape so a second provider can be added here later
(Backlog item 17) without touching any caller.
"""

import anthropic

import config

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def ask(model, prompt, max_tokens=8000):
    """Send one prompt, return the reply as plain text.

    `max_tokens` bounds thinking and reply together on the models that think,
    so give the synthesize and copy edit calls plenty of room — a tight budget
    truncates the report rather than shortening it.

    Whether a model thinks at all depends on which one it is. The 4.6 models
    do not unless asked — they would need `thinking={"type": "adaptive"}`
    passed here — while the 5 models think by default. Nothing sets it today,
    so synthesize and copy edit currently run without thinking.
    """
    response = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")

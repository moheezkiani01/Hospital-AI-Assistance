"""Role-safe, bounded conversation context for the LLM.

Past messages are evidence about a dialogue, never fresh instructions. Every user
or assistant message is encoded as one JSON string, so embedded newlines and
speaker labels cannot create an additional turn in the prompt.
"""

import json
from typing import Iterable, Optional, Tuple


def _pair(user: str, assistant: str) -> str:
    return (
        "User: " + json.dumps(user, ensure_ascii=False) + "\n"
        "Assistant: " + json.dumps(assistant, ensure_ascii=False)
    )


def _last_pair_that_fits(user: str, assistant: str, max_chars: int) -> str:
    """Prefer the newest user request, then fill remaining room with its reply."""
    max_chars = max(60, int(max_chars))
    if len(_pair(user, assistant)) <= max_chars:
        return _pair(user, assistant)

    # Trim message *contents* before JSON encoding, never an encoded string.
    # Reserve a small part of the budget for the assistant turn when possible.
    user_limit = min(len(user), max(20, (max_chars - 27) * 2 // 3))
    user_part = user[-user_limit:]
    assistant_part = assistant
    rendered = _pair(user_part, assistant_part)
    while len(rendered) > max_chars and assistant_part:
        assistant_part = assistant_part[max(1, len(rendered) - max_chars):]
        rendered = _pair(user_part, assistant_part)
    while len(rendered) > max_chars and user_part:
        user_part = user_part[max(1, len(rendered) - max_chars):]
        rendered = _pair(user_part, assistant_part)
    return rendered if len(rendered) <= max_chars else _pair("", "")


def render_history(pairs: Iterable[Tuple[str, str]], max_chars: int) -> str:
    """Return as many newest complete user/assistant pairs as fit.

    Only the latest pair may be shortened. Both roles remain present, with
    valid JSON strings; no message from a different session is loaded here.
    """
    budget = max(60, int(max_chars))
    picked = []
    used = 0
    for user, assistant in reversed(list(pairs)):
        item = _pair(str(user or "").strip(), str(assistant or "").strip())
        remaining = budget - used - (1 if picked else 0)
        if remaining < 60:
            break
        if len(item) > remaining:
            if picked:
                break
            item = _last_pair_that_fits(str(user or "").strip(), str(assistant or "").strip(), remaining)
        picked.append(item)
        used += len(item) + (1 if len(picked) > 1 else 0)
    return "\n".join(reversed(picked))


def clip_history(context: Optional[str], max_chars: int) -> str:
    """Bound serialized history again for smaller routing/reply prompts.

    Non-serialized legacy/synthetic text is treated as one untrusted payload,
    rather than trusted prompt text or additional speaker turns.
    """
    source = str(context or "").strip()
    if not source:
        return ""
    lines = source.splitlines()
    if len(lines) % 2 == 0:
        pairs = []
        try:
            for i in range(0, len(lines), 2):
                if not (lines[i].startswith("User: ") and lines[i + 1].startswith("Assistant: ")):
                    raise ValueError("Unexpected message format")
                user = json.loads(lines[i][6:])
                assistant = json.loads(lines[i + 1][11:])
                if not isinstance(user, str) or not isinstance(assistant, str):
                    raise ValueError("Unexpected message type")
                pairs.append((user, assistant))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        else:
            return render_history(pairs, max_chars)
    # Older unstructured histories: escape the whole blob as data, not a role.
    budget = max(60, int(max_chars))
    safe_text = source[-max(0, budget - 30):]
    rendered = "Previous chat excerpt: " + json.dumps(safe_text, ensure_ascii=False)
    while len(rendered) > budget and safe_text:
        safe_text = safe_text[max(1, len(rendered) - budget):]
        rendered = "Previous chat excerpt: " + json.dumps(safe_text, ensure_ascii=False)
    return rendered

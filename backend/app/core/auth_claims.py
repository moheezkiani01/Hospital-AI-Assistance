"""Safe parsing of token claims without depending on JWT implementation details."""


def get_user_id_from_claim(subject: object) -> int | None:
    """Return a valid positive integer subject, or None for malformed tokens."""
    if isinstance(subject, bool):
        return None
    if not isinstance(subject, (str, int)):
        return None
    if isinstance(subject, str) and not subject.isascii():
        return None
    try:
        user_id = int(subject)
    except (TypeError, ValueError, OverflowError):
        return None
    return user_id if user_id > 0 else None

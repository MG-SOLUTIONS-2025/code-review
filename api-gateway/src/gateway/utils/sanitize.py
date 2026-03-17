import re

_MAX_LENGTH = 50_000

# Patterns commonly used in prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"<\|.*?\|>", re.DOTALL),           # Token-style injections
    re.compile(r"\[INST\].*?\[/INST\]", re.DOTALL), # Instruction injections
    re.compile(r"<<SYS>>.*?<</SYS>>", re.DOTALL),  # System prompt injections
]


def sanitize_prompt_input(text: str) -> str:
    """Strip injection patterns, limit length, and clean input text."""
    if not isinstance(text, str):
        return ""

    # Truncate to max length
    text = text[:_MAX_LENGTH]

    # Strip known injection patterns
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("", text)

    # Remove null bytes
    text = text.replace("\x00", "")

    return text.strip()

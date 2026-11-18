from datetime import UTC, datetime
from secrets import token_hex


def generate_reference_number() -> str:
    """64 random bits; the creation service retries reference uniqueness violations."""
    return f"CMK-{datetime.now(UTC).year}-{token_hex(8).upper()}"

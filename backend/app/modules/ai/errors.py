"""Never reflect provider exception messages, request bodies, or credentials."""

from fastapi import HTTPException


class AIUnavailable(HTTPException):
    def __init__(self, detail: str = "AI service unavailable. Manual workflows remain available."):
        super().__init__(503, detail)


class InvalidAIOutput(HTTPException):
    def __init__(self):
        super().__init__(502, "AI returned an invalid structured result. Please try again later.")


class AIQuotaExceeded(HTTPException):
    def __init__(self):
        super().__init__(
            429, "AI request limit reached. Please try again later.", headers={"Retry-After": "60"}
        )

class AuthenticationError(Exception):
    def __init__(
        self, detail: str = "Invalid or expired authentication.", *, clear_cookie: bool = False
    ) -> None:
        self.detail = detail
        self.clear_cookie = clear_cookie
        super().__init__(detail)

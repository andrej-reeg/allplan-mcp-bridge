"""Agent-side error types."""


class AllplanApiError(Exception):
    """Wraps any exception raised by the Allplan API.

    The original message is preserved so it surfaces in IPC error responses.
    """

    def __init__(self, message: str, original: BaseException | None = None) -> None:
        super().__init__(message)
        self.original = original

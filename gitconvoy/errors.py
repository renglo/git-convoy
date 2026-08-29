class GitConvoyError(Exception):
    """User-facing failure. CLI prints the message and exits 1."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

class NoteSmithError(Exception):
    """Base exception for the application."""

    def __init__(self, detail: str, status_code: int = 500):
        self.detail = detail
        self.status_code = status_code


class NotFoundError(NoteSmithError):
    def __init__(self, resource: str, resource_id: int | str):
        super().__init__(
            detail=f"{resource} with id '{resource_id}' not found",
            status_code=404,
        )


class ConflictError(NoteSmithError):
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=409)

# Chapter 8: Dependency Injection, Middleware, and Error Handling

This chapter goes deeper into three FastAPI systems you have already been using: dependency injection, middleware, and error handling. Understanding these well is what separates a working prototype from production-grade code.

## 8.1 Dependency Injection in Depth

You have already used dependency injection for database sessions (`get_db`) and authentication (`CurrentUser`). This section covers the mechanics and additional patterns.

**How it works:** When FastAPI receives a request, it inspects the endpoint function's parameters. For each parameter that uses `Depends(some_function)`, FastAPI calls that function (resolving its own dependencies recursively), and passes the result to your endpoint.

Dependencies can depend on other dependencies, forming a chain:

```
Request
  → OAuth2PasswordBearer (extracts token from header)
    → get_current_user (decodes token, loads user from DB)
      → get_current_active_user (checks is_active)
        → Your endpoint function
```

FastAPI resolves this entire chain for each request. If any dependency raises an `HTTPException`, the chain stops and FastAPI returns the error response.

**Dependencies are cached per request.** If two parameters depend on `get_db`, FastAPI calls `get_db` once and shares the result. This is why all database operations within a single request use the same session.

### Generator Dependencies (yield)

You wrote a generator dependency in Chapter 4. Here is how it works under the hood:

```python
# Already in src/notesmith/database.py — do not add this again.
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session       # Endpoint runs here
            await session.commit()   # After successful endpoint
        except Exception:
            await session.rollback()  # After failed endpoint
            raise
```

The code before `yield` runs during setup. The code after `yield` runs during teardown. This is how we get automatic commit/rollback without any boilerplate in our endpoints.

### Class-Based Dependencies

For dependencies with configuration, use a callable class. The following example demonstrates the pattern — we will not add this to NoteSmith, but it is a technique worth knowing for your own projects:

```python
# Pattern demonstration — not project code.
class Pagination:
    def __init__(self, max_limit: int = 100):
        self.max_limit = max_limit

    def __call__(self, skip: int = 0, limit: int = 20) -> dict:
        return {"skip": max(0, skip), "limit": min(limit, self.max_limit)}


paginate = Pagination(max_limit=100)


@router.get("/notes")
async def list_notes(
    db: DB,
    current_user: CurrentUser,
    pagination: dict = Depends(paginate),
):
    notes = await service.get_notes_by_owner(
        db, owner_id=current_user.id,
        skip=pagination["skip"], limit=pagination["limit"],
    )
    return notes
```

`Pagination(max_limit=100)` creates an instance. When FastAPI calls `paginate(skip=0, limit=20)`, it invokes `__call__`, which validates and clamps the values. This pattern is useful for reusable validation logic that multiple endpoints share.

## 8.2 Middleware

Middleware runs on **every request**, before and after your endpoint code. It wraps the entire request-response cycle.

### CORS Middleware

Cross-Origin Resource Sharing (CORS) controls which frontend domains can make requests to your API. Without it, browsers block requests from any origin other than your API's own domain.

We will add CORS to `main.py` shortly, after we also create the custom middleware and exception handler below. Section 8.4 shows the complete file.

`allow_origins` is a list of domains that are allowed to make requests. In production, set this to your actual frontend URLs. During development, `localhost` with common dev server ports is sufficient. Avoid `["*"]` for origins in production — it allows any website to call your API.

### Custom Middleware

You can write middleware for cross-cutting concerns like request logging or timing. Create `src/notesmith/middleware.py`:

```python
# src/notesmith/middleware.py
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("notesmith")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
```

This middleware logs the HTTP method, path, status code, and response time for every request. It is added to `main.py` in Section 8.4.

Middleware is applied in **reverse order** — the last middleware added is the outermost (runs first). We will add CORS middleware after `RequestLoggingMiddleware` so that CORS runs first and handles preflight requests immediately.

## 8.3 Error Handling

### HTTPException (Review)

For expected errors (resource not found, invalid input, unauthorized), raise `HTTPException`:

```python
# You have already used this pattern — this is a recap.
raise HTTPException(status_code=404, detail="Note not found")
```

### Custom Exception Handlers

For application-specific error types, define custom exceptions and register handlers. Create `src/notesmith/exceptions.py`:

```python
# src/notesmith/exceptions.py


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
```

The exception handler for `NoteSmithError` is registered in `main.py` in Section 8.4.

Now your service layer can raise `NotFoundError("Note", note_id)` instead of constructing `HTTPException` objects. This keeps HTTP-specific details out of the service layer.

### Validation Error Responses

Pydantic validation errors return 422 with a detailed error body by default:

```json
{
    "detail": [
        {
            "type": "missing",
            "loc": ["body", "title"],
            "msg": "Field required",
            "input": {}
        }
    ]
}
```

This format is helpful for frontend developers — it tells them exactly which field failed and why. You generally do not need to customize it.

### Unhandled Exception Safety

In production, unhandled exceptions should return a generic 500 error without leaking stack traces or internal details. FastAPI does this by default — it returns `{"detail": "Internal Server Error"}` for any unhandled exception. The full traceback is printed to the server log, not sent to the client.

## 8.4 Structuring main.py for Production

Now update `src/notesmith/main.py` to incorporate everything from this chapter: CORS middleware, request logging middleware, and the custom exception handler.

```python
# src/notesmith/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from notesmith.auth.router import router as auth_router
from notesmith.database import engine
from notesmith.exceptions import NoteSmithError
from notesmith.middleware import RequestLoggingMiddleware
from notesmith.notes.router import router as notes_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify database connection
    async with engine.begin() as conn:
        await conn.run_sync(lambda conn: None)
    yield
    # Shutdown: dispose of the connection pool
    await engine.dispose()


app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
    lifespan=lifespan,
)

# Middleware (applied in reverse order — last added runs first)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")


# Exception handlers
@app.exception_handler(NoteSmithError)
async def notesmith_error_handler(request: Request, exc: NoteSmithError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

Walk through what changed from the previous version of `main.py` (Chapter 6):

- **`RequestLoggingMiddleware`** is imported from the new `middleware.py` module and added before `CORSMiddleware`. Because middleware runs in reverse registration order, CORS runs first (outermost), then logging runs around your endpoint code.
- **`CORSMiddleware`** allows requests from common development frontend ports. Adjust `allow_origins` when you deploy.
- **`notesmith_error_handler`** catches any `NoteSmithError` (or its subclasses `NotFoundError`, `ConflictError`) raised anywhere in the application and converts it to a JSON response with the appropriate status code.

The AI router will be added in the next chapter.

---

Proceed to [Chapter 9: Anthropic SDK Integration](./09-anthropic-sdk.md).

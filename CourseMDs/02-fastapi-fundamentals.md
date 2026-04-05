# Chapter 2: FastAPI Fundamentals

This chapter covers how FastAPI handles requests: defining endpoints, extracting data from URLs, query strings, and request bodies, returning responses with proper status codes, and running the application with Uvicorn.

## 2.1 Your First Endpoint

Open `src/notesmith/main.py` and write:

```python
# src/notesmith/main.py
from fastapi import FastAPI

app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

The `app` object is the core of your application. Every route, middleware, and configuration attaches to it. The keyword arguments (`title`, `version`, `description`) populate the auto-generated OpenAPI documentation.

`@app.get("/health")` registers the function `health_check` as the handler for `GET /health`. The function is `async def` because FastAPI runs on an async event loop. When the handler has no I/O to await, `async def` still works fine — it just returns immediately.

## 2.2 Running with Uvicorn

Start the development server:

```bash
uvicorn src.notesmith.main:app --reload --port 8000
```

Breaking this down:

- `src.notesmith.main:app` — Python dotted path to the module (`src/notesmith/main.py`), then a colon, then the name of the `FastAPI` instance (`app`).
- `--reload` — Watches for file changes and restarts automatically. Development only.
- `--port 8000` — Listen on port 8000 (the default, but explicit is better).

You should see output like:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using WatchFiles
```

Open your browser to `http://127.0.0.1:8000/health`. You should see:

```json
{"status": "ok"}
```

Now visit `http://127.0.0.1:8000/docs`. This is FastAPI's built-in **Swagger UI** — an interactive API explorer generated from your route definitions. Every endpoint you create will appear here automatically.

There is also a **ReDoc** interface at `http://127.0.0.1:8000/redoc`, which presents the same information in a different layout.

Leave the server running for the rest of this chapter. Uvicorn will reload automatically as you save changes.

## 2.3 Path Parameters

Path parameters extract values from the URL itself.

Add this to `main.py` below your health check endpoint:

```python
@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
```

The `{item_id}` in the path becomes a function parameter. FastAPI uses the **type annotation** (`int`) to:

1. **Validate** — If someone requests `/items/abc`, FastAPI returns a 422 error automatically. It does not call your function.
2. **Convert** — The raw URL segment is a string. FastAPI converts it to `int` before calling your function.
3. **Document** — The Swagger UI shows that `item_id` is an integer parameter.

Test it:

- `GET /items/42` → `{"item_id": 42}`
- `GET /items/abc` → `422 Unprocessable Entity` with a validation error body

## 2.4 Query Parameters

Any function parameter that is not part of the path is treated as a query parameter.

```python
@app.get("/items")
async def list_items(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}
```

- `GET /items` → `{"skip": 0, "limit": 10}` (defaults apply)
- `GET /items?skip=5&limit=20` → `{"skip": 5, "limit": 20}`
- `GET /items?limit=abc` → `422` (validation error)

Default values make the parameter optional. Without a default, it becomes required:

```python
@app.get("/search")
async def search(q: str):
    return {"query": q}
```

- `GET /search` → `422` (missing required parameter `q`)
- `GET /search?q=hello` → `{"query": "hello"}`

To make a parameter explicitly optional without a default value, annotate it with `None`:

```python
@app.get("/search")
async def search(q: str | None = None):
    if q is None:
        return {"results": []}
    return {"query": q}
```

## 2.5 Request Bodies

For `POST`, `PUT`, and `PATCH` requests, you typically send data in the request body as JSON. FastAPI uses **Pydantic models** to define the shape of that data.

```python
from pydantic import BaseModel


class ItemCreate(BaseModel):
    name: str
    price: float
    description: str | None = None


@app.post("/items")
async def create_item(item: ItemCreate):
    return {"name": item.name, "price": item.price, "description": item.description}
```

When FastAPI sees a function parameter typed as a Pydantic model, it:

1. Reads the JSON request body
2. Validates it against the model's fields and types
3. Returns a 422 error if validation fails
4. Passes the validated model instance to your function

A valid request:

```bash
curl -X POST http://127.0.0.1:8000/items \
  -H "Content-Type: application/json" \
  -d '{"name": "Widget", "price": 9.99}'
```

Response: `{"name": "Widget", "price": 9.99, "description": null}`

An invalid request (missing `name`):

```bash
curl -X POST http://127.0.0.1:8000/items \
  -H "Content-Type: application/json" \
  -d '{"price": 9.99}'
```

Response: `422` with details about the missing field.

You can combine path parameters, query parameters, and request bodies in a single endpoint. FastAPI resolves each based on where it appears:

```python
@app.put("/items/{item_id}")
async def update_item(item_id: int, item: ItemCreate, notify: bool = False):
    return {
        "item_id": item_id,      # From path
        "item": item.model_dump(), # From request body
        "notify": notify,          # From query string
    }
```

## 2.6 Response Status Codes

By default, FastAPI returns `200 OK` for all successful responses. Override this with the `status_code` parameter:

```python
from fastapi import status


@app.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate):
    return {"name": item.name, "price": item.price}
```

The `status` module provides named constants (`HTTP_201_CREATED`, `HTTP_204_NO_CONTENT`, etc.) so you do not need to memorize numeric codes.

For endpoints that return no body:

```python
@app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int):
    # ... delete logic ...
    return None
```

## 2.7 Response Models

You can declare the shape of the response body using the `response_model` parameter. This serves two purposes: it filters out fields you do not want to expose, and it documents the response in the OpenAPI schema.

```python
class ItemResponse(BaseModel):
    name: str
    price: float


@app.post("/items", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate):
    # Even if your internal data has extra fields (like 'description'),
    # the response will only include 'name' and 'price'.
    return item
```

This is essential for security — it prevents accidentally leaking internal fields like password hashes or internal IDs.

## 2.8 HTTPException for Error Responses

When something goes wrong, raise an `HTTPException`:

```python
from fastapi import HTTPException

# In-memory storage for demonstration
fake_db: dict[int, dict] = {}


@app.get("/items/{item_id}")
async def read_item(item_id: int):
    if item_id not in fake_db:
        raise HTTPException(status_code=404, detail="Item not found")
    return fake_db[item_id]
```

`HTTPException` stops execution immediately and returns the specified status code and detail message. The response body will be:

```json
{"detail": "Item not found"}
```

## 2.9 APIRouter for Modular Code

Putting all routes in `main.py` does not scale. **APIRouter** lets you define routes in separate files and then attach them to the main app.

This is the pattern we will use for the rest of the tutorial. Here is a preview — open `src/notesmith/notes/router.py`:

```python
# src/notesmith/notes/router.py
from fastapi import APIRouter

router = APIRouter(
    prefix="/notes",
    tags=["notes"],
)


@router.get("/")
async def list_notes():
    return {"notes": []}


@router.get("/{note_id}")
async def get_note(note_id: int):
    return {"note_id": note_id}
```

Then in `main.py`, include the router:

```python
# src/notesmith/main.py
from fastapi import FastAPI
from notesmith.notes.router import router as notes_router

app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
)

app.include_router(notes_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

Now `GET /api/v1/notes/` hits `list_notes`, and `GET /api/v1/notes/42` hits `get_note`. The prefixes stack: the app-level `/api/v1` plus the router-level `/notes` plus the route-level `/` or `/{note_id}`.

The `tags=["notes"]` groups these endpoints together in the Swagger UI for readability.

## 2.10 Async vs Sync Endpoints

FastAPI handles both `async def` and plain `def` endpoints, but they execute differently:

- **`async def`** — Runs directly on the main async event loop. Use this when your function calls `await` on async I/O (database queries, HTTP requests, etc.). **Never perform blocking operations** (synchronous file I/O, `time.sleep`, CPU-bound computation) inside `async def` — it blocks the entire event loop.

- **`def`** (plain) — FastAPI runs this in a **thread pool** automatically. Use this when you must call synchronous/blocking code. It will not block the event loop.

The rule is simple: if your function uses `await`, make it `async def`. If it does not, use plain `def`. Since our entire stack is async (async SQLAlchemy, async Anthropic SDK), we will use `async def` for nearly everything.

## 2.11 Clean Up main.py

Before proceeding, clean `main.py` down to the production structure we will build on. Remove all the demonstration endpoints (the `ItemCreate` model, `fake_db`, etc.) and leave only this:

```python
# src/notesmith/main.py
from fastapi import FastAPI

app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

We will add routers, middleware, and the lifespan handler in later chapters.

---

Proceed to [Chapter 3: Pydantic v2 Schemas and Validation](./03-pydantic-schemas.md).

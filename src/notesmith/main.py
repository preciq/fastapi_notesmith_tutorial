from fastapi import FastAPI

app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
)


### Sample GET endpoints for testing and demonstration purposes ###


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# GET http://127.0.0.1:8000/health -> {"status": "ok"}


@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}


# GET http://127.0.0.1:8000/items/1 -> {"item_id": 1}
# GET http://127.0.0.1:8000/items/abc -> 422 Unprocessable Entity


@app.get("/items")
async def list_items(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}


# GET http://127.0.0.1:8000/items -> {"skip": 0, "limit": 10} (defaults apply)
# GET http://127.0.0.1:8000/items?skip=5&limit=20 -> {"skip": 5, "limit": 20}
# GET http://127.0.0.1:8000/items?skip=abc&limit=xyz -> 422 Unprocessable Entity (validation error)


@app.get("/search")
async def search(q: str):
    return {"query": q}


# GET http://127.0.0.1:8000/search?q=fastapi -> {"query": "fastapi"}
# GET http://127.0.0.1:8000/search -> 422 Unprocessable Entity (missing required query parameter 'q')


@app.get("/searchTwo")
async def searchTwo(q: str | None = None):
    if q is None:
        return {"results": []}
    return {"query": q}


# GET http://127.0.0.1:8000/searchTwo?q=fastapi -> {"query": "fastapi"}
# GET http://127.0.0.1:8000/searchTwo -> {"results": []}


### POST, PUT and PATH requests with Pydantic body parameters for JSON ###


from pydantic import BaseModel
# Ignore the warning about not being on top but in a real product, we would organize imports properly


class ItemCreate(BaseModel):
    name: str
    price: float
    description: str | None = None


@app.post("/items")
async def create_item(item: ItemCreate):
    return {"name": item.name, "price": item.price, "description": item.description}


"""
A valid request: 
```bash
curl -X POST http://127.0.0.1:8000/items \
  -H "Content-Type: application/json" \
  -d '{"name": "Widget", "price": 9.99}'
```

Response: Response: `{"name": "Widget", "price": 9.99, "description": null}`
"""

"""
An invalid request: 
```bash
curl -X POST http://127.0.0.1:8000/items \
  -H "Content-Type: application/json" \
  -d '{"price": 9.99}'
```

Response: `422` with details about the missing field.
"""


@app.put("/items/{item_id}")
async def update_item(item_id: int, item: ItemCreate, notify: bool = False):
    return {
        "item_id": item_id,  # From path
        "item": item.model_dump(),  # From request body
        "notify": notify,  # From query string
    }


"""
Combining path parameters, query parameters and request bodies in a single endpoint.

Valid request:
```bash
curl -X PUT "http://127.0.0.1:8000/items/42?notify=true" \
  -H "Content-Type: application/json" \
  -d '{"name": "Widget", "price": 9.99, "description": "A fine widget"}'
```

Response:
{
    "item_id": 42,
    "item": {"name": "Widget", "price": 9.99, "description": "A fine widget"},
    "notify": true
}

Valid request — optional fields omitted:
```bash
curl -X PUT "http://127.0.0.1:8000/items/7" \
  -H "Content-Type: application/json" \
  -d '{"name": "Gadget", "price": 4.50}'
```

Response:
{
    "item_id": 7,
    "item": {"name": "Gadget", "price": 4.50, "description": null},
    "notify": false
}

Invalid — non-integer path parameter:
```bash
curl -X PUT "http://127.0.0.1:8000/items/abc" \
  -H "Content-Type: application/json" \
  -d '{"name": "Widget", "price": 9.99}'
```

Response: `422`:
{
    "detail": [
        {
            "type": "int_parsing",
            "loc": ["path", "item_id"],
            "msg": "Input should be a valid integer, unable to parse string as an integer",
            "input": "abc"
        }
    ]
}

Invalid — missing required body field (name):
```bash
curl -X PUT "http://127.0.0.1:8000/items/42" \
  -H "Content-Type: application/json" \
  -d '{"price": 9.99}'
```

Response: `422` with details about the missing field.
{
    "detail": [
        {
            "type": "missing",
            "loc": ["body", "name"],
            "msg": "Field required",
            "input": {"price": 9.99}
        }
    ]
}

Invalid — wrong type for body field (price is a string):
```bash
curl -X PUT "http://127.0.0.1:8000/items/42" \
  -H "Content-Type: application/json" \
  -d '{"name": "Widget", "price": "expensive"}'
```

Response: `422` with details about the type error.
{
    "detail": [
        {
            "type": "float_parsing",
            "loc": ["body", "price"],
            "msg": "Input should be a valid number, unable to parse string as a number",
            "input": "expensive"
        }
    ]
}

Invalid — no request body at all:
```bash
curl -X PUT "http://127.0.0.1:8000/items/42"
```

Response: `422` with details about the missing body.
"""

# Chapter 3: Pydantic v2 Schemas and Validation

Pydantic is the data validation layer beneath FastAPI. Every request body, response model, and configuration object in your application is a Pydantic model. This chapter covers Pydantic v2 syntax — the version FastAPI now requires.

## 3.1 Defining Models

A Pydantic model is a Python class that inherits from `BaseModel`. Each field is a class attribute with a type annotation.

```python
from pydantic import BaseModel


class NoteCreate(BaseModel):
    title: str
    content: str
    is_pinned: bool = False
```

This defines three fields:

- `title` — required, must be a string
- `content` — required, must be a string
- `is_pinned` — optional, defaults to `False`

When you instantiate or when FastAPI parses JSON into this model, Pydantic validates every field. If `title` is missing or `is_pinned` receives `"not a bool"`, Pydantic raises a `ValidationError` (which FastAPI converts to a 422 response).

## 3.2 Field Constraints

Use `Field()` to add validation constraints beyond type checking:

```python
from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    is_pinned: bool = False
```

Common constraints:

| Type | Constraints |
|------|-------------|
| `str` | `min_length`, `max_length`, `pattern` (regex) |
| `int`, `float` | `gt`, `ge`, `lt`, `le` (greater than, greater or equal, etc.) |
| `list` | `min_length`, `max_length` |

`Field()` also accepts `description` (appears in OpenAPI docs) and `examples`:

```python
title: str = Field(
    min_length=1,
    max_length=200,
    description="The title of the note.",
    examples=["Meeting notes", "Shopping list"],
)
```

## 3.3 Optional and Nullable Fields

In Pydantic v2, how you annotate a field determines its nullability:

```python
from pydantic import BaseModel


class NoteCreate(BaseModel):
    title: str                        # Required, cannot be None
    content: str                      # Required, cannot be None
    tag: str | None = None            # Optional, can be None, defaults to None
    priority: int = 1                 # Optional (has default), cannot be None
```

The distinction matters:

- `str` means the field must be present and must be a non-null string.
- `str | None = None` means the field can be omitted (defaults to `None`) or explicitly set to `null`.
- `str | None` (no default) means the field is **required** but its value can be `null`.

## 3.4 Nested Models

Models can reference other models:

```python
class Tag(BaseModel):
    name: str
    color: str = "gray"


class NoteCreate(BaseModel):
    title: str
    content: str
    tags: list[Tag] = []
```

A valid JSON request body for this:

```json
{
    "title": "Meeting notes",
    "content": "Discussed Q2 roadmap.",
    "tags": [
        {"name": "work", "color": "blue"},
        {"name": "important"}
    ]
}
```

Pydantic validates each `Tag` in the list independently.

## 3.5 model_config and ORM Mode

When using SQLAlchemy, you need Pydantic to read data from ORM model objects (which are not dictionaries). In Pydantic v2, this is configured through `model_config`:

```python
from pydantic import BaseModel, ConfigDict


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    is_pinned: bool
```

`from_attributes=True` (called `orm_mode` in Pydantic v1) tells Pydantic to read values from object attributes (`obj.title`) rather than dictionary keys (`obj["title"]`). This is essential for converting SQLAlchemy model instances into API responses.

With this configuration, you can do:

```python
# sqlalchemy_user is a SQLAlchemy model instance
note_response = NoteResponse.model_validate(sqlalchemy_note)
```

FastAPI does this conversion automatically when you set `response_model=NoteResponse` on an endpoint.

## 3.6 Serialization Methods

Pydantic v2 renamed its serialization methods. Use the new names:

| Pydantic v1 | Pydantic v2 | Purpose |
|-------------|-------------|---------|
| `.dict()` | `.model_dump()` | Convert to Python dictionary |
| `.json()` | `.model_dump_json()` | Convert to JSON string |
| `.from_orm(obj)` | `.model_validate(obj)` | Create instance from ORM object |
| `parse_obj(data)` | `model_validate(data)` | Create instance from dict |

The v1 methods still work but emit deprecation warnings. Always use the v2 methods.

```python
note = NoteCreate(title="Test", content="Hello")

# To dictionary
data = note.model_dump()
# {'title': 'Test', 'content': 'Hello', 'is_pinned': False}

# To dictionary, excluding unset fields
data = note.model_dump(exclude_unset=True)
# {'title': 'Test', 'content': 'Hello'}

# To JSON string
json_str = note.model_dump_json()
# '{"title":"Test","content":"Hello","is_pinned":false}'
```

The `exclude_unset=True` parameter is particularly useful for partial updates — it lets you distinguish between "the user set this field to its default value" and "the user did not include this field."

## 3.7 Custom Validators

Use `@field_validator` to add custom validation logic to individual fields:

```python
from pydantic import BaseModel, field_validator


class NoteCreate(BaseModel):
    title: str
    content: str

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty or whitespace only")
        return v.strip()
```

Key syntax rules:

- The decorator is `@field_validator("field_name")`, not the v1 `@validator`.
- The method **must** be decorated with `@classmethod`.
- The first argument after `cls` is the field value.
- Return the (possibly modified) value, or raise `ValueError` to reject it.

For validation that depends on multiple fields, use `@model_validator`:

```python
from pydantic import BaseModel, model_validator


class NoteCreate(BaseModel):
    title: str
    content: str
    summary: str | None = None

    @model_validator(mode="after")
    def summary_must_be_shorter_than_content(self) -> "NoteCreate":
        if self.summary and len(self.summary) >= len(self.content):
            raise ValueError("Summary must be shorter than content")
        return self
```

`mode="after"` means the validator runs after all field-level validation is complete, so all fields are guaranteed to have valid values. `mode="before"` runs before field validation and receives raw input data.

## 3.8 The Schema Pattern: Separate Input and Output Models

A common and important pattern in FastAPI is defining separate Pydantic models for different operations on the same resource:

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# Used for POST request body — fields the client provides
class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    is_pinned: bool = False


# Used for PUT/PATCH request body — all fields optional
class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    is_pinned: bool | None = None


# Used for responses — includes server-generated fields
class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    is_pinned: bool
    owner_id: int
    created_at: datetime
    updated_at: datetime
```

This separation exists for good reasons:

- **`NoteCreate`** has required fields because you need a title and content to create a note.
- **`NoteUpdate`** has all-optional fields because a partial update might only change the title.
- **`NoteResponse`** includes fields the client never provides (id, timestamps, owner_id) and excludes fields that should never be in responses (like internal flags).

Never use one model for all three purposes. Separate models prevent data leaks (exposing internal fields) and allow precise validation per operation.

## 3.9 Configuration with pydantic-settings

Application configuration (database URLs, API keys, secret keys) should come from environment variables, not hardcoded values. `pydantic-settings` provides a `BaseSettings` class that reads from the environment and `.env` files.

Open `src/notesmith/config.py`:

```python
# src/notesmith/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str

    # Authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Anthropic
    anthropic_api_key: str

    # Application
    debug: bool = False


settings = Settings()
```

`BaseSettings` automatically reads environment variables matching the field names (case-insensitive). It also reads from the `.env` file specified in `model_config`. The precedence is: environment variables override `.env` values, which override defaults.

The `settings` instance at the bottom is a module-level singleton. Import it anywhere:

```python
from notesmith.config import settings

print(settings.database_url)
```

This pattern centralizes all configuration, validates it at startup (the app will not start if `database_url` is missing), and provides type safety.

---

Proceed to [Chapter 4: Database Setup with Async SQLAlchemy](./04-database-setup.md).

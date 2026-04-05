# Chapter 1: Project Setup with Poetry

Poetry manages your project's dependencies, virtual environment, and metadata. This chapter covers creating a project from scratch, understanding `pyproject.toml`, and installing all the dependencies we will use throughout this tutorial.

## 1.1 Creating the Project

Open your terminal and run:

```bash
poetry new notesmith
```

This creates a directory called `notesmith/` with a `src/` layout:

```
notesmith/
├── src/
│   └── notesmith/
│       └── __init__.py
├── tests/
│   └── __init__.py
├── pyproject.toml
└── README.md
```

The `src/` directory is the default in Poetry 2.x and is a Python packaging best practice — it prevents you from accidentally importing your source code without installing it.

Enter the project directory:

```bash
cd notesmith
```

## 1.2 Understanding `pyproject.toml`

Open `pyproject.toml`. Poetry 2.x uses the **PEP 621 standard** for project metadata. The generated file will look similar to this:

```toml
[project]
name = "notesmith"
version = "0.1.0"
description = ""
authors = [
    { name = "Your Name", email = "you@example.com" }
]
readme = "README.md"
requires-python = ">=3.10"
dependencies = []

[build-system]
requires = ["poetry-core>=2.0,<3.0"]
build-backend = "poetry.core.masonry.api"
```

Key things to understand:

- **`[project]`** — This is the PEP 621 standard section. In Poetry 1.x, this was `[tool.poetry]`. The old format still works but is deprecated.
- **`requires-python`** — Sets the minimum Python version. We use `>=3.10` because that is the floor for our entire stack.
- **`dependencies`** — Runtime dependencies go here. Poetry manages this list for you when you run `poetry add`.
- **`[build-system]`** — Tells Python build tools to use Poetry's backend. Do not modify this.

## 1.3 Configuring the Virtual Environment

Tell Poetry to create the virtual environment inside the project directory. This makes it easier for editors to detect and keeps things self-contained:

```bash
poetry config virtualenvs.in-project true
```

Now install the (currently empty) project to create the virtual environment:

```bash
poetry install
```

You should see a `.venv/` directory appear in your project root. All subsequent `poetry add` and `poetry run` commands use this environment.

## 1.4 Adding Dependencies

We will install all runtime dependencies now, then development dependencies separately.

Enter into a shell environment with the venv generated via: 

```
eval "$(poetry env activate)" # to enter
deactivate # to exit
```

**Runtime dependencies:**

```bash
poetry add "fastapi[standard]" "sqlalchemy[asyncio]" asyncpg alembic anthropic pyjwt "pwdlib[argon2]" pydantic-settings python-multipart
```

What each package provides:

| Package | Purpose |
|---------|---------|
| `fastapi[standard]` | FastAPI framework. The `[standard]` extra includes Uvicorn, httptools, uvloop, and other production essentials. |
| `sqlalchemy[asyncio]` | SQLAlchemy ORM. The `[asyncio]` extra installs `greenlet`, which is required for async support. |
| `asyncpg` | High-performance async PostgreSQL driver. |
| `alembic` | Database migration tool for SQLAlchemy. |
| `anthropic` | Anthropic's official Python SDK for the Claude API. |
| `pyjwt` | JWT token encoding and decoding. |
| `pwdlib[argon2]` | Password hashing. The `[argon2]` extra installs the Argon2 backend (recommended over bcrypt). |
| `pydantic-settings` | Loads configuration from environment variables and `.env` files. Separated from Pydantic core since v2. |
| `python-multipart` | Required by FastAPI for form data parsing (used by OAuth2 password flow). |

**Development dependencies:**

```bash
poetry add --group dev pytest pytest-asyncio httpx aiosqlite
```

| Package | Purpose |
|---------|---------|
| `pytest` | Test runner. |
| `pytest-asyncio` | Plugin for running async test functions. |
| `httpx` | Async HTTP client. Used to test FastAPI endpoints without a real server. |
| `aiosqlite` | Async SQLite driver. Used for test databases so tests do not require PostgreSQL. |

## 1.5 The Lock File

After adding dependencies, Poetry generates (or updates) `poetry.lock`. This file pins every dependency and sub-dependency to exact versions. It ensures that every developer on the project — and every deployment — uses identical versions.

**Always commit `poetry.lock` to version control.** It is what makes your builds reproducible. If you ever need to update dependencies, run:

```bash
poetry update          # Updates all dependencies within version constraints
poetry update fastapi  # Updates only fastapi (and its sub-dependencies)
```

To synchronize your environment to exactly what the lock file specifies (removing anything extra), use:

```bash
poetry sync
```

`poetry sync` is preferred over `poetry install` for reproducible environments because it also removes packages that are no longer in the lock file.

## 1.6 Running Commands Inside the Environment

Poetry 2.x removed the `poetry shell` command. You have two options for running commands inside the virtual environment:

**Option A: `poetry run` (recommended for one-off commands)**

```bash
poetry run python -c "import fastapi; print(fastapi.__version__)"
poetry run uvicorn src.notesmith.main:app --reload
```

**Option B: Activate the environment in your current shell**

```bash
# On macOS/Linux (bash/zsh):
eval "$(poetry env activate)"

# Now all commands use the venv automatically:
python -c "import fastapi; print(fastapi.__version__)"

# To deactivate:
deactivate
```

Throughout the rest of this tutorial, commands will be shown without the `poetry run` prefix. If you have not activated the environment, prepend `poetry run` to every command.

## 1.7 Project Structure

Before we write any code, set up the directory structure we will use for the rest of the tutorial. Create these directories and files:

```bash
mkdir -p src/notesmith/auth
mkdir -p src/notesmith/notes
mkdir -p src/notesmith/ai

touch src/notesmith/main.py
touch src/notesmith/config.py
touch src/notesmith/database.py
touch src/notesmith/auth/__init__.py
touch src/notesmith/auth/router.py
touch src/notesmith/auth/schemas.py
touch src/notesmith/auth/models.py
touch src/notesmith/auth/service.py
touch src/notesmith/auth/dependencies.py
touch src/notesmith/notes/__init__.py
touch src/notesmith/notes/router.py
touch src/notesmith/notes/schemas.py
touch src/notesmith/notes/models.py
touch src/notesmith/notes/service.py
touch src/notesmith/ai/__init__.py
touch src/notesmith/ai/router.py
touch src/notesmith/ai/service.py
```

Also create a `.env` file in the project root for environment variables:

```bash
touch .env
```

Add the following to `.env` (replace the database credentials with your own):

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/notesmith
ANTHROPIC_API_KEY=sk-ant-your-key-here
JWT_SECRET_KEY=change-me-to-a-random-hex-string
```

Generate a proper secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and replace `change-me-to-a-random-hex-string` in your `.env` file.


Now create the database on your remote PostgreSQL instance. Since you do not have `psql` installed locally, use DBeaver:

1. Open DBeaver and connect to your PostgreSQL server.
2. Open a new SQL editor (right-click your connection → **SQL Editor** → **New SQL Script**).
3. Run:

```sql
CREATE DATABASE notesmith;
```

4. Right-click your connection in the sidebar and select **Refresh** to confirm `notesmith` appears in the database list.

Then update your `.env` file to point at the remote instance:

```env
DATABASE_URL=postgresql+asyncpg://<USERNAME>:<PASSWORD>@<HOST>:<PORT>/notesmith
```

Replace the placeholders with the values from your DBeaver connection settings (right-click connection → **Edit Connection**):

| Placeholder | Where to find it |
|---|---|
| `<USERNAME>` | "Username" field |
| `<PASSWORD>` | "Password" field |
| `<HOST>` | "Host" field (domain or IP) |
| `<PORT>` | "Port" field (typically `5432`) |

If your password contains special characters (`@`, `:`, `/`, `%`), URL-encode them — for example, `p@ss` becomes `p%40ss`.


Your final project tree should look like this:

```
notesmith/
├── src/
│   └── notesmith/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   ├── models.py
│       │   ├── service.py
│       │   └── dependencies.py
│       ├── notes/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   ├── models.py
│       │   └── service.py
│       └── ai/
│           ├── __init__.py
│           ├── router.py
│           └── service.py
├── tests/
│   └── __init__.py
├── .env
├── pyproject.toml
├── poetry.lock
└── README.md
```

## 1.8 Verify the Setup

Run this command to confirm everything installed correctly:

```bash
python -c "
import fastapi
import sqlalchemy
import alembic
import anthropic
import jwt
import pwdlib
import httpx
import uvicorn

print(f'FastAPI:     {fastapi.__version__}')
print(f'SQLAlchemy:  {sqlalchemy.__version__}')
print(f'Alembic:     {alembic.__version__}')
print(f'Anthropic:   {anthropic.__version__}')
print(f'PyJWT:       {jwt.__version__}')
print(f'pwdlib:      {pwdlib.__version__}')
print(f'httpx:       {httpx.__version__}')
print(f'Uvicorn:     {uvicorn.__version__}')
print('All dependencies OK.')
"
```

All versions should print without errors. If any import fails, re-run `poetry install` and check for error messages.

Verify that the database connection is valid: 

```bash
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv
import os

load_dotenv()

async def test():
    engine = create_async_engine(os.getenv('DATABASE_URL'))
    async with engine.connect() as conn:
        result = await conn.execute(text('SELECT 1'))
        print(f'Connection successful: {result.scalar()}')
    await engine.dispose()

asyncio.run(test())
"
```

Verify that the anthropic API key has been set correctly:

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
from anthropic import Anthropic
client = Anthropic()
msg = client.messages.create(model='claude-sonnet-4-20250514', max_tokens=10, messages=[{'role':'user','content':'Hi'}])
print('Key works. Response:', msg.content[0].text)
"
```

---

Proceed to [Chapter 2: FastAPI Fundamentals](./02-fastapi-fundamentals.md).

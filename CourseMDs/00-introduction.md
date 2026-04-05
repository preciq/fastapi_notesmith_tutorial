# Chapter 0: Introduction

## What This Tutorial Covers

This is a ground-up tutorial for building production-grade Python APIs with FastAPI. By the end, you will have built a fully functional backend application connected to PostgreSQL with AI-powered features, JWT authentication, and a proper test suite.

The stack:

- **FastAPI 0.135.x** — async web framework
- **Poetry 2.x** — dependency management and project configuration
- **Uvicorn 0.42.x** — ASGI server
- **SQLAlchemy 2.0.x** (async) — ORM with the modern `mapped_column` syntax
- **Alembic 1.18.x** — database migrations
- **asyncpg 0.31.x** — async PostgreSQL driver
- **PyJWT 2.12.x** — JSON Web Token encoding/decoding
- **pwdlib 0.3.x** — password hashing (Argon2)
- **Anthropic Python SDK 0.86.x** — Claude AI integration
- **httpx 0.28.x + pytest-asyncio** — async testing

## Prerequisites

This tutorial assumes you have:

1. **Working knowledge of Python** — functions, classes, type hints, `async`/`await` syntax, context managers, decorators. You do not need to be an expert, but you should not be seeing these concepts for the first time.
2. **Python 3.10 or later installed.** This is the minimum version required by FastAPI, Poetry 2.x, and pwdlib. Verify with `python3 --version`.
3. **PostgreSQL installed and running.** You need a local PostgreSQL server (version 13+). You should be able to create databases. If you are on macOS, `brew install postgresql@16` works. On Ubuntu/Debian, `sudo apt install postgresql`. On Windows, download from postgresql.org.
4. **A text editor or IDE.** VS Code with the Python extension is recommended but not required.
5. **Poetry installed.** Install it with `pipx install poetry`. If you do not have `pipx`, install it first: `pip install --user pipx && pipx ensurepath`. Verify with `poetry --version` (should show 2.x).
6. **An Anthropic API key.** Sign up at console.anthropic.com and generate an API key. The free tier is sufficient for this tutorial.

## What We Will Build

The capstone project is **NoteSmith** — a notes API backend with AI capabilities. Users can register, authenticate, and manage notes. The AI features include summarizing notes and analyzing their content via Claude. The project exercises every concept taught in the tutorial:

- Project setup and dependency management (Poetry)
- Route definition and request validation (FastAPI + Pydantic v2)
- Async database operations (SQLAlchemy 2.0 + asyncpg + PostgreSQL)
- Schema migrations (Alembic)
- Password hashing and JWT authentication (pwdlib + PyJWT)
- Dependency injection and middleware (FastAPI)
- AI integration with streaming support (Anthropic SDK)
- Async testing (pytest + httpx)

## How the Tutorial Is Structured

Each chapter introduces one layer of the stack, with explanations followed by code you write yourself. Chapters build on each other sequentially — do not skip ahead.

| Chapter | Topic |
|---------|-------|
| 1 | Project Setup with Poetry |
| 2 | FastAPI Fundamentals |
| 3 | Pydantic v2 Schemas and Validation |
| 4 | Database Setup with Async SQLAlchemy |
| 5 | Alembic Migrations |
| 6 | CRUD Operations and the Service Layer |
| 7 | JWT Authentication |
| 8 | Dependency Injection, Middleware, and Error Handling |
| 9 | Anthropic SDK Integration |
| 10 | Testing with pytest and httpx |
| 11 | Capstone Project: NoteSmith |

## Conventions Used

- All terminal commands assume a Unix-like shell (macOS/Linux). Windows equivalents are noted where they differ.
- File paths are relative to the project root unless stated otherwise.
- Code blocks labeled `# filename.py` indicate the file you should create or edit.
- When a code block shows only a portion of a file, the surrounding context is indicated with `...` (ellipsis).
- "Run this" means execute the command in your terminal, inside the Poetry virtual environment.

---

Proceed to [Chapter 1: Project Setup with Poetry](./01-project-setup.md).

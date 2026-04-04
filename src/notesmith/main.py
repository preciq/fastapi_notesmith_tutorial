from contextlib import asynccontextmanager

from fastapi import FastAPI

from notesmith.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify database connection
    async with engine.begin() as conn:
        # This will raise if the database is unreachable
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


@app.get("/health")
async def health_check():
    return {"status": "ok"}

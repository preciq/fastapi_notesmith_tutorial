from contextlib import asynccontextmanager

from fastapi import FastAPI

from notesmith.auth.router import router as auth_router
from notesmith.database import engine
from notesmith.notes.router import router as notes_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(lambda conn: None)
    yield
    await engine.dispose()


app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
    lifespan=lifespan,
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok"}

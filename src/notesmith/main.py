from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from notesmith.auth.router import router as auth_router
from notesmith.database import engine
from notesmith.exceptions import NoteSmithError
from notesmith.middleware import RequestLoggingMiddleware
from notesmith.notes.router import router as notes_router
from notesmith.ai.router import router as ai_router


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
app.include_router(ai_router, prefix="/api/v1")


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

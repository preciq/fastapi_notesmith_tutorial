from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from notesmith.ai.router import router as ai_router
from notesmith.auth.router import router as auth_router
from notesmith.database import engine
from notesmith.exceptions import NoteSmithError
from notesmith.mcp.router import router as mcp_router
from notesmith.mcp.server import mcp as mcp_server
from notesmith.middleware import RequestLoggingMiddleware
from notesmith.notes.router import router as notes_router

# Create the MCP ASGI app. The path parameter sets the endpoint
# within the mounted sub-application (default is "/mcp").
mcp_app = mcp_server.http_app(path="/mcp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database startup
    async with engine.begin() as conn:
        await conn.run_sync(lambda conn: None)
    # MCP server startup — required for the mounted MCP app to function.
    # FastMCP's http_app() has an internal lifespan that initializes
    # session management and transport state. The FastMCP documentation
    # requires connecting it to the host application's lifespan.
    # We nest it inside ours so both lifecycles run.
    async with mcp_app.router.lifespan_context(mcp_app):
        yield
    # Database shutdown
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

# REST API routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(mcp_router, prefix="/api/v1")

# MCP server mount — accessible at /mcp-server/mcp
app.mount("/mcp-server", mcp_app)


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

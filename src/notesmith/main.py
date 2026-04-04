from fastapi import FastAPI

app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

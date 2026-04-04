from fastapi import APIRouter

router = APIRouter(
    prefix="/notes",
    tags=["notes"],
)
# use modular design; this router will be included in the main app in main.py so we don't have to write all our endpoints in main.py

@router.get("/")
async def list_notes():
    return {"notes": []}


@router.get("/{note_id}")
async def get_note(note_id: int):
    return {"note_id": note_id}

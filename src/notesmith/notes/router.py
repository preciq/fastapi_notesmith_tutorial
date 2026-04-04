from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.database import get_db
from notesmith.notes import service
from notesmith.notes.schemas import NoteCreate, NoteResponse, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])

# Type alias for the database session dependency
DB = Annotated[AsyncSession, Depends(get_db)]

# Placeholder: we will replace this with real auth in Chapter 7
TEMP_USER_ID = 1


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note_data: NoteCreate, db: DB):
    note = await service.create_note(db, note_data, owner_id=TEMP_USER_ID)
    return note


@router.get("/", response_model=list[NoteResponse])
async def list_notes(db: DB, skip: int = 0, limit: int = 50):
    notes = await service.get_notes_by_owner(
        db, owner_id=TEMP_USER_ID, skip=skip, limit=limit
    )
    return notes


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, db: DB):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != TEMP_USER_ID:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, note_data: NoteUpdate, db: DB):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != TEMP_USER_ID:
        raise HTTPException(status_code=404, detail="Note not found")
    updated = await service.update_note(db, note, note_data)
    return updated


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: int, db: DB):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != TEMP_USER_ID:
        raise HTTPException(status_code=404, detail="Note not found")
    await service.delete_note(db, note)
    return None

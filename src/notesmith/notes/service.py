from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.notes.models import Note
from notesmith.notes.schemas import NoteCreate, NoteUpdate


async def create_note(
    session: AsyncSession,
    note_data: NoteCreate,
    owner_id: int,
) -> Note:
    note = Note(
        title=note_data.title,
        content=note_data.content,
        is_pinned=note_data.is_pinned,
        owner_id=owner_id,
    )
    session.add(note)
    await session.flush()
    return note


async def get_note_by_id(
    session: AsyncSession,
    note_id: int,
) -> Note | None:
    stmt = select(Note).where(Note.id == note_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_notes_by_owner(
    session: AsyncSession,
    owner_id: int,
    skip: int = 0,
    limit: int = 50,
) -> list[Note]:
    stmt = (
        select(Note)
        .where(Note.owner_id == owner_id)
        .order_by(Note.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_note(
    session: AsyncSession,
    note: Note,
    note_data: NoteUpdate,
) -> Note:
    update_fields = note_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(note, field, value)
    await session.flush()
    await session.refresh(note)
    return note


async def delete_note(
    session: AsyncSession,
    note: Note,
) -> None:
    await session.delete(note)
    await session.flush()

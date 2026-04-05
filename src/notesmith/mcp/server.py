from fastmcp import FastMCP

from notesmith.database import async_session_maker
from notesmith.notes import service as notes_service
from notesmith.notes.schemas import NoteCreate

mcp = FastMCP(
    "NoteSmith",
    instructions=(
        "NoteSmith is a notes API. Use these tools to list, retrieve, "
        "create, and search notes for a given user."
    ),
)


@mcp.tool
async def list_notes(owner_id: int, skip: int = 0, limit: int = 50) -> list[dict]:
    """List all notes for a user, ordered by creation date (newest first).

    Args:
        owner_id: The ID of the user whose notes to list.
        skip: Number of notes to skip (for pagination).
        limit: Maximum number of notes to return.
    """
    async with async_session_maker() as session:
        notes = await notes_service.get_notes_by_owner(
            session, owner_id, skip=skip, limit=limit
        )
        return [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content[:200] + "..."
                if len(n.content) > 200
                else n.content,
                "is_pinned": n.is_pinned,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ]


@mcp.tool
async def get_note(note_id: int) -> dict:
    """Get the full content of a specific note by its ID.

    Args:
        note_id: The ID of the note to retrieve.
    """
    async with async_session_maker() as session:
        note = await notes_service.get_note_by_id(session, note_id)
        if note is None:
            return {"error": f"Note {note_id} not found"}
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "is_pinned": note.is_pinned,
            "summary": note.summary,
            "owner_id": note.owner_id,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }


@mcp.tool
async def create_note(
    owner_id: int, title: str, content: str, is_pinned: bool = False
) -> dict:
    """Create a new note for a user.

    Args:
        owner_id: The ID of the user who owns the note.
        title: The title of the note (max 200 characters).
        content: The content of the note.
        is_pinned: Whether to pin the note (default: false).
    """
    note_data = NoteCreate(title=title, content=content, is_pinned=is_pinned)
    async with async_session_maker() as session:
        note = await notes_service.create_note(session, note_data, owner_id)
        await session.commit()
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "is_pinned": note.is_pinned,
            "owner_id": note.owner_id,
            "created_at": note.created_at.isoformat(),
        }


@mcp.tool
async def search_notes(owner_id: int, query: str) -> list[dict]:
    """Search notes by keyword in title or content.

    Args:
        owner_id: The ID of the user whose notes to search.
        query: The search term to look for in note titles and content.
    """
    from sqlalchemy import select, or_

    from notesmith.notes.models import Note

    async with async_session_maker() as session:
        stmt = (
            select(Note)
            .where(
                Note.owner_id == owner_id,
                or_(
                    Note.title.ilike(f"%{query}%"),
                    Note.content.ilike(f"%{query}%"),
                ),
            )
            .order_by(Note.created_at.desc())
            .limit(20)
        )
        result = await session.execute(stmt)
        notes = result.scalars().all()
        return [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content[:200] + "..."
                if len(n.content) > 200
                else n.content,
                "is_pinned": n.is_pinned,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ]

from httpx import AsyncClient


async def test_create_note(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note", "content": "This is test content."},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test note"
    assert data["content"] == "This is test content."
    assert data["is_pinned"] is False
    assert "id" in data
    assert "created_at" in data


async def test_create_note_unauthenticated(client: AsyncClient):
    response = await client.post(
        "/api/v1/notes/",
        json={"title": "Test note", "content": "Content"},
    )
    assert response.status_code == 401


async def test_create_note_invalid_data(client: AsyncClient, auth_headers):
    # Missing required 'content' field
    response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note"},
    )
    assert response.status_code == 422


async def test_list_notes(client: AsyncClient, auth_headers):
    # Create two notes
    await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Note 1", "content": "Content 1"},
    )
    await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Note 2", "content": "Content 2"},
    )

    response = await client.get("/api/v1/notes/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


async def test_get_note(client: AsyncClient, auth_headers):
    # Create a note
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test", "content": "Content"},
    )
    note_id = create_response.json()["id"]

    # Get it
    response = await client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Test"


async def test_get_nonexistent_note(client: AsyncClient, auth_headers):
    response = await client.get("/api/v1/notes/99999", headers=auth_headers)
    assert response.status_code == 404


async def test_update_note(client: AsyncClient, auth_headers):
    # Create
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Original", "content": "Original content"},
    )
    note_id = create_response.json()["id"]

    # Update title only (partial update)
    response = await client.patch(
        f"/api/v1/notes/{note_id}",
        headers=auth_headers,
        json={"title": "Updated"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated"
    assert data["content"] == "Original content"  # Unchanged


async def test_delete_note(client: AsyncClient, auth_headers):
    # Create
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "To delete", "content": "Will be deleted"},
    )
    note_id = create_response.json()["id"]

    # Delete
    response = await client.delete(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify it is gone
    response = await client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 404

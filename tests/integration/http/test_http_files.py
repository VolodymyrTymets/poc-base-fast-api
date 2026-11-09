"""POST/PATCH/GET /api/v1/files over HTTP on a real database. Task: 8.2.

Callers sign up through the API, so each test has its own account; rows stay for the module. The service rules (size from
the bytes, the name fallback, nothing stored after a failed check) are tested in test_db_files_service.py; the status codes and
error bodies are tested here only.
"""

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from utils.auth import sign_up
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.main import create_app
from app.models import AccountProfile, File

PATH = "/api/v1/files"
PNG = b"\x89PNG\r\n\x1a\n-bytes"
JPEG = b"\xff\xd8\xff-bytes"
MISSING_ID = "00000000-0000-4000-8000-000000000000"
FILE_KEYS = {"id", "name", "mimeType", "size", "createdAt", "contentUrl"}


def make_app(database_url: str, max_size: int = 10_485_760) -> FastAPI:
    return create_app(
        Settings(
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
            file_max_size=max_size,
        )
    )


async def caller(client: httpx.AsyncClient) -> dict[str, str]:
    tokens = await sign_up(client, f"{uuid.uuid4().hex}@example.com", "correct-horse")
    return tokens.headers


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    content: bytes = PNG,
    content_type: str = "image/png",
    name: str | None = None,
    filename: str = "photo.png",
) -> httpx.Response:
    return await client.post(
        PATH,
        headers=headers,
        files={"file": (filename, content, content_type)},
        data={"name": name} if name is not None else None,
    )


def error_of(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def test_an_upload_is_created_with_its_metadata_and_stored_bytes(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, name="Holiday")

    # Assert
    body = response.json()
    assert response.status_code == 201
    assert set(body) == FILE_KEYS
    assert (body["name"], body["mimeType"], body["size"]) == (
        "Holiday",
        "image/png",
        len(PNG),
    )
    assert body["contentUrl"] == f"{PATH}/{body['id']}/content"
    async with db_engine.connect() as connection:
        stored = (
            await connection.execute(select(File.content).where(File.id == body["id"]))
        ).scalar_one()
    assert stored == PNG


async def test_an_empty_name_falls_back_to_the_filename(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, name="", filename="photo.png")

    # Assert
    assert (response.status_code, response.json()["name"]) == (201, "photo.png")


async def test_a_name_sent_twice_keeps_the_last_one(module_database_url: str) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await client.post(
            PATH,
            headers=headers,
            files={"file": ("a.png", PNG, "image/png")},
            data={"name": ["first", "second"]},
        )

    # Assert
    assert (response.status_code, response.json()["name"]) == (201, "second")


async def test_a_name_over_255_characters_is_422_on_the_name_field(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, name="n" * 256)

    # Assert
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert [d["field"] for d in error["details"]] == ["name"]


async def test_an_upload_without_a_token_is_401(module_database_url: str) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        # Act
        response = await client.post(PATH, files={"file": ("a.png", PNG, "image/png")})

    # Assert
    assert error_of(response) == (401, "UNAUTHORIZED")


async def test_an_upload_with_no_file_part_is_422_in_the_error_contract(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await client.post(PATH, headers=headers, data={"name": "x"})

    # Assert
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert [d["field"] for d in error["details"]] == ["file"]


async def test_a_zero_byte_part_with_an_empty_filename_counts_as_no_file(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, content=b"", filename="")

    # Assert
    assert error_of(response) == (422, "VALIDATION_FAILED")


async def test_a_disallowed_mime_type_is_422_on_the_file_field(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, b"hi", "text/plain")

    # Assert
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert [d["field"] for d in error["details"]] == ["file"]


async def test_an_upload_over_the_size_limit_is_413(module_database_url: str) -> None:
    # Arrange
    async with running_client(make_app(module_database_url, max_size=10)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, content=b"x" * 11)

    # Assert
    assert error_of(response) == (413, "VALIDATION_FAILED")


async def test_the_metadata_is_read_back_without_the_bytes(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Holiday")).json()

        # Act
        response = await client.get(f"{PATH}/{created['id']}", headers=headers)

    # Assert
    assert (response.status_code, response.json()) == (200, created)


async def test_a_rename_keeps_the_size_and_type(module_database_url: str) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Old")).json()

        # Act
        response = await client.patch(
            f"{PATH}/{created['id']}", headers=headers, data={"name": "New"}
        )

    # Assert
    assert (response.status_code, response.json()) == (200, {**created, "name": "New"})


async def test_a_new_file_replaces_the_stored_bytes(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Keep")).json()

        # Act
        response = await client.patch(
            f"{PATH}/{created['id']}",
            headers=headers,
            files={"file": ("b.jpg", JPEG, "image/jpeg")},
        )

    # Assert
    body = response.json()
    assert (response.status_code, body["mimeType"], body["size"]) == (
        200,
        "image/jpeg",
        len(JPEG),
    )
    async with db_engine.connect() as connection:
        stored = (
            await connection.execute(
                select(File.content).where(File.id == created["id"])
            )
        ).scalar_one()
    assert stored == JPEG


async def test_a_patch_with_nothing_to_change_returns_the_file_as_it_is(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers)).json()

        # Act
        response = await client.patch(f"{PATH}/{created['id']}", headers=headers)

    # Assert
    assert (response.status_code, response.json()) == (200, created)


async def test_a_replacement_over_the_size_limit_is_413(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url, max_size=20)) as client:
        headers = await caller(client)
        created = (await upload(client, headers)).json()

        # Act
        response = await client.patch(
            f"{PATH}/{created['id']}",
            headers=headers,
            files={"file": ("b.png", b"x" * 21, "image/png")},
        )

    # Assert
    assert error_of(response) == (413, "VALIDATION_FAILED")


@pytest.mark.parametrize("method", ["GET", "PATCH"])
@pytest.mark.parametrize("target", ["another_accounts_file", "unknown_id"])
async def test_a_file_the_caller_does_not_own_is_403(
    module_database_url: str, method: str, target: str
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        owner = await caller(client)
        stranger = await caller(client)
        owned = (await upload(client, owner)).json()
        file_id = owned["id"] if target == "another_accounts_file" else MISSING_ID

        # Act
        response = await client.request(
            method, f"{PATH}/{file_id}", headers=stranger, data={"name": "x"}
        )

    # Assert
    assert error_of(response) == (403, "FORBIDDEN")


async def test_an_uploaded_file_is_accepted_as_an_avatar(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(
            client, f"{uuid.uuid4().hex}@example.com", "correct-horse"
        )
        created = (await upload(client, tokens.headers)).json()
        account = (await client.get("/api/v1/account", headers=tokens.headers)).json()

        # Act
        response = await client.patch(
            f"/api/v1/accounts/{account['id']}/profile",
            headers=tokens.headers,
            json={"avatarId": created["id"]},
        )

    # Assert
    async with db_engine.connect() as connection:
        avatar_id = (
            await connection.execute(
                select(AccountProfile.avatar_id).where(
                    AccountProfile.account_id == account["id"]
                )
            )
        ).scalar_one()
    assert (response.status_code, avatar_id) == (200, created["id"])


async def test_the_owner_downloads_exactly_the_uploaded_bytes(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers)).json()

        # Act
        response = await client.get(f"{PATH}/{created['id']}/content", headers=headers)

    # Assert
    assert (response.status_code, response.content) == (200, PNG)
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-length"] == str(len(PNG))
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_download_after_a_replacement_is_the_new_file(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers)).json()
        await client.patch(
            f"{PATH}/{created['id']}",
            headers=headers,
            files={"file": ("b.jpg", JPEG, "image/jpeg")},
        )

        # Act
        response = await client.get(f"{PATH}/{created['id']}/content", headers=headers)

    # Assert
    assert (response.status_code, response.content) == (200, JPEG)
    assert response.headers["content-type"] == "image/jpeg"


async def test_an_empty_file_downloads_as_an_empty_body(
    module_database_url: str,
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, content=b"")).json()

        # Act
        response = await client.get(f"{PATH}/{created['id']}/content", headers=headers)

    # Assert
    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["content-length"] == "0"


async def test_the_content_without_a_token_is_401(module_database_url: str) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        # Act
        response = await client.get(f"{PATH}/{MISSING_ID}/content")

    # Assert
    assert error_of(response) == (401, "UNAUTHORIZED")


@pytest.mark.parametrize("target", ["another_accounts_file", "unknown_id"])
async def test_the_content_of_a_file_the_caller_does_not_own_is_403(
    module_database_url: str, target: str
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        owner = await caller(client)
        stranger = await caller(client)
        owned = (await upload(client, owner)).json()
        file_id = owned["id"] if target == "another_accounts_file" else MISSING_ID

        # Act
        response = await client.get(f"{PATH}/{file_id}/content", headers=stranger)

    # Assert
    assert error_of(response) == (403, "FORBIDDEN")


async def test_the_content_of_a_row_with_no_stored_bytes_is_404(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(
            client, f"{uuid.uuid4().hex}@example.com", "correct-horse"
        )
        account = (await client.get("/api/v1/account", headers=tokens.headers)).json()
        row = File(name="x", mime_type="image/png", size=0, created_by_id=account["id"])
        async with AsyncSession(db_engine) as session, session.begin():
            session.add(row)
            await session.flush()
            file_id = row.id

        # Act
        response = await client.get(f"{PATH}/{file_id}/content", headers=tokens.headers)

    # Assert
    assert error_of(response) == (404, "NOT_FOUND")


async def test_a_file_with_no_stored_mime_type_downloads_as_octet_stream(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # Arrange
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(
            client, f"{uuid.uuid4().hex}@example.com", "correct-horse"
        )
        account = (await client.get("/api/v1/account", headers=tokens.headers)).json()
        row = File(
            name="x", mime_type=None, size=1, created_by_id=account["id"], content=b"x"
        )
        async with AsyncSession(db_engine) as session, session.begin():
            session.add(row)
            await session.flush()
            file_id = row.id

        # Act
        response = await client.get(f"{PATH}/{file_id}/content", headers=tokens.headers)

    # Assert
    assert (response.status_code, response.content) == (200, b"x")
    assert response.headers["content-type"] == "application/octet-stream"

"""POST/PATCH/GET /api/v1/files over HTTP on a real database. Task: 8.2.

Callers sign up through the API, so each test has its own account; rows stay for the module.
"""

import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.auth import sign_up
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.main import create_app
from app.models import File

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


async def test_without_a_name_the_upload_filename_is_the_name(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, filename="photo.png")

    assert (response.status_code, response.json()["name"]) == (201, "photo.png")


async def test_an_empty_name_falls_back_to_the_filename(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, name="", filename="photo.png")

    assert (response.status_code, response.json()["name"]) == (201, "photo.png")


async def test_a_name_over_255_characters_is_422(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, name="n" * 256)

    body = response.json()["error"]
    assert (response.status_code, body["code"]) == (422, "VALIDATION_FAILED")
    assert [d["field"] for d in body["details"]] == ["name"]


async def test_an_upload_without_a_token_is_401(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url)) as client:
        # Act
        response = await client.post(PATH, files={"file": ("a.png", PNG, "image/png")})

    assert (response.status_code, response.json()["error"]["code"]) == (
        401,
        "UNAUTHORIZED",
    )


async def test_an_upload_with_no_file_part_is_422_in_the_error_contract(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await client.post(PATH, headers=headers, data={"name": "x"})

    body = response.json()["error"]
    assert (response.status_code, body["code"]) == (422, "VALIDATION_FAILED")
    assert [d["field"] for d in body["details"]] == ["file"]


async def test_a_zero_byte_part_with_an_empty_filename_counts_as_no_file(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, content=b"", filename="")

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "VALIDATION_FAILED",
    )


async def test_a_disallowed_mime_type_is_422_and_stores_nothing(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        async with db_engine.connect() as connection:
            before = len((await connection.execute(select(File.id))).all())

        # Act
        response = await upload(
            client, headers, content=b"hi", content_type="text/plain"
        )

    body = response.json()["error"]
    assert (response.status_code, body["code"]) == (422, "VALIDATION_FAILED")
    assert body["details"][0]["field"] == "file"
    async with db_engine.connect() as connection:
        assert len((await connection.execute(select(File.id))).all()) == before


async def test_an_upload_over_the_size_limit_is_413(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url, max_size=10)) as client:
        headers = await caller(client)

        # Act
        response = await upload(client, headers, content=b"x" * 11)

    body = response.json()["error"]
    assert (response.status_code, body["code"]) == (413, "VALIDATION_FAILED")


async def test_the_metadata_is_read_back_without_the_bytes(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Holiday")).json()

        # Act
        response = await client.get(f"{PATH}/{created['id']}", headers=headers)

    assert (response.status_code, response.json()) == (200, created)


async def test_a_rename_keeps_the_bytes_size_and_type(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Old")).json()

        # Act
        response = await client.patch(
            f"{PATH}/{created['id']}", headers=headers, data={"name": "New"}
        )

    assert (response.status_code, response.json()) == (200, {**created, "name": "New"})


async def test_a_new_file_replaces_the_bytes_size_and_type(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Keep")).json()

        # Act
        response = await client.patch(
            f"{PATH}/{created['id']}",
            headers=headers,
            files={"file": ("b.jpg", JPEG, "image/jpeg")},
        )

    body = response.json()
    assert (response.status_code, body["name"], body["mimeType"], body["size"]) == (
        200,
        "Keep",
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
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)
        created = (await upload(client, headers)).json()

        # Act
        response = await client.patch(f"{PATH}/{created['id']}", headers=headers)

    assert (response.status_code, response.json()) == (200, created)


async def test_a_replacement_over_the_limit_is_413_and_changes_nothing(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url, max_size=20)) as client:
        headers = await caller(client)
        created = (await upload(client, headers, name="Keep")).json()

        # Act
        response = await client.patch(
            f"{PATH}/{created['id']}",
            headers=headers,
            data={"name": "Nope"},
            files={"file": ("b.png", b"x" * 21, "image/png")},
        )
        after = await client.get(f"{PATH}/{created['id']}", headers=headers)

    assert response.status_code == 413
    assert after.json() == created


async def test_another_accounts_unknown_and_missing_files_are_all_403(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        owner = await caller(client)
        stranger = await caller(client)
        created = (await upload(client, owner)).json()

        # Act
        responses = [
            await client.get(f"{PATH}/{created['id']}", headers=stranger),
            await client.patch(
                f"{PATH}/{created['id']}", headers=stranger, data={"name": "x"}
            ),
            await client.get(f"{PATH}/{MISSING_ID}", headers=owner),
        ]

    assert [(r.status_code, r.json()["error"]["code"]) for r in responses] == [
        (403, "FORBIDDEN")
    ] * 3


async def test_a_uploaded_file_is_accepted_as_an_avatar(
    module_database_url: str,
) -> None:
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

    assert response.status_code == 200


async def test_a_name_sent_twice_keeps_the_last_one(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url)) as client:
        headers = await caller(client)

        # Act
        response = await client.post(
            PATH,
            headers=headers,
            files={"file": ("a.png", PNG, "image/png")},
            data={"name": ["first", "second"]},
        )

    assert (response.status_code, response.json()["name"]) == (201, "second")

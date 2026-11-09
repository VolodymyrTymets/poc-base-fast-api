"""The /files routes: upload, update, metadata (task 8.2) and content (task 8.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import TokenClaims
from app.core.validation import FileName
from app.dependencies import get_files_service, require_roles
from app.models import AccountRoleType
from app.schemas.files import FileMetadataResponse
from app.services.files import FilesService

router = APIRouter(prefix="/files", tags=["files"])

# Authenticate, then the role (rule P7); the third layer, that the caller owns the file, is the service's (ADR-0022).
Caller = Annotated[
    TokenClaims,
    Depends(require_roles(AccountRoleType.ADMIN, AccountRoleType.CUSTOMER)),
]
FileId = Annotated[str, Path(alias="id", description="The file's id")]


@router.post("", status_code=201, response_model=FileMetadataResponse)
async def create_file(
    claims: Caller,
    # The form is parsed before this runs, so the memory bound is the body-limit middleware, not a read here (task 1.6).
    file: Annotated[
        UploadFile, File(description="The bytes: jpeg or png, at most FILE_MAX_SIZE")
    ],
    service: Annotated[FilesService, Depends(get_files_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[FileName | None, Form()] = None,
) -> FileMetadataResponse:
    """Store an upload for the caller; the size and mime type come from the upload, never from the client."""
    created = await service.create(
        claims.account_id, await file.read(), file.content_type, file.filename, name
    )
    await session.commit()
    return FileMetadataResponse.model_validate(created)


@router.patch("/{id}", response_model=FileMetadataResponse)
async def update_file(
    file_id: FileId,
    claims: Caller,
    service: Annotated[FilesService, Depends(get_files_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile | None, File()] = None,
    name: Annotated[FileName | None, Form()] = None,
) -> FileMetadataResponse:
    """Rename the caller's file, replace its bytes, or both; what is not sent stays as it is."""
    updated = await service.update(
        file_id,
        claims.account_id,
        name=name,
        content=await file.read() if file is not None else None,
        mime_type=file.content_type if file is not None else None,
    )
    await session.commit()
    return FileMetadataResponse.model_validate(updated)


@router.get("/{id}", response_model=FileMetadataResponse)
async def get_file(
    file_id: FileId,
    claims: Caller,
    service: Annotated[FilesService, Depends(get_files_service)],
) -> FileMetadataResponse:
    """The metadata of the caller's file, with `contentUrl`; the bytes are served by the content route (task 8.3)."""
    return FileMetadataResponse.model_validate(
        await service.get(file_id, claims.account_id)
    )


@router.get(
    "/{id}/content",
    response_class=Response,
    responses={
        200: {
            "description": "The file's bytes, with the stored mime type as `Content-Type`",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def get_file_content(
    file_id: FileId,
    claims: Caller,
    service: Annotated[FilesService, Depends(get_files_service)],
) -> Response:
    """The bytes of the caller's file, read whole from the database (ADR-0009); 404 when the row holds none.

    It reads and never commits, so it takes no session of its own. `nosniff` because the type is the uploader's declaration.
    """
    stored = await service.get_content(file_id, claims.account_id)
    return Response(
        content=stored.content,
        media_type=stored.mime_type or "application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )

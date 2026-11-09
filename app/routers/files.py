"""The /files routes: upload, update and metadata (task 8.2); the content route is task 8.3."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import TokenClaims
from app.core.validation import FileName
from app.dependencies import get_files_service, require_roles
from app.models import AccountRoleType
from app.schemas.files import FileResponse
from app.services.files import FilesService

router = APIRouter(prefix="/files", tags=["files"])

# Authenticate, then the role (rule P7); the third layer, that the caller owns the file, is the service's (ADR-0022).
Caller = Annotated[
    TokenClaims,
    Depends(require_roles(AccountRoleType.ADMIN, AccountRoleType.CUSTOMER)),
]
FileId = Annotated[str, Path(alias="id", description="The file's id")]


@router.post("", status_code=201, response_model=FileResponse)
async def create_file(
    claims: Caller,
    # The form is parsed before this runs, so the memory bound is the body-limit middleware, not a read here (task 1.6).
    file: Annotated[
        UploadFile, File(description="The bytes: jpeg or png, at most FILE_MAX_SIZE")
    ],
    service: Annotated[FilesService, Depends(get_files_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[FileName | None, Form()] = None,
) -> FileResponse:
    """Store an upload for the caller; the size and mime type come from the upload, never from the client."""
    created = await service.create(
        claims.account_id, await file.read(), file.content_type, file.filename, name
    )
    await session.commit()
    return FileResponse.model_validate(created)


@router.patch("/{id}", response_model=FileResponse)
async def update_file(
    file_id: FileId,
    claims: Caller,
    service: Annotated[FilesService, Depends(get_files_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile | None, File()] = None,
    name: Annotated[FileName | None, Form()] = None,
) -> FileResponse:
    """Rename the caller's file, replace its bytes, or both; what is not sent stays as it is."""
    updated = await service.update(
        file_id,
        claims.account_id,
        name=name,
        content=await file.read() if file is not None else None,
        mime_type=file.content_type if file is not None else None,
    )
    await session.commit()
    return FileResponse.model_validate(updated)


@router.get("/{id}", response_model=FileResponse)
async def get_file(
    file_id: FileId,
    claims: Caller,
    service: Annotated[FilesService, Depends(get_files_service)],
) -> FileResponse:
    """The metadata of the caller's file, with `contentUrl`; the bytes are served by the content route (task 8.3)."""
    return FileResponse.model_validate(await service.get(file_id, claims.account_id))

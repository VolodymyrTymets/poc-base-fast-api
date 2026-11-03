"""The /files routes: upload, update, metadata and content. Tasks: 8.2, 8.3."""

from fastapi import APIRouter

router = APIRouter(prefix="/files", tags=["files"])

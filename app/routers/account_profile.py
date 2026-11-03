"""PATCH /accounts/{accountId}/profile. Tasks: 5.4."""

from fastapi import APIRouter

router = APIRouter(prefix="/accounts", tags=["account_profile"])

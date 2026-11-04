"""The /auth routes: OTP request and verify, sign-up, sign-in, refresh, sign-out, password change, restore and reset. Tasks: 7.1 to 7.6."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import get_session
from app.dependencies import app_settings, get_otp_service, get_token_service
from app.schemas.auth import (
    OtpRequestInput,
    OtpRequestResponse,
    OtpVerifyInput,
    TokenResponse,
)
from app.services.otp import OtpService
from app.services.tokens import TokenService

router = APIRouter(prefix="/auth", tags=["auth"])

# Environments whose response to an OTP request carries the code, so a developer can sign in without reading the worker log
# (ENDPOINTS.md `signInOtp`). Anywhere else the code travels by SMS only.
CODE_IN_BODY_ENVS = frozenset({"local", "development", "test"})


@router.post(
    "/otp/request", response_model=OtpRequestResponse, response_model_exclude_none=True
)
async def request_otp(
    body: OtpRequestInput,
    settings: Annotated[Settings, Depends(app_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[OtpService, Depends(get_otp_service)],
) -> OtpRequestResponse:
    """Issue a one-time sign-in code for a phone number and queue it as an SMS; an unknown number becomes a customer account."""
    issued = await service.issue(body.phone_number)
    # Commit first, deliver after: a job must never carry a code the database does not hold (routes-convention 3).
    await session.commit()
    await service.deliver(issued)
    in_body = settings.app_env in CODE_IN_BODY_ENVS
    return OtpRequestResponse(success=True, code=issued.code if in_body else None)


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(
    body: OtpVerifyInput,
    session: Annotated[AsyncSession, Depends(get_session)],
    otp: Annotated[OtpService, Depends(get_otp_service)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> TokenResponse:
    """Exchange a sign-in code for an access and a refresh token; a bad, expired or spent code is 401 INVALID_CREDENTIALS."""
    account_id = await otp.verify(body.phone_number, body.code)
    pair = await tokens.issue(account_id)
    # One commit for the spent code, the verified phone and the new refresh hash: any failure above leaves the code usable.
    await session.commit()
    return TokenResponse(
        access_token=pair.access_token, refresh_token=pair.refresh_token
    )

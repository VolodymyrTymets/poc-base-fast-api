"""The /auth routes: OTP request and verify, sign-up, sign-in, refresh, sign-out, password change, restore and reset. Tasks: 7.1 to 7.6."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import get_session
from app.dependencies import (
    app_settings,
    get_otp_service,
    get_password_auth_service,
    get_token_service,
)
from app.schemas.auth import (
    OtpRequestInput,
    OtpRequestResponse,
    OtpVerifyInput,
    SignInInput,
    SignUpInput,
    TokenResponse,
)
from app.services.otp import OtpService
from app.services.password_auth import PasswordAuthService
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
    challenge = await otp.find_challenge(body.phone_number)
    # End the read before the slow Argon2 check: this route is unauthenticated, and a connection held through the hash would let a flood of
    # calls occupy the whole pool. Nothing is written yet; `spend` starts a new transaction and its conditional UPDATE stays race-safe.
    await session.rollback()
    await otp.check(challenge, body.code)
    account_id = await otp.spend(challenge)
    pair = await tokens.issue(account_id)
    # One commit for the spent code, the verified phone and the new refresh hash: any failure above leaves the code usable.
    await session.commit()
    return TokenResponse(
        access_token=pair.access_token, refresh_token=pair.refresh_token
    )


@router.post(
    "/sign-up", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def sign_up(
    body: SignUpInput,
    session: Annotated[AsyncSession, Depends(get_session)],
    password_auth: Annotated[PasswordAuthService, Depends(get_password_auth_service)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> TokenResponse:
    """Register a customer with an email and a password and sign them in; an email already in use is 409 EMAIL_ALREADY_REGISTERED."""
    account_id = await password_auth.sign_up(body.email, body.password)
    pair = await tokens.issue(account_id)
    # One commit for the account, its identity and the refresh hash: a failure above leaves nothing behind.
    await session.commit()
    return TokenResponse(
        access_token=pair.access_token, refresh_token=pair.refresh_token
    )


@router.post("/sign-in", response_model=TokenResponse)
async def sign_in(
    body: SignInInput,
    session: Annotated[AsyncSession, Depends(get_session)],
    password_auth: Annotated[PasswordAuthService, Depends(get_password_auth_service)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> TokenResponse:
    """Exchange an email and a password for an access and a refresh token; every failure is 401 INVALID_CREDENTIALS."""
    credential = await password_auth.find_credential(body.email)
    # End the read before the slow Argon2 check: this route is unauthenticated, and a connection held through the hash would let a flood of
    # calls occupy the whole pool. Nothing is written yet; `tokens.issue` starts a new transaction.
    await session.rollback()
    account_id = await password_auth.check(credential, body.password)
    pair = await tokens.issue(account_id)
    await session.commit()
    return TokenResponse(
        access_token=pair.access_token, refresh_token=pair.refresh_token
    )

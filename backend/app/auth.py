import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, owner_id: str, email: str):
        self.owner_id = owner_id
        self.email = email


def _jwks_client():
    settings = get_settings()
    jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(jwks_url)


def verify_supabase_token(token: str) -> dict:
    """Verify a Supabase access token.

    Supports both signing setups:
    - legacy HS256 project JWT secret (SUPABASE_JWT_SECRET)
    - new asymmetric keys via the project's JWKS endpoint (RS256)
    """
    settings = get_settings()
    try:
        if settings.supabase_jwt_secret:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        elif settings.supabase_url:
            signing_key = _jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                options={"verify_aud": False},
            )
        else:
            logger.warning("No SUPABASE_JWT_SECRET or SUPABASE_URL — token NOT verified")
            payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid session token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    settings = get_settings()

    # Demo mode (no real Supabase backend): bypass token auth and act as the
    # fixed demo owner so the dashboard works fully offline.
    if settings.demo_mode_on:
        if credentials is not None:
            try:
                return CurrentUser(
                    owner_id=payload_owner(credentials.credentials),
                    email="demo@local",
                )
            except HTTPException:
                pass  # invalid token still falls back to the demo owner
        return CurrentUser(owner_id=settings.demo_owner_id, email="demo@local")

    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    payload = verify_supabase_token(credentials.credentials)
    owner_id = payload.get("sub")
    if not owner_id:
        raise HTTPException(status_code=401, detail="Invalid session token")
    return CurrentUser(owner_id=owner_id, email=payload.get("email", ""))


def payload_owner(token: str) -> str:
    payload = verify_supabase_token(token)
    owner_id = payload.get("sub")
    if not owner_id:
        raise HTTPException(status_code=401, detail="Invalid session token")
    return owner_id

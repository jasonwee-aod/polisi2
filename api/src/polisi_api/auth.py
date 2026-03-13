"""Supabase-backed authentication helpers for API routes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import InvalidTokenError

from polisi_api.config import Settings, get_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    """Normalized user identity resolved from a verified bearer token."""

    user_id: str
    email: str | None
    role: str | None
    claims: dict[str, Any]


class TokenVerificationError(ValueError):
    """Raised when a bearer token cannot be trusted."""


class SupabaseTokenVerifier:
    """Verify Supabase JWTs against local signing material."""

    def __init__(self, *, jwt_secret: str | None = None, jwks_json: str | None = None) -> None:
        if not jwt_secret and not jwks_json:
            raise TokenVerificationError(
                "SUPABASE_JWT_SECRET or SUPABASE_JWKS_JSON must be configured"
            )
        self._jwt_secret = jwt_secret
        self._jwks = json.loads(jwks_json) if jwks_json else None

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            claims = jwt.decode(
                token,
                key=self._resolve_key(token),
                algorithms=self._resolve_algorithms(token),
                options={"require": ["sub", "exp"], "verify_aud": False},
            )
        except InvalidTokenError as exc:
            raise TokenVerificationError("Invalid bearer token") from exc

        audience = claims.get("aud")
        if audience not in (None, "authenticated", ["authenticated"]):
            raise TokenVerificationError("Unexpected Supabase audience")

        return AuthenticatedUser(
            user_id=str(claims["sub"]),
            email=_string_or_none(claims.get("email")),
            role=_string_or_none(claims.get("role")),
            claims=claims,
        )

    def _resolve_key(self, token: str) -> str | Any:
        if self._jwt_secret:
            return self._jwt_secret
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        if not key_id:
            raise TokenVerificationError("Missing JWT key id")
        for jwk in self._jwks.get("keys", []):
            if jwk.get("kid") == key_id:
                if jwk.get("kty") == "EC":
                    return jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(jwk))
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        raise TokenVerificationError("No matching signing key")

    def _resolve_algorithms(self, token: str) -> list[str]:
        if self._jwt_secret:
            return ["HS256"]
        header = jwt.get_unverified_header(token)
        return [str(header.get("alg", "RS256"))]


def get_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    return token


@lru_cache(maxsize=8)
def _cached_verifier(jwt_secret: str | None, jwks_json: str | None) -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(jwt_secret=jwt_secret, jwks_json=jwks_json)


def build_token_verifier(settings: Settings) -> SupabaseTokenVerifier:
    return _cached_verifier(settings.supabase_jwt_secret, settings.supabase_jwks_json)


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    token = get_bearer_token(authorization)
    verifier = build_token_verifier(settings)

    try:
        return verifier.verify(token)
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

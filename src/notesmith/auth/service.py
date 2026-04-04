from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth.models import User
from notesmith.auth.schemas import UserCreate # shows error but will go away once the file/class is created
from notesmith.config import settings

# Password hashing instance — uses Argon2 by default
password_hash = PasswordHash.recommended()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored hash."""
    return password_hash.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return password_hash.hash(password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT token.

    Args:
        subject: The token subject — typically the user's ID as a string.
        expires_delta: How long the token is valid. Defaults to the
            configured access_token_expire_minutes.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": subject,
        "exp": expire,
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises InvalidTokenError on failure."""
    return jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, user_data: UserCreate) -> User:
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hash_password(user_data.password),
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> User | None:
    """Verify credentials. Returns the User if valid, None otherwise.

    To prevent timing attacks, we always run the password verification
    even if the user does not exist. This ensures the response time is
    constant regardless of whether the username is valid.
    """
    user = await get_user_by_username(session, username)
    if user is None:
        # Dummy verify to prevent timing-based user enumeration
        password_hash.verify(password, password_hash.hash("dummy"))
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

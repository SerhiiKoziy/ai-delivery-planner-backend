"""Grant or revoke the admin role.

There's no admin UI for roles: every signup is a plain USER, and admins are
promoted by hand with this command (locally or on Fly via `fly ssh console`):

    python -m app.scripts.set_user_role someone@example.com admin
    python -m app.scripts.set_user_role someone@example.com user
"""

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import UserRole
from app.repositories.user_repository import UserRepository


async def set_user_role(session: AsyncSession, email: str, role: UserRole) -> bool:
    """Set `role` on the user with `email`; False if there is no such user."""
    repo = UserRepository(session)
    user = await repo.get_by_email(email)
    if user is None:
        return False
    await repo.update(user.id, role=role)
    return True


async def _main(email: str, role: UserRole) -> int:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        if not await set_user_role(session, email, role):
            print(f"No user with email {email}", file=sys.stderr)
            return 1
    print(f"{email} is now {role.value}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("role", choices=[role.value for role in UserRole])
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.email, UserRole(args.role))))


if __name__ == "__main__":
    main()

"""User roles.

USER is every account by default (including every self-service signup).
ADMIN is granted by hand (see app/scripts/set_user_role.py) and unlocks the
experimental quantum features: the Quantum lab API, the IBM job ledger and
the quantum territory solvers.
"""

import enum


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


DEFAULT_USER_ROLE = UserRole.USER

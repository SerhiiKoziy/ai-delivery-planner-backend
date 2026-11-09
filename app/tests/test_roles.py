"""User roles: every account is a USER by default, and the quantum features
(Quantum lab API, IBM job ledger, quantum territory solvers) are ADMIN-only.

Importing `scenario`/`mock_geocode` from test_territories_api does not carry
over that module's `as_admin` mark, so `client` here is a plain USER unless a
test asks for `as_admin` itself.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import UserRole
from app.db.models.user import User
from app.repositories.user_repository import UserRepository
from app.scripts.set_user_role import set_user_role
from app.tests import test_territories_api
from app.tests.test_territories_api import _plan

# Reuse the territory fixtures (pytest finds fixtures by module attribute name).
mock_geocode = test_territories_api.mock_geocode
scenario = test_territories_api.scenario

QUANTUM_ENDPOINTS = [
    "/api/v1/quantum/runs",
    "/api/v1/quantum/summary",
    "/api/v1/quantum/ledger/",
]


def test_me_returns_the_user_role(client: TestClient, test_user: User) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == test_user.email
    assert body["organizationId"] == str(test_user.organization_id)
    assert body["role"] == "user"
    assert body["isVerified"] is test_user.is_verified


def test_me_reports_admin_after_promotion(client: TestClient, as_admin: User) -> None:
    assert client.get("/api/v1/auth/me").json()["role"] == "admin"


def test_me_requires_auth(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/api/v1/auth/me").status_code == 401


async def test_new_registrations_are_plain_users(
    unauthenticated_client: TestClient, db_session: AsyncSession
) -> None:
    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "new.signup@example.com", "password": "a-strong-password-1"},
    )

    user = await UserRepository(db_session).get_by_email("new.signup@example.com")
    assert user is not None
    assert user.role == UserRole.USER


@pytest.mark.parametrize("path", QUANTUM_ENDPOINTS)
def test_quantum_api_is_forbidden_for_users(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required"


@pytest.mark.parametrize("path", QUANTUM_ENDPOINTS[:2])
def test_quantum_api_is_open_to_admins(client: TestClient, as_admin: User, path: str) -> None:
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("solver", ["quantum_simulator", "ibm_emulator", "ibm_quantum"])
def test_users_cannot_run_quantum_territory_solvers(
    client: TestClient, scenario: dict, solver: str
) -> None:
    response = _plan(client, scenario, solver)

    assert response.status_code == 403
    assert response.json()["detail"] == "Quantum solvers require the admin role"


def test_users_can_plan_territories_classically(client: TestClient, scenario: dict) -> None:
    response = _plan(client, scenario, "classical")

    assert response.status_code == 200
    assert response.json()["solver"] == "classical"


def test_territory_solver_defaults_to_classical(client: TestClient, scenario: dict) -> None:
    response = client.post(
        "/api/v1/territories/plans",
        json={
            "delivery_ids": [d["id"] for d in scenario["deliveries"]],
            "vehicle_ids": [v["id"] for v in scenario["vehicles"][:2]],
        },
    )

    assert response.status_code == 200
    assert response.json()["solver"] == "classical"


def test_admins_can_run_the_quantum_simulator(
    client: TestClient, scenario: dict, as_admin: User
) -> None:
    response = _plan(client, scenario, "quantum_simulator")

    assert response.status_code == 200
    assert response.json()["solver"] == "quantum_simulator"


async def test_set_user_role_promotes_and_demotes(
    db_session: AsyncSession, test_user: User
) -> None:
    repo = UserRepository(db_session)

    assert await set_user_role(db_session, test_user.email, UserRole.ADMIN) is True
    assert (await repo.get(test_user.id)).role == UserRole.ADMIN

    assert await set_user_role(db_session, test_user.email, UserRole.USER) is True
    assert (await repo.get(test_user.id)).role == UserRole.USER


async def test_set_user_role_reports_unknown_email(db_session: AsyncSession) -> None:
    assert await set_user_role(db_session, "nobody@example.com", UserRole.ADMIN) is False

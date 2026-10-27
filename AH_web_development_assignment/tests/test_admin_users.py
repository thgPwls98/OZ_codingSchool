import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from sqlalchemy.exc import SQLAlchemyError

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.apis.admin_apis import router
from app.apis.user_apis import get_user_service
from app.core.db.databases import async_get_db
from app.core.dependencies import get_current_user
from app.models.enums import Department, Role
from app.schemas.user import RoleChangeRequest
from app.services.user_service import UserService


class AdminApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.user = SimpleNamespace(
            id=1, email="admin@example.com", name="관리자",
            department=Department.MEDICAL, gender="female",
            phone_number="01012345678", role=Role.ADMIN, is_active=True,
            hashed_password="must-not-be-returned",
        )
        self.service = AsyncMock()
        self.service.list_users.return_value = [self.user]
        self.service.change_role.return_value = self.user
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.app.dependency_overrides[get_user_service] = lambda: self.service
        self.client = TestClient(self.app)

    def test_list_normalizes_query_and_excludes_password(self):
        response = self.client.get("/api/v1/admin/users", params={
            "query": "  hong  ", "department": "medical",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("hashed_password", response.json()[0])
        self.service.list_users.assert_awaited_once_with("hong", Department.MEDICAL)

    def test_query_length_is_checked_after_trimming(self):
        response = self.client.get("/api/v1/admin/users", params={"query": " " * 300})
        self.assertEqual(response.status_code, 200)
        self.service.list_users.assert_awaited_once_with("", None)

    def test_invalid_inputs(self):
        for params in ({"department": "unknown"}, {"query": "a" * 256}):
            self.assertEqual(self.client.get("/api/v1/admin/users", params=params).status_code, 422)
        for body in ({"user_id": 0, "new_role": "staff"},
                     {"user_id": 2, "new_role": "unknown"},
                     {"user_id": 2, "new_role": "staff", "is_active": False}):
            self.assertEqual(self.client.patch("/api/v1/admin/users/role", json=body).status_code, 422)

    def test_non_admin_is_rejected(self):
        for role in (Role.STAFF, Role.PENDING):
            self.user.role = role
            self.assertEqual(self.client.get("/api/v1/admin/users").status_code, 403)
            self.assertEqual(self.client.patch("/api/v1/admin/users/role", json={
                "user_id": 2, "new_role": "staff",
            }).status_code, 403)
        self.service.list_users.assert_not_awaited()
        self.service.change_role.assert_not_awaited()

    def test_missing_authentication(self):
        self.app.dependency_overrides.pop(get_current_user)
        self.app.dependency_overrides[async_get_db] = lambda: AsyncMock()
        self.assertEqual(self.client.get("/api/v1/admin/users").status_code, 401)


class RoleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_self_change_is_rejected(self):
        repository = AsyncMock()
        with self.assertRaises(HTTPException) as error:
            await UserService(repository).change_role(1, RoleChangeRequest(user_id=1, new_role="staff"))
        self.assertEqual(error.exception.status_code, 400)
        repository.get_by_id.assert_not_awaited()

    async def test_missing_target(self):
        repository = AsyncMock()
        repository.get_by_id.return_value = None
        with self.assertRaises(HTTPException) as error:
            await UserService(repository).change_role(1, RoleChangeRequest(user_id=2, new_role="staff"))
        self.assertEqual(error.exception.status_code, 404)

    async def test_role_update_and_noop(self):
        repository = AsyncMock()
        user = SimpleNamespace(id=2, role=Role.PENDING, is_active=False)
        repository.get_by_id.return_value = user
        service = UserService(repository)
        await service.change_role(1, RoleChangeRequest(user_id=2, new_role="staff"))
        repository.update_role.assert_awaited_once_with(user, Role.STAFF)
        repository.update_role.reset_mock()
        result = await service.change_role(1, RoleChangeRequest(user_id=2, new_role="pending"))
        self.assertIs(result, user)
        repository.update_role.assert_not_awaited()


class DeleteFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_failure_rolls_back_and_returns_500(self):
        repository = AsyncMock()
        repository.delete.side_effect = SQLAlchemyError('database failure')
        with self.assertRaises(HTTPException) as error:
            await UserService(repository).delete_me(SimpleNamespace(id=1))
        self.assertEqual(error.exception.status_code, 500)
        self.assertEqual(error.exception.detail, '잠시 후 다시 시도해주세요.')
        repository.db.rollback.assert_awaited_once()

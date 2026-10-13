import unittest
from app import create_app
from app.extensions import db
from app.models.tenant import Tenant
from app.models.user import User, UserRole


class CRMCoreAPITestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_health_check(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "healthy")

    def test_register_tenant_and_user_admin(self):
        payload = {
            "tenant_name": "Acme Corp",
            "email": "admin@acme.com",
            "password": "Password123!",
            "plan": "pro",
        }
        response = self.client.post("/api/auth/register-tenant", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()

        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["tenant"]["name"], "Acme Corp")
        self.assertEqual(data["tenant"]["plan"], "pro")
        self.assertEqual(data["user"]["email"], "admin@acme.com")
        self.assertEqual(data["user"]["role"], "TenantAdmin")
        self.assertEqual(data["user"]["tenant_id"], data["tenant"]["id"])

    def test_duplicate_email_registration(self):
        payload = {
            "tenant_name": "First Tenant",
            "email": "unique@example.com",
            "password": "Password123!",
        }
        res1 = self.client.post("/api/auth/register-tenant", json=payload)
        self.assertEqual(res1.status_code, 201)

        payload2 = {
            "tenant_name": "Second Tenant",
            "email": "unique@example.com",
            "password": "OtherPassword!",
        }
        res2 = self.client.post("/api/auth/register-tenant", json=payload2)
        self.assertEqual(res2.status_code, 409)

    def test_login_and_me_profile(self):
        # 1. Registrar
        register_payload = {
            "tenant_name": "Stark Industries",
            "email": "tony@stark.com",
            "password": "IronManPassword!",
        }
        reg_res = self.client.post("/api/auth/register-tenant", json=register_payload)
        self.assertEqual(reg_res.status_code, 201)

        # 2. Login
        login_payload = {
            "email": "tony@stark.com",
            "password": "IronManPassword!",
        }
        login_res = self.client.post("/api/auth/login", json=login_payload)
        self.assertEqual(login_res.status_code, 200)
        login_data = login_res.get_json()
        token = login_data["access_token"]
        self.assertIsNotNone(token)
        self.assertEqual(login_data["user"]["email"], "tony@stark.com")

        # 3. GET /api/auth/me sin token -> 401
        me_unauth = self.client.get("/api/auth/me")
        self.assertEqual(me_unauth.status_code, 401)

        # 4. GET /api/auth/me con Bearer token -> 200 y validación de contexto
        headers = {"Authorization": f"Bearer {token}"}
        me_auth = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_auth.status_code, 200)
        me_data = me_auth.get_json()
        self.assertEqual(me_data["user"]["email"], "tony@stark.com")
        self.assertEqual(me_data["tenant"]["name"], "Stark Industries")


if __name__ == "__main__":
    unittest.main()

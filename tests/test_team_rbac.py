import unittest
from app import create_app
from app.extensions import db
from app.models.user import User


class TeamRBACSprint4TestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.token_tenant_a = self._create_tenant_and_get_token(
            "Tenant Team A", "admin_a@team.test"
        )
        self.token_tenant_b = self._create_tenant_and_get_token(
            "Tenant Team B", "admin_b@team.test"
        )

        self.admin_a = User.query.filter_by(email="admin_a@team.test").first()
        self.admin_b = User.query.filter_by(email="admin_b@team.test").first()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_tenant_and_get_token(self, tenant_name, email):
        payload = {
            "tenant_name": tenant_name,
            "email": email,
            "password": "Password123!",
            "plan": "pro",
        }
        response = self.client.post("/api/auth/register-tenant", json=payload)
        self.assertEqual(response.status_code, 201)
        return response.get_json()["access_token"]

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _invite(self, token, email, role="User", password="Password123!"):
        return self.client.post(
            "/api/team/invite",
            json={"email": email, "password": password, "role": role},
            headers=self._headers(token),
        )

    def _login(self, email, password="Password123!"):
        response = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["access_token"]

    def test_admin_can_invite_list_and_update_roles(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        res_user = self._invite(self.token_tenant_a, "user@team.test", "User")
        self.assertEqual(res_user.status_code, 201)
        user_id = res_user.get_json()["user"]["id"]
        self.assertEqual(res_user.get_json()["user"]["role"], "User")
        self.assertNotIn("password", res_user.get_json()["user"])
        self.assertNotIn("password_hash", res_user.get_json()["user"])

        res_auditor = self._invite(self.token_tenant_a, "auditor@team.test", "Auditor")
        self.assertEqual(res_auditor.status_code, 201)

        # Listado del tenant con los 3 miembros (admin + 2 invitados)
        res_list = self.client.get("/api/team/members", headers=headers_a)
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(res_list.get_json()["total"], 3)

        # Tenant B solo ve su propio admin
        res_list_b = self.client.get("/api/team/members", headers=headers_b)
        self.assertEqual(res_list_b.status_code, 200)
        self.assertEqual(res_list_b.get_json()["total"], 1)
        self.assertEqual(
            res_list_b.get_json()["items"][0]["email"], "admin_b@team.test"
        )

        # Validaciones de invitación
        self.assertEqual(
            self._invite(self.token_tenant_a, "user@team.test", "User").status_code,
            409,
        )
        self.assertEqual(
            self._invite(self.token_tenant_b, "user@team.test", "User").status_code,
            409,
        )
        self.assertEqual(
            self._invite(self.token_tenant_a, "super@team.test", "SuperAdmin").status_code,
            400,
        )
        self.assertEqual(
            self._invite(self.token_tenant_a, "bad-email", "User").status_code,
            400,
        )
        self.assertEqual(
            self._invite(
                self.token_tenant_a, "short@team.test", "User", password="123"
            ).status_code,
            400,
        )

        # Cambio de rol permitido
        res_role = self.client.put(
            f"/api/team/members/{user_id}/role",
            json={"role": "Auditor"},
            headers=headers_a,
        )
        self.assertEqual(res_role.status_code, 200)
        self.assertEqual(res_role.get_json()["user"]["role"], "Auditor")

        # Aislamiento: Tenant B no puede modificar ni desactivar a un miembro de A
        res_cross_put = self.client.put(
            f"/api/team/members/{user_id}/role",
            json={"role": "User"},
            headers=headers_b,
        )
        self.assertEqual(res_cross_put.status_code, 404)

        res_cross_delete = self.client.delete(
            f"/api/team/members/{user_id}", headers=headers_b
        )
        self.assertEqual(res_cross_delete.status_code, 404)

    def test_non_admin_cannot_manage_team_or_delete_critical_data(self):
        self.assertEqual(
            self._invite(self.token_tenant_a, "user@team.test", "User").status_code,
            201,
        )
        self.assertEqual(
            self._invite(self.token_tenant_a, "auditor@team.test", "Auditor").status_code,
            201,
        )

        user_token = self._login("user@team.test")
        auditor_token = self._login("auditor@team.test")
        user_headers = self._headers(user_token)
        auditor_headers = self._headers(auditor_token)
        admin_headers = self._headers(self.token_tenant_a)

        # Lectura permitida para roles no administrativos
        self.assertEqual(
            self.client.get("/api/team/members", headers=user_headers).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/team/members", headers=auditor_headers).status_code,
            200,
        )

        # Escrituras de equipo restringidas a TenantAdmin
        self.assertEqual(
            self.client.post(
                "/api/team/invite",
                json={
                    "email": "hacker@team.test",
                    "password": "Password123!",
                    "role": "TenantAdmin",
                },
                headers=user_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(
                f"/api/team/members/{self.admin_a.id}/role",
                json={"role": "User"},
                headers=user_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/team/members/{self.admin_a.id}", headers=auditor_headers
            ).status_code,
            403,
        )

        # Crear transacción con un admin y comprobar que User/Auditor no pueden borrarla
        res_tx = self.client.post(
            "/api/finance/transactions",
            json={
                "type": "expense",
                "amount": 100.0,
                "description": "Gasto protegido",
                "date": "2026-10-15",
            },
            headers=admin_headers,
        )
        self.assertEqual(res_tx.status_code, 201)
        tx_id = res_tx.get_json()["transaction"]["id"]

        self.assertEqual(
            self.client.delete(
                f"/api/finance/transactions/{tx_id}", headers=user_headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/finance/transactions/{tx_id}", headers=auditor_headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/finance/transactions/{tx_id}", headers=admin_headers
            ).status_code,
            200,
        )

        # Sin token -> 401
        self.assertEqual(self.client.get("/api/team/members").status_code, 401)

    def test_self_protection_and_immediate_revocation(self):
        headers_a = self._headers(self.token_tenant_a)

        # No puede cambiarse el rol ni desactivarse a sí mismo
        self.assertEqual(
            self.client.put(
                f"/api/team/members/{self.admin_a.id}/role",
                json={"role": "User"},
                headers=headers_a,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/team/members/{self.admin_a.id}", headers=headers_a
            ).status_code,
            400,
        )

        # Segundo TenantAdmin
        res_admin2 = self._invite(
            self.token_tenant_a, "admin2@team.test", "TenantAdmin"
        )
        self.assertEqual(res_admin2.status_code, 201)
        admin2_id = res_admin2.get_json()["user"]["id"]
        admin2_old_token = self._login("admin2@team.test")
        admin2_old_headers = self._headers(admin2_old_token)

        # Un TenantAdmin de segundo nivel puede gestionar mientras su rol vigente lo permita
        res_invite = self._invite(self.token_tenant_a, "member@team.test", "User")
        self.assertEqual(res_invite.status_code, 201)
        member_id = res_invite.get_json()["user"]["id"]

        # Degradar al segundo admin: el token antiguo conserva el claim TenantAdmin,
        # pero el rol vigente en BD ya no permite gestionar equipo.
        res_demote = self.client.put(
            f"/api/team/members/{admin2_id}/role",
            json={"role": "User"},
            headers=headers_a,
        )
        self.assertEqual(res_demote.status_code, 200)
        self.assertEqual(res_demote.get_json()["user"]["role"], "User")

        res_stale_admin = self.client.put(
            f"/api/team/members/{member_id}/role",
            json={"role": "Auditor"},
            headers=admin2_old_headers,
        )
        self.assertEqual(res_stale_admin.status_code, 403)

        # Desactivación: el token previo deja de servir de inmediato y el login falla
        res_delete = self.client.delete(
            f"/api/team/members/{admin2_id}", headers=headers_a
        )
        self.assertEqual(res_delete.status_code, 200)
        self.assertFalse(res_delete.get_json()["user"]["is_active"])

        self.assertEqual(
            self.client.get("/api/team/members", headers=admin2_old_headers).status_code,
            403,
        )

        login_inactive = self.client.post(
            "/api/auth/login",
            json={"email": "admin2@team.test", "password": "Password123!"},
        )
        self.assertEqual(login_inactive.status_code, 403)

        # El miembro desactivado sigue listado con is_active=False
        res_list = self.client.get("/api/team/members", headers=headers_a)
        members = {item["id"]: item for item in res_list.get_json()["items"]}
        self.assertFalse(members[admin2_id]["is_active"])


if __name__ == "__main__":
    unittest.main()

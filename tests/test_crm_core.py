import unittest
from app import create_app
from app.extensions import db
from app.models.company import Company
from app.models.contact import Contact
from app.models.activity_log import ActivityLog


class CRMCoreSprint1TestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Configurar dos Tenants para probar aislamiento Multi-Tenant
        self.token_tenant_a = self._create_tenant_and_get_token("Tenant A", "admin_a@tenant-a.com")
        self.token_tenant_b = self._create_tenant_and_get_token("Tenant B", "admin_b@tenant-b.com")

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
        res = self.client.post("/api/auth/register-tenant", json=payload)
        self.assertEqual(res.status_code, 201)
        return res.get_json()["access_token"]

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ==========================================
    # TESTS PARA COMPANY
    # ==========================================
    def test_company_crud_and_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # 1. Crear Company en Tenant A
        create_payload = {
            "name": "Empresa Alfa",
            "tax_id": "J-12345678-9",
            "industry": "Tecnología",
            "website": "https://alfa.com",
            "phone": "+584120000000",
        }
        res = self.client.post("/api/companies", json=create_payload, headers=headers_a)
        self.assertEqual(res.status_code, 201)
        company_a = res.get_json()["company"]
        company_a_id = company_a["id"]
        self.assertEqual(company_a["name"], "Empresa Alfa")
        self.assertEqual(company_a["tax_id"], "J-12345678-9")

        # 2. Listar Company en Tenant A -> debe aparecer
        res = self.client.get("/api/companies", headers=headers_a)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["name"], "Empresa Alfa")

        # 3. Listar Company en Tenant B -> NO debe aparecer (aislamiento)
        res_b = self.client.get("/api/companies", headers=headers_b)
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.get_json()
        self.assertEqual(data_b["total"], 0)
        self.assertEqual(len(data_b["items"]), 0)

        # 4. Tenant B intenta consultar detalle de Company de Tenant A -> 404
        res_b_get = self.client.get(f"/api/companies/{company_a_id}", headers=headers_b)
        self.assertEqual(res_b_get.status_code, 404)

        # 5. Tenant A consulta detalle con contactos
        res_a_get = self.client.get(f"/api/companies/{company_a_id}", headers=headers_a)
        self.assertEqual(res_a_get.status_code, 200)
        self.assertIn("contacts", res_a_get.get_json()["company"])

        # 6. Actualizar Company en Tenant A
        res_update = self.client.put(
            f"/api/companies/{company_a_id}",
            json={"name": "Empresa Alfa Modificada", "industry": "Finanzas"},
            headers=headers_a,
        )
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.get_json()["company"]["name"], "Empresa Alfa Modificada")
        self.assertEqual(res_update.get_json()["company"]["industry"], "Finanzas")

        # 7. Tenant B intenta modificar Company de Tenant A -> 404
        res_b_update = self.client.put(
            f"/api/companies/{company_a_id}",
            json={"name": "Hacked"},
            headers=headers_b,
        )
        self.assertEqual(res_b_update.status_code, 404)

        # 8. Eliminar Company en Tenant A
        res_del = self.client.delete(f"/api/companies/{company_a_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 200)

        # Confirmar borrado
        res_check = self.client.get(f"/api/companies/{company_a_id}", headers=headers_a)
        self.assertEqual(res_check.status_code, 404)

    def test_company_search_and_pagination(self):
        headers_a = self._headers(self.token_tenant_a)

        # Crear múltiples empresas
        for i in range(1, 16):
            name = f"Inversiones {i}" if i <= 10 else f"Comercializadora {i}"
            self.client.post("/api/companies", json={"name": name}, headers=headers_a)

        # Búsqueda por "Inversiones"
        res_search = self.client.get("/api/companies?search=Inversiones", headers=headers_a)
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.get_json()["total"], 10)

        # Paginación
        res_page = self.client.get("/api/companies?page=1&per_page=5", headers=headers_a)
        self.assertEqual(res_page.status_code, 200)
        data = res_page.get_json()
        self.assertEqual(len(data["items"]), 5)
        self.assertEqual(data["total"], 15)
        self.assertEqual(data["pages"], 3)

    def test_company_all_flag_bypasses_pagination(self):
        headers_a = self._headers(self.token_tenant_a)

        for i in range(1, 4):
            self.client.post("/api/companies", json={"name": f"Select Co {i}"}, headers=headers_a)

        # all=1 ignora per_page y devuelve todas las empresas
        res_all = self.client.get("/api/companies?all=1&per_page=1", headers=headers_a)
        self.assertEqual(res_all.status_code, 200)
        data = res_all.get_json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["pages"], 1)

        # Orden alfabético para selects
        names = [c["name"] for c in data["items"]]
        self.assertEqual(names, sorted(names))

        # all=1 sigue respetando el filtro search
        res_search = self.client.get("/api/companies?all=1&search=Select Co 2", headers=headers_a)
        self.assertEqual(res_search.get_json()["total"], 1)

        # Sin all=1 la paginación sigue intacta
        res_page = self.client.get("/api/companies?per_page=2", headers=headers_a)
        self.assertEqual(len(res_page.get_json()["items"]), 2)

    def test_delete_company_keeps_contacts_with_null_company(self):
        headers_a = self._headers(self.token_tenant_a)

        res_c = self.client.post("/api/companies", json={"name": "Empresa Borrable"}, headers=headers_a)
        company_id = res_c.get_json()["company"]["id"]

        res_ct = self.client.post(
            "/api/contacts",
            json={"first_name": "Ana", "last_name": "Perez", "company_id": company_id},
            headers=headers_a,
        )
        self.assertEqual(res_ct.status_code, 201)
        contact_id = res_ct.get_json()["contact"]["id"]

        res_del = self.client.delete(f"/api/companies/{company_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 200)

        # El contacto sobrevive y su company_id queda en NULL
        res_check = self.client.get(f"/api/contacts/{contact_id}", headers=headers_a)
        self.assertEqual(res_check.status_code, 200)
        contact = res_check.get_json()["contact"]
        self.assertIsNone(contact["company_id"])
        self.assertIsNone(contact["company"])
        self.assertIsNone(contact["company_name"])

    # ==========================================
    # TESTS PARA CONTACT
    # ==========================================
    def test_contact_crud_and_cross_tenant_protection(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # Crear empresa en Tenant A y en Tenant B
        res_ca = self.client.post("/api/companies", json={"name": "Company A"}, headers=headers_a)
        comp_a_id = res_ca.get_json()["company"]["id"]

        res_cb = self.client.post("/api/companies", json={"name": "Company B"}, headers=headers_b)
        comp_b_id = res_cb.get_json()["company"]["id"]

        # 1. Tenant A intenta crear contacto asociándolo a una empresa de Tenant B -> 400
        res_cross = self.client.post(
            "/api/contacts",
            json={"first_name": "Pedro", "last_name": "Perez", "company_id": comp_b_id},
            headers=headers_a,
        )
        self.assertEqual(res_cross.status_code, 400)

        # 2. Tenant A crea contacto legítimo asociado a Company A
        res_contact = self.client.post(
            "/api/contacts",
            json={
                "first_name": "Pedro",
                "last_name": "Perez",
                "email": "pedro@companya.com",
                "phone": "+584141112233",
                "position": "Gerente de Compras",
                "company_id": comp_a_id,
            },
            headers=headers_a,
        )
        self.assertEqual(res_contact.status_code, 201)
        contact_id = res_contact.get_json()["contact"]["id"]
        self.assertEqual(res_contact.get_json()["contact"]["company_name"], "Company A")

        # 3. Filtrar contactos por company_id
        res_filter = self.client.get(f"/api/contacts?company_id={comp_a_id}", headers=headers_a)
        self.assertEqual(res_filter.status_code, 200)
        self.assertEqual(res_filter.get_json()["total"], 1)

        # 4. Búsqueda por email o nombre
        res_search = self.client.get("/api/contacts?search=pedro@companya.com", headers=headers_a)
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.get_json()["total"], 1)

        # 5. Tenant B no puede ver contacto de Tenant A
        res_b_get = self.client.get(f"/api/contacts/{contact_id}", headers=headers_b)
        self.assertEqual(res_b_get.status_code, 404)

        # 6. Actualizar contacto en Tenant A
        res_upd = self.client.put(
            f"/api/contacts/{contact_id}",
            json={"position": "Director de Operaciones"},
            headers=headers_a,
        )
        self.assertEqual(res_upd.status_code, 200)
        self.assertEqual(res_upd.get_json()["contact"]["position"], "Director de Operaciones")

        # 7. Verificar que Company A incluye a Pedro en su detalle
        res_comp_detail = self.client.get(f"/api/companies/{comp_a_id}", headers=headers_a)
        contacts_in_comp = res_comp_detail.get_json()["company"]["contacts"]
        self.assertEqual(len(contacts_in_comp), 1)
        self.assertEqual(contacts_in_comp[0]["id"], contact_id)

    # ==========================================
    # TESTS PARA ACTIVITYLOG
    # ==========================================
    def test_contact_activities_timeline_and_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # Crear contacto en Tenant A
        res_c = self.client.post("/api/contacts", json={"first_name": "Maria", "last_name": "Lopez"}, headers=headers_a)
        contact_id = res_c.get_json()["contact"]["id"]

        # 1. Registrar actividades válidas
        act1 = self.client.post(
            f"/api/contacts/{contact_id}/activities",
            json={"type": "call", "content": "Primera llamada exploratoria."},
            headers=headers_a,
        )
        self.assertEqual(act1.status_code, 201)
        act1_data = act1.get_json()["activity"]
        self.assertEqual(act1_data["type"], "call")
        self.assertEqual(act1_data["content"], "Primera llamada exploratoria.")
        self.assertEqual(act1_data["user_email"], "admin_a@tenant-a.com")

        act2 = self.client.post(
            f"/api/contacts/{contact_id}/activities",
            json={"type": "meeting", "content": "Reunión de demostración del producto."},
            headers=headers_a,
        )
        self.assertEqual(act2.status_code, 201)

        # 2. Registrar con tipo inválido -> 400
        act_invalid = self.client.post(
            f"/api/contacts/{contact_id}/activities",
            json={"type": "invalid_type", "content": "Contenido test."},
            headers=headers_a,
        )
        self.assertEqual(act_invalid.status_code, 400)

        # 3. Listar timeline de actividades
        res_timeline = self.client.get(f"/api/contacts/{contact_id}/activities", headers=headers_a)
        self.assertEqual(res_timeline.status_code, 200)
        activities = res_timeline.get_json()["activities"]
        self.assertEqual(len(activities), 2)
        # Debe estar ordenado de la más reciente a la más antigua
        self.assertEqual(activities[0]["type"], "meeting")
        self.assertEqual(activities[1]["type"], "call")

        # 4. Tenant B intenta registrar actividad en contacto de Tenant A -> 404
        res_b_act = self.client.post(
            f"/api/contacts/{contact_id}/activities",
            json={"type": "note", "content": "Espionaje industrial"},
            headers=headers_b,
        )
        self.assertEqual(res_b_act.status_code, 404)

        # 5. Tenant B intenta listar actividades del contacto de Tenant A -> 404
        res_b_list = self.client.get(f"/api/contacts/{contact_id}/activities", headers=headers_b)
        self.assertEqual(res_b_list.status_code, 404)

        # 6. Borrar contacto y verificar cascada de actividades
        res_del_contact = self.client.delete(f"/api/contacts/{contact_id}", headers=headers_a)
        self.assertEqual(res_del_contact.status_code, 200)
        self.assertEqual(ActivityLog.query.filter_by(contact_id=contact_id).count(), 0)

    # ==========================================
    # TESTS PARA DASHBOARD STATS
    # ==========================================
    def test_dashboard_stats_counts_and_tenant_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # 1. Sin datos -> conteos en cero
        res_empty = self.client.get("/api/dashboard/stats", headers=headers_a)
        self.assertEqual(res_empty.status_code, 200)
        empty_data = res_empty.get_json()
        self.assertEqual(empty_data["contacts_total"], 0)
        self.assertEqual(empty_data["companies_total"], 0)
        self.assertEqual(empty_data["deals_pipeline_count"], 0)
        self.assertEqual(empty_data["deals_pipeline_value"], 0.0)
        self.assertEqual(empty_data["mrr_estimated"], 0.0)

        # 2. Crear datos solo en Tenant A
        for i in range(3):
            self.client.post("/api/companies", json={"name": f"Empresa Stats {i}"}, headers=headers_a)
        for i in range(2):
            self.client.post(
                "/api/contacts",
                json={"first_name": f"Contacto{i}", "last_name": "Stats"},
                headers=headers_a,
            )

        # Tenant B crea un registro que no debe contar para A
        self.client.post("/api/companies", json={"name": "Empresa Tenant B"}, headers=headers_b)
        self.client.post(
            "/api/contacts",
            json={"first_name": "B", "last_name": "Solamente"},
            headers=headers_b,
        )

        # 3. Tenant A ve sus conteos reales, aislados de B
        res_a = self.client.get("/api/dashboard/stats", headers=headers_a)
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.get_json()
        self.assertEqual(data_a["contacts_total"], 2)
        self.assertEqual(data_a["companies_total"], 3)

        # 4. Tenant B ve los suyos
        res_b = self.client.get("/api/dashboard/stats", headers=headers_b)
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.get_json()
        self.assertEqual(data_b["contacts_total"], 1)
        self.assertEqual(data_b["companies_total"], 1)

        # 5. Sin token -> 401
        res_unauth = self.client.get("/api/dashboard/stats")
        self.assertEqual(res_unauth.status_code, 401)

        # 6. Borra un contacto -> el conteo de A baja a 1
        contacts_res = self.client.get("/api/contacts", headers=headers_a)
        contact_id = contacts_res.get_json()["items"][0]["id"]
        self.client.delete(f"/api/contacts/{contact_id}", headers=headers_a)
        res_after_delete = self.client.get("/api/dashboard/stats", headers=headers_a)
        self.assertEqual(res_after_delete.get_json()["contacts_total"], 1)


if __name__ == "__main__":
    unittest.main()

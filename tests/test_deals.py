import unittest
from datetime import date
from decimal import Decimal
from app import create_app
from app.extensions import db
from app.models.stage import Stage
from app.models.deal import Deal
from app.models.company import Company
from app.models.contact import Contact


class DealsSprint3TestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Configurar dos Tenants para probar aislamiento Multi-Tenant estricto
        self.token_tenant_a = self._create_tenant_and_get_token("Tenant Deals A", "deals_a@test.com")
        self.token_tenant_b = self._create_tenant_and_get_token("Tenant Deals B", "deals_b@test.com")

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

    def _create_company(self, token, name="Empresa Test"):
        res = self.client.post(
            "/api/companies",
            json={"name": name, "industry": "Tecnología"},
            headers=self._headers(token),
        )
        self.assertEqual(res.status_code, 201)
        return res.get_json()["company"]

    def _create_contact(self, token, company_id, first_name="Juan", email="juan@test.com"):
        res = self.client.post(
            "/api/contacts",
            json={
                "company_id": company_id,
                "first_name": first_name,
                "last_name": "Pérez",
                "email": email,
            },
            headers=self._headers(token),
        )
        self.assertEqual(res.status_code, 201)
        return res.get_json()["contact"]

    # ==========================================
    # TESTS PARA STAGES
    # ==========================================
    def test_stage_auto_seed_and_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # 1. Tenant A consulta stages por primera vez -> debe auto-inicializar 6 etapas
        res_a = self.client.get("/api/deals/stages", headers=headers_a)
        self.assertEqual(res_a.status_code, 200)
        stages_a = res_a.get_json()
        self.assertEqual(len(stages_a), 6)
        self.assertEqual(stages_a[0]["name"], "Prospección")
        self.assertEqual(stages_a[0]["order"], 1)
        self.assertEqual(stages_a[0]["probability"], 10)
        self.assertEqual(stages_a[4]["name"], "Cerrado Ganado")
        self.assertEqual(stages_a[4]["probability"], 100)
        self.assertEqual(stages_a[5]["name"], "Cerrado Perdido")
        self.assertEqual(stages_a[5]["probability"], 0)

        # 2. Tenant B consulta stages -> debe obtener sus propias 6 etapas aisladas
        res_b = self.client.get("/api/deals/stages", headers=headers_b)
        self.assertEqual(res_b.status_code, 200)
        stages_b = res_b.get_json()
        self.assertEqual(len(stages_b), 6)

        # Verificar que los IDs de etapas no se compartan entre tenants
        ids_a = {s["id"] for s in stages_a}
        ids_b = {s["id"] for s in stages_b}
        self.assertTrue(ids_a.isdisjoint(ids_b))

    def test_stage_custom_creation_and_update(self):
        headers_a = self._headers(self.token_tenant_a)

        # Crear etapa personalizada
        res = self.client.post(
            "/api/deals/stages",
            json={"name": "Demostración Técnica", "order": 2, "probability": 40},
            headers=headers_a,
        )
        self.assertEqual(res.status_code, 201)
        stage = res.get_json()["stage"]
        self.assertEqual(stage["name"], "Demostración Técnica")
        self.assertEqual(stage["probability"], 40)
        stage_id = stage["id"]

        # Actualizar etapa
        res_up = self.client.put(
            f"/api/deals/stages/{stage_id}",
            json={"probability": 45, "name": "Demo Realizada"},
            headers=headers_a,
        )
        self.assertEqual(res_up.status_code, 200)
        updated_stage = res_up.get_json()["stage"]
        self.assertEqual(updated_stage["probability"], 45)
        self.assertEqual(updated_stage["name"], "Demo Realizada")

        # Eliminar etapa vacía
        res_del = self.client.delete(f"/api/deals/stages/{stage_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 200)

    # ==========================================
    # TESTS PARA DEALS (CRUD, VALIDACIONES Y MULTI-TENANCY)
    # ==========================================
    def test_deal_creation_and_tenant_validation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # Configurar entidades para Tenant A
        company_a = self._create_company(self.token_tenant_a, "Empresa Alpha")
        contact_a = self._create_contact(self.token_tenant_a, company_a["id"], "Carlos")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()
        stage_a_id = stages_a[0]["id"]

        # Configurar entidades para Tenant B
        company_b = self._create_company(self.token_tenant_b, "Empresa Beta")
        stages_b = self.client.get("/api/deals/stages", headers=headers_b).get_json()
        stage_b_id = stages_b[0]["id"]

        # Intento de Tenant A usando Company de Tenant B -> 400
        bad_payload = {
            "title": "Trato Ilegal",
            "company_id": company_b["id"],
            "stage_id": stage_a_id,
            "value": 5000.0,
        }
        res_bad = self.client.post("/api/deals", json=bad_payload, headers=headers_a)
        self.assertEqual(res_bad.status_code, 400)

        # Intento de Tenant A usando Stage de Tenant B -> 400
        bad_payload_stage = {
            "title": "Trato Ilegal Etapa",
            "company_id": company_a["id"],
            "stage_id": stage_b_id,
            "value": 5000.0,
        }
        res_bad_stage = self.client.post("/api/deals", json=bad_payload_stage, headers=headers_a)
        self.assertEqual(res_bad_stage.status_code, 400)

        # Creación exitosa en Tenant A
        valid_payload = {
            "title": "Implementación CRM Enterprise",
            "company_id": company_a["id"],
            "contact_id": contact_a["id"],
            "stage_id": stage_a_id,
            "value": 15000.50,
            "expected_close_date": "2026-12-15",
            "status": "open",
        }
        res_ok = self.client.post("/api/deals", json=valid_payload, headers=headers_a)
        self.assertEqual(res_ok.status_code, 201)
        deal_data = res_ok.get_json()["deal"]
        self.assertEqual(deal_data["title"], "Implementación CRM Enterprise")
        self.assertEqual(deal_data["value"], 15000.50)
        self.assertEqual(deal_data["company_name"], "Empresa Alpha")
        self.assertEqual(deal_data["contact_name"], "Carlos Pérez")
        self.assertEqual(deal_data["stage_name"], "Prospección")
        self.assertEqual(deal_data["status"], "open")

    def test_deal_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        company_a = self._create_company(self.token_tenant_a, "Empresa Aislada")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        res_create = self.client.post(
            "/api/deals",
            json={
                "title": "Trato Secreto A",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 25000.0,
            },
            headers=headers_a,
        )
        deal_a_id = res_create.get_json()["deal"]["id"]

        # Tenant B no debe ver el trato en su listado
        res_b_list = self.client.get("/api/deals", headers=headers_b)
        self.assertEqual(res_b_list.status_code, 200)
        self.assertEqual(res_b_list.get_json()["total"], 0)

        # Tenant B no puede consultar por ID
        res_b_get = self.client.get(f"/api/deals/{deal_a_id}", headers=headers_b)
        self.assertEqual(res_b_get.status_code, 404)

        # Tenant B no puede modificarlo
        res_b_put = self.client.put(
            f"/api/deals/{deal_a_id}",
            json={"title": "Hackeado"},
            headers=headers_b,
        )
        self.assertEqual(res_b_put.status_code, 404)

        # Tenant B no puede moverlo
        res_b_move = self.client.patch(
            f"/api/deals/{deal_a_id}/move",
            json={"status": "lost"},
            headers=headers_b,
        )
        self.assertEqual(res_b_move.status_code, 404)

        # Tenant B no puede eliminarlo
        res_b_del = self.client.delete(f"/api/deals/{deal_a_id}", headers=headers_b)
        self.assertEqual(res_b_del.status_code, 404)

    def test_deal_filters_and_kanban_grouping(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Corporación Alfa")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        # Crear 3 tratos en distintas etapas y estados
        self.client.post(
            "/api/deals",
            json={
                "title": "Proyecto Alpha 1",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 5000.0,
                "status": "open",
            },
            headers=headers_a,
        )
        self.client.post(
            "/api/deals",
            json={
                "title": "Proyecto Alpha 2",
                "company_id": company_a["id"],
                "stage_id": stages_a[1]["id"],
                "value": 10000.0,
                "status": "won",
            },
            headers=headers_a,
        )

        # 1. Filtro por status
        res_filter_status = self.client.get("/api/deals?status=won", headers=headers_a)
        self.assertEqual(res_filter_status.status_code, 200)
        self.assertEqual(res_filter_status.get_json()["total"], 1)
        self.assertEqual(res_filter_status.get_json()["items"][0]["title"], "Proyecto Alpha 2")

        # 2. Filtro por búsqueda
        res_search = self.client.get("/api/deals?search=Alpha 1", headers=headers_a)
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.get_json()["total"], 1)

        # 3. Vista agrupada para Kanban
        res_kanban = self.client.get("/api/deals?grouped=true", headers=headers_a)
        self.assertEqual(res_kanban.status_code, 200)
        kanban_stages = res_kanban.get_json()["stages"]
        self.assertEqual(len(kanban_stages), 6)

        # Primer etapa tiene 1 trato de 5000
        stage_0 = kanban_stages[0]
        self.assertEqual(stage_0["total_deals"], 1)
        self.assertEqual(stage_0["total_value"], 5000.0)
        self.assertEqual(len(stage_0["deals"]), 1)

    def test_deal_move_endpoint(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Compañía Movimientos")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        # Crear trato en etapa 0 (Prospección)
        res_deal = self.client.post(
            "/api/deals",
            json={
                "title": "Trato a Mover",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 20000.0,
                "status": "open",
            },
            headers=headers_a,
        )
        deal_id = res_deal.get_json()["deal"]["id"]

        # Mover trato a etapa 4 ("Cerrado Ganado") -> auto status a 'won'
        stage_won = stages_a[4]  # Cerrado Ganado
        res_move = self.client.patch(
            f"/api/deals/{deal_id}/move",
            json={"stage_id": stage_won["id"]},
            headers=headers_a,
        )
        self.assertEqual(res_move.status_code, 200)
        moved_deal = res_move.get_json()["deal"]
        self.assertEqual(moved_deal["stage_id"], stage_won["id"])
        self.assertEqual(moved_deal["status"], "won")

        # Mover con status explícito a lost
        stage_lost = stages_a[5]  # Cerrado Perdido
        res_move_lost = self.client.patch(
            f"/api/deals/{deal_id}/move",
            json={"stage_id": stage_lost["id"], "status": "lost"},
            headers=headers_a,
        )
        self.assertEqual(res_move_lost.status_code, 200)
        self.assertEqual(res_move_lost.get_json()["deal"]["status"], "lost")

    def test_stage_delete_prevented_with_deals(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Empresa Bloqueo")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()
        stage_id = stages_a[0]["id"]

        # Crear deal en esta etapa
        self.client.post(
            "/api/deals",
            json={
                "title": "Trato en Etapa",
                "company_id": company_a["id"],
                "stage_id": stage_id,
                "value": 1000.0,
            },
            headers=headers_a,
        )

        # Intentar eliminar etapa -> debe rechazar con 409
        res_del = self.client.delete(f"/api/deals/stages/{stage_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 409)

    # ==========================================
    # TESTS PARA FORECAST COMERCIAL
    # ==========================================
    def test_deal_forecast_metrics(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        company_a = self._create_company(self.token_tenant_a, "Forecast Corp")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        # Etapa 0: Prospección (prob: 10%)
        # Etapa 1: Calificado (prob: 25%)
        # Etapa 2: Propuesta Enviada (prob: 50%)
        # Etapa 4: Cerrado Ganado (prob: 100%)

        today_str = date.today().isoformat()

        # Deal 1 (Open): $10,000 en Prospección (10%) -> Ponderado: $1,000
        self.client.post(
            "/api/deals",
            json={
                "title": "Deal 1",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 10000.0,
                "status": "open",
            },
            headers=headers_a,
        )

        # Deal 2 (Open): $20,000 en Propuesta Enviada (50%) -> Ponderado: $10,000
        self.client.post(
            "/api/deals",
            json={
                "title": "Deal 2",
                "company_id": company_a["id"],
                "stage_id": stages_a[2]["id"],
                "value": 20000.0,
                "status": "open",
            },
            headers=headers_a,
        )

        # Deal 3 (Won): $12,500 en Cerrado Ganado este mes
        self.client.post(
            "/api/deals",
            json={
                "title": "Deal 3 Won",
                "company_id": company_a["id"],
                "stage_id": stages_a[4]["id"],
                "value": 12500.0,
                "expected_close_date": today_str,
                "status": "won",
            },
            headers=headers_a,
        )

        # Deal 4 (Lost): $8,000 en Cerrado Perdido
        self.client.post(
            "/api/deals",
            json={
                "title": "Deal 4 Lost",
                "company_id": company_a["id"],
                "stage_id": stages_a[5]["id"],
                "value": 8000.0,
                "status": "lost",
            },
            headers=headers_a,
        )

        # Tenant B crea un deal de $99,000 para verificar que no afecte el forecast de A
        company_b = self._create_company(self.token_tenant_b, "Company B Forecast")
        stages_b = self.client.get("/api/deals/stages", headers=headers_b).get_json()
        self.client.post(
            "/api/deals",
            json={
                "title": "Deal Tenant B",
                "company_id": company_b["id"],
                "stage_id": stages_b[0]["id"],
                "value": 99000.0,
                "status": "open",
            },
            headers=headers_b,
        )

        # Consultar forecast de Tenant A
        res_forecast = self.client.get("/api/deals/forecast", headers=headers_a)
        self.assertEqual(res_forecast.status_code, 200)
        data = res_forecast.get_json()

        # Validación métrica:
        # Total abierto = 10,000 + 20,000 = 30,000.00
        self.assertEqual(data["total_open_value"], 30000.0)

        # Total ganado mes actual = 12,500.00
        self.assertEqual(data["total_won_month"], 12500.0)

        # Ponderado = (10,000 * 0.10) + (20,000 * 0.50) = 1,000 + 10,000 = 11,000.00
        self.assertEqual(data["weighted_pipeline_value"], 11000.0)

        # Conteo de tratos
        self.assertEqual(data["counts"]["open"], 2)
        self.assertEqual(data["counts"]["won"], 1)
        self.assertEqual(data["counts"]["lost"], 1)
        self.assertEqual(data["counts"]["total"], 4)

        # Desglose por etapas presente y ordenado
        self.assertEqual(len(data["stage_breakdown"]), 6)

    def test_deal_update_and_delete(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Empresa Update")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        res_create = self.client.post(
            "/api/deals",
            json={
                "title": "Trato Inicial",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 3000.0,
            },
            headers=headers_a,
        )
        deal_id = res_create.get_json()["deal"]["id"]

        # Actualizar via PUT
        res_put = self.client.put(
            f"/api/deals/{deal_id}",
            json={
                "title": "Trato Modificado",
                "value": 4500.0,
                "status": "won",
            },
            headers=headers_a,
        )
        self.assertEqual(res_put.status_code, 200)
        updated = res_put.get_json()["deal"]
        self.assertEqual(updated["title"], "Trato Modificado")
        self.assertEqual(updated["value"], 4500.0)
        self.assertEqual(updated["status"], "won")

        # Eliminar trato via DELETE
        res_del = self.client.delete(f"/api/deals/{deal_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 200)

        # Consultar de nuevo -> 404
        res_get = self.client.get(f"/api/deals/{deal_id}", headers=headers_a)
        self.assertEqual(res_get.status_code, 404)


if __name__ == "__main__":
    unittest.main()

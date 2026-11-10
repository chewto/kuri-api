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

        # Set up two tenants to test strict Multi-Tenant isolation
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

    def _create_company(self, token, name="Test Company"):
        res = self.client.post(
            "/api/companies",
            json={"name": name, "industry": "Technology"},
            headers=self._headers(token),
        )
        self.assertEqual(res.status_code, 201)
        return res.get_json()["company"]

    def _create_contact(self, token, company_id, first_name="John", email="juan@test.com"):
        res = self.client.post(
            "/api/contacts",
            json={
                "company_id": company_id,
                "first_name": first_name,
                "last_name": "Perez",
                "email": email,
            },
            headers=self._headers(token),
        )
        self.assertEqual(res.status_code, 201)
        return res.get_json()["contact"]

    # ==========================================
    # STAGE TESTS
    # ==========================================
    def test_stage_auto_seed_and_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # 1. Tenant A fetches stages for the first time -> it should auto-seed 6 stages
        res_a = self.client.get("/api/deals/stages", headers=headers_a)
        self.assertEqual(res_a.status_code, 200)
        stages_a = res_a.get_json()
        self.assertEqual(len(stages_a), 6)
        self.assertEqual(stages_a[0]["name"], "Prospecting")
        self.assertEqual(stages_a[0]["order"], 1)
        self.assertEqual(stages_a[0]["probability"], 10)
        self.assertEqual(stages_a[4]["name"], "Closed Won")
        self.assertEqual(stages_a[4]["probability"], 100)
        self.assertEqual(stages_a[5]["name"], "Closed Lost")
        self.assertEqual(stages_a[5]["probability"], 0)

        # 2. Tenant B fetches stages -> it should get its own isolated 6 stages
        res_b = self.client.get("/api/deals/stages", headers=headers_b)
        self.assertEqual(res_b.status_code, 200)
        stages_b = res_b.get_json()
        self.assertEqual(len(stages_b), 6)

        # Verify that stage IDs are not shared between tenants
        ids_a = {s["id"] for s in stages_a}
        ids_b = {s["id"] for s in stages_b}
        self.assertTrue(ids_a.isdisjoint(ids_b))

    def test_stage_custom_creation_and_update(self):
        headers_a = self._headers(self.token_tenant_a)

        # Create a custom stage
        res = self.client.post(
            "/api/deals/stages",
            json={"name": "Technical Demo", "order": 2, "probability": 40},
            headers=headers_a,
        )
        self.assertEqual(res.status_code, 201)
        stage = res.get_json()["stage"]
        self.assertEqual(stage["name"], "Technical Demo")
        self.assertEqual(stage["probability"], 40)
        stage_id = stage["id"]

        # Update the stage
        res_up = self.client.put(
            f"/api/deals/stages/{stage_id}",
            json={"probability": 45, "name": "Demo Completed"},
            headers=headers_a,
        )
        self.assertEqual(res_up.status_code, 200)
        updated_stage = res_up.get_json()["stage"]
        self.assertEqual(updated_stage["probability"], 45)
        self.assertEqual(updated_stage["name"], "Demo Completed")

        # Delete the empty stage
        res_del = self.client.delete(f"/api/deals/stages/{stage_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 200)

    # ==========================================
    # DEALS TESTS (CRUD, VALIDATIONS, AND MULTI-TENANCY)
    # ==========================================
    def test_deal_creation_and_tenant_validation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # Set up entities for Tenant A
        company_a = self._create_company(self.token_tenant_a, "Alpha Company")
        contact_a = self._create_contact(self.token_tenant_a, company_a["id"], "Carlos")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()
        stage_a_id = stages_a[0]["id"]

        # Set up entities for Tenant B
        company_b = self._create_company(self.token_tenant_b, "Beta Company")
        stages_b = self.client.get("/api/deals/stages", headers=headers_b).get_json()
        stage_b_id = stages_b[0]["id"]

        # Tenant A tries to use a Tenant B company -> 400
        bad_payload = {
            "title": "Illegal Deal",
            "company_id": company_b["id"],
            "stage_id": stage_a_id,
            "value": 5000.0,
        }
        res_bad = self.client.post("/api/deals", json=bad_payload, headers=headers_a)
        self.assertEqual(res_bad.status_code, 400)

        # Tenant A tries to use a Tenant B stage -> 400
        bad_payload_stage = {
            "title": "Illegal Stage Deal",
            "company_id": company_a["id"],
            "stage_id": stage_b_id,
            "value": 5000.0,
        }
        res_bad_stage = self.client.post("/api/deals", json=bad_payload_stage, headers=headers_a)
        self.assertEqual(res_bad_stage.status_code, 400)

        # Successful creation in Tenant A
        valid_payload = {
            "title": "Enterprise CRM Implementation",
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
        self.assertEqual(deal_data["title"], "Enterprise CRM Implementation")
        self.assertEqual(deal_data["value"], 15000.50)
        self.assertEqual(deal_data["company_name"], "Alpha Company")
        self.assertEqual(deal_data["contact_name"], "Carlos Perez")
        self.assertEqual(deal_data["stage_name"], "Prospecting")
        self.assertEqual(deal_data["status"], "open")

    def test_deal_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        company_a = self._create_company(self.token_tenant_a, "Isolated Company")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        res_create = self.client.post(
            "/api/deals",
            json={
                "title": "Secret Deal A",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 25000.0,
            },
            headers=headers_a,
        )
        deal_a_id = res_create.get_json()["deal"]["id"]

        # Tenant B must not see the deal in its listing
        res_b_list = self.client.get("/api/deals", headers=headers_b)
        self.assertEqual(res_b_list.status_code, 200)
        self.assertEqual(res_b_list.get_json()["total"], 0)

        # Tenant B cannot fetch it by ID
        res_b_get = self.client.get(f"/api/deals/{deal_a_id}", headers=headers_b)
        self.assertEqual(res_b_get.status_code, 404)

        # Tenant B cannot update it
        res_b_put = self.client.put(
            f"/api/deals/{deal_a_id}",
            json={"title": "Hacked"},
            headers=headers_b,
        )
        self.assertEqual(res_b_put.status_code, 404)

        # Tenant B cannot move it
        res_b_move = self.client.patch(
            f"/api/deals/{deal_a_id}/move",
            json={"status": "lost"},
            headers=headers_b,
        )
        self.assertEqual(res_b_move.status_code, 404)

        # Tenant B cannot delete it
        res_b_del = self.client.delete(f"/api/deals/{deal_a_id}", headers=headers_b)
        self.assertEqual(res_b_del.status_code, 404)

    def test_deal_filters_and_kanban_grouping(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Alpha Corporation")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        # Create 3 deals in different stages and statuses
        self.client.post(
            "/api/deals",
            json={
                "title": "Project Alpha 1",
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
                "title": "Project Alpha 2",
                "company_id": company_a["id"],
                "stage_id": stages_a[1]["id"],
                "value": 10000.0,
                "status": "won",
            },
            headers=headers_a,
        )

        # 1. Filter by status
        res_filter_status = self.client.get("/api/deals?status=won", headers=headers_a)
        self.assertEqual(res_filter_status.status_code, 200)
        self.assertEqual(res_filter_status.get_json()["total"], 1)
        self.assertEqual(res_filter_status.get_json()["items"][0]["title"], "Project Alpha 2")

        # 2. Filter by search
        res_search = self.client.get("/api/deals?search=Alpha 1", headers=headers_a)
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.get_json()["total"], 1)

        # 3. Grouped view for Kanban
        res_kanban = self.client.get("/api/deals?grouped=true", headers=headers_a)
        self.assertEqual(res_kanban.status_code, 200)
        kanban_stages = res_kanban.get_json()["stages"]
        self.assertEqual(len(kanban_stages), 6)

        # First stage has 1 deal worth 5000
        stage_0 = kanban_stages[0]
        self.assertEqual(stage_0["total_deals"], 1)
        self.assertEqual(stage_0["total_value"], 5000.0)
        self.assertEqual(len(stage_0["deals"]), 1)

    def test_deal_move_endpoint(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Movements Company")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        # Create a deal in stage 0 (Prospecting)
        res_deal = self.client.post(
            "/api/deals",
            json={
                "title": "Deal to Move",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 20000.0,
                "status": "open",
            },
            headers=headers_a,
        )
        deal_id = res_deal.get_json()["deal"]["id"]

        # Move the deal to stage 4 ("Closed Won") -> status auto-set to 'won'
        stage_won = stages_a[4]  # Closed Won
        res_move = self.client.patch(
            f"/api/deals/{deal_id}/move",
            json={"stage_id": stage_won["id"]},
            headers=headers_a,
        )
        self.assertEqual(res_move.status_code, 200)
        moved_deal = res_move.get_json()["deal"]
        self.assertEqual(moved_deal["stage_id"], stage_won["id"])
        self.assertEqual(moved_deal["status"], "won")

        # Move with explicit status to lost
        stage_lost = stages_a[5]  # Closed Lost
        res_move_lost = self.client.patch(
            f"/api/deals/{deal_id}/move",
            json={"stage_id": stage_lost["id"], "status": "lost"},
            headers=headers_a,
        )
        self.assertEqual(res_move_lost.status_code, 200)
        self.assertEqual(res_move_lost.get_json()["deal"]["status"], "lost")

    def test_stage_delete_prevented_with_deals(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Blocking Company")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()
        stage_id = stages_a[0]["id"]

        # Create a deal in this stage
        self.client.post(
            "/api/deals",
            json={
                "title": "Deal in Stage",
                "company_id": company_a["id"],
                "stage_id": stage_id,
                "value": 1000.0,
            },
            headers=headers_a,
        )

        # Try to delete the stage -> it must be rejected with 409
        res_del = self.client.delete(f"/api/deals/stages/{stage_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 409)

    # ==========================================
    # SALES FORECAST TESTS
    # ==========================================
    def test_deal_forecast_metrics(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        company_a = self._create_company(self.token_tenant_a, "Forecast Corp")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        # Stage 0: Prospecting (prob: 10%)
        # Stage 1: Qualified (prob: 25%)
        # Stage 2: Proposal Sent (prob: 50%)
        # Stage 4: Closed Won (prob: 100%)

        today_str = date.today().isoformat()

        # Deal 1 (Open): $10,000 in Prospecting (10%) -> Weighted: $1,000
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

        # Deal 2 (Open): $20,000 in Proposal Sent (50%) -> Weighted: $10,000
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

        # Deal 3 (Won): $12,500 in Closed Won this month
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

        # Deal 4 (Lost): $8,000 in Closed Lost
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

        # Tenant B creates a $99,000 deal to verify it does not affect Tenant A's forecast
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

        # Fetch Tenant A's forecast
        res_forecast = self.client.get("/api/deals/forecast", headers=headers_a)
        self.assertEqual(res_forecast.status_code, 200)
        data = res_forecast.get_json()

        # Metric validation:
        # Total open = 10,000 + 20,000 = 30,000.00
        self.assertEqual(data["total_open_value"], 30000.0)

        # Total won this month = 12,500.00
        self.assertEqual(data["total_won_month"], 12500.0)

        # Weighted = (10,000 * 0.10) + (20,000 * 0.50) = 1,000 + 10,000 = 11,000.00
        self.assertEqual(data["weighted_pipeline_value"], 11000.0)

        # Deal counts
        self.assertEqual(data["counts"]["open"], 2)
        self.assertEqual(data["counts"]["won"], 1)
        self.assertEqual(data["counts"]["lost"], 1)
        self.assertEqual(data["counts"]["total"], 4)

        # Stage breakdown is present and ordered
        self.assertEqual(len(data["stage_breakdown"]), 6)

    def test_deal_update_and_delete(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Update Company")
        stages_a = self.client.get("/api/deals/stages", headers=headers_a).get_json()

        res_create = self.client.post(
            "/api/deals",
            json={
                "title": "Initial Deal",
                "company_id": company_a["id"],
                "stage_id": stages_a[0]["id"],
                "value": 3000.0,
            },
            headers=headers_a,
        )
        deal_id = res_create.get_json()["deal"]["id"]

        # Update via PUT
        res_put = self.client.put(
            f"/api/deals/{deal_id}",
            json={
                "title": "Modified Deal",
                "value": 4500.0,
                "status": "won",
            },
            headers=headers_a,
        )
        self.assertEqual(res_put.status_code, 200)
        updated = res_put.get_json()["deal"]
        self.assertEqual(updated["title"], "Modified Deal")
        self.assertEqual(updated["value"], 4500.0)
        self.assertEqual(updated["status"], "won")

        # Delete the deal via DELETE
        res_del = self.client.delete(f"/api/deals/{deal_id}", headers=headers_a)
        self.assertEqual(res_del.status_code, 200)

        # Fetch again -> 404
        res_get = self.client.get(f"/api/deals/{deal_id}", headers=headers_a)
        self.assertEqual(res_get.status_code, 404)


if __name__ == "__main__":
    unittest.main()

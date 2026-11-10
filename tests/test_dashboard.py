import unittest
from app import create_app
from app.extensions import db
from app.models.stage import Stage
from app.models.deal import Deal
from app.models.subscription import Subscription


class DashboardStatsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.token_tenant_a = self._create_tenant_and_get_token("Tenant A", "dash_a@test.com")
        self.token_tenant_b = self._create_tenant_and_get_token("Tenant B", "dash_b@test.com")

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

    def _create_contact(self, token, company_id, first_name="Jane", last_name="Doe"):
        res = self.client.post(
            "/api/contacts",
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": f"{first_name.lower()}@test.com",
                "company_id": company_id,
            },
            headers=self._headers(token),
        )
        self.assertEqual(res.status_code, 201)
        return res.get_json()["contact"]

    def test_dashboard_stats_empty(self):
        res = self.client.get("/api/dashboard/stats", headers=self._headers(self.token_tenant_a))
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["contacts_total"], 0)
        self.assertEqual(data["companies_total"], 0)
        self.assertEqual(data["deals_pipeline_count"], 0)
        self.assertEqual(data["deals_pipeline_value"], 0.0)
        self.assertEqual(data["deals_won_count"], 0)
        self.assertEqual(data["deals_won_value"], 0.0)
        self.assertEqual(data["mrr_estimated"], 0.0)

    def test_dashboard_stats_with_deals_and_subscriptions(self):
        headers_a = self._headers(self.token_tenant_a)
        company_a = self._create_company(self.token_tenant_a, "Acme Inc")
        self._create_contact(self.token_tenant_a, company_a["id"], "John", "Smith")

        # Get default stages for tenant A
        stages_res = self.client.get("/api/deals/stages", headers=headers_a)
        self.assertEqual(stages_res.status_code, 200)
        stage_id = stages_res.get_json()[0]["id"]

        # Create Open deals
        res_d1 = self.client.post(
            "/api/deals",
            json={
                "title": "Open Deal 1",
                "value": 1500.0,
                "stage_id": stage_id,
                "company_id": company_a["id"],
                "status": "open",
            },
            headers=headers_a,
        )
        self.assertEqual(res_d1.status_code, 201)

        res_d2 = self.client.post(
            "/api/deals",
            json={
                "title": "Open Deal 2",
                "value": 2500.5,
                "stage_id": stage_id,
                "company_id": company_a["id"],
                "status": "open",
            },
            headers=headers_a,
        )
        self.assertEqual(res_d2.status_code, 201)

        # Create Won deal (Revenue Generated)
        res_dw = self.client.post(
            "/api/deals",
            json={
                "title": "Won Deal",
                "value": 5000.0,
                "stage_id": stage_id,
                "company_id": company_a["id"],
                "status": "won",
            },
            headers=headers_a,
        )
        self.assertEqual(res_dw.status_code, 201)

        # Create Lost deal (Ignored from pipeline & won)
        res_dl = self.client.post(
            "/api/deals",
            json={
                "title": "Lost Deal",
                "value": 9000.0,
                "stage_id": stage_id,
                "company_id": company_a["id"],
                "status": "lost",
            },
            headers=headers_a,
        )
        self.assertEqual(res_dl.status_code, 201)

        # Create Active Subscriptions for MRR
        res_s1 = self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Slack Pro",
                "cost": 100.0,
                "billing_cycle": "monthly",
                "next_billing_date": "2026-12-01",
                "status": "active",
            },
            headers=headers_a,
        )
        self.assertEqual(res_s1.status_code, 201)

        res_s2 = self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Annual Cloud",
                "cost": 1200.0,
                "billing_cycle": "yearly",
                "next_billing_date": "2026-12-01",
                "status": "active",
            },
            headers=headers_a,
        )
        self.assertEqual(res_s2.status_code, 201)

        # Create a Cancelled Subscription (should be excluded from active MRR)
        res_s3 = self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Old Tool",
                "cost": 500.0,
                "billing_cycle": "monthly",
                "next_billing_date": "2026-12-01",
                "status": "cancelled",
            },
            headers=headers_a,
        )
        self.assertEqual(res_s3.status_code, 201)

        # Verify Dashboard stats for Tenant A
        dash_res = self.client.get("/api/dashboard/stats", headers=headers_a)
        self.assertEqual(dash_res.status_code, 200)
        data = dash_res.get_json()

        self.assertEqual(data["contacts_total"], 1)
        self.assertEqual(data["companies_total"], 1)
        self.assertEqual(data["deals_pipeline_count"], 2)
        self.assertEqual(data["deals_pipeline_value"], 4000.5)
        self.assertEqual(data["deals_won_count"], 1)
        self.assertEqual(data["deals_won_value"], 5000.0)
        self.assertEqual(data["mrr_estimated"], 200.0)

        # Verify Multi-tenant isolation: Tenant B should still have zeroes
        dash_b = self.client.get("/api/dashboard/stats", headers=self._headers(self.token_tenant_b))
        self.assertEqual(dash_b.status_code, 200)
        data_b = dash_b.get_json()
        self.assertEqual(data_b["contacts_total"], 0)
        self.assertEqual(data_b["deals_pipeline_count"], 0)
        self.assertEqual(data_b["deals_pipeline_value"], 0.0)
        self.assertEqual(data_b["deals_won_count"], 0)
        self.assertEqual(data_b["deals_won_value"], 0.0)
        self.assertEqual(data_b["mrr_estimated"], 0.0)


if __name__ == "__main__":
    unittest.main()

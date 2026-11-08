import unittest
from datetime import date, datetime, timezone
from app import create_app
from app.extensions import db
from app.models.category import Category
from app.models.company import Company
from app.models.deal import Deal
from app.models.stage import Stage
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User


class AnalyticsSprint4TestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.token_tenant_a = self._create_tenant_and_get_token(
            "Tenant Analytics A", "admin_a@analytics.test"
        )
        self.token_tenant_b = self._create_tenant_and_get_token(
            "Tenant Analytics B", "admin_b@analytics.test"
        )
        self.token_tenant_c = self._create_tenant_and_get_token(
            "Tenant Analytics C", "admin_c@analytics.test"
        )

        self.tenant_a_id = self._tenant_id("admin_a@analytics.test")
        self.tenant_b_id = self._tenant_id("admin_b@analytics.test")
        self.tenant_c_id = self._tenant_id("admin_c@analytics.test")

        self._seed_tenant_a()
        self._seed_tenant_b()

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

    def _tenant_id(self, email):
        user = User.query.filter_by(email=email).first()
        return user.tenant_id

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _seed_tenant_a(self):
        tenant_id = self.tenant_a_id

        category_infra = Category(tenant_id=tenant_id, name="Infraestructura", color="#6366F1")
        category_sales = Category(tenant_id=tenant_id, name="Ventas", color="#F59E0B")
        company = Company(tenant_id=tenant_id, name="Cliente A")
        stage = Stage(tenant_id=tenant_id, name="Cerrado Ganado", order=1, probability=100)
        db.session.add_all([category_infra, category_sales, company, stage])
        db.session.flush()

        deals = [
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal octubre 1",
                value=5000.0,
                status="won",
                expected_close_date=date(2026, 10, 10),
            ),
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal octubre 2",
                value=2000.0,
                status="won",
                expected_close_date=date(2026, 10, 20),
            ),
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal noviembre",
                value=999.0,
                status="won",
                expected_close_date=date(2026, 11, 5),
            ),
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal sin fecha esperada",
                value=500.0,
                status="won",
                expected_close_date=None,
                created_at=datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc),
            ),
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal abierto",
                value=1000.0,
                status="open",
            ),
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal perdido",
                value=500.0,
                status="lost",
            ),
        ]
        db.session.add_all(deals)

        subscriptions = [
            Subscription(
                tenant_id=tenant_id,
                category_id=category_infra.id,
                name="Suscripción mensual",
                cost=20.0,
                billing_cycle="monthly",
                next_billing_date=date(2026, 11, 1),
                status="active",
            ),
            Subscription(
                tenant_id=tenant_id,
                category_id=category_infra.id,
                name="Suscripción anual",
                cost=1200.0,
                billing_cycle="yearly",
                next_billing_date=date(2027, 1, 1),
                status="active",
            ),
            Subscription(
                tenant_id=tenant_id,
                category_id=category_sales.id,
                name="Suscripción trimestral",
                cost=60.0,
                billing_cycle="quarterly",
                next_billing_date=date(2026, 12, 1),
                status="active",
            ),
            Subscription(
                tenant_id=tenant_id,
                category_id=category_sales.id,
                name="Suscripción pausada",
                cost=50.0,
                billing_cycle="monthly",
                next_billing_date=date(2026, 11, 1),
                status="paused",
            ),
        ]
        db.session.add_all(subscriptions)

        transactions = [
            Transaction(
                tenant_id=tenant_id,
                category_id=category_infra.id,
                type="expense",
                amount=300.0,
                description="Gasto infraestructura",
                date=date(2026, 10, 12),
            ),
            Transaction(
                tenant_id=tenant_id,
                category_id=None,
                type="expense",
                amount=200.0,
                description="Gasto sin categoría",
                date=date(2026, 10, 15),
            ),
            Transaction(
                tenant_id=tenant_id,
                category_id=category_sales.id,
                type="expense",
                amount=50.0,
                description="Gasto ventas",
                date=date(2026, 10, 18),
            ),
            Transaction(
                tenant_id=tenant_id,
                category_id=category_sales.id,
                type="income",
                amount=1000.0,
                description="Ingreso no computable como deal",
                date=date(2026, 10, 20),
            ),
            Transaction(
                tenant_id=tenant_id,
                category_id=category_infra.id,
                type="expense",
                amount=999.0,
                description="Gasto fuera de periodo",
                date=date(2026, 9, 30),
            ),
        ]
        db.session.add_all(transactions)
        db.session.commit()

    def _seed_tenant_b(self):
        tenant_id = self.tenant_b_id
        company = Company(tenant_id=tenant_id, name="Cliente B")
        stage = Stage(tenant_id=tenant_id, name="Cerrado Ganado", order=1, probability=100)
        db.session.add_all([company, stage])
        db.session.flush()

        db.session.add(
            Deal(
                tenant_id=tenant_id,
                company_id=company.id,
                stage_id=stage.id,
                title="Deal exclusivo B",
                value=5000.0,
                status="won",
                expected_close_date=date(2026, 10, 12),
            )
        )
        db.session.commit()

    def test_profitability_metrics_and_breakdown(self):
        response = self.client.get(
            "/api/analytics/profitability?year=2026&month=10",
            headers=self._headers(self.token_tenant_a),
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual(data["period"]["start_date"], "2026-10-01")
        self.assertEqual(data["period"]["end_date"], "2026-10-31")

        # 3 deals ganados dentro del periodo: 5000 + 2000 + 500 (fallback created_at)
        self.assertEqual(data["revenue"]["deals_won_total"], 7500.0)
        self.assertEqual(data["revenue"]["deals_won_count"], 3)

        # Suscripciones activas: 20 + 1200/12 + 60/3 = 140
        self.assertEqual(data["opex"]["subscriptions_monthly"], 140.0)
        self.assertEqual(data["opex"]["active_subscriptions_count"], 3)
        # Gastos: 300 + 200 + 50 = 550 (income y gasto de septiembre no cuentan)
        self.assertEqual(data["opex"]["transactions_expenses"], 550.0)
        self.assertEqual(data["opex"]["total"], 690.0)

        self.assertEqual(data["profitability"]["net_margin"], 6810.0)
        self.assertEqual(data["profitability"]["margin_percentage"], 90.8)
        self.assertEqual(data["burn_rate"]["monthly"], 140.0)
        self.assertEqual(data["burn_rate"]["annual"], 1680.0)

        categories = {
            item["category_name"]: item for item in data["expense_categories"]
        }
        self.assertEqual(categories["Infraestructura"]["amount"], 420.0)
        self.assertEqual(categories["Infraestructura"]["percentage"], 60.87)
        self.assertEqual(categories["Ventas"]["amount"], 70.0)
        self.assertEqual(categories["Ventas"]["percentage"], 10.14)
        self.assertEqual(categories["Sin categoría"]["amount"], 200.0)
        self.assertEqual(categories["Sin categoría"]["percentage"], 28.99)
        self.assertIsNone(categories["Sin categoría"]["category_id"])

        pipeline = data["pipeline_status"]
        self.assertEqual(pipeline["open"]["count"], 1)
        self.assertEqual(pipeline["open"]["total_value"], 1000.0)
        self.assertEqual(pipeline["won"]["count"], 4)
        self.assertEqual(pipeline["won"]["total_value"], 8499.0)
        self.assertEqual(pipeline["lost"]["count"], 1)
        self.assertEqual(pipeline["lost"]["total_value"], 500.0)
        self.assertEqual(pipeline["total"]["count"], 6)
        self.assertEqual(pipeline["total"]["total_value"], 9999.0)

    def test_tenant_isolation_and_empty_tenant(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)
        headers_c = self._headers(self.token_tenant_c)

        data_b = self.client.get(
            "/api/analytics/profitability?year=2026&month=10", headers=headers_b
        ).get_json()
        self.assertEqual(data_b["revenue"]["deals_won_total"], 5000.0)
        self.assertEqual(data_b["opex"]["total"], 0.0)
        self.assertEqual(data_b["profitability"]["net_margin"], 5000.0)

        # A no debe haberse contaminado con el deal de B
        data_a = self.client.get(
            "/api/analytics/profitability?year=2026&month=10", headers=headers_a
        ).get_json()
        self.assertEqual(data_a["revenue"]["deals_won_total"], 7500.0)

        data_c = self.client.get(
            "/api/analytics/profitability?year=2026&month=10", headers=headers_c
        ).get_json()
        self.assertEqual(data_c["revenue"]["deals_won_total"], 0.0)
        self.assertEqual(data_c["opex"]["total"], 0.0)
        self.assertEqual(data_c["profitability"]["net_margin"], 0.0)
        self.assertEqual(data_c["profitability"]["margin_percentage"], 0.0)
        self.assertEqual(data_c["expense_categories"], [])
        self.assertEqual(data_c["pipeline_status"]["total"]["count"], 0)
        self.assertEqual(data_c["pipeline_status"]["open"]["percentage"], 0.0)

    def test_period_validation_default_and_authentication(self):
        headers = self._headers(self.token_tenant_a)

        self.assertEqual(
            self.client.get("/api/analytics/profitability?month=13", headers=headers).status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/analytics/profitability?month=abc", headers=headers).status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/analytics/profitability?year=1999", headers=headers).status_code,
            400,
        )

        default_period = self.client.get(
            "/api/analytics/profitability", headers=headers
        )
        self.assertEqual(default_period.status_code, 200)
        period = default_period.get_json()["period"]
        today = date.today()
        self.assertEqual(period["year"], today.year)
        self.assertEqual(period["month"], today.month)

        self.assertEqual(
            self.client.get("/api/analytics/profitability").status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()

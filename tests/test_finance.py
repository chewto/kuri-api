import unittest
from datetime import date, timedelta
from calendar import monthrange
from app import create_app
from app.extensions import db
from app.models.category import Category
from app.models.subscription import Subscription
from app.models.transaction import Transaction


class FinanceSprint2TestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Set up two tenants to test strict Multi-Tenant isolation
        self.token_tenant_a = self._create_tenant_and_get_token("Tenant Finance A", "finance_a@test.com")
        self.token_tenant_b = self._create_tenant_and_get_token("Tenant Finance B", "finance_b@test.com")

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
    # CATEGORY TESTS
    # ==========================================
    def test_category_crud_and_isolation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # 1. Create a category in Tenant A
        res_cat = self.client.post(
            "/api/finance/categories",
            json={"name": "Software & AI", "color": "#6366F1"},
            headers=headers_a,
        )
        self.assertEqual(res_cat.status_code, 201)
        cat_data = res_cat.get_json()["category"]
        self.assertEqual(cat_data["name"], "Software & AI")
        self.assertEqual(cat_data["color"], "#6366F1")
        cat_a_id = cat_data["id"]

        # 2. List categories in Tenant A
        res_list_a = self.client.get("/api/finance/categories", headers=headers_a)
        self.assertEqual(res_list_a.status_code, 200)
        items_a = res_list_a.get_json()
        self.assertEqual(len(items_a), 1)
        self.assertEqual(items_a[0]["id"], cat_a_id)

        # 3. List categories in Tenant B -> it must be empty (isolation)
        res_list_b = self.client.get("/api/finance/categories", headers=headers_b)
        self.assertEqual(res_list_b.status_code, 200)
        self.assertEqual(len(res_list_b.get_json()), 0)

        # 4. Validation: name is required
        res_invalid = self.client.post(
            "/api/finance/categories",
            json={"name": "   "},
            headers=headers_a,
        )
        self.assertEqual(res_invalid.status_code, 400)

    # ==========================================
    # SUBSCRIPTION TESTS
    # ==========================================
    def test_subscription_crud_and_validation(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # Create a category and a company in Tenant A
        res_cat = self.client.post(
            "/api/finance/categories",
            json={"name": "Cloud Infrastructure"},
            headers=headers_a,
        )
        cat_id = res_cat.get_json()["category"]["id"]

        res_comp = self.client.post(
            "/api/companies",
            json={"name": "Client AWS Corp"},
            headers=headers_a,
        )
        comp_id = res_comp.get_json()["company"]["id"]

        # 1. Tenant B tries to register a subscription with a Tenant A category or company -> 400
        res_cross_cat = self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Hacked AWS",
                "cost": 150.0,
                "billing_cycle": "monthly",
                "next_billing_date": "2026-11-01",
                "category_id": cat_id,
            },
            headers=headers_b,
        )
        self.assertEqual(res_cross_cat.status_code, 400)

        res_cross_comp = self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Hacked AWS",
                "cost": 150.0,
                "billing_cycle": "monthly",
                "next_billing_date": "2026-11-01",
                "company_id": comp_id,
            },
            headers=headers_b,
        )
        self.assertEqual(res_cross_comp.status_code, 400)

        # 2. Register a legitimate subscription in Tenant A
        res_sub = self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "AWS Hosting",
                "cost": 120.50,
                "billing_cycle": "monthly",
                "next_billing_date": "2026-11-05",
                "category_id": cat_id,
                "company_id": comp_id,
                "status": "active",
            },
            headers=headers_a,
        )
        self.assertEqual(res_sub.status_code, 201)
        sub_data = res_sub.get_json()["subscription"]
        sub_id = sub_data["id"]
        self.assertEqual(sub_data["name"], "AWS Hosting")
        self.assertEqual(sub_data["cost"], 120.50)
        self.assertEqual(sub_data["category_name"], "Cloud Infrastructure")
        self.assertEqual(sub_data["company_name"], "Client AWS Corp")

        # 3. List with filters in Tenant A
        res_filter_status = self.client.get("/api/finance/subscriptions?status=active", headers=headers_a)
        self.assertEqual(res_filter_status.status_code, 200)
        self.assertEqual(len(res_filter_status.get_json()), 1)

        res_filter_cat = self.client.get(f"/api/finance/subscriptions?category_id={cat_id}", headers=headers_a)
        self.assertEqual(res_filter_cat.status_code, 200)
        self.assertEqual(len(res_filter_cat.get_json()), 1)

        res_filter_paused = self.client.get("/api/finance/subscriptions?status=paused", headers=headers_a)
        self.assertEqual(res_filter_paused.status_code, 200)
        self.assertEqual(len(res_filter_paused.get_json()), 0)

        # 4. Tenant B tries to update or delete a Tenant A subscription -> 404
        res_b_put = self.client.put(
            f"/api/finance/subscriptions/{sub_id}",
            json={"cost": 999.0},
            headers=headers_b,
        )
        self.assertEqual(res_b_put.status_code, 404)

        res_b_del = self.client.delete(f"/api/finance/subscriptions/{sub_id}", headers=headers_b)
        self.assertEqual(res_b_del.status_code, 404)

        # 5. Update the subscription in Tenant A
        res_put_a = self.client.put(
            f"/api/finance/subscriptions/{sub_id}",
            json={"cost": 140.0, "status": "paused"},
            headers=headers_a,
        )
        self.assertEqual(res_put_a.status_code, 200)
        self.assertEqual(res_put_a.get_json()["subscription"]["cost"], 140.0)
        self.assertEqual(res_put_a.get_json()["subscription"]["status"], "paused")

        # 6. Delete the subscription in Tenant A
        res_del_a = self.client.delete(f"/api/finance/subscriptions/{sub_id}", headers=headers_a)
        self.assertEqual(res_del_a.status_code, 200)
        self.assertEqual(Subscription.query.filter_by(id=sub_id).count(), 0)

    # ==========================================
    # TRANSACTION TESTS
    # ==========================================
    def test_transaction_crud_and_filters(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        # 1. Register test transactions in Tenant A
        res_tx1 = self.client.post(
            "/api/finance/transactions",
            json={
                "type": "income",
                "amount": 2500.0,
                "description": "CRM development payment for Client X",
                "date": "2026-10-10",
            },
            headers=headers_a,
        )
        self.assertEqual(res_tx1.status_code, 201)
        tx1_id = res_tx1.get_json()["transaction"]["id"]

        res_tx2 = self.client.post(
            "/api/finance/transactions",
            json={
                "type": "expense",
                "amount": 350.0,
                "description": "Servers and Domain",
                "date": "2026-10-15",
            },
            headers=headers_a,
        )
        self.assertEqual(res_tx2.status_code, 201)

        # 2. List transactions in Tenant A and filter by type
        res_income = self.client.get("/api/finance/transactions?type=income", headers=headers_a)
        self.assertEqual(res_income.status_code, 200)
        self.assertEqual(res_income.get_json()["total"], 1)
        self.assertEqual(res_income.get_json()["items"][0]["amount"], 2500.0)

        res_expense = self.client.get("/api/finance/transactions?type=expense", headers=headers_a)
        self.assertEqual(res_expense.status_code, 200)
        self.assertEqual(res_expense.get_json()["total"], 1)

        # 3. Filter by date range
        res_date_range = self.client.get(
            "/api/finance/transactions?start_date=2026-10-12&end_date=2026-10-20",
            headers=headers_a,
        )
        self.assertEqual(res_date_range.status_code, 200)
        self.assertEqual(res_date_range.get_json()["total"], 1)
        self.assertEqual(res_date_range.get_json()["items"][0]["description"], "Servers and Domain")

        # 4. Isolation: Tenant B does not see Tenant A transactions
        res_b_tx = self.client.get("/api/finance/transactions", headers=headers_b)
        self.assertEqual(res_b_tx.status_code, 200)
        self.assertEqual(res_b_tx.get_json()["total"], 0)

        # 5. Tenant B tries to delete a Tenant A transaction -> 404
        res_b_del = self.client.delete(f"/api/finance/transactions/{tx1_id}", headers=headers_b)
        self.assertEqual(res_b_del.status_code, 404)

        # 6. Tenant A deletes its transaction
        res_a_del = self.client.delete(f"/api/finance/transactions/{tx1_id}", headers=headers_a)
        self.assertEqual(res_a_del.status_code, 200)
        self.assertEqual(Transaction.query.filter_by(id=tx1_id).count(), 0)

    # ==========================================
    # FINANCE SUMMARY TESTS
    # ==========================================
    def test_finance_summary_metrics(self):
        headers_a = self._headers(self.token_tenant_a)
        headers_b = self._headers(self.token_tenant_b)

        today = date.today()

        # 1. Create subscriptions in Tenant A:
        # - Claude Pro: $20/month (active) -> contributes 20 MRR
        # - AWS Hosting: $1200/year (active) -> contributes 100 MRR
        # - Zoom: $60/quarter (active) -> contributes 20 MRR
        # - Heroku: $50/month (paused) -> must not add to MRR
        # Expected total MRR = 20 + 100 + 20 = 140.00
        self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Claude Pro",
                "cost": 20.0,
                "billing_cycle": "monthly",
                "next_billing_date": (today + timedelta(days=3)).isoformat(),  # Falls within 7 and 30 days
                "status": "active",
            },
            headers=headers_a,
        )
        self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "AWS Hosting",
                "cost": 1200.0,
                "billing_cycle": "yearly",
                "next_billing_date": (today + timedelta(days=15)).isoformat(),  # Falls only within 30 days
                "status": "active",
            },
            headers=headers_a,
        )
        self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Zoom",
                "cost": 60.0,
                "billing_cycle": "quarterly",
                "next_billing_date": (today + timedelta(days=45)).isoformat(),  # Outside 30 days
                "status": "active",
            },
            headers=headers_a,
        )
        self.client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Heroku",
                "cost": 50.0,
                "billing_cycle": "monthly",
                "next_billing_date": (today + timedelta(days=2)).isoformat(),
                "status": "paused",
            },
            headers=headers_a,
        )

        # 2. Create transactions for the current month in Tenant A
        current_date_tx = today.isoformat()
        self.client.post(
            "/api/finance/transactions",
            json={
                "type": "income",
                "amount": 3000.0,
                "description": "Software sale",
                "date": current_date_tx,
            },
            headers=headers_a,
        )
        self.client.post(
            "/api/finance/transactions",
            json={
                "type": "expense",
                "amount": 800.0,
                "description": "Operating expense",
                "date": current_date_tx,
            },
            headers=headers_a,
        )

        # Transaction from a previous month (must not count for the current month)
        past_date = date(today.year - 1, 1, 1).isoformat()
        self.client.post(
            "/api/finance/transactions",
            json={
                "type": "income",
                "amount": 50000.0,
                "description": "Income from last year",
                "date": past_date,
            },
            headers=headers_a,
        )

        # 3. Fetch /api/finance/summary for Tenant A
        res_summary = self.client.get("/api/finance/summary", headers=headers_a)
        self.assertEqual(res_summary.status_code, 200)
        data = res_summary.get_json()

        # Verified MRR: 20 + (1200/12) + (60/3) = 140.00
        self.assertEqual(data["monthly_expense_mrr"], 140.0)
        self.assertEqual(data["active_subscriptions_count"], 3)

        # Upcoming renewals
        self.assertEqual(data["upcoming_renewals"]["next_7_days"]["count"], 1)
        self.assertEqual(data["upcoming_renewals"]["next_7_days"]["items"][0]["name"], "Claude Pro")

        self.assertEqual(data["upcoming_renewals"]["next_30_days"]["count"], 2)

        # Current month balance
        self.assertEqual(data["current_month_balance"]["total_income"], 3000.0)
        self.assertEqual(data["current_month_balance"]["total_expenses"], 800.0)
        self.assertEqual(data["current_month_balance"]["net_balance"], 2200.0)

        # 4. Check isolation with Tenant B
        res_summary_b = self.client.get("/api/finance/summary", headers=headers_b)
        self.assertEqual(res_summary_b.status_code, 200)
        data_b = res_summary_b.get_json()
        self.assertEqual(data_b["monthly_expense_mrr"], 0.0)
        self.assertEqual(data_b["active_subscriptions_count"], 0)
        self.assertEqual(data_b["current_month_balance"]["total_income"], 0.0)
        self.assertEqual(data_b["current_month_balance"]["total_expenses"], 0.0)
        self.assertEqual(data_b["current_month_balance"]["net_balance"], 0.0)


if __name__ == "__main__":
    unittest.main()

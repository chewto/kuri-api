from datetime import date
from calendar import monthrange
from flask import Blueprint, request, jsonify, g
from app.models.deal import Deal
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.middlewares.tenant_context import tenant_required

analytics_bp = Blueprint("analytics", __name__)

PIPELINE_STATUSES = ("open", "won", "lost")
UNCATEGORIZED_KEY = "__uncategorized__"
UNCATEGORIZED_NAME = "Uncategorized"
UNCATEGORIZED_COLOR = "#94A3B8"


def _monthly_subscription_cost(subscription):
    """Normalizes a subscription cost to its monthly equivalent."""
    cost = float(subscription.cost) if subscription.cost is not None else 0.0

    if subscription.billing_cycle == "monthly":
        return cost
    if subscription.billing_cycle == "yearly":
        return cost / 12.0
    if subscription.billing_cycle == "quarterly":
        return cost / 3.0
    return 0.0


def _parse_period():
    """Validates and resolves the requested period, defaulting to the current month."""
    today = date.today()

    raw_year = request.args.get("year")
    raw_month = request.args.get("month")

    try:
        target_year = int(raw_year) if raw_year is not None else today.year
        target_month = int(raw_month) if raw_month is not None else today.month
    except (TypeError, ValueError):
        return None, None, (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'year' and 'month' parameters must be integers.",
                }
            ),
            400,
        )

    if target_year < 2000 or target_year > 2100:
        return None, None, (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'year' parameter must be between 2000 and 2100.",
                }
            ),
            400,
        )

    if target_month < 1 or target_month > 12:
        return None, None, (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'month' parameter must be between 1 and 12.",
                }
            ),
            400,
        )

    return target_year, target_month, None


@analytics_bp.route("/profitability", methods=["GET"])
@tenant_required
def get_profitability():
    """Returns the consolidated revenue, OPEX, margin, and pipeline summary.

    - Revenue: deals with status 'won' whose effective date (expected_close_date or
      created_at) falls within the requested period.
    - OPEX: normalized monthly cost of active subscriptions plus transactions
      of type 'expense' for the period.
    - Burn Rate: monthly fixed cost of active subscriptions (and its annualized value).
    - Expense breakdown by category and deal distribution by status.
    """
    target_year, target_month, period_error = _parse_period()
    if period_error is not None:
        return period_error

    start_of_month = date(target_year, target_month, 1)
    _, last_day = monthrange(target_year, target_month)
    end_of_month = date(target_year, target_month, last_day)

    try:
        # 1. Revenue from deals won during the period.
        won_deals = Deal.query.filter_by(
            tenant_id=g.tenant_id,
            status="won",
        ).all()

        won_deals_count = 0
        won_revenue = 0.0

        for deal in won_deals:
            effective_date = deal.expected_close_date
            if effective_date is None and deal.created_at is not None:
                effective_date = deal.created_at.date()

            if effective_date and start_of_month <= effective_date <= end_of_month:
                won_deals_count += 1
                won_revenue += float(deal.value) if deal.value is not None else 0.0

        won_revenue = round(won_revenue, 2)

        # 2. OPEX: normalized active subscriptions plus transactions for the month.
        active_subscriptions = Subscription.query.filter_by(
            tenant_id=g.tenant_id,
            status="active",
        ).all()

        subscriptions_monthly = 0.0
        subscription_costs = []
        for subscription in active_subscriptions:
            monthly_cost = _monthly_subscription_cost(subscription)
            subscriptions_monthly += monthly_cost
            subscription_costs.append((subscription, monthly_cost))

        subscriptions_monthly = round(subscriptions_monthly, 2)

        month_transactions = (
            Transaction.query.filter(
                Transaction.tenant_id == g.tenant_id,
                Transaction.date >= start_of_month,
                Transaction.date <= end_of_month,
            ).all()
        )

        expense_transactions = [
            transaction
            for transaction in month_transactions
            if transaction.type == "expense"
        ]
        transaction_expenses = round(
            sum(
                float(transaction.amount)
                for transaction in expense_transactions
                if transaction.amount is not None
            ),
            2,
        )

        total_opex = round(subscriptions_monthly + transaction_expenses, 2)

        # 3. Rentabilidad.
        net_margin = round(won_revenue - total_opex, 2)
        margin_percentage = (
            round((net_margin / won_revenue) * 100, 2) if won_revenue > 0 else 0.0
        )

        # 4. Expense breakdown by category.
        category_totals = {}

        def add_category_expense(category_id, category_name, category_color, amount):
            if amount <= 0:
                return

            key = category_id or UNCATEGORIZED_KEY
            bucket = category_totals.get(key)
            if bucket is None:
                bucket = {
                    "category_id": category_id,
                    "category_name": category_name,
                    "color": category_color,
                    "amount": 0.0,
                }
                category_totals[key] = bucket
            bucket["amount"] += amount

        for transaction in expense_transactions:
            category = transaction.category
            add_category_expense(
                transaction.category_id,
                category.name if category else UNCATEGORIZED_NAME,
                category.color if category else UNCATEGORIZED_COLOR,
                float(transaction.amount) if transaction.amount is not None else 0.0,
            )

        for subscription, monthly_cost in subscription_costs:
            category = subscription.category
            add_category_expense(
                subscription.category_id,
                category.name if category else UNCATEGORIZED_NAME,
                category.color if category else UNCATEGORIZED_COLOR,
                monthly_cost,
            )

        expense_categories = []
        for bucket in category_totals.values():
            amount = round(bucket["amount"], 2)
            expense_categories.append(
                {
                    "category_id": bucket["category_id"],
                    "category_name": bucket["category_name"],
                    "color": bucket["color"],
                    "amount": amount,
                    "percentage": (
                        round((amount / total_opex) * 100, 2) if total_opex > 0 else 0.0
                    ),
                }
            )
        expense_categories.sort(key=lambda item: item["amount"], reverse=True)

        # 5. Pipeline distribution by status (all deals in the workspace).
        all_deals = Deal.query.filter_by(tenant_id=g.tenant_id).all()
        status_counts = {status: 0 for status in PIPELINE_STATUSES}
        status_values = {status: 0.0 for status in PIPELINE_STATUSES}

        for deal in all_deals:
            if deal.status not in status_counts:
                continue
            status_counts[deal.status] += 1
            status_values[deal.status] += (
                float(deal.value) if deal.value is not None else 0.0
            )

        total_deals_count = len(all_deals)
        total_deals_value = round(sum(status_values.values()), 2)

        pipeline_status = {}
        for status in PIPELINE_STATUSES:
            pipeline_status[status] = {
                "count": status_counts[status],
                "total_value": round(status_values[status], 2),
                "percentage": (
                    round((status_counts[status] / total_deals_count) * 100, 2)
                    if total_deals_count > 0
                    else 0.0
                ),
            }

        pipeline_status["total"] = {
            "count": total_deals_count,
            "total_value": total_deals_value,
            "percentage": 100.0 if total_deals_count > 0 else 0.0,
        }

        return (
            jsonify(
                {
                    "period": {
                        "year": target_year,
                        "month": target_month,
                        "start_date": start_of_month.isoformat(),
                        "end_date": end_of_month.isoformat(),
                    },
                    "revenue": {
                        "deals_won_total": won_revenue,
                        "deals_won_count": won_deals_count,
                    },
                    "opex": {
                        "total": total_opex,
                        "subscriptions_monthly": subscriptions_monthly,
                        "transactions_expenses": transaction_expenses,
                        "active_subscriptions_count": len(active_subscriptions),
                    },
                    "profitability": {
                        "net_margin": net_margin,
                        "margin_percentage": margin_percentage,
                    },
                    "burn_rate": {
                        "monthly": subscriptions_monthly,
                        "annual": round(subscriptions_monthly * 12, 2),
                    },
                    "expense_categories": expense_categories,
                    "pipeline_status": pipeline_status,
                }
            ),
            200,
        )

    except Exception as exc:
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not calculate profitability: {str(exc)}",
                }
            ),
            500,
        )

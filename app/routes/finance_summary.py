from datetime import date, timedelta
from calendar import monthrange
from flask import Blueprint, jsonify, g
from app.extensions import db
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.middlewares.tenant_context import tenant_required

finance_summary_bp = Blueprint("finance_summary", __name__)


@finance_summary_bp.route("", methods=["GET"])
@tenant_required
def get_finance_summary():
    """Devuelve las métricas financieras consolidadas del tenant actual:

    - MRR de gastos fijos mensuales en suscripciones activas (normalizado).
    - Próximos vencimientos de suscripciones en los próximos 7 y 30 días.
    - Balance total de transacciones del mes actual (Total Ingresos, Total Gastos, Balance Neto).
    """
    today = date.today()

    try:
        # 1. Total de gasto fijo mensual en suscripciones (MRR de gastos)
        active_subscriptions = (
            Subscription.query.filter_by(tenant_id=g.tenant_id, status="active").all()
        )

        monthly_expense_mrr = 0.0
        for sub in active_subscriptions:
            cost = float(sub.cost) if sub.cost else 0.0
            if sub.billing_cycle == "monthly":
                monthly_expense_mrr += cost
            elif sub.billing_cycle == "yearly":
                monthly_expense_mrr += cost / 12.0
            elif sub.billing_cycle == "quarterly":
                monthly_expense_mrr += cost / 3.0

        monthly_expense_mrr = round(monthly_expense_mrr, 2)

        # 2. Próximos vencimientos de suscripciones en 7 y 30 días
        limit_7_days = today + timedelta(days=7)
        limit_30_days = today + timedelta(days=30)

        upcoming_7_days = [
            sub.to_dict()
            for sub in active_subscriptions
            if today <= sub.next_billing_date <= limit_7_days
        ]
        # Ordenar por fecha de cobro ascendente
        upcoming_7_days.sort(key=lambda s: s["next_billing_date"])

        upcoming_30_days = [
            sub.to_dict()
            for sub in active_subscriptions
            if today <= sub.next_billing_date <= limit_30_days
        ]
        upcoming_30_days.sort(key=lambda s: s["next_billing_date"])

        # 3. Balance de transacciones del mes actual
        start_of_month = date(today.year, today.month, 1)
        _, last_day = monthrange(today.year, today.month)
        end_of_month = date(today.year, today.month, last_day)

        month_transactions = (
            Transaction.query.filter(
                Transaction.tenant_id == g.tenant_id,
                Transaction.date >= start_of_month,
                Transaction.date <= end_of_month,
            ).all()
        )

        total_income = sum(
            float(tx.amount) for tx in month_transactions if tx.type == "income"
        )
        total_expenses = sum(
            float(tx.amount) for tx in month_transactions if tx.type == "expense"
        )
        total_income = round(total_income, 2)
        total_expenses = round(total_expenses, 2)
        net_balance = round(total_income - total_expenses, 2)

        return (
            jsonify(
                {
                    "monthly_expense_mrr": monthly_expense_mrr,
                    "active_subscriptions_count": len(active_subscriptions),
                    "upcoming_renewals": {
                        "next_7_days": {
                            "count": len(upcoming_7_days),
                            "items": upcoming_7_days,
                        },
                        "next_30_days": {
                            "count": len(upcoming_30_days),
                            "items": upcoming_30_days,
                        },
                    },
                    "current_month_balance": {
                        "start_date": start_of_month.isoformat(),
                        "end_date": end_of_month.isoformat(),
                        "total_income": total_income,
                        "total_expenses": total_expenses,
                        "net_balance": net_balance,
                        "transactions_count": len(month_transactions),
                    },
                }
            ),
            200,
        )

    except Exception as exc:
        return (
            jsonify(
                {
                    "error": "Error interno",
                    "message": f"No se pudo calcular el resumen financiero: {str(exc)}",
                }
            ),
            500,
        )

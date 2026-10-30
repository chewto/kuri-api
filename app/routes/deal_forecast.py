from datetime import date, datetime
from calendar import monthrange
from flask import Blueprint, jsonify, request, g
from app.models.deal import Deal
from app.models.stage import Stage
from app.middlewares.tenant_context import tenant_required

deal_forecast_bp = Blueprint("deal_forecast", __name__)


@deal_forecast_bp.route("", methods=["GET"])
@tenant_required
def get_deal_forecast():
    """Devuelve métricas comerciales y proyecciones de ventas (Forecast) del tenant:

    - Valor total en Pipeline Abierto (open deals).
    - Valor total de Negocios Ganados (won deals) en el mes actual.
    - Valor Ponderado total (Suma de valor * probabilidad de etapa).
    - Desglose por etapas con conteo y métricas valorizadas.
    - Conteo general de tratos por estado.
    """
    today = date.today()

    # Opcional: permitir filtrar mes/año para el cálculo de negocios ganados
    try:
        target_year = int(request.args.get("year", today.year))
        target_month = int(request.args.get("month", today.month))
    except (ValueError, TypeError):
        target_year = today.year
        target_month = today.month

    start_of_month = date(target_year, target_month, 1)
    _, last_day = monthrange(target_year, target_month)
    end_of_month = date(target_year, target_month, last_day)

    # 1. Obtener etapas del tenant
    stages = (
        Stage.query.filter_by(tenant_id=g.tenant_id)
        .order_by(Stage.order.asc())
        .all()
    )

    stage_map = {s.id: s for s in stages}

    # 2. Obtener todos los tratos del tenant
    deals = Deal.query.filter_by(tenant_id=g.tenant_id).all()

    total_open_value = 0.0
    weighted_pipeline_value = 0.0
    total_won_month_value = 0.0

    open_deals_count = 0
    won_deals_count = 0
    lost_deals_count = 0

    # Inicializar breakdown por etapa
    stage_breakdown_dict = {}
    for stage in stages:
        stage_breakdown_dict[stage.id] = {
            "stage_id": stage.id,
            "stage_name": stage.name,
            "order": stage.order,
            "probability": stage.probability,
            "deals_count": 0,
            "total_value": 0.0,
            "weighted_value": 0.0,
        }

    for deal in deals:
        val = float(deal.value) if deal.value is not None else 0.0

        if deal.status == "open":
            open_deals_count += 1
            total_open_value += val

            # Cálculo ponderado según probabilidad de la etapa
            deal_stage = stage_map.get(deal.stage_id)
            prob = deal_stage.probability if deal_stage else 100
            weighted_val = val * (prob / 100.0)
            weighted_pipeline_value += weighted_val

            if deal.stage_id in stage_breakdown_dict:
                stage_breakdown_dict[deal.stage_id]["deals_count"] += 1
                stage_breakdown_dict[deal.stage_id]["total_value"] += val
                stage_breakdown_dict[deal.stage_id]["weighted_value"] += weighted_val

        elif deal.status == "won":
            won_deals_count += 1
            # Verificar si corresponde al mes solicitado:
            # Si tiene expected_close_date, se usa esa fecha; sino, la fecha de created_at
            deal_date = deal.expected_close_date
            if not deal_date and deal.created_at:
                deal_date = deal.created_at.date()

            if deal_date and (start_of_month <= deal_date <= end_of_month):
                total_won_month_value += val

        elif deal.status == "lost":
            lost_deals_count += 1

    # Formatear el breakdown ordenado por order
    breakdown_list = sorted(
        stage_breakdown_dict.values(),
        key=lambda item: item["order"],
    )
    for b in breakdown_list:
        b["total_value"] = round(b["total_value"], 2)
        b["weighted_value"] = round(b["weighted_value"], 2)

    total_deals_count = len(deals)

    return (
        jsonify(
            {
                "total_open_value": round(total_open_value, 2),
                "total_won_month": round(total_won_month_value, 2),
                "weighted_pipeline_value": round(weighted_pipeline_value, 2),
                "counts": {
                    "open": open_deals_count,
                    "won": won_deals_count,
                    "lost": lost_deals_count,
                    "total": total_deals_count,
                },
                "period": {
                    "year": target_year,
                    "month": target_month,
                    "start_date": start_of_month.isoformat(),
                    "end_date": end_of_month.isoformat(),
                },
                "stage_breakdown": breakdown_list,
            }
        ),
        200,
    )

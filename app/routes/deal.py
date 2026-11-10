from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.deal import Deal
from app.models.stage import Stage
from app.models.company import Company
from app.models.contact import Contact
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

deal_bp = Blueprint("deals", __name__)

VALID_DEAL_STATUSES = {"open", "won", "lost"}


@deal_bp.route("", methods=["GET"])
@tenant_required
def get_deals():
    """Lists the workspace deals with optional filters.

    Supports filters by stage_id, status, company_id, and contact_id, title search (?search=),
    stage grouping for Kanban views (?grouped=true), and pagination.
    """
    stage_id = request.args.get("stage_id", "").strip()
    status = request.args.get("status", "").strip().lower()
    company_id = request.args.get("company_id", "").strip()
    contact_id = request.args.get("contact_id", "").strip()
    search = request.args.get("search", "").strip()
    grouped = request.args.get("grouped", "").strip() in ("1", "true", "True")
    fetch_all = request.args.get("all", "").strip() in ("1", "true", "True")

    # If grouped output is requested for the Kanban view
    if grouped:
        stages = (
            Stage.query.filter_by(tenant_id=g.tenant_id)
            .order_by(Stage.order.asc())
            .all()
        )
        # Query all deals in the workspace
        deals_query = Deal.query.filter_by(tenant_id=g.tenant_id)
        if status:
            if status in VALID_DEAL_STATUSES:
                deals_query = deals_query.filter_by(status=status)
        if company_id:
            deals_query = deals_query.filter_by(company_id=company_id)
        if search:
            deals_query = deals_query.filter(Deal.title.ilike(f"%{search}%"))

        deals = deals_query.order_by(Deal.created_at.desc()).all()

        deals_by_stage = {}
        for d in deals:
            deals_by_stage.setdefault(d.stage_id, []).append(d.to_dict())

        grouped_stages = []
        for stage in stages:
            stage_dict = stage.to_dict()
            stage_dict["deals"] = deals_by_stage.get(stage.id, [])
            stage_dict["total_deals"] = len(stage_dict["deals"])
            stage_dict["total_value"] = sum(d["value"] for d in stage_dict["deals"])
            grouped_stages.append(stage_dict)

        return jsonify({"stages": grouped_stages}), 200

    query = Deal.query.filter_by(tenant_id=g.tenant_id)

    if stage_id:
        query = query.filter_by(stage_id=stage_id)

    if status:
        if status not in VALID_DEAL_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": f"Invalid status. Options: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                    }
                ),
                400,
            )
        query = query.filter_by(status=status)

    if company_id:
        query = query.filter_by(company_id=company_id)

    if contact_id:
        query = query.filter_by(contact_id=contact_id)

    if search:
        query = query.filter(Deal.title.ilike(f"%{search}%"))

    query = query.order_by(Deal.created_at.desc())

    if fetch_all:
        deals = query.limit(2000).all()
        items = [deal.to_dict() for deal in deals]
        return (
            jsonify(
                {
                    "items": items,
                    "total": len(items),
                    "page": 1,
                    "per_page": len(items),
                    "pages": 1,
                }
            ),
            200,
        )

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        page = 1
        per_page = 20

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return (
        jsonify(
            {
                "items": [d.to_dict() for d in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "per_page": pagination.per_page,
                "pages": pagination.pages,
            }
        ),
        200,
    )


@deal_bp.route("/<deal_id>", methods=["GET"])
@tenant_required
def get_deal(deal_id):
    """Returns the details of a deal belonging to the workspace."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "Not found", "message": "The requested deal does not exist."}),
            404,
        )
    return jsonify(deal.to_dict()), 200


@deal_bp.route("", methods=["POST"])
@tenant_required
def create_deal():
    """Creates a new sales opportunity associated with a company and contact."""
    data = request.get_json(silent=True) or {}

    title = str(data.get("title", "")).strip()
    if not title:
        return (
            jsonify({"error": "Validation failed", "message": "The 'title' field is required."}),
            400,
        )

    company_id = str(data.get("company_id", "")).strip()
    if not company_id:
        return (
            jsonify({"error": "Validation failed", "message": "The 'company_id' field is required."}),
            400,
        )

    # Verify that the company belongs to the workspace
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The specified company does not exist or does not belong to your organization.",
                }
            ),
            400,
        )

    stage_id = str(data.get("stage_id", "")).strip()
    if not stage_id:
        return (
            jsonify({"error": "Validation failed", "message": "The 'stage_id' field is required."}),
            400,
        )

    # Verify that the stage belongs to the workspace
    stage = Stage.query.filter_by(id=stage_id, tenant_id=g.tenant_id).first()
    if not stage:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The specified stage does not exist or does not belong to your organization.",
                }
            ),
            400,
        )

    # Validate the optional contact
    contact_id = data.get("contact_id")
    if contact_id:
        contact_id = str(contact_id).strip()
        contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
        if not contact:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The specified contact does not exist or does not belong to your organization.",
                    }
                ),
                400,
            )
    else:
        contact_id = None

    # Validate the value amount
    value_raw = data.get("value")
    if value_raw is None:
        return (
            jsonify({"error": "Validation failed", "message": "The 'value' field is required."}),
            400,
        )
    try:
        deal_value = Decimal(str(value_raw))
        if deal_value < Decimal("0.00"):
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'value' field must be a decimal number greater than or equal to 0.",
                }
            ),
            400,
        )

    # Validate status
    status = str(data.get("status", "open")).strip().lower()
    if status not in VALID_DEAL_STATUSES:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": f"Invalid status. Options: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                }
            ),
            400,
        )

    # Validate expected_close_date
    expected_close_date = None
    date_str = data.get("expected_close_date")
    if date_str:
        try:
            expected_close_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "Invalid 'expected_close_date' format. Use YYYY-MM-DD.",
                    }
                ),
                400,
            )

    deal = Deal(
        tenant_id=g.tenant_id,
        company_id=company_id,
        contact_id=contact_id,
        stage_id=stage_id,
        title=title,
        value=deal_value,
        expected_close_date=expected_close_date,
        status=status,
    )

    try:
        db.session.add(deal)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Deal created successfully.",
                    "deal": deal.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not create the deal: {str(exc)}",
                }
            ),
            500,
        )


@deal_bp.route("/<deal_id>", methods=["PUT"])
@tenant_required
def update_deal(deal_id):
    """Updates all fields of a sales opportunity."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "Not found", "message": "The requested deal does not exist."}),
            404,
        )

    data = request.get_json(silent=True) or {}

    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            return (
                jsonify({"error": "Validation failed", "message": "The 'title' field cannot be empty."}),
                400,
            )
        deal.title = title

    if "company_id" in data:
        cid = str(data["company_id"]).strip()
        company = Company.query.filter_by(id=cid, tenant_id=g.tenant_id).first()
        if not company:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The specified company does not exist or does not belong to your organization.",
                    }
                ),
                400,
            )
        deal.company_id = cid

    if "stage_id" in data:
        sid = str(data["stage_id"]).strip()
        stage = Stage.query.filter_by(id=sid, tenant_id=g.tenant_id).first()
        if not stage:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The specified stage does not exist or does not belong to your organization.",
                    }
                ),
                400,
            )
        deal.stage_id = sid

    if "contact_id" in data:
        ctid = data["contact_id"]
        if ctid:
            ctid = str(ctid).strip()
            contact = Contact.query.filter_by(id=ctid, tenant_id=g.tenant_id).first()
            if not contact:
                return (
                    jsonify(
                        {
                            "error": "Validation failed",
                            "message": "The specified contact does not exist or does not belong to your organization.",
                        }
                    ),
                    400,
                )
            deal.contact_id = ctid
        else:
            deal.contact_id = None

    if "value" in data:
        try:
            val = Decimal(str(data["value"]))
            if val < Decimal("0.00"):
                raise ValueError()
            deal.value = val
        except (InvalidOperation, ValueError, TypeError):
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The 'value' field must be a decimal number greater than or equal to 0.",
                    }
                ),
                400,
            )

    if "status" in data:
        st = str(data["status"]).strip().lower()
        if st not in VALID_DEAL_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": f"Invalid status. Options: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                    }
                ),
                400,
            )
        deal.status = st

    if "expected_close_date" in data:
        date_str = data["expected_close_date"]
        if date_str:
            try:
                deal.expected_close_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": "Validation failed",
                            "message": "Invalid 'expected_close_date' format. Use YYYY-MM-DD.",
                        }
                    ),
                    400,
                )
        else:
            deal.expected_close_date = None

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Deal updated successfully.",
                    "deal": deal.to_dict(),
                }
            ),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not update the deal: {str(exc)}",
                }
            ),
            500,
        )


@deal_bp.route("/<deal_id>/move", methods=["PATCH"])
@tenant_required
def move_deal(deal_id):
    """Optimized endpoint for moving a deal to another stage (stage_id) or changing its status (Kanban drag and drop)."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "Not found", "message": "The requested deal does not exist."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    new_stage_id = data.get("stage_id")
    new_status = data.get("status")

    if not new_stage_id and not new_status:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "You must provide at least 'stage_id' or 'status' to move the deal.",
                }
            ),
            400,
        )

    if new_stage_id:
        new_stage_id = str(new_stage_id).strip()
        stage = Stage.query.filter_by(id=new_stage_id, tenant_id=g.tenant_id).first()
        if not stage:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The target stage does not exist or does not belong to your organization.",
                    }
                ),
                400,
            )
        deal.stage_id = new_stage_id

        # Infer the status when none was provided explicitly:
        if not new_status:
            normalized_name = stage.name.lower()
            if "won" in normalized_name:
                deal.status = "won"
            elif "lost" in normalized_name:
                deal.status = "lost"
            elif deal.status in ("won", "lost"):
                # If the deal moves back to an intermediate pipeline stage
                deal.status = "open"

    if new_status:
        st = str(new_status).strip().lower()
        if st not in VALID_DEAL_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": f"Invalid status. Options: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                    }
                ),
                400,
            )
        deal.status = st

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Deal moved successfully.",
                    "deal": deal.to_dict(),
                }
            ),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not move the deal: {str(exc)}",
                }
            ),
            500,
        )


@deal_bp.route("/<deal_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_deal(deal_id):
    """Deletes a sales opportunity."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "Not found", "message": "The requested deal does not exist."}),
            404,
        )

    try:
        db.session.delete(deal)
        db.session.commit()
        return jsonify({"message": "Deal deleted successfully."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not delete the deal: {str(exc)}",
                }
            ),
            500,
        )

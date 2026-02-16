from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from core.db_client import get_db
from dashboard.service.dashboard_service import DashboardKeyService
from dashboard.data.repository import EvalRecordRepository
from pathlib import Path
import json

dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@dashboard_router.get("", response_class=HTMLResponse)
def get_dashboard(api_key: str = Query(..., alias="api_key"), db: Session = Depends(get_db)):
    service = DashboardKeyService()
    if not service.validate_key(api_key):
        raise HTTPException(status_code=403, detail="Invalid or expired API key")

    repo = EvalRecordRepository(db)
    records = repo.get_daily_aggregates(days=30)

    chart_data = json.dumps([{
        "date": r.created_at.isoformat() if r.created_at else None,
        "faithfulness": r.faithfulness,
        "relevancy": r.response_relevancy,
        "total_cost": r.total_cost,
        "eval_cost": r.eval_cost,
        "node_costs": r.node_costs,
        "document_id": r.document_id,
        "user_query": r.user_query,
        "user_email": r.user_email,
        "latency_ms": r.latency_ms,
        "is_rag_retrieved": r.is_rag_retrieved,
    } for r in records])

    html_path = Path(__file__).parent.parent.parent / "static" / "dashboard.html"
    html_content = html_path.read_text()
    html_content = html_content.replace("\"{{CHART_DATA}}\"", chart_data)
    return HTMLResponse(content=html_content)


@dashboard_router.get("/evaluations", response_class=HTMLResponse)
def get_evaluations(api_key: str = Query(..., alias="api_key"), db: Session = Depends(get_db)):
    service = DashboardKeyService()
    if not service.validate_key(api_key):
        raise HTTPException(status_code=403, detail="Invalid or expired API key")

    repo = EvalRecordRepository(db)
    records = repo.get_daily_aggregates(days=30)

    chart_data = json.dumps([{
        "date": r.created_at.isoformat() if r.created_at else None,
        "faithfulness": r.faithfulness,
        "relevancy": r.response_relevancy,
        "total_cost": r.total_cost,
        "eval_cost": r.eval_cost,
        "node_costs": r.node_costs,
        "document_id": r.document_id,
        "user_query": r.user_query,
        "user_email": r.user_email,
        "latency_ms": r.latency_ms,
        "is_rag_retrieved": r.is_rag_retrieved,
    } for r in records])

    html_path = Path(__file__).parent.parent.parent / "static" / "evaluations.html"
    html_content = html_path.read_text()
    html_content = html_content.replace("\"{{CHART_DATA}}\"", chart_data)
    return HTMLResponse(content=html_content)


@dashboard_router.delete("/data")
def delete_all_eval_data(api_key: str = Query(..., alias="api_key"), db: Session = Depends(get_db)):
    service = DashboardKeyService()
    if not service.validate_key(api_key):
        raise HTTPException(status_code=403, detail="Invalid or expired API key")

    repo = EvalRecordRepository(db)
    deleted = repo.delete_all()
    return {"deleted": deleted}


@dashboard_router.get("/data")
def get_dashboard_data(api_key: str = Query(..., alias="api_key"), db: Session = Depends(get_db)):
    service = DashboardKeyService()
    if not service.validate_key(api_key):
        raise HTTPException(status_code=403, detail="Invalid or expired API key")

    repo = EvalRecordRepository(db)
    records = repo.get_daily_aggregates(days=30)
    return [{
        "date": r.created_at.isoformat() if r.created_at else None,
        "faithfulness": r.faithfulness,
        "relevancy": r.response_relevancy,
        "total_cost": r.total_cost,
        "eval_cost": r.eval_cost,
        "node_costs": r.node_costs,
        "document_id": r.document_id,
        "user_query": r.user_query,
        "user_email": r.user_email,
        "latency_ms": r.latency_ms,
        "is_rag_retrieved": r.is_rag_retrieved,
    } for r in records]

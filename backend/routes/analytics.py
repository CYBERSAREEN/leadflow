import logging
from fastapi import APIRouter, HTTPException, Depends
from backend import database, auth

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/analytics/dashboard")
async def get_dashboard(current_user: dict = Depends(auth.get_current_user)):
    try:
        stats = database.get_dashboard_stats(user_id=current_user["user_id"])
        return stats
    except Exception as e:
        logger.error(f"GET /analytics/dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/leads-over-time")
async def get_leads_over_time(
    days: int = 30,
    current_user: dict = Depends(auth.get_current_user),
):
    try:
        data = database.get_leads_over_time(days=days, user_id=current_user["user_id"])
        return {"data": data}
    except Exception as e:
        logger.error(f"GET /analytics/leads-over-time error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/conversion-funnel")
async def get_conversion_funnel(current_user: dict = Depends(auth.get_current_user)):
    try:
        data = database.get_conversion_funnel(user_id=current_user["user_id"])
        return {"data": data}
    except Exception as e:
        logger.error(f"GET /analytics/conversion-funnel error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/reports")
async def get_reports(
    limit: int = 30,
    current_user: dict = Depends(auth.get_current_user),
):
    try:
        reports = database.get_reports(limit=limit, user_id=current_user["user_id"])
        return {"reports": reports}
    except Exception as e:
        logger.error(f"GET /analytics/reports error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/followup")
async def get_followup_leads(current_user: dict = Depends(auth.get_current_user)):
    try:
        leads = database.get_leads_needing_followup(user_id=current_user["user_id"])
        return {"leads": leads, "total": len(leads)}
    except Exception as e:
        logger.error(f"GET /analytics/followup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

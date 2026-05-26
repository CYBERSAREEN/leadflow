import asyncio
import logging
from datetime import date
from fastapi import APIRouter, HTTPException, Depends
from backend import database, auth
from backend.models import SuggestReplyRequest
from backend.services import groq_service

router = APIRouter()
logger = logging.getLogger(__name__)

_score_all_progress = {"running": False, "done": 0, "total": 0, "errors": 0}


@router.post("/ai/suggest-reply")
async def suggest_reply(
    body: SuggestReplyRequest,
    current_user: dict = Depends(auth.get_current_user),
):
    try:
        lead = database.get_lead_by_id(body.lead_id, user_id=current_user["user_id"])
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        messages = database.get_messages_for_lead(body.lead_id)
        history = []
        for m in messages[-10:]:
            prefix = "[Customer]" if m["direction"] == "inbound" else "[Agent]"
            history.append(f"{prefix}: {m['body']}")

        suggestion = groq_service.suggest_reply(history)
        return {"suggestion": suggestion}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /ai/suggest-reply error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/score-all")
async def score_all_leads(current_user: dict = Depends(auth.get_current_user)):
    global _score_all_progress
    if _score_all_progress["running"]:
        return {"status": "already_running", "progress": _score_all_progress}

    user_id = current_user["user_id"]

    async def _run_scoring():
        global _score_all_progress
        _score_all_progress = {"running": True, "done": 0, "total": 0, "errors": 0}
        try:
            unscored = database.get_unscored_leads(limit=50, user_id=user_id)
            _score_all_progress["total"] = len(unscored)

            for lead in unscored:
                try:
                    messages = database.get_messages_for_lead(lead["id"])
                    message_bodies = [m["body"] for m in messages]
                    result = groq_service.score_lead(lead["name"], message_bodies)
                    database.update_lead(
                        lead["id"],
                        user_id=user_id,
                        ai_score=result["score"],
                        ai_summary=f"{result['reason']} | Action: {result['suggested_action']}"
                    )
                    _score_all_progress["done"] += 1
                except Exception as e:
                    logger.error(f"score_all error on lead {lead['id']}: {e}")
                    _score_all_progress["errors"] += 1

                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"score_all job error: {e}")
        finally:
            _score_all_progress["running"] = False

    asyncio.create_task(_run_scoring())
    return {"status": "started", "progress": _score_all_progress}


@router.get("/ai/score-all/progress")
async def score_all_progress():
    return _score_all_progress


@router.get("/ai/daily-insights")
async def get_daily_insights(current_user: dict = Depends(auth.get_current_user)):
    try:
        today = date.today().isoformat()
        user_id = current_user["user_id"]

        if database.get_today_report_exists(user_id=user_id):
            reports = database.get_reports(limit=1, user_id=user_id)
            if reports:
                return {
                    "date": today,
                    "insights": reports[0]["ai_insights"],
                    "cached": True
                }

        stats = database.get_dashboard_stats(user_id=user_id)
        leads = database.get_all_leads(limit=500, user_id=user_id)
        insights = groq_service.generate_daily_insights(stats, leads)
        database.save_daily_report(today, stats, insights, user_id=user_id)

        return {"date": today, "insights": insights, "cached": False}
    except Exception as e:
        logger.error(f"GET /ai/daily-insights error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai/top-leads")
async def get_top_leads(
    limit: int = 5,
    current_user: dict = Depends(auth.get_current_user),
):
    try:
        leads = database.get_top_scored_leads(limit=limit, user_id=current_user["user_id"])
        return {"leads": leads}
    except Exception as e:
        logger.error(f"GET /ai/top-leads error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

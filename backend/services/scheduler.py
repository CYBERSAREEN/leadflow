import asyncio
import logging
from datetime import date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def run_morning_report():
    from backend import database
    from backend.services import groq_service, whatsapp_bridge

    logger.info("Running morning report job...")
    try:
        stats = database.get_dashboard_stats()
        leads = database.get_all_leads(limit=500)
        insights = groq_service.generate_daily_insights(stats, leads)

        today = date.today().isoformat()
        database.save_daily_report(today, stats, insights)

        report_msg = (
            f"LeadFlow AI Morning Report - {today}\n\n"
            f"Total Leads: {stats['total_leads']}\n"
            f"New Today: {stats['new_today']}\n"
            f"Contacted: {stats['contacted']}\n"
            f"Converted: {stats['converted']}\n"
            f"Conversion Rate: {stats['conversion_rate']}%\n"
            f"Messages Today: {stats['messages_today']}\n\n"
            f"AI Insights:\n{insights}"
        )

        manager_phone = "917087603933"
        success = await whatsapp_bridge.send_message(manager_phone, report_msg)
        if success:
            logger.info("Morning report sent to manager via WhatsApp")
        else:
            logger.warning("Failed to send morning report via WhatsApp")

    except Exception as e:
        logger.error(f"Morning report job error: {e}")


def start_scheduler():
    try:
        scheduler.add_job(
            run_morning_report,
            CronTrigger(hour=8, minute=0),
            id="morning_report",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        logger.info("Scheduler started — morning report job scheduled at 08:00 daily")
    except Exception as e:
        logger.error(f"Scheduler start error: {e}")


def stop_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
    except Exception as e:
        logger.error(f"Scheduler stop error: {e}")

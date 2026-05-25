"""
Database layer using the Supabase Python client (HTTPS/REST).
This avoids direct TCP to the DB, which solves IPv6-only Supabase
hosts being unreachable from Render's IPv4-only network.
"""
import os
import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Supabase client (lazy singleton)
# ──────────────────────────────────────────────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    from supabase import create_client, Client
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    _client = create_client(url, key)
    return _client


def _clean(row) -> dict:
    """Convert Supabase row (already a dict) to a plain dict."""
    if row is None:
        return None
    d = dict(row)
    # Ensure datetime fields are strings (Supabase already returns ISO strings)
    for field in ("created_at", "last_contacted", "follow_up_date"):
        if field in d and d[field] is not None and not isinstance(d[field], str):
            d[field] = str(d[field])
    # Supabase returns None for default '' TEXT fields sometimes
    for field in ("ai_summary", "notes", "source", "status"):
        if d.get(field) is None:
            d[field] = ""
    if d.get("ai_score") is None:
        d["ai_score"] = 0
    return d


# ──────────────────────────────────────────────────────────────────────────
# Schema bootstrap (idempotent — only runs once at startup)
# ──────────────────────────────────────────────────────────────────────────
def init_db():
    """
    Create tables if they don't exist, using Supabase's REST DDL endpoint.
    If the tables already exist this is a no-op (handled by the except).
    """
    import psycopg2, psycopg2.extras
    from urllib.parse import urlparse, unquote

    db_url = os.environ.get("DATABASE_URL", "")
    supabase_url = os.environ.get("SUPABASE_URL", "")

    # Try direct psycopg2 first (works when DB is reachable over IPv4)
    if db_url:
        try:
            parsed = urlparse(db_url)
            conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                dbname=(parsed.path or "/postgres").lstrip("/"),
                user=unquote(parsed.username or "postgres"),
                password=unquote(parsed.password or ""),
                sslmode="require",
                connect_timeout=10,
            )
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    source TEXT DEFAULT 'manual',
                    status TEXT DEFAULT 'new',
                    ai_score INTEGER DEFAULT 0,
                    ai_summary TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_contacted TIMESTAMP,
                    follow_up_date TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    lead_id INTEGER REFERENCES leads(id),
                    phone TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    body TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    wa_message_id TEXT UNIQUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id SERIAL PRIMARY KEY,
                    report_date DATE UNIQUE,
                    total_leads INTEGER,
                    new_leads INTEGER,
                    contacted INTEGER,
                    converted INTEGER,
                    ai_insights TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
            logger.info("Database tables initialized via psycopg2")
            return
        except Exception as e:
            logger.warning(f"psycopg2 init_db failed (expected if IPv6-only): {e}")

    # Fallback: tables must already exist (created manually in Supabase Dashboard)
    # Verify via supabase-py REST
    try:
        sb = _get_client()
        # Just test the connection — if tables don't exist, operations will fail clearly
        sb.table("leads").select("id").limit(1).execute()
        logger.info("Database verified via Supabase REST API")
    except Exception as e:
        logger.error(f"init_db: REST check failed: {e}")
        logger.warning("Tables may not exist. Run CREATE TABLE via Supabase Dashboard SQL editor.")


# ──────────────────────────────────────────────────────────────────────────
# LEADS
# ──────────────────────────────────────────────────────────────────────────

def get_all_leads(status: Optional[str] = None, limit: int = 100, offset: int = 0) -> list:
    try:
        sb = _get_client()
        q = sb.table("leads").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_all_leads error: {e}")
        return []


def get_lead_by_id(lead_id: int) -> Optional[dict]:
    try:
        sb = _get_client()
        res = sb.table("leads").select("*").eq("id", lead_id).maybe_single().execute()
        return _clean(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_lead_by_id error: {e}")
        return None


def get_lead_by_phone(phone: str) -> Optional[dict]:
    try:
        sb = _get_client()
        res = sb.table("leads").select("*").eq("phone", phone).maybe_single().execute()
        return _clean(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_lead_by_phone error: {e}")
        return None


def create_lead(name: str, phone: str, source: str = "manual") -> Optional[dict]:
    try:
        sb = _get_client()
        res = sb.table("leads").insert(
            {"name": name, "phone": phone, "source": source}
        ).execute()
        if res.data:
            return _clean(res.data[0])
        return None
    except Exception as e:
        err = str(e)
        if "duplicate" in err.lower() or "unique" in err.lower() or "23505" in err:
            logger.warning(f"create_lead: duplicate phone {phone}")
            return None
        logger.error(f"create_lead error: {e}")
        raise


def update_lead(lead_id: int, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_lead_by_id(lead_id)
    try:
        sb = _get_client()
        res = sb.table("leads").update(kwargs).eq("id", lead_id).execute()
        if res.data:
            return _clean(res.data[0])
        return get_lead_by_id(lead_id)
    except Exception as e:
        logger.error(f"update_lead error: {e}")
        return None


def delete_lead(lead_id: int) -> bool:
    try:
        sb = _get_client()
        sb.table("messages").delete().eq("lead_id", lead_id).execute()
        sb.table("leads").delete().eq("id", lead_id).execute()
        return True
    except Exception as e:
        logger.error(f"delete_lead error: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────
# MESSAGES
# ──────────────────────────────────────────────────────────────────────────

def get_messages_for_lead(lead_id: int) -> list:
    try:
        sb = _get_client()
        res = sb.table("messages").select("*").eq("lead_id", lead_id).order("timestamp").execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_messages_for_lead error: {e}")
        return []


def save_message(phone: str, direction: str, body: str, wa_message_id: Optional[str] = None) -> Optional[dict]:
    try:
        sb = _get_client()

        # Find lead
        lead_res = sb.table("leads").select("id").eq("phone", phone).maybe_single().execute()
        lead_id = lead_res.data["id"] if lead_res.data else None

        # Update last_contacted on inbound
        if lead_id and direction == "inbound":
            sb.table("leads").update({"last_contacted": datetime.utcnow().isoformat()}).eq("id", lead_id).execute()

        # Insert message (upsert on wa_message_id)
        payload = {"lead_id": lead_id, "phone": phone, "direction": direction, "body": body}
        if wa_message_id:
            payload["wa_message_id"] = wa_message_id
            res = sb.table("messages").upsert(payload, on_conflict="wa_message_id", ignore_duplicates=True).execute()
        else:
            res = sb.table("messages").insert(payload).execute()

        if res.data:
            return _clean(res.data[0])
        return None
    except Exception as e:
        logger.error(f"save_message error: {e}")
        return None


def get_recent_messages(limit: int = 50) -> list:
    try:
        sb = _get_client()
        # Supabase REST supports FK expansion
        res = sb.table("messages").select("*, leads(name)").order("timestamp", desc=True).limit(limit).execute()
        rows = []
        for r in (res.data or []):
            row = _clean(r)
            # Flatten nested lead name
            lead_obj = row.pop("leads", None)
            row["lead_name"] = (lead_obj or {}).get("name") if isinstance(lead_obj, dict) else None
            rows.append(row)
        return rows
    except Exception as e:
        logger.error(f"get_recent_messages error: {e}")
        return []


def delete_message(message_id: int) -> bool:
    try:
        sb = _get_client()
        sb.table("messages").delete().eq("id", message_id).execute()
        return True
    except Exception as e:
        logger.error(f"delete_message error: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────
# ANALYTICS
# ──────────────────────────────────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    try:
        sb = _get_client()
        today = date.today().isoformat()

        # Fetch all leads in one request and compute stats locally
        all_leads_res = sb.table("leads").select("id,status,source,created_at").execute()
        all_leads = all_leads_res.data or []

        total = len(all_leads)
        new_today = sum(1 for l in all_leads if (l.get("created_at") or "")[:10] == today)
        contacted = sum(1 for l in all_leads if l.get("status") == "contacted")
        converted = sum(1 for l in all_leads if l.get("status") == "converted")
        lost = sum(1 for l in all_leads if l.get("status") == "lost")

        msgs_res = sb.table("messages").select("id").gte("timestamp", today).execute()
        msgs_today = len(msgs_res.data or [])

        source_counts: dict = {}
        for l in all_leads:
            src = l.get("source") or "manual"
            source_counts[src] = source_counts.get(src, 0) + 1
        top_sources = sorted(
            [{"source": k, "count": v} for k, v in source_counts.items()],
            key=lambda x: -x["count"]
        )[:5]

        conversion_rate = round(converted / total * 100, 1) if total > 0 else 0.0

        return {
            "total_leads": total,
            "new_today": new_today,
            "contacted": contacted,
            "converted": converted,
            "lost": lost,
            "conversion_rate": conversion_rate,
            "messages_today": msgs_today,
            "top_sources": top_sources,
        }
    except Exception as e:
        logger.error(f"get_dashboard_stats error: {e}")
        return {
            "total_leads": 0, "new_today": 0, "contacted": 0,
            "converted": 0, "lost": 0, "conversion_rate": 0.0,
            "messages_today": 0, "top_sources": []
        }


def get_leads_over_time(days: int = 30) -> list:
    try:
        sb = _get_client()
        from datetime import timedelta
        since = (date.today() - timedelta(days=days)).isoformat()
        res = sb.table("leads").select("created_at").gte("created_at", since).execute()
        # Aggregate by date
        counts: dict = {}
        for r in (res.data or []):
            d = (r.get("created_at") or "")[:10]
            if d:
                counts[d] = counts.get(d, 0) + 1
        return sorted([{"date": k, "count": v} for k, v in counts.items()], key=lambda x: x["date"])
    except Exception as e:
        logger.error(f"get_leads_over_time error: {e}")
        return []


def get_conversion_funnel() -> list:
    try:
        sb = _get_client()
        statuses = ["new", "contacted", "interested", "converted", "lost"]
        results = []
        for s in statuses:
            cnt = len(sb.table("leads").select("id").eq("status", s).execute().data or [])
            results.append({"stage": s, "count": cnt})
        return results
    except Exception as e:
        logger.error(f"get_conversion_funnel error: {e}")
        return []


def get_leads_needing_followup() -> list:
    try:
        sb = _get_client()
        today = date.today().isoformat()
        res = (
            sb.table("leads")
            .select("*")
            .lte("follow_up_date", today)
            .not_.in_("status", ["converted", "lost"])
            .order("follow_up_date")
            .execute()
        )
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_leads_needing_followup error: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────
# REPORTS
# ──────────────────────────────────────────────────────────────────────────

def save_daily_report(report_date: str, stats: dict, ai_insights: str) -> bool:
    try:
        sb = _get_client()
        payload = {
            "report_date": report_date,
            "total_leads": stats.get("total_leads", 0),
            "new_leads": stats.get("new_today", 0),
            "contacted": stats.get("contacted", 0),
            "converted": stats.get("converted", 0),
            "ai_insights": ai_insights,
        }
        sb.table("daily_reports").upsert(payload, on_conflict="report_date").execute()
        return True
    except Exception as e:
        logger.error(f"save_daily_report error: {e}")
        return False


def get_reports(limit: int = 30) -> list:
    try:
        sb = _get_client()
        res = sb.table("daily_reports").select("*").order("report_date", desc=True).limit(limit).execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_reports error: {e}")
        return []


def get_today_report_exists() -> bool:
    try:
        sb = _get_client()
        today = date.today().isoformat()
        res = sb.table("daily_reports").select("id").eq("report_date", today).maybe_single().execute()
        return res.data is not None
    except Exception as e:
        logger.error(f"get_today_report_exists error: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────
# AI HELPERS
# ──────────────────────────────────────────────────────────────────────────

def get_unscored_leads(limit: int = 10) -> list:
    try:
        sb = _get_client()
        res = sb.table("leads").select("*").eq("ai_score", 0).order("created_at", desc=True).limit(limit).execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_unscored_leads error: {e}")
        return []


def get_top_scored_leads(limit: int = 5) -> list:
    try:
        sb = _get_client()
        res = sb.table("leads").select("*").gt("ai_score", 0).order("ai_score", desc=True).limit(limit).execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_top_scored_leads error: {e}")
        return []


def search_leads(query: str) -> list:
    try:
        sb = _get_client()
        # Use or_ with ilike for case-insensitive search across name and phone
        res = (
            sb.table("leads")
            .select("*")
            .or_(f"name.ilike.%{query}%,phone.ilike.%{query}%")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"search_leads error: {e}")
        return []

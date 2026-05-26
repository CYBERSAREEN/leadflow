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
    for field in ("created_at", "last_contacted", "follow_up_date"):
        if field in d and d[field] is not None and not isinstance(d[field], str):
            d[field] = str(d[field])
    for field in ("ai_summary", "notes", "source", "status"):
        if d.get(field) is None:
            d[field] = ""
    if d.get("ai_score") is None:
        d["ai_score"] = 0
    return d


def _norm_phone(phone: str) -> str:
    """Normalize phone number — strip +, spaces, dashes."""
    return phone.replace("+", "").replace(" ", "").replace("-", "").strip()


# ──────────────────────────────────────────────────────────────────────────
# Schema bootstrap (idempotent — only runs once at startup)
# ──────────────────────────────────────────────────────────────────────────
def init_db():
    """
    Create tables if they don't exist, using psycopg2 for DDL.
    Falls back to REST verification if psycopg2 can't connect.
    """
    import psycopg2, psycopg2.extras
    from urllib.parse import urlparse, unquote

    db_url = os.environ.get("DATABASE_URL", "")
    supabase_url = os.environ.get("SUPABASE_URL", "")

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

            # ── Users table ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Leads table ──
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
                    follow_up_date TIMESTAMP,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                )
            """)

            # ── Messages table ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
                    phone TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    body TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    wa_message_id TEXT UNIQUE
                )
            """)

            # ── Daily reports table ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id SERIAL PRIMARY KEY,
                    report_date DATE UNIQUE,
                    total_leads INTEGER,
                    new_leads INTEGER,
                    contacted INTEGER,
                    converted INTEGER,
                    ai_insights TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                )
            """)

            # ── Migrations: add columns if they don't exist ──
            try:
                cur.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
            except Exception:
                conn.rollback()

            try:
                cur.execute("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
            except Exception:
                conn.rollback()

            conn.commit()

            # ── Create default user (vedant) if not exists ──
            cur.execute("SELECT id FROM users WHERE username = 'vedant'")
            if not cur.fetchone():
                from backend.auth import get_password_hash
                hashed = get_password_hash("Vedant@1234")
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
                    ("vedant", hashed)
                )
                conn.commit()
                logger.info("Default user 'vedant' created")

            conn.close()
            logger.info("Database tables initialized via psycopg2")
            return
        except Exception as e:
            logger.warning(f"psycopg2 init_db failed (expected if IPv6-only): {e}")

    # Fallback: verify via Supabase REST
    try:
        sb = _get_client()
        sb.table("leads").select("id").limit(1).execute()
        logger.info("Database verified via Supabase REST API")
    except Exception as e:
        logger.error(f"init_db: REST check failed: {e}")
        logger.warning("Tables may not exist. Run CREATE TABLE via Supabase Dashboard SQL editor.")


# ──────────────────────────────────────────────────────────────────────────
# USERS
# ──────────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> Optional[dict]:
    try:
        sb = _get_client()
        res = sb.table("users").select("*").eq("username", username).maybe_single().execute()
        return dict(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_user_by_username error: {e}")
        return None


def get_user_by_id(user_id: int) -> Optional[dict]:
    try:
        sb = _get_client()
        res = sb.table("users").select("id,username,created_at").eq("id", user_id).maybe_single().execute()
        return dict(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_user_by_id error: {e}")
        return None


def create_user(username: str, password_hash: str) -> Optional[dict]:
    try:
        sb = _get_client()
        res = sb.table("users").insert({"username": username, "password_hash": password_hash}).execute()
        if res.data:
            return dict(res.data[0])
        return None
    except Exception as e:
        err = str(e)
        if "duplicate" in err.lower() or "unique" in err.lower():
            return None
        logger.error(f"create_user error: {e}")
        raise

# ──────────────────────────────────────────────────────────────────────────
# LEADS
# ──────────────────────────────────────────────────────────────────────────

def ensure_default_user():
    """Create default vedant user via REST if not exists (Supabase fallback)."""
    try:
        sb = _get_client()
        res = sb.table("users").select("id").eq("username", "vedant").maybe_single().execute()
        if not res.data:
            from backend.auth import get_password_hash
            hashed = get_password_hash("Vedant@1234")
            sb.table("users").insert({"username": "vedant", "password_hash": hashed}).execute()
            logger.info("Default user 'vedant' created via REST")
    except Exception as e:
        logger.error(f"ensure_default_user error: {e}")


# ──────────────────────────────────────────────────────────────────────────
# LEADS
# ──────────────────────────────────────────────────────────────────────────

def get_all_leads(status: Optional[str] = None, limit: int = 100, offset: int = 0,
                  user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        q = sb.table("leads").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
        if status:
            q = q.eq("status", status)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_all_leads error: {e}")
        return []


def get_lead_by_id(lead_id: int, user_id: Optional[int] = None) -> Optional[dict]:
    try:
        sb = _get_client()
        q = sb.table("leads").select("*").eq("id", lead_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.maybe_single().execute()
        return _clean(res.data) if res.data else None
    except Exception as e:
        logger.error(f"get_lead_by_id error: {e}")
        return None


def get_lead_by_phone(phone: str, user_id: Optional[int] = None) -> Optional[dict]:
    """Find lead by phone. Normalizes phone number."""
    try:
        phone_norm = _norm_phone(phone)
        sb = _get_client()
        # Try exact match first
        q = sb.table("leads").select("*").eq("phone", phone_norm)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.maybe_single().execute()
        if res.data:
            return _clean(res.data)
        # Try original phone if different
        if phone != phone_norm:
            q2 = sb.table("leads").select("*").eq("phone", phone)
            if user_id is not None:
                q2 = q2.eq("user_id", user_id)
            res2 = q2.maybe_single().execute()
            if res2.data:
                return _clean(res2.data)
        return None
    except Exception as e:
        logger.error(f"get_lead_by_phone error: {e}")
        return None


def create_lead(name: str, phone: str, source: str = "manual",
                user_id: Optional[int] = None) -> Optional[dict]:
    try:
        phone_norm = _norm_phone(phone)
        sb = _get_client()
        payload = {"name": name, "phone": phone_norm, "source": source}
        if user_id is not None:
            payload["user_id"] = user_id
        res = sb.table("leads").insert(payload).execute()
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


def update_lead(lead_id: int, user_id: Optional[int] = None, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_lead_by_id(lead_id)
    try:
        # Remove None values
        update_data = {k: v for k, v in kwargs.items() if v is not None or k in ('follow_up_date', 'last_contacted')}
        if not update_data:
            return get_lead_by_id(lead_id)
        sb = _get_client()
        q = sb.table("leads").update(update_data).eq("id", lead_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        if res.data:
            return _clean(res.data[0])
        return get_lead_by_id(lead_id)
    except Exception as e:
        logger.error(f"update_lead error: {e}")
        return None


def delete_lead(lead_id: int, user_id: Optional[int] = None) -> bool:
    try:
        sb = _get_client()
        # Check ownership first
        if user_id is not None:
            lead = get_lead_by_id(lead_id, user_id=user_id)
            if not lead:
                return False
        sb.table("messages").delete().eq("lead_id", lead_id).execute()
        q = sb.table("leads").delete().eq("id", lead_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        q.execute()
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


def save_message(phone: str, direction: str, body: str,
                 wa_message_id: Optional[str] = None,
                 user_id: Optional[int] = None) -> Optional[dict]:
    try:
        phone_norm = _norm_phone(phone)
        sb = _get_client()

        # Find lead by phone (for any user if user_id not given, else restrict)
        lead_res = sb.table("leads").select("id,user_id").eq("phone", phone_norm).maybe_single().execute()
        lead_id = lead_res.data["id"] if lead_res.data else None

        # Update last_contacted on inbound
        if lead_id and direction == "inbound":
            sb.table("leads").update({"last_contacted": datetime.utcnow().isoformat()}).eq("id", lead_id).execute()

        # Insert message (upsert on wa_message_id to avoid duplicates)
        payload = {"lead_id": lead_id, "phone": phone_norm, "direction": direction, "body": body}
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


def get_recent_messages(limit: int = 50, user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        # Get messages with lead info
        res = sb.table("messages").select("*, leads(name, user_id)").order("timestamp", desc=True).limit(limit).execute()
        rows = []
        for r in (res.data or []):
            row = _clean(r)
            lead_obj = row.pop("leads", None)
            lead_name = (lead_obj or {}).get("name") if isinstance(lead_obj, dict) else None
            lead_user_id = (lead_obj or {}).get("user_id") if isinstance(lead_obj, dict) else None
            row["lead_name"] = lead_name

            # Filter by user_id if provided
            if user_id is not None and lead_user_id is not None and lead_user_id != user_id:
                continue
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


def get_last_message_for_lead(lead_id: int) -> Optional[dict]:
    """Get the most recent message for a lead (for hover preview)."""
    try:
        sb = _get_client()
        res = sb.table("messages").select("*").eq("lead_id", lead_id).order("timestamp", desc=True).limit(1).execute()
        if res.data:
            return _clean(res.data[0])
        return None
    except Exception as e:
        logger.error(f"get_last_message_for_lead error: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# ANALYTICS
# ──────────────────────────────────────────────────────────────────────────

def get_dashboard_stats(user_id: Optional[int] = None) -> dict:
    try:
        sb = _get_client()
        today = date.today().isoformat()

        q = sb.table("leads").select("id,status,source,created_at,user_id")
        if user_id is not None:
            q = q.eq("user_id", user_id)
        all_leads_res = q.execute()
        all_leads = all_leads_res.data or []

        total = len(all_leads)
        new_today = sum(1 for l in all_leads if (l.get("created_at") or "")[:10] == today)
        contacted = sum(1 for l in all_leads if l.get("status") == "contacted")
        converted = sum(1 for l in all_leads if l.get("status") == "converted")
        lost = sum(1 for l in all_leads if l.get("status") == "lost")

        # Messages count (filtered if user_id given)
        if user_id is not None:
            lead_ids = [l["id"] for l in all_leads]
            if lead_ids:
                msgs_res = sb.table("messages").select("id").gte("timestamp", today).in_("lead_id", lead_ids).execute()
                msgs_today = len(msgs_res.data or [])
            else:
                msgs_today = 0
        else:
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


def get_leads_over_time(days: int = 30, user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        from datetime import timedelta
        since = (date.today() - timedelta(days=days)).isoformat()
        q = sb.table("leads").select("created_at").gte("created_at", since)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        counts: dict = {}
        for r in (res.data or []):
            d = (r.get("created_at") or "")[:10]
            if d:
                counts[d] = counts.get(d, 0) + 1
        return sorted([{"date": k, "count": v} for k, v in counts.items()], key=lambda x: x["date"])
    except Exception as e:
        logger.error(f"get_leads_over_time error: {e}")
        return []


def get_conversion_funnel(user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        statuses = ["new", "contacted", "interested", "converted", "lost"]
        results = []
        for s in statuses:
            q = sb.table("leads").select("id").eq("status", s)
            if user_id is not None:
                q = q.eq("user_id", user_id)
            cnt = len(q.execute().data or [])
            results.append({"stage": s, "count": cnt})
        return results
    except Exception as e:
        logger.error(f"get_conversion_funnel error: {e}")
        return []


def get_leads_needing_followup(user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        today = date.today().isoformat()
        q = (
            sb.table("leads")
            .select("*")
            .lte("follow_up_date", today)
            .not_.in_("status", ["converted", "lost"])
            .order("follow_up_date")
        )
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_leads_needing_followup error: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────
# REPORTS
# ──────────────────────────────────────────────────────────────────────────

def save_daily_report(report_date: str, stats: dict, ai_insights: str,
                      user_id: Optional[int] = None) -> bool:
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
        if user_id is not None:
            payload["user_id"] = user_id
        sb.table("daily_reports").upsert(payload, on_conflict="report_date").execute()
        return True
    except Exception as e:
        logger.error(f"save_daily_report error: {e}")
        return False


def get_reports(limit: int = 30, user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        q = sb.table("daily_reports").select("*").order("report_date", desc=True).limit(limit)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_reports error: {e}")
        return []


def get_today_report_exists(user_id: Optional[int] = None) -> bool:
    try:
        sb = _get_client()
        today = date.today().isoformat()
        q = sb.table("daily_reports").select("id").eq("report_date", today)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.maybe_single().execute()
        return res.data is not None
    except Exception as e:
        logger.error(f"get_today_report_exists error: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────
# AI HELPERS
# ──────────────────────────────────────────────────────────────────────────

def get_unscored_leads(limit: int = 10, user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        q = sb.table("leads").select("*").eq("ai_score", 0).order("created_at", desc=True).limit(limit)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_unscored_leads error: {e}")
        return []


def get_top_scored_leads(limit: int = 5, user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        q = sb.table("leads").select("*").gt("ai_score", 0).order("ai_score", desc=True).limit(limit)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"get_top_scored_leads error: {e}")
        return []


def search_leads(query: str, user_id: Optional[int] = None) -> list:
    try:
        sb = _get_client()
        q = (
            sb.table("leads")
            .select("*")
            .or_(f"name.ilike.%{query}%,phone.ilike.%{query}%")
            .order("created_at", desc=True)
            .limit(100)
        )
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return [_clean(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"search_leads error: {e}")
        return []

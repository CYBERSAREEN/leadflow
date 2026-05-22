import os
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, Any

logger = logging.getLogger(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "leadflow.db")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER REFERENCES leads(id),
                phone TEXT NOT NULL,
                direction TEXT NOT NULL,
                body TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                wa_message_id TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date DATE UNIQUE,
                total_leads INTEGER,
                new_leads INTEGER,
                contacted INTEGER,
                converted INTEGER,
                ai_insights TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        raise


def row_to_dict(row) -> dict:
    if row is None:
        return None
    return dict(row)


def get_all_leads(status: Optional[str] = None, limit: int = 100, offset: int = 0) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        if status:
            cur.execute(
                "SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            )
        else:
            cur.execute(
                "SELECT * FROM leads ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_all_leads error: {e}")
        return []


def get_lead_by_id(lead_id: int) -> Optional[dict]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = row_to_dict(cur.fetchone())
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"get_lead_by_id error: {e}")
        return None


def get_lead_by_phone(phone: str) -> Optional[dict]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM leads WHERE phone = ?", (phone,))
        row = row_to_dict(cur.fetchone())
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"get_lead_by_phone error: {e}")
        return None


def create_lead(name: str, phone: str, source: str = "manual") -> Optional[dict]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO leads (name, phone, source) VALUES (?, ?, ?)",
            (name, phone, source)
        )
        lead_id = cur.lastrowid
        conn.commit()
        cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = row_to_dict(cur.fetchone())
        conn.close()
        return row
    except sqlite3.IntegrityError as e:
        logger.error(f"create_lead integrity error (duplicate phone?): {e}")
        return None
    except sqlite3.Error as e:
        logger.error(f"create_lead error: {e}")
        return None


def update_lead(lead_id: int, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_lead_by_id(lead_id)
    try:
        conn = get_connection()
        cur = conn.cursor()
        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [lead_id]
        cur.execute(f"UPDATE leads SET {fields} WHERE id = ?", values)
        conn.commit()
        cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = row_to_dict(cur.fetchone())
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"update_lead error: {e}")
        return None


def delete_lead(lead_id: int) -> bool:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE lead_id = ?", (lead_id,))
        cur.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        logger.error(f"delete_lead error: {e}")
        return False


def get_messages_for_lead(lead_id: int) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM messages WHERE lead_id = ? ORDER BY timestamp ASC",
            (lead_id,)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_messages_for_lead error: {e}")
        return []


def save_message(phone: str, direction: str, body: str, wa_message_id: Optional[str] = None) -> Optional[dict]:
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT id FROM leads WHERE phone = ?", (phone,))
        lead_row = cur.fetchone()
        lead_id = lead_row["id"] if lead_row else None

        if lead_id and direction == "inbound":
            cur.execute(
                "UPDATE leads SET last_contacted = CURRENT_TIMESTAMP WHERE id = ?",
                (lead_id,)
            )

        cur.execute(
            """INSERT OR IGNORE INTO messages (lead_id, phone, direction, body, wa_message_id)
               VALUES (?, ?, ?, ?, ?)""",
            (lead_id, phone, direction, body, wa_message_id)
        )
        msg_id = cur.lastrowid
        conn.commit()

        cur.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
        row = row_to_dict(cur.fetchone())
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"save_message error: {e}")
        return None


def get_dashboard_stats() -> dict:
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as cnt FROM leads")
        total_leads = cur.fetchone()["cnt"]

        today = date.today().isoformat()
        cur.execute("SELECT COUNT(*) as cnt FROM leads WHERE DATE(created_at) = ?", (today,))
        new_today = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = 'contacted'")
        contacted = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = 'converted'")
        converted = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = 'lost'")
        lost = cur.fetchone()["cnt"]

        conversion_rate = round((converted / total_leads * 100), 1) if total_leads > 0 else 0.0

        cur.execute("SELECT COUNT(*) as cnt FROM messages WHERE DATE(timestamp) = ?", (today,))
        messages_today = cur.fetchone()["cnt"]

        cur.execute(
            "SELECT source, COUNT(*) as cnt FROM leads GROUP BY source ORDER BY cnt DESC LIMIT 5"
        )
        top_sources = [{"source": r["source"], "count": r["cnt"]} for r in cur.fetchall()]

        conn.close()
        return {
            "total_leads": total_leads,
            "new_today": new_today,
            "contacted": contacted,
            "converted": converted,
            "lost": lost,
            "conversion_rate": conversion_rate,
            "messages_today": messages_today,
            "top_sources": top_sources,
        }
    except sqlite3.Error as e:
        logger.error(f"get_dashboard_stats error: {e}")
        return {
            "total_leads": 0, "new_today": 0, "contacted": 0,
            "converted": 0, "lost": 0, "conversion_rate": 0.0,
            "messages_today": 0, "top_sources": []
        }


def get_leads_needing_followup() -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        today = date.today().isoformat()
        cur.execute(
            """SELECT * FROM leads
               WHERE follow_up_date <= ?
               AND status NOT IN ('converted', 'lost')
               ORDER BY follow_up_date ASC""",
            (today,)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_leads_needing_followup error: {e}")
        return []


def save_daily_report(report_date: str, stats: dict, ai_insights: str) -> bool:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO daily_reports
               (report_date, total_leads, new_leads, contacted, converted, ai_insights)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                report_date,
                stats.get("total_leads", 0),
                stats.get("new_today", 0),
                stats.get("contacted", 0),
                stats.get("converted", 0),
                ai_insights,
            )
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        logger.error(f"save_daily_report error: {e}")
        return False


def get_reports(limit: int = 30) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT ?",
            (limit,)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_reports error: {e}")
        return []


def get_leads_over_time(days: int = 30) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """SELECT DATE(created_at) as date, COUNT(*) as count
               FROM leads
               WHERE created_at >= DATE('now', ?)
               GROUP BY DATE(created_at)
               ORDER BY date ASC""",
            (f"-{days} days",)
        )
        rows = [{"date": r["date"], "count": r["count"]} for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_leads_over_time error: {e}")
        return []


def get_conversion_funnel() -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        statuses = ["new", "contacted", "interested", "converted", "lost"]
        results = []
        for s in statuses:
            cur.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = ?", (s,))
            results.append({"stage": s, "count": cur.fetchone()["cnt"]})
        conn.close()
        return results
    except sqlite3.Error as e:
        logger.error(f"get_conversion_funnel error: {e}")
        return []


def get_recent_messages(limit: int = 50) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """SELECT m.*, l.name as lead_name
               FROM messages m
               LEFT JOIN leads l ON m.lead_id = l.id
               ORDER BY m.timestamp DESC
               LIMIT ?""",
            (limit,)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_recent_messages error: {e}")
        return []


def get_unscored_leads(limit: int = 10) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM leads WHERE ai_score = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_unscored_leads error: {e}")
        return []


def get_top_scored_leads(limit: int = 5) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM leads WHERE ai_score > 0 ORDER BY ai_score DESC LIMIT ?",
            (limit,)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"get_top_scored_leads error: {e}")
        return []


def search_leads(query: str) -> list:
    try:
        conn = get_connection()
        cur = conn.cursor()
        pattern = f"%{query}%"
        cur.execute(
            "SELECT * FROM leads WHERE name LIKE ? OR phone LIKE ? ORDER BY created_at DESC LIMIT 100",
            (pattern, pattern)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"search_leads error: {e}")
        return []


def delete_message(message_id: int) -> bool:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except sqlite3.Error as e:
        logger.error(f"delete_message error: {e}")
        return False


def get_today_report_exists() -> bool:
    try:
        conn = get_connection()
        cur = conn.cursor()
        today = date.today().isoformat()
        cur.execute("SELECT id FROM daily_reports WHERE report_date = ?", (today,))
        exists = cur.fetchone() is not None
        conn.close()
        return exists
    except sqlite3.Error as e:
        logger.error(f"get_today_report_exists error: {e}")
        return False

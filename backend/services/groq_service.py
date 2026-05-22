import os
import json
import logging
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in environment")
        _client = Groq(api_key=api_key)
    return _client


def score_lead(lead_name: str, lead_messages: list[str]) -> dict:
    fallback = {
        "score": 50,
        "reason": "Unable to score",
        "intent": "medium",
        "suggested_action": "Follow up manually"
    }
    try:
        client = get_client()
        messages_joined = " | ".join(lead_messages[-10:]) if lead_messages else "No messages yet"

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a lead scoring AI for an education platform. "
                        "Score leads 0-100 based on engagement signals in their WhatsApp messages. "
                        "Return ONLY valid JSON with keys: score (int 0-100), "
                        "reason (str max 30 words), intent (one of: high/medium/low), "
                        "suggested_action (str max 20 words)."
                    )
                },
                {
                    "role": "user",
                    "content": f"Lead: {lead_name}. Messages: {messages_joined}"
                }
            ],
            temperature=0.3,
            max_tokens=200,
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        result = json.loads(raw)

        if not isinstance(result.get("score"), int):
            result["score"] = int(result.get("score", 50))
        result["score"] = max(0, min(100, result["score"]))

        for key in ["reason", "intent", "suggested_action"]:
            if key not in result:
                result[key] = fallback[key]

        return result

    except json.JSONDecodeError as e:
        logger.error(f"score_lead JSON parse error: {e}")
        return fallback
    except Exception as e:
        logger.error(f"score_lead error: {e}")
        return fallback


def generate_daily_insights(stats: dict, leads: list) -> str:
    try:
        client = get_client()
        lead_count = len(leads)
        stats_text = (
            f"Total leads: {stats.get('total_leads', 0)}, "
            f"New today: {stats.get('new_today', 0)}, "
            f"Contacted: {stats.get('contacted', 0)}, "
            f"Converted: {stats.get('converted', 0)}, "
            f"Lost: {stats.get('lost', 0)}, "
            f"Conversion rate: {stats.get('conversion_rate', 0)}%, "
            f"Messages today: {stats.get('messages_today', 0)}, "
            f"Active leads in pipeline: {lead_count}"
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a CRM analyst. Generate a 3-bullet daily insight summary "
                        "for a sales manager. Be specific with numbers. Max 150 words."
                    )
                },
                {
                    "role": "user",
                    "content": f"Today's CRM stats: {stats_text}"
                }
            ],
            temperature=0.5,
            max_tokens=250,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"generate_daily_insights error: {e}")
        return (
            f"• Total leads in system: {stats.get('total_leads', 0)}\n"
            f"• New leads today: {stats.get('new_today', 0)}\n"
            f"• Conversion rate: {stats.get('conversion_rate', 0)}%"
        )


def suggest_reply(conversation_history: list[str]) -> str:
    try:
        client = get_client()
        history_text = "\n".join(conversation_history[-6:]) if conversation_history else "No messages yet"

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful education counselor assistant. "
                        "Suggest a warm, professional WhatsApp reply in under 50 words "
                        "based on conversation context. Return only the reply text, nothing else."
                    )
                },
                {
                    "role": "user",
                    "content": f"Conversation:\n{history_text}"
                }
            ],
            temperature=0.6,
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"suggest_reply error: {e}")
        return "Thank you for reaching out! I'd be happy to help you learn more about our programs. When would be a good time to connect?"

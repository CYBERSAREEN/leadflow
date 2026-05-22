import httpx
import logging

logger = logging.getLogger(__name__)
WA_SERVER_URL = "http://localhost:3001"


async def send_message(phone: str, message: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{WA_SERVER_URL}/send",
                json={"phone": phone, "message": message}
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("success", False)
            else:
                logger.error(f"send_message HTTP error {response.status_code}: {response.text}")
                return False
    except httpx.ConnectError:
        logger.error("send_message: WhatsApp server not reachable at localhost:3001")
        return False
    except Exception as e:
        logger.error(f"send_message error: {e}")
        return False


async def get_qr_code() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{WA_SERVER_URL}/qr")
            if response.status_code == 200:
                return response.json()
            return {"connected": False, "qr": None}
    except httpx.ConnectError:
        return {"connected": False, "qr": None}
    except Exception as e:
        logger.error(f"get_qr_code error: {e}")
        return {"connected": False, "qr": None}


async def get_connection_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{WA_SERVER_URL}/status")
            if response.status_code == 200:
                return response.json()
            return {"connected": False, "phone": None}
    except httpx.ConnectError:
        return {"connected": False, "phone": None}
    except Exception as e:
        logger.error(f"get_connection_status error: {e}")
        return {"connected": False, "phone": None}


async def disconnect() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{WA_SERVER_URL}/disconnect")
            if response.status_code == 200:
                return response.json()
            return {"success": False}
    except httpx.ConnectError:
        return {"success": False, "error": "Bridge not reachable"}
    except Exception as e:
        logger.error(f"disconnect error: {e}")
        return {"success": False, "error": str(e)}

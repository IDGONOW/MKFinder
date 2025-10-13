import os
import httpx
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from main import parse_query_to_filters, _is_valid_consulta, _match, MOCK_DATA

router = APIRouter(prefix="/bot/telegram", tags=["telegram"])
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def _send_message(chat_id: int, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(api, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

@router.post("/webhook")
async def tg_webhook(request: Request):
    payload: Dict[str, Any] = await request.json()
    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if not text:
        await _send_message(chat_id, "Envíame lo que buscas. Ej: ‘Venta en Miraflores y San Isidro, 2 dorm, hasta 250k usd, con ascensor’.")
        return {"ok": True}

    consulta = parse_query_to_filters(text)
    if not _is_valid_consulta(consulta):
        await _send_message(chat_id, "Necesito al menos un distrito y un parámetro extra (tipo, precio, m², dormitorios/baños o amenidades).")
        return {"ok": True}

    matches = [p for p in MOCK_DATA if _match(p, consulta)]
    if not matches:
        await _send_message(chat_id, "No encontré coincidencias en el demo. Ajusta filtros o prueba otro distrito.")
        return {"ok": True}

    lines = [f"<b>{m['titulo']}</b>\n{m['operacion'].title()} · {m['tipo']} · {m['distrito']}\n{m['moneda']} {m['precio']:,}\n{m['url_aviso']}" for m in matches[:5]]
    await _send_message(chat_id, "\n\n".join(lines))
    return {"ok": True}

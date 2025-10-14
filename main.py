# main.py
from fastapi import FastAPI, Request
import os
import httpx
import time
from typing import Dict, Any, List

# Importa el adapter real de Urbania
from adapters.urbania import UrbaniaAdapter

app = FastAPI(title="MK Finder MVP")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# =============================
# 🔒 Memoria corta por chat (RAM)
# =============================
# Estructura:
# SESSION[chat_id] = {
#   "filtros": dict,
#   "awaiting": None | "moneda",
#   "ts": epoch_seconds
# }
SESSION: Dict[int, Dict[str, Any]] = {}
SESSION_TTL_SECONDS = 10 * 60  # 10 minutos

def _now() -> int:
    return int(time.time())

def _get_session(chat_id: int) -> Dict[str, Any]:
    s = SESSION.get(chat_id) or {}
    # limpiar si expira
    if s and (_now() - s.get("ts", 0) > SESSION_TTL_SECONDS):
        s = {}
    # asegurar estructura mínima
    s.setdefault("filtros", {})
    s.setdefault("awaiting", None)
    s["ts"] = _now()
    SESSION[chat_id] = s
    return s

def _clear_session(chat_id: int) -> None:
    SESSION.pop(chat_id, None)

# =============================
# 🧠 Parser simple con moneda
# =============================
def parse_query_to_filters(query: str) -> dict:
    """Convierte texto libre en filtros (detecta operación, distritos, dormitorios, precio, moneda)."""
    q = (query or "").lower()
    filtros = {
        "distritos": [],
        "precio_max": None,
        "dormitorios": None,
        "operacion": None,
        "tipo": None,
        "moneda": None,
        "ascensor": "ascensor" in q,
    }

    # Operación
    if "venta" in q:
        filtros["operacion"] = "venta"
    elif "alquiler" in q or "renta" in q:
        filtros["operacion"] = "alquiler"

    # Tipos (muy básico)
    for t in ["departamento", "casa", "duplex", "dúplex", "flat"]:
        if t in q:
            filtros["tipo"] = t

    # Distritos (amplía según necesites)
    for d in ["miraflores", "san isidro", "surco", "san borja", "barranco", "magdalena", "la molina", "jesus maria", "jesús maría"]:
        if d in q:
            filtros["distritos"].append(d.title())

    # Moneda
    if "usd" in q or "$" in q or "dólar" in q or "dolares" in q or "dólares" in q:
        filtros["moneda"] = "USD"
    elif "sol" in q or "soles" in q or "pen" in q:
        filtros["moneda"] = "PEN"

    # Precio y dormitorios (heurística simple)
    tokens = q.replace(",", " ").split()
    for tok in tokens:
        if "k" in tok:
            try:
                filtros["precio_max"] = int(float(tok.replace("k", "")) * 1000)
            except:
                pass
        elif tok.isdigit() and int(tok) > 1000:
            filtros["precio_max"] = int(tok)
        elif tok.isdigit() and int(tok) <= 10:
            # podría ser dormitorios si no hay m2 al lado
            filtros["dormitorios"] = int(tok)

    return filtros

def _is_valid_consulta(filtros: dict) -> bool:
    # Requerimos al menos un distrito y algún otro filtro u operación
    if not filtros.get("distritos"):
        return False
    extra = [
        filtros.get("operacion"),
        filtros.get("tipo"),
        filtros.get("precio_max"),
        filtros.get("dormitorios"),
        filtros.get("ascensor"),
        filtros.get("moneda"),
    ]
    return any(v not in (None, False, "", []) for v in extra)

# =============================
# 💬 Envío a Telegram
# =============================
async def _tg_send_message(chat_id: int, text: str) -> None:
    token = TELEGRAM_BOT_TOKEN
    if not token:
        print("⚠️ TELEGRAM_BOT_TOKEN no detectado en entorno")
        return
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            await client.post(api, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception as e:
            print(f"❌ Error enviando mensaje: {e}")

# =============================
# 🔁 Fusión de filtros (estado previo + nuevos)
# =============================
def _merge_filters(old: dict, new: dict) -> dict:
    merged = dict(old or {})
    for k, v in (new or {}).items():
        if v not in (None, "", [], False):
            merged[k] = v
    if "distritos" in new and new["distritos"]:
        # unir distritos sin duplicar
        merged.setdefault("distritos", [])
        merged["distritos"] = sorted(list(dict.fromkeys(merged["distritos"] + new["distritos"])))
    return merged

# =============================
# 🚀 Webhook de Telegram con estado
# =============================
@app.post("/bot/telegram/webhook")
async def tg_webhook(request: Request):
    payload = await request.json()
    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    # Carga/crea sesión
    sess = _get_session(chat_id)

    # Si venimos de una pregunta de moneda, intenta resolver con esta respuesta
    if sess.get("awaiting") == "moneda":
        lower = text.lower()
        if lower in ("usd", "dólar", "dolares", "dólares", "$"):
            sess["filtros"]["moneda"] = "USD"
            sess["awaiting"] = None
        elif lower in ("pen", "sol", "soles", "s/"):
            sess["filtros"]["moneda"] = "PEN"
            sess["awaiting"] = None
        else:
            await _tg_send_message(chat_id, "Por favor responde con <b>USD</b> o <b>Soles</b>.")
            return {"ok": True}

        # Ya tenemos moneda, seguimos con la búsqueda usando los filtros guardados
        consulta = sess["filtros"]
        await _tg_send_message(chat_id, "🔍 Gracias. Buscando propiedades…")
        adapter = UrbaniaAdapter()
        try:
            resultados = await adapter.buscar(consulta)
        except Exception as e:
            print(f"Error Urbania (moneda-respuesta): {e}")
            await _tg_send_message(chat_id, "❌ Ocurrió un error al conectar con Urbania.")
            return {"ok": True}

        if not resultados:
            await _tg_send_message(chat_id, "No encontré coincidencias en Urbania. Ajusta los filtros o prueba otro distrito.")
            return {"ok": True}

        lines: List[str] = []
        for m in resultados[:5]:
            line = (
                f"<b>{m.get('titulo','(sin título)')}</b>\n"
                f"{m.get('operacion','').title()} · {m.get('tipo','')} · {m.get('distrito','')}\n"
                f"{m.get('moneda','')} {m.get('precio',''):,}\n"
                f"{m.get('url_aviso','')}"
            )
            lines.append(line)
        await _tg_send_message(chat_id, "\n\n".join(lines))
        # opcional: limpiar sesión
        _clear_session(chat_id)
        return {"ok": True}

    # Flujo normal: nuevo mensaje de búsqueda
    if not text:
        await _tg_send_message(chat_id, "Envíame lo que buscas. Ejemplo: ‘Venta en Miraflores, 2 dorm, hasta 250k usd’.")
        return {"ok": True}

    new_filters = parse_query_to_filters(text)
    # fusiona con lo que ya teníamos en memoria (por si el usuario envía detalles en varios mensajes)
    consulta = _merge_filters(sess.get("filtros"), new_filters)
    sess["filtros"] = consulta  # persiste

    # Validación base
    if not consulta.get("distritos"):
        await _tg_send_message(chat_id, "Necesito al menos un distrito (Miraflores, Surco, etc.) y algún filtro adicional como precio, m² o dormitorios.")
        return {"ok": True}

    # Si no especificó moneda, pregúntala y queda en espera
    if not consulta.get("moneda"):
        sess["awaiting"] = "moneda"
        await _tg_send_message(chat_id, "¿En qué moneda deseas buscar propiedades? 💰\n\nResponde escribiendo <b>USD</b> o <b>Soles</b>.")
        return {"ok": True}

    # Ya tenemos todo, buscar en Urbania
    await _tg_send_message(chat_id, "🔍 Buscando propiedades en Urbania, un momento por favor...")
    adapter = UrbaniaAdapter()
    try:
        resultados = await adapter.buscar(consulta)
    except Exception as e:
        print(f"Error Urbania: {e}")
        await _tg_send_message(chat_id, "❌ Ocurrió un error al conectar con Urbania.")
        return {"ok": True}

    if not resultados:
        await _tg_send_message(chat_id, "No encontré coincidencias en Urbania. Ajusta los filtros o prueba otro distrito.")
        return {"ok": True}

    lines: List[str] = []
    for m in resultados[:5]:
        line = (
            f"<b>{m.get('titulo','(sin título)')}</b>\n"
            f"{m.get('operacion','').title()} · {m.get('tipo','')} · {m.get('distrito','')}\n"
            f"{m.get('moneda','')} {m.get('precio',''):,}\n"
            f"{m.get('url_aviso','')}"
        )
        lines.append(line)
    await _tg_send_message(chat_id, "\n\n".join(lines))
    # opcional: limpiar sesión después de responder
    _clear_session(chat_id)
    return {"ok": True}

# =============================
# 🩺 Healthcheck
# =============================
@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "MK Finder MVP",
        "telegram": bool(TELEGRAM_BOT_TOKEN),
        "sessions": len(SESSION),
    }

# =============================
# ✅ Inicio local/Railway
# =============================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)


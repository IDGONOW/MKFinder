# main.py
from fastapi import FastAPI, Request
import os
import httpx
from adapters.urbania import UrbaniaAdapter

# =============================
# 🔧 Configuración básica
# =============================
app = FastAPI(title="MK Finder MVP")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# =============================
# 🧠 Función de parsing del texto
# =============================
def parse_query_to_filters(query: str) -> dict:
    """Convierte texto libre en filtros estructurados (detecta moneda, distritos, etc.)."""
    query = query.lower()
    filtros = {
        "distritos": [],
        "precio_max": None,
        "dormitorios": None,
        "operacion": None,
        "tipo": None,
        "moneda": None,
        "ascensor": "ascensor" in query,
    }

    # Operación
    if "venta" in query:
        filtros["operacion"] = "venta"
    elif "alquiler" in query or "renta" in query:
        filtros["operacion"] = "alquiler"

    # Distritos
    for d in ["miraflores", "san isidro", "surco", "san borja", "barranco", "magdalena", "la molina", "jesus maria"]:
        if d in query:
            filtros["distritos"].append(d.title())

    # Moneda
    if "usd" in query or "$" in query or "dólar" in query or "dolares" in query:
        filtros["moneda"] = "USD"
    elif "sol" in query or "soles" in query or "pen" in query:
        filtros["moneda"] = "PEN"

    # Precio y dormitorios
    for palabra in query.replace(",", " ").split():
        if "k" in palabra:
            try:
                filtros["precio_max"] = int(float(palabra.replace("k", "")) * 1000)
            except:
                pass
        elif palabra.isdigit() and int(palabra) > 1000:
            filtros["precio_max"] = int(palabra)
        elif palabra.isdigit() and int(palabra) <= 10:
            filtros["dormitorios"] = int(palabra)

    return filtros


def _is_valid_consulta(filtros: dict) -> bool:
    return len(filtros["distritos"]) > 0


# =============================
# 💬 Función para enviar mensaje a Telegram
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
            print(f"✅ Mensaje enviado a chat_id={chat_id}")
        except Exception as e:
            print(f"❌ Error enviando mensaje: {e}")

# =============================
# 🚀 Webhook de Telegram
# =============================
@app.post("/bot/telegram/webhook")
async def tg_webhook(request: Request):
    payload = await request.json()
    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if not text:
        await _tg_send_message(chat_id, "Envíame lo que buscas. Ejemplo: ‘Venta en Miraflores, 2 dorm, hasta 250k usd’.")
        return {"ok": True}

    # Parseo del texto
    consulta = parse_query_to_filters(text)

    # Validación de entrada
    if not _is_valid_consulta(consulta):
        await _tg_send_message(chat_id, "Necesito al menos un distrito (Miraflores, Surco, etc.) y algún filtro adicional como precio, m² o dormitorios.")
        return {"ok": True}

    # Si no especificó moneda, preguntar
    if not consulta.get("moneda"):
        await _tg_send_message(chat_id, "¿En qué moneda deseas buscar propiedades? 💰\n\nResponde escribiendo USD o Soles.")
        return {"ok": True}

    # Llamar a Urbania
    adapter = UrbaniaAdapter()
    await _tg_send_message(chat_id, "🔍 Buscando propiedades en Urbania, un momento por favor...")

    try:
        resultados = await adapter.buscar(consulta)
    except Exception as e:
        print(f"Error al buscar en Urbania: {e}")
        await _tg_send_message(chat_id, "❌ Ocurrió un error al conectar con Urbania.")
        return {"ok": True}

    if not resultados:
        await _tg_send_message(chat_id, "No encontré coincidencias en Urbania. Ajusta los filtros o prueba otro distrito.")
        return {"ok": True}

    # Mostrar los primeros resultados
    lines = []
    for m in resultados[:5]:
        line = (
            f"<b>{m.get('titulo','(sin título)')}</b>\n"
            f"{m.get('operacion','').title()} · {m.get('tipo','')} · {m.get('distrito','')}\n"
            f"{m.get('moneda','')} {m.get('precio',''):,}\n"
            f"{m.get('url_aviso','')}"
        )
        lines.append(line)

    await _tg_send_message(chat_id, "\n\n".join(lines))
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
    }

# =============================
# ✅ Inicio local o Railway
# =============================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

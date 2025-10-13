# main.py
from fastapi import FastAPI, Request
import os
import httpx

# =============================
# 🔧 Configuración básica
# =============================
app = FastAPI(title="MK Finder MVP")

# Lee el token desde las variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# =============================
# 🧩 Datos MOCK para demo
# =============================
MOCK_DATA = [
    {
        "titulo": "Departamento moderno en Miraflores",
        "operacion": "venta",
        "tipo": "departamento",
        "distrito": "Miraflores",
        "precio": 230000,
        "moneda": "USD",
        "url_aviso": "https://urbania.pe/inmueble/departamento-en-venta-miraflores-230000usd",
    },
    {
        "titulo": "Departamento con vista al parque en San Isidro",
        "operacion": "venta",
        "tipo": "departamento",
        "distrito": "San Isidro",
        "precio": 245000,
        "moneda": "USD",
        "url_aviso": "https://urbania.pe/inmueble/departamento-en-venta-san-isidro-245000usd",
    },
    {
        "titulo": "Flat en Surco con cochera",
        "operacion": "venta",
        "tipo": "departamento",
        "distrito": "Surco",
        "precio": 180000,
        "moneda": "USD",
        "url_aviso": "https://urbania.pe/inmueble/departamento-en-venta-surco-180000usd",
    },
]

# =============================
# 🧠 Funciones de búsqueda mock
# =============================

def parse_query_to_filters(query: str) -> dict:
    """Convierte el texto libre en filtros simples"""
    query = query.lower()
    filtros = {
        "distritos": [],
        "precio_max": None,
        "dormitorios": None,
        "operacion": None,
        "tipo": None,
        "ascensor": "ascensor" in query,
    }
    if "venta" in query:
        filtros["operacion"] = "venta"
    elif "alquiler" in query:
        filtros["operacion"] = "alquiler"

    for d in ["miraflores", "san isidro", "surco", "san borja", "barranco"]:
        if d in query:
            filtros["distritos"].append(d.title())

    for palabra in query.split():
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


def _match(prop: dict, filtros: dict) -> bool:
    if filtros["operacion"] and prop["operacion"] != filtros["operacion"]:
        return False
    if filtros["tipo"] and prop["tipo"] != filtros["tipo"]:
        return False
    if filtros["distritos"] and prop["distrito"] not in filtros["distritos"]:
        return False
    if filtros["precio_max"] and prop["precio"] > filtros["precio_max"]:
        return False
    return True

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
            await client.post(
                api,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            )
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

    consulta = parse_query_to_filters(text)
    if not _is_valid_consulta(consulta):
        await _tg_send_message(chat_id, "Necesito al menos un distrito (Miraflores, Surco, etc.) y algún filtro adicional como precio, m² o dormitorios.")
        return {"ok": True}

    matches = [p for p in MOCK_DATA if _match(p, consulta)]
    if not matches:
        await _tg_send_message(chat_id, "No encontré coincidencias demo. Ajusta los filtros o prueba otro distrito.")
        return {"ok": True}

    lines = [
        f"<b>{m['titulo']}</b>\n{m['operacion'].title()} · {m['tipo']} · {m['distrito']}\n"
        f"{m['moneda']} {m['precio']:,}\n{m['url_aviso']}"
        for m in matches[:5]
    ]
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
# ✅ Inicio de app (para Railway)
# =============================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

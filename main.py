# main.py
from fastapi import FastAPI, Request
import os
import httpx
from adapters.urbania import UrbaniaAdapter

app = FastAPI(title="MK Finder MVP")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "MK Finder MVP",
        "telegram": bool(TELEGRAM_BOT_TOKEN)
    }

@app.get("/test/urbania")
async def test_urbania():
    adapter = UrbaniaAdapter()
    consulta = {
        "operacion": "venta",
        "distritos": ["miraflores"],
        "precio_max": 300000,
        "moneda": "USD"
    }
    res = await adapter.buscar(consulta)
    return {"count": len(res), "sample": res[:5]}

# Webhook de Telegram (solo placeholder para probar)
@app.post("/bot/telegram/webhook")
async def telegram_webhook(request: Request):
    payload = await request.json()
    print("📩 Mensaje recibido de Telegram:", payload)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

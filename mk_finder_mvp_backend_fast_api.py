"""
MK Finder - MVP backend (FastAPI)
---------------------------------

Qué incluye este MVP (listo para ejecutar):
1) /nlu/parse  -> recibe texto libre y devuelve consulta estructurada (distritos obligatorios).
2) /buscar     -> recibe texto libre o JSON estructurado; valida reglas y filtra un dataset de ejemplo.

Cómo ejecutar localmente:
- Python 3.10+
- pip install fastapi uvicorn pydantic
- Guardar este archivo como main.py
- Ejecutar: uvicorn main:app --reload --port 8000

Probar:
- NLU:    POST http://localhost:8000/nlu/parse {"query": "alquiler en Surco o San Borja, 3 dorm, hasta 2500 soles, con cochera"}
- Buscar: POST http://localhost:8000/buscar {"query": "venta en Miraflores y San Isidro, 2 dorm, min 70 m2, hasta 250k usd"}

Notas:
- Distritos: mapeo y normalización básica (Lima/Callao más comunes). Se puede ampliar fácilmente.
- Reglas: al menos 1 distrito + 1 parámetro adicional (precio, m2, dorm/baños, tipo, amenidades).
- Dataset: mock en memoria; luego conectaremos Urbania/Properati.
"""
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import re

app = FastAPI(title="MK Finder MVP", version="0.1.0")

# -----------------------------
# 1) Catálogo de distritos (base)
# -----------------------------
DISTRITOS_CANONICOS = [
    "Miraflores", "San Isidro", "Barranco", "Santiago de Surco",
    "La Molina", "San Borja", "San Miguel", "Magdalena del Mar",
    "Jesús María", "Lince", "Pueblo Libre", "San Luis", "Lima",
    "Breña", "Rímac", "Chorrillos", "Surquillo", "Ate", "Santa Anita",
    "La Victoria", "San Juan de Miraflores", "Villa El Salvador",
    "Villa María del Triunfo", "Comas", "Los Olivos",
    "San Martín de Porres", "Independencia", "Carabayllo",
    "Puente Piedra", "Callao", "La Perla", "Bellavista", "La Punta"
]

# Sinónimos -> canónico
DISTRITOS_MAP = {
    "surco": "Santiago de Surco",
    "santiago de surco": "Santiago de Surco",
    "miraflores": "Miraflores",
    "san isidro": "San Isidro",
    "barranco": "Barranco",
    "la molina": "La Molina",
    "san borja": "San Borja",
    "san miguel": "San Miguel",
    "magdalena": "Magdalena del Mar",
    "magdalena del mar": "Magdalena del Mar",
    "jesus maria": "Jesús María",
    "jesús maría": "Jesús María",
    "lince": "Lince",
    "pueblo libre": "Pueblo Libre",
    "san luis": "San Luis",
    "cercado": "Lima",
    "lima": "Lima",
    "breña": "Breña",
    "rimac": "Rímac",
    "rímac": "Rímac",
    "chorrillos": "Chorrillos",
    "surquillo": "Surquillo",
    "ate": "Ate",
    "santa anita": "Santa Anita",
    "la victoria": "La Victoria",
    "sjm": "San Juan de Miraflores",
    "san juan de miraflores": "San Juan de Miraflores",
    "ves": "Villa El Salvador",
    "villa el salvador": "Villa El Salvador",
    "vmt": "Villa María del Triunfo",
    "villa maria del triunfo": "Villa María del Triunfo",
    "comas": "Comas",
    "los olivos": "Los Olivos",
    "san martin de porres": "San Martín de Porres",
    "san martín de porres": "San Martín de Porres",
    "independencia": "Independencia",
    "carabayllo": "Carabayllo",
    "puente piedra": "Puente Piedra",
    "callao": "Callao",
    "la perla": "La Perla",
    "bellavista": "Bellavista",
    "la punta": "La Punta",
}

TIPOS = ["departamento", "casa", "dúplex", "duplex", "flat", "oficina", "local", "terreno"]
AMENIDADES = ["cochera", "ascensor", "terraza", "amoblado", "pet friendly", "pet-friendly", "estreno", "frente a parque", "cuarto de servicio", "baño de servicio"]

# -----------------------------
# 2) Modelos Pydantic
# -----------------------------
class NLURequest(BaseModel):
    query: str = Field(..., description="Búsqueda en lenguaje natural")

class ConsultaEstructurada(BaseModel):
    operacion: Optional[str] = Field(None, description="venta|alquiler")
    distritos: List[str] = Field(default_factory=list)
    tipo: Optional[List[str]] = None
    precio_min: Optional[float] = None
    precio_max: Optional[float] = None
    moneda: Optional[str] = None  # USD|PEN
    area_min_m2: Optional[float] = None
    area_max_m2: Optional[float] = None
    dormitorios_min: Optional[int] = None
    dormitorios_max: Optional[int] = None
    banos_min: Optional[float] = None
    banos_max: Optional[float] = None
    cocheras_min: Optional[int] = None
    ascensor: Optional[bool] = None
    terraza: Optional[bool] = None
    amoblado: Optional[bool] = None
    pet_friendly: Optional[bool] = None

class BuscarRequest(BaseModel):
    query: Optional[str] = None
    filtros: Optional[ConsultaEstructurada] = None

# -----------------------------
# 3) Parsers sencillos (regex + listas)
# -----------------------------
_money_pattern = re.compile(r"(\$|usd|dolares|dólares|\bs\/?|soles)\s*(\d+[\d\.,]*)", re.IGNORECASE)
_range_money_pattern = re.compile(r"(hasta|max(?:imo)?|tope)\s*(\$|usd|s\/?|soles)?\s*(\d+[\d\.,]*)|entre\s*(\d+[\d\.,]*)\s*(y|-|a)\s*(\d+[\d\.,]*)\s*(usd|\$|s\/?|soles)?", re.IGNORECASE)
_area_pattern = re.compile(r"(m2|m²)")
_number_pattern = re.compile(r"\d+[\.,]?\d*")
_dorm_pattern = re.compile(r"(\d+)\s*(dorm|dormitorio|habitaci[oó]n|hab)", re.IGNORECASE)
_banos_pattern = re.compile(r"(\d+(?:\.5)?)\s*(baño|banos|baños)", re.IGNORECASE)

OPERACIONES = {"venta", "alquiler", "alquilo", "alquilar", "compro", "comprar", "vendo"}


def _norm_moneda(token: str) -> Optional[str]:
    t = token.lower()
    if t in {"$", "usd", "dolares", "dólares"}: return "USD"
    if t in {"s/", "s", "soles"}: return "PEN"
    return None


def _to_float(num_str: str) -> float:
    return float(num_str.replace(".", "").replace(",", "."))


def parse_query_to_filters(texto: str) -> ConsultaEstructurada:
    t = texto.lower()
    result = ConsultaEstructurada()

    # Operación
    if any(op in t for op in ["alquiler", "alquilo", "alquilar"]):
        result.operacion = "alquiler"
    elif any(op in t for op in ["venta", "comprar", "compro", "vendo"]):
        result.operacion = "venta"

    # Distritos (multi)
    distritos_detectados = []
    for key, canon in DISTRITOS_MAP.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            distritos_detectados.append(canon)
    # Unificar y ordenar
    result.distritos = sorted(list(dict.fromkeys(distritos_detectados)))

    # Tipo(s)
    tipos_detect = [tp for tp in TIPOS if re.search(rf"\b{re.escape(tp)}s?\b", t)]
    if tipos_detect:
        # Normalizar dúplex/duplex
        tipos_norm = ["dúplex" if tp in {"dúplex", "duplex"} else tp for tp in tipos_detect]
        result.tipo = sorted(list(dict.fromkeys(tipos_norm)))

    # Precio (rango o tope)
    m_range = _range_money_pattern.search(t)
    if m_range:
        # diferentes grupos por las 2 opciones del regex
        if m_range.group(3):  # caso: hasta 2500 soles
            result.precio_max = _to_float(m_range.group(3))
            if (mon := _norm_moneda(m_range.group(2) or "")):
                result.moneda = mon
        elif m_range.group(4) and m_range.group(6):  # caso: entre 200k y 300k usd
            lo = _to_float(m_range.group(4))
            hi = _to_float(m_range.group(6))
            result.precio_min, result.precio_max = min(lo, hi), max(lo, hi)
            if (mon := _norm_moneda(m_range.group(7) or "")):
                result.moneda = mon
    else:
        # primer monto aislado
        for m in _money_pattern.finditer(t):
            monto = _to_float(m.group(2))
            result.precio_max = monto
            if (mon := _norm_moneda(m.group(1))):
                result.moneda = mon
            break

    # Área (mínima si hay número + m2/m²)
    if _area_pattern.search(t):
        nums = [n.group(0) for n in _number_pattern.finditer(t)]
        if nums:
            try:
                # toma el último número antes de m2 si existe
                result.area_min_m2 = _to_float(nums[-1])
            except Exception:
                pass

    # Dormitorios / Baños
    d = _dorm_pattern.search(t)
    if d:
        result.dormitorios_min = int(d.group(1))
    b = _banos_pattern.search(t)
    if b:
        try:
            result.banos_min = float(b.group(1))
        except Exception:
            pass

    # Amenidades
    if "cochera" in t: result.cocheras_min = 1
    if "ascensor" in t: result.ascensor = True
    if "terraza" in t: result.terraza = True
    if "amoblado" in t: result.amoblado = True
    if "pet friendly" in t or "pet-friendly" in t or "mascotas" in t: result.pet_friendly = True

    return result


# -----------------------------
# 4) Dataset de ejemplo (mock)
# -----------------------------
MOCK_DATA: List[Dict[str, Any]] = [
    {
        "id_fuente": "urbania:001",
        "fuente": "urbania",
        "titulo": "Dúplex frente a parque",
        "operacion": "venta",
        "tipo": "departamento",
        "precio": 205000,
        "moneda": "USD",
        "area_total_m2": 84,
        "dormitorios": 3,
        "banos": 2,
        "cocheras": 1,
        "ascensor": True,
        "terraza": True,
        "distrito": "Santiago de Surco",
        "url_aviso": "https://urbania.pe/aviso/001"
    },
    {
        "id_fuente": "properati:1001",
        "fuente": "properati",
        "titulo": "Flat céntrico con ascensor",
        "operacion": "venta",
        "tipo": "departamento",
        "precio": 240000,
        "moneda": "USD",
        "area_total_m2": 72,
        "dormitorios": 2,
        "banos": 2,
        "cocheras": 1,
        "ascensor": True,
        "terraza": False,
        "distrito": "Miraflores",
        "url_aviso": "https://properati.pe/prop/1001"
    },
    {
        "id_fuente": "urbania:777",
        "fuente": "urbania",
        "titulo": "Departamento amoblado vista ciudad",
        "operacion": "alquiler",
        "tipo": "departamento",
        "precio": 2500,
        "moneda": "PEN",
        "area_total_m2": 95,
        "dormitorios": 3,
        "banos": 2,
        "cocheras": 1,
        "ascensor": True,
        "terraza": False,
        "distrito": "San Borja",
        "url_aviso": "https://urbania.pe/aviso/777"
    }
]

# -----------------------------
# 5) Endpoints
# -----------------------------
@app.post("/nlu/parse")
def nlu_parse(req: NLURequest) -> ConsultaEstructurada:
    parsed = parse_query_to_filters(req.query)
    return parsed


def _is_valid_consulta(c: ConsultaEstructurada) -> bool:
    # Regla: distritos obligatorios + al menos otro filtro
    if not c.distritos:
        return False
    extra = [c.tipo, c.precio_min, c.precio_max, c.area_min_m2, c.area_max_m2,
             c.dormitorios_min, c.dormitorios_max, c.banos_min, c.banos_max,
             c.cocheras_min, c.ascensor, c.terraza, c.amoblado, c.pet_friendly,
             c.operacion]
    return any(v not in (None, [], "") for v in extra)


def _match(prop: Dict[str, Any], c: ConsultaEstructurada) -> bool:
    # distrito
    if prop.get("distrito") not in c.distritos:
        return False
    # operacion
    if c.operacion and prop.get("operacion") != c.operacion:
        return False
    # tipo
    if c.tipo and prop.get("tipo") not in c.tipo:
        return False
    # precio
    price = prop.get("precio")
    if c.precio_min and price < c.precio_min: return False
    if c.precio_max and price > c.precio_max: return False
    # moneda (si viene, debe coincidir)
    if c.moneda and prop.get("moneda") != c.moneda: return False
    # area
    area = prop.get("area_total_m2") or 0
    if c.area_min_m2 and area < c.area_min_m2: return False
    if c.area_max_m2 and area > c.area_max_m2: return False
    # dormitorios / baños / cochera
    if c.dormitorios_min and (prop.get("dormitorios") or 0) < c.dormitorios_min: return False
    if c.banos_min and (prop.get("banos") or 0) < c.banos_min: return False
    if c.cocheras_min and (prop.get("cocheras") or 0) < c.cocheras_min: return False
    # amenidades bool
    if c.ascensor is True and prop.get("ascensor") is not True: return False
    if c.terraza is True and prop.get("terraza") is not True: return False
    if c.amoblado is True and prop.get("amoblado") is not True: return False
    if c.pet_friendly is True and prop.get("pet_friendly") is not True: return False
    return True


@app.post("/buscar")
def buscar(req: BuscarRequest) -> Dict[str, Any]:
    # Construir consulta
    if req.query:
        consulta = parse_query_to_filters(req.query)
    elif req.filtros:
        consulta = req.filtros
    else:
        raise HTTPException(status_code=400, detail="Falta 'query' o 'filtros'")

    # Validación de reglas
    if not _is_valid_consulta(consulta):
        raise HTTPException(status_code=400, detail="La consulta debe incluir al menos un distrito y un parámetro adicional (tipo, precio, m², dormitorios/baños, amenidades o operación).")

    # Filtrar mock
    matches = [p for p in MOCK_DATA if _match(p, consulta)]

    # Orden simple (precio asc + preferir más recientes en futuro)
    matches.sort(key=lambda x: (x.get("precio") or 0))

    return {
        "query_struct": consulta.dict(),
        "total": len(matches),
        "results": matches
    }


@app.get("/")
def root():
    return {"ok": True, "service": "MK Finder MVP"}

# ==============================
# NUEVOS MÓDULOS PARA Railway + NocoDB + Telegram
# ==============================

# requirements.txt
# -----------------
# Copia este contenido en un archivo llamado requirements.txt
# y en Railway configura el deploy con este archivo.

fastapi==0.115.0
uvicorn==0.30.6
pydantic==2.9.2
httpx==0.27.2
python-dotenv==1.0.1

# (Opcional si luego añadimos ASR/NLP avanzado):
# openai, spacy, torch, whisper, meilisearch


# railway.json (opcional)
# -----------------------
# Si usas templates en Railway, este archivo ayuda a detectar el servicio web.
{
  "build": {
    "builder": "NIXPACKS",
    "nixpacksPlan": {
      "phases": {
        "setup": {
          "nixPkgs": ["python311"]
        },
        "install": {
          "cmds": ["pip install -r requirements.txt"]
        },
        "start": {
          "cmd": "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
        }
      }
    }
  }
}


# .env (variables en Railway → Variables de Entorno)
# --------------------------------------------------
# Configúralas en el panel de Railway (no subir a GitHub):
# TELEGRAM_BOT_TOKEN=xxxxx:yyyyy
# BOT_WEBHOOK_SECRET=un_token_largo_unico
# PUBLIC_BASE_URL=https://<tu-servicio>.up.railway.app
# NOCO_API_URL=https://<tu-nocodb>.railway.app
# NOCO_TOKEN=<token de NocoDB si aplica>
# NOCO_DB=<slug o id de base>
# NOCO_TABLE=<slug o id de tabla>


# services/nocodb_client.py
# -------------------------
# Cliente simple para insertar/actualizar propiedades en NocoDB.

import os
import httpx
from typing import Dict, Any, List, Optional

NOCO_API_URL = os.getenv("NOCO_API_URL")
NOCO_TOKEN = os.getenv("NOCO_TOKEN")
NOCO_DB = os.getenv("NOCO_DB")
NOCO_TABLE = os.getenv("NOCO_TABLE")

_headers = {}
if NOCO_TOKEN:
    _headers["xc-token"] = NOCO_TOKEN

async def noco_upsert_props(items: List[Dict[str, Any]], id_field: str = "id_fuente") -> Dict[str, Any]:
    """Upsert por id_fuente usando NocoDB REST: /api/v2/tables/{table}/records
    Requiere que la tabla tenga una columna única para id_fuente o que validemos manual.
    """
    if not (NOCO_API_URL and NOCO_DB and NOCO_TABLE):
        return {"ok": False, "reason": "NOCO_* env vars missing"}

    # Endpoint genérico v2: /api/v2/tables/{table}/records
    url = f"{NOCO_API_URL}/api/v2/tables/{NOCO_TABLE}/records"

    async with httpx.AsyncClient(timeout=30.0) as client:
        results = []
        for it in items:
            # Intento de encontrar registro existente por id_fuente
            q = {
                "where": f"({id_field},eq,{it.get(id_field)})",
                "limit": 1
            }
            r = await client.get(url, headers=_headers, params=q)
            r.raise_for_status()
            data = r.json()
            if data.get("list"):
                rec_id = data["list"][0]["Id"]
                upd = await client.patch(f"{url}/{rec_id}", headers=_headers, json={"data": it})
                upd.raise_for_status()
                results.append({"action": "update", "id": rec_id})
            else:
                ins = await client.post(url, headers=_headers, json={"data": it})
                ins.raise_for_status()
                results.append({"action": "insert", "id": ins.json().get("Id")})
        return {"ok": True, "results": results}


# bot/telegram_webhook.py
# -----------------------
# Webhook muy simple usando FastAPI (no usa python-telegram-bot para mantenerlo ligero).

import os
import httpx
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from main import parse_query_to_filters, _is_valid_consulta, _match, MOCK_DATA

router = APIRouter(prefix="/bot/telegram", tags=["telegram"])
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_WEBHOOK_SECRET = os.getenv("BOT_WEBHOOK_SECRET", "")

async def _send_message(chat_id: int, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(api, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

@router.post("/webhook")
async def tg_webhook(request: Request):
    # Seguridad simple por header opcional
    secret = request.headers.get("X-Tg-Secret", "")
    if BOT_WEBHOOK_SECRET and secret != BOT_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload: Dict[str, Any] = await request.json()
    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if not text:
        await _send_message(chat_id, "Envíame lo que buscas. Ej: ‘Venta en Miraflores y San Isidro, 2 dorm, hasta 250k usd, con ascensor’.")
        return {"ok": True}

    # Parseo y búsqueda sobre MOCK (luego conectamos fuentes reales)
    consulta = parse_query_to_filters(text)
    if not _is_valid_consulta(consulta):
        await _send_message(chat_id, "Necesito al menos un distrito y un parámetro extra (tipo, precio, m², dormitorios/baños o amenidades).")
        return {"ok": True}

    matches = [p for p in MOCK_DATA if _match(p, consulta)]
    if not matches:
        await _send_message(chat_id, "No encontré coincidencias en el demo. Ajusta filtros o prueba otro distrito.")
        return {"ok": True}

    # Render simple (máx 5 resultados)
    lines = [f"<b>{m['titulo']}</b>
{m['operacion'].title()} · {m['tipo']} · {m['distrito']}
{m['moneda']} {m['precio']:,}
{m['url_aviso']}" for m in matches[:5]]
    await _send_message(chat_id, "

".join(lines))
    return {"ok": True}


# main.py (ADDENDUM)
# ------------------
# Agrega al final de tu main.py la inclusión del router de Telegram y un ping de salud.

from fastapi import APIRouter
from bot.telegram_webhook import router as tg_router

app.include_router(tg_router)

@app.get("/health")
def health():
    return {"ok": True, "service": "MK Finder MVP", "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN"))}


# ==============================
# INSTRUCCIONES DE DESPLIEGUE EN RAILWAY
# ==============================
# 1) Crea un nuevo proyecto en Railway y conecta tu repo con estos archivos.
# 2) Variables de entorno (Project → Variables):
#    - TELEGRAM_BOT_TOKEN
#    - BOT_WEBHOOK_SECRET (elige una cadena larga)
#    - PUBLIC_BASE_URL (Railway te la da tras el primer deploy)
#    - (Opcional, para NocoDB) NOCO_API_URL, NOCO_TOKEN, NOCO_DB, NOCO_TABLE
# 3) Deploy: Railway autodetectará Python con requirements.txt y ejecutará uvicorn.
# 4) Configura el webhook de Telegram:
#    - Obtén tu URL pública: https://<tu-servicio>.up.railway.app
#    - Ejecuta en tu terminal local:
#      curl -X GET "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook?url=$PUBLIC_BASE_URL/bot/telegram/webhook"
#      (Si usas secreto en header, añade un proxy o desactiva la verificación temporalmente.)
# 5) Abre Telegram y envía un mensaje al bot: debe responder con resultados del mock.
# 6) Cuando integremos fuentes reales, el endpoint /buscar ya devolverá resultados unificados.

# ==============================
# NOTAS PARA INTEGRAR PROPERATI/URBANIA
# ==============================
# - Properati: si contamos con un feed/dataset, crear un adapter async que consuma y normalice campos → guardar con noco_upsert_props().
# - Urbania: si TOS/robots lo permiten, usar Playwright/Scrapy con throttling para extraer (título, precio, m², distritos, etc.).
# - Dedupe: clave por id_fuente ("urbania:<id>", "properati:<id>") y, si falta, hash de dirección+precio+área.
# - Buscar: reemplazar MOCK_DATA por consultas a NocoDB o a una DB (PostgreSQL/Meilisearch) según el volumen.


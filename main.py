from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, APIRouter, Request
from pydantic import BaseModel, Field
import re
import os

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
    result.distritos = sorted(list(dict.fromkeys(distritos_detectados)))

    # Tipo(s)
    tipos_detect = [tp for tp in TIPOS if re.search(rf"\b{re.escape(tp)}s?\b", t)]
    if tipos_detect:
        tipos_norm = ["dúplex" if tp in {"dúplex", "duplex"} else tp for tp in tipos_detect]
        result.tipo = sorted(list(dict.fromkeys(tipos_norm)))

    # Precio (rango o tope)
    m_range = _range_money_pattern.search(t)
    if m_range:
        if m_range.group(3):  # caso: hasta 2500 soles
            result.precio_max = _to_float(m_range.group(3))
            mon = _norm_moneda(m_range.group(2) or "")
            if mon: result.moneda = mon
        elif m_range.group(4) and m_range.group(6):  # entre 200k y 300k usd
            lo = _to_float(m_range.group(4))
            hi = _to_float(m_range.group(6))
            result.precio_min, result.precio_max = min(lo, hi), max(lo, hi)
            mon = _norm_moneda(m_range.group(7) or "")
            if mon: result.moneda = mon
    else:
        for m in _money_pattern.finditer(t):
            monto = _to_float(m.group(2))
            result.precio_max = monto
            mon = _norm_moneda(m.group(1))
            if mon: result.moneda = mon
            break

    # Área
    if _area_pattern.search(t):
        nums = [n.group(0) for n in _number_pattern.finditer(t)]
        if nums:
            try:
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
# 5) Validadores y endpoints principales
# -----------------------------
def _is_valid_consulta(c: ConsultaEstructurada) -> bool:
    if not c.distritos:
        return False
    extra = [c.tipo, c.precio_min, c.precio_max, c.area_min_m2, c.area_max_m2,
             c.dormitorios_min, c.dormitorios_max, c.banos_min, c.banos_max,
             c.cocheras_min, c.ascensor, c.terraza, c.amoblado, c.pet_friendly,
             c.operacion]
    return any(v not in (None, [], "") for v in extra)

def _match(prop: Dict[str, Any], c: ConsultaEstructurada) -> bool:
    if prop.get("distrito") not in c.distritos:
        return False
    if c.operacion and prop.get("operacion") != c.operacion:
        return False
    if c.tipo and prop.get("tipo") not in c.tipo:
        return False
    price = prop.get("precio")
    if c.precio_min and price < c.precio_min: return False
    if c.precio_max and price > c.precio_max: return False
    if c.moneda and prop.get("moneda") != c.moneda: return False
    area = prop.get("area_total_m2") or 0
    if c.area_min_m2 and area < c.area_min_m2: return False
    if c.area_max_m2 and area > c.area_max_m2: return False
    if c.dormitorios_min and (prop.get("dormitorios") or 0) < c.dormitorios_min: return False
    if c.banos_min and (prop.get("banos") or 0) < c.banos_min: return False
    if c.cocheras_min and (prop.get("cocheras") or 0) < c.cocheras_min: return False
    if c.ascensor is True and prop.get("ascensor") is not True: return False
    if c.terraza is True and prop.get("terraza") is not True: return False
    if c.amoblado is True and prop.get("amoblado") is not True: return False
    if c.pet_friendly is True and prop.get("pet_friendly") is not True: return False
    return True

@app.post("/nlu/parse")
def nlu_parse(req: NLURequest) -> ConsultaEstructurada:
    parsed = parse_query_to_filters(req.query)
    return parsed

@app.post("/buscar")
def buscar(req: BuscarRequest) -> Dict[str, Any]:
    if req.query:
        consulta = parse_query_to_filters(req.query)
    elif req.filtros:
        consulta = req.filtros
    else:
        raise HTTPException(status_code=400, detail="Falta 'query' o 'filtros'")

    if not _is_valid_consulta(consulta):
        raise HTTPException(status_code=400, detail="La consulta debe incluir al menos un distrito y un parámetro adicional (tipo, precio, m², dormitorios/baños, amenidades o operación).")

    matches = [p for p in MOCK_DATA if _match(p, consulta)]
    matches.sort(key=lambda x: (x.get("precio") or 0))

    return {
        "query_struct": consulta.dict(),
        "total": len(matches),
        "results": matches
    }

# Telegram webhook router (import below)
from bot.telegram_webhook import router as tg_router
app.include_router(tg_router)

@app.get("/health")
def health():
    return {"ok": True, "service": "MK Finder MVP", "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN"))}

@app.get("/")
def root():
    return {"ok": True, "service": "MK Finder MVP"} 

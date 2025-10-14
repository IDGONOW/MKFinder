# adapters/urbania.py
from typing import List, Dict, Any
import httpx, re

class UrbaniaAdapter:
    """
    Adapter para consultar propiedades en Urbania.pe
    (versión inicial; ajustaremos parámetros tras probar en prod)
    """
    base_url = "https://urbania.pe/busquedas/buscar"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; MKFinderBot/1.0; +https://mkfinder.up.railway.app)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://urbania.pe/",
    }

    async def buscar(self, consulta: Dict[str, Any]) -> List[Dict[str, Any]]:
        distritos = consulta.get("distritos", [])
        operacion = consulta.get("operacion", "venta")
        dormitorios = consulta.get("dormitorios")
        precio_max = consulta.get("precio_max")
        moneda = consulta.get("moneda")  # "USD" | "PEN" | None

        if not distritos:
            return []

        params_base = {
            "pagina": 1,
            "operacion": "venta" if operacion == "venta" else "alquiler",
            "departamento": "lima",
            "tiposInmueble": "departamento",
        }
        if dormitorios:
            params_base["dormitorios"] = str(dormitorios)
        if precio_max:
            params_base["precioHasta"] = str(precio_max)
        if moneda == "USD":
            params_base["moneda"] = "dolares"
        elif moneda == "PEN":
            params_base["moneda"] = "soles"

        out: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20.0, headers=self.HEADERS) as client:
            for d in distritos:
                params = dict(params_base)
                params["distrito"] = d.lower()
                try:
                    r = await client.get(self.base_url, params=params)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    for item in data.get("anuncios", []):
                        mapped = self._map(item)
                        if mapped:
                            out.append(mapped)
                except Exception as e:
                    print(f"[Urbania] Error distrito={d}: {e}")
        return out

    def _map(self, item: Dict[str, Any]) -> Dict[str, Any]:
        precio_txt = (item.get("precio") or "").replace(",", "")
        nums = re.findall(r"\d+", precio_txt)
        precio_num = int(nums[0]) if nums else 0
        moneda = "USD" if "US$" in (item.get("precio") or "") else "PEN"
        return {
            "id_fuente": f"urbania:{item.get('id','')}",
            "fuente": "urbania",
            "titulo": (item.get("titulo") or "").strip(),
            "operacion": (item.get("operacion") or "").lower(),
            "tipo": (item.get("tipoInmueble") or "").lower(),
            "precio": precio_num,
            "moneda": moneda,
            "area_total_m2": item.get("areaTotal") or 0,
            "dormitorios": item.get("dormitorios") or 0,
            "banos": item.get("banos") or 0,
            "cocheras": item.get("cocheras") or 0,
            "distrito": (item.get("distrito") or "").title(),
            "url_aviso": f"https://urbania.pe{item.get('urlDetalle','')}",
            "fotos": item.get("fotos") or [],
        }

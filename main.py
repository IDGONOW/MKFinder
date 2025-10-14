# adapters/urbania.py
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
import re, math

class UrbaniaAdapter:
    """
    Scraper real de Urbania.pe (versión ligera)
    Soporta venta/alquiler, distritos, dormitorios, y rango de precio ±20%.
    """

    BASE_URL = "https://urbania.pe/buscar"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; MKFinderBot/1.0; +https://mkfinder.up.railway.app)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async def buscar(self, consulta: Dict[str, Any]) -> List[Dict[str, Any]]:
        resultados = []
        distritos = consulta.get("distritos", [])
        operacion = consulta.get("operacion", "venta")
        dormitorios = consulta.get("dormitorios")
        precio = consulta.get("precio_max")
        moneda = consulta.get("moneda") or "USD"

        # Calcular rango de precio ±20 %
        precio_min = None
        precio_max = None
        if precio:
            precio_min = int(precio * 0.8)
            precio_max = int(precio * 1.2)

        async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
            for distrito in distritos:
                url = f"{self.BASE_URL}/{operacion}/{distrito.lower()}/departamento"
                params = {}

                if dormitorios:
                    params["dormitorios"] = str(dormitorios)
                if precio_min and precio_max:
                    params["precioMin"] = str(precio_min)
                    params["precioMax"] = str(precio_max)
                if moneda == "PEN":
                    params["moneda"] = "soles"
                else:
                    params["moneda"] = "dolares"

                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        print(f"[Urbania] Error {resp.status_code} en {url}")
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select("div.posting-card")

                    for c in cards:
                        try:
                            titulo = (c.select_one(".posting-title") or {}).get_text(strip=True)
                            precio_txt = (c.select_one(".first-price") or {}).get_text(strip=True)
                            link_tag = c.select_one("a.go-to-posting")
                            href = link_tag["href"] if link_tag else ""
                            url_aviso = f"https://urbania.pe{href}"

                            # Extraer números del precio
                            nums = re.findall(r"\d+", precio_txt.replace(".", ""))
                            precio_num = int("".join(nums)) if nums else 0

                            resultados.append({
                                "titulo": titulo,
                                "precio": precio_num,
                                "moneda": "PEN" if "S/" in precio_txt or "sol" in precio_txt.lower() else "USD",
                                "distrito": distrito.title(),
                                "url_aviso": url_aviso,
                                "fuente": "urbania",
                            })
                        except Exception as e:
                            print(f"[Urbania] Error parseando tarjeta: {e}")

                except Exception as e:
                    print(f"[Urbania] Error conectando con {url}: {e}")

        print(f"[Urbania] Total encontrados: {len(resultados)}")
        return resultados



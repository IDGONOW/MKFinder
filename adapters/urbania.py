# adapters/urbania.py
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
import re
import unicodedata

def _slug(s: str) -> str:
    # "San Isidro" -> "san-isidro"
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

class UrbaniaAdapter:
    """
    Scraper ligero de Urbania.pe
    - Soporta: venta/alquiler, distritos, dormitorios, moneda, y rango ±20% sobre precio_max.
    - Prueba múltiples rutas y selectores.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 MKFinderBot/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://urbania.pe/",
    }

    # Dos patrones de URL comunes que suele usar Urbania
    def _build_urls(self, operacion: str, distrito: str) -> List[str]:
        slug_d = _slug(distrito)
        urls = []
        # Ej: /buscar/venta-de-departamentos-en-miraflores-lima
        urls.append(f"https://urbania.pe/buscar/{operacion}-de-departamentos-en-{slug_d}-lima")
        # Ej: /buscar/venta/miraflores/departamento (fallback histórico)
        urls.append(f"https://urbania.pe/buscar/{operacion}/{slug_d}/departamento")
        return urls

    def _build_params(self, consulta: Dict[str, Any]) -> Dict[str, str]:
        p: Dict[str, str] = {}
        dormitorios = consulta.get("dormitorios")
        precio = consulta.get("precio_max")
        moneda = consulta.get("moneda") or "USD"

        # Moneda
        p["moneda"] = "dolares" if moneda == "USD" else "soles"

        # Dormitorios (si viene)
        if dormitorios:
            p["dormitorios"] = str(dormitorios)

        # Rango ±20% del precio_max (si viene)
        if precio:
            try:
                precio = int(precio)
                p["precioMin"] = str(int(precio * 0.8))
                p["precioMax"] = str(int(precio * 1.2))
            except Exception:
                pass

        # Primera página
        p["pagina"] = "1"
        return p

    def _parse_cards(self, html: str, distrito: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")

        # Cascada de selectores (Urbania cambia clases a veces)
        candidates = []
        for sel in [
            "div.posting-card",
            "div.ui-posting-card",
            "article.posting-card",
            "article[data-id]",
            "li.posting-card",
        ]:
            found = soup.select(sel)
            if found:
                candidates = found
                break

        results: List[Dict[str, Any]] = []
        for c in candidates:
            try:
                # Título (varios selectores posibles)
                title_el = (
                    c.select_one(".posting-title")
                    or c.select_one("h2")
                    or c.select_one("h3")
                    or c.select_one("[data-testid='posting-title']")
                )
                titulo = title_el.get_text(strip=True) if title_el else "(sin título)"

                # Precio
                price_el = (
                    c.select_one(".first-price")
                    or c.select_one(".posting-price")
                    or c.select_one("[data-testid='price']")
                    or c.find("span", string=re.compile(r"\$|US|S/"))
                )
                precio_txt = price_el.get_text(" ", strip=True) if price_el else ""
                nums = re.findall(r"\d+", precio_txt.replace(".", "").replace(",", ""))
                precio_num = int("".join(nums)) if nums else 0
                moneda = "USD" if any(x in precio_txt.upper() for x in ["US$", "USD", "$"]) and "S/" not in precio_txt else "PEN"

                # Link
                link = c.select_one("a[href*='/inmueble/'], a.go-to-posting, a[href*='/propiedad/']")
                href = link["href"] if link and link.has_attr("href") else ""
                if href and href.startswith("/"):
                    url_aviso = f"https://urbania.pe{href}"
                else:
                    url_aviso = href or ""

                results.append({
                    "titulo": titulo,
                    "precio": precio_num,
                    "moneda": moneda,
                    "distrito": distrito.title(),
                    "url_aviso": url_aviso,
                    "fuente": "urbania",
                })
            except Exception as e:
                print(f"[Urbania] Error parseando tarjeta: {e}")
        return results

    async def buscar(self, consulta: Dict[str, Any]) -> List[Dict[str, Any]]:
        distritos = consulta.get("distritos") or []
        operacion = (consulta.get("operacion") or "venta").lower()
        if operacion not in ("venta", "alquiler"):
            operacion = "venta"

        if not distritos:
            return []

        params = self._build_params(consulta)
        out: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
            for distrito in distritos:
                urls = self._build_urls(operacion, distrito)
                got = []
                for url in urls:
                    try:
                        r = await client.get(url, params=params)
                        if r.status_code != 200:
                            print(f"[Urbania] {r.status_code} - {url}")
                            continue
                        parsed = self._parse_cards(r.text, distrito)
                        if parsed:
                            got = parsed
                            break  # si un patrón funcionó, no probamos el siguiente
                    except Exception as e:
                        print(f"[Urbania] Error request {url}: {e}")
                if not got:
                    print(f"[Urbania] 0 resultados para distrito={distrito} urls={urls}")
                out.extend(got)

        print(f"[Urbania] Total encontrados: {len(out)}")
        return out

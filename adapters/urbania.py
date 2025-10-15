# adapters/urbania.py
import asyncio
import re
import unicodedata
from typing import List, Dict, Any

import httpx
from bs4 import BeautifulSoup


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class UrbaniaAdapter:
    """
    Scraper ligero de Urbania.pe con:
    - Warm-up de cookies
    - Headers realistas
    - HTTP/2 (si está disponible)
    - Rutas alternativas
    - Precio ±20%
    """

    HOME = "https://urbania.pe/"
    ROUTE_PATTERNS = [
        # Ej: /buscar/venta-de-departamentos-en-miraflores-lima
        "https://urbania.pe/buscar/{operacion}-de-departamentos-en-{slug}-lima",
        # Ej: /buscar/venta/miraflores/departamento
        "https://urbania.pe/buscar/{operacion}/{slug}/departamento",
        # Variante adicional frecuente
        "https://urbania.pe/buscar/{operacion}-de-departamentos-en-{slug}",
    ]

    BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": '"Chromium";v="124", "Not:A-Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "Referer": "https://urbania.pe/",
        "Connection": "keep-alive",
    }

    def _build_urls(self, operacion: str, distrito: str) -> List[str]:
        slug_d = _slug(distrito)
        return [p.format(operacion=operacion, slug=slug_d) for p in self.ROUTE_PATTERNS]

    def _build_params(self, consulta: Dict[str, Any]) -> Dict[str, str]:
        p: Dict[str, str] = {"pagina": "1"}
        dormitorios = consulta.get("dormitorios")
        precio = consulta.get("precio_max")
        moneda = consulta.get("moneda") or "USD"

        p["moneda"] = "dolares" if moneda == "USD" else "soles"

        if dormitorios:
            p["dormitorios"] = str(dormitorios)

        # Rango ±20% del precio_max
        if precio:
            try:
                precio = int(precio)
                p["precioMin"] = str(int(precio * 0.8))
                p["precioMax"] = str(int(precio * 1.2))
            except Exception:
                pass

        return p

    def _parse_cards(self, html: str, distrito: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")

        candidates = []
        for sel in [
            "div.posting-card",
            "div.ui-posting-card",
            "article.posting-card",
            "article[data-id]",
            "li.posting-card",
            "[data-testid='posting-card']",
        ]:
            found = soup.select(sel)
            if found:
                candidates = found
                break

        results: List[Dict[str, Any]] = []
        for c in candidates:
            try:
                title_el = (
                    c.select_one(".posting-title")
                    or c.select_one("h2")
                    or c.select_one("h3")
                    or c.select_one("[data-testid='posting-title']")
                )
                titulo = title_el.get_text(strip=True) if title_el else "(sin título)"

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

    async def _warmup(self, client: httpx.AsyncClient) -> None:
        try:
            r = await client.get(self.HOME)
            if r.status_code != 200:
                print(f"[Urbania] Warm-up status={r.status_code}")
        except Exception as e:
            print(f"[Urbania] Warm-up error: {e}")

    async def buscar(self, consulta: Dict[str, Any]) -> List[Dict[str, Any]]:
        distritos = consulta.get("distritos") or []
        operacion = (consulta.get("operacion") or "venta").lower()
        if operacion not in ("venta", "alquiler"):
            operacion = "venta"
        if not distritos:
            return []

        params = self._build_params(consulta)
        out: List[Dict[str, Any]] = []

        # http2=True requiere lib h2 (opcional)
        async with httpx.AsyncClient(
            timeout=40.0,
            headers=self.BASE_HEADERS,
            http2=True,
        ) as client:
            # 1) warm-up para obtener cookies y consent
            await self._warmup(client)

            # 2) iterar distritos
            for distrito in distritos:
                urls = self._build_urls(operacion, distrito)
                got = []

                for i, url in enumerate(urls):
                    try:
                        r = await client.get(url, params=params)
                        if r.status_code != 200:
                            print(f"[Urbania] {r.status_code} - {url}")
                            # pequeño backoff y reintento simple para el siguiente patrón
                            await asyncio.sleep(0.8)
                            continue

                        parsed = self._parse_cards(r.text, distrito)
                        if parsed:
                            got = parsed
                            break
                    except Exception as e:
                        print(f"[Urbania] Error request {url}: {e}")
                        await asyncio.sleep(0.8)

                if not got:
                    print(f"[Urbania] 0 resultados para distrito={distrito} urls={urls}")
                out.extend(got)

        print(f"[Urbania] Total encontrados: {len(out)}")
        return out

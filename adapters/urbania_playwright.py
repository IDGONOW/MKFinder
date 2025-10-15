# adapters/urbania_playwright.py
import re, unicodedata, asyncio
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

class UrbaniaPlayAdapter:
    """
    Urbania vía Playwright (navegador real) para sortear 403.
    Soporta: venta/alquiler, distritos, dormitorios, moneda y rango ±20% (sobre precio_max).
    """

    ROUTES = [
        "https://urbania.pe/buscar/{operacion}-de-departamentos-en-{slug}-lima",
        "https://urbania.pe/buscar/{operacion}/{slug}/departamento",
        "https://urbania.pe/buscar/{operacion}-de-departamentos-en-{slug}",
    ]

    def _build_urls(self, operacion: str, distrito: str) -> List[str]:
        slug = _slug(distrito)
        return [r.format(operacion=operacion, slug=slug) for r in self.ROUTES]

    def _build_query(self, consulta: Dict[str, Any]) -> Dict[str, str]:
        q: Dict[str, str] = {"pagina": "1"}
        moneda = (consulta.get("moneda") or "USD").upper()
        q["moneda"] = "dolares" if moneda == "USD" else "soles"

        dorm = consulta.get("dormitorios")
        if dorm:
            q["dormitorios"] = str(dorm)

        precio = consulta.get("precio_max")
        if precio:
            try:
                p = int(precio)
                q["precioMin"] = str(int(p * 0.8))
                q["precioMax"] = str(int(p * 1.2))
            except:
                pass
        return q

    def _parse_cards(self, html: str, distrito: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for sel in [
            "div.posting-card", "div.ui-posting-card", "article.posting-card",
            "article[data-id]", "li.posting-card", "[data-testid='posting-card']",
        ]:
            found = soup.select(sel)
            if found:
                candidates = found
                break

        out: List[Dict[str, Any]] = []
        for c in candidates:
            try:
                title_el = c.select_one(".posting-title") or c.select_one("h2") or c.select_one("h3")
                titulo = title_el.get_text(strip=True) if title_el else "(sin título)"
                price_el = c.select_one(".first-price") or c.select_one(".posting-price")
                precio_txt = price_el.get_text(" ", strip=True) if price_el else ""
                nums = re.findall(r"\d+", precio_txt.replace(".", "").replace(",", ""))
                precio_num = int("".join(nums)) if nums else 0
                moneda = "USD" if any(x in precio_txt.upper() for x in ["US$", "USD", "$"]) and "S/" not in precio_txt else "PEN"
                link = c.select_one("a[href*='/inmueble/'], a.go-to-posting, a[href*='/propiedad/']")
                href = link.get("href") if link else ""
                url_aviso = f"https://urbania.pe{href}" if href.startswith("/") else href
                out.append({
                    "titulo": titulo,
                    "precio": precio_num,
                    "moneda": moneda,
                    "distrito": distrito.title(),
                    "url_aviso": url_aviso,
                    "fuente": "urbania",
                })
            except Exception as e:
                print(f"[UrbaniaPW] parse error: {e}")
        return out

    async def buscar(self, consulta: Dict[str, Any]) -> List[Dict[str, Any]]:
        distritos = consulta.get("distritos") or []
        operacion = (consulta.get("operacion") or "venta").lower()
        if operacion not in ("venta", "alquiler"):
            operacion = "venta"
        if not distritos:
            return []

        query = self._build_query(consulta)
        out: List[Dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(locale="es-PE")
            page = await context.new_page()

            # Warm-up (home) para consent/cookies
            try:
                await page.goto("https://urbania.pe/", wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"[UrbaniaPW] warm-up error: {e}")

            for distrito in distritos:
                urls = self._build_urls(operacion, distrito)
                got = []
                for url in urls:
                    try:
                        # Construir URL con parámetros
                        if query:
                            q = "&".join([f"{k}={v}" for k, v in query.items()])
                            final_url = f"{url}?{q}"
                        else:
                            final_url = url

                        await page.goto(final_url, wait_until="domcontentloaded", timeout=45000)
                        # pequeña espera para que cargue listado
                        await page.wait_for_timeout(1200)
                        html = await page.content()
                        parsed = self._parse_cards(html, distrito)
                        if parsed:
                            got = parsed
                            break
                    except Exception as e:
                        print(f"[UrbaniaPW] nav error {url}: {e}")
                        await page.wait_for_timeout(800)

                if not got:
                    print(f"[UrbaniaPW] 0 resultados distrito={distrito} urls={urls}")
                out.extend(got)

            await context.close()
            await browser.close()

        print(f"[UrbaniaPW] total={len(out)}")
        return out

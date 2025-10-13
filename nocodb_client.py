import os
import httpx
from typing import Dict, Any, List

NOCO_API_URL = os.getenv("NOCO_API_URL")
NOCO_TOKEN = os.getenv("NOCO_TOKEN")
NOCO_DB = os.getenv("NOCO_DB")
NOCO_TABLE = os.getenv("NOCO_TABLE")

_headers = {}
if NOCO_TOKEN:
    _headers["xc-token"] = NOCO_TOKEN

async def noco_upsert_props(items: List[Dict[str, Any]], id_field: str = "id_fuente") -> Dict[str, Any]:
    """Upsert simple por id_fuente usando NocoDB REST v2 tables endpoint"""
    if not (NOCO_API_URL and NOCO_DB and NOCO_TABLE):
        return {"ok": False, "reason": "NOCO_* env vars missing"}

    url = f"{NOCO_API_URL}/api/v2/tables/{NOCO_TABLE}/records"

    async with httpx.AsyncClient(timeout=30.0) as client:
        results = []
        for it in items:
            q = {"where": f"({id_field},eq,{it.get(id_field)})", "limit": 1}
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

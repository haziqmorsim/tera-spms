import os
import requests
from typing import Any, Dict, List, Optional
from app.core.config import FUSIONSOLAR_BASE_URL

class FusionSolarClient:
    def __init__(self) -> None:
        self.base_url = FUSIONSOLAR_BASE_URL.rstrip("/")
        self.session = requests.Session()

        jsessionid = os.getenv("FUSIONSOLAR_JSESSIONID")
        if not jsessionid:
            raise RuntimeError("FUSIONSOLAR_JSESSIONID not set")

        self.session.cookies.set(
            "JSESSIONID",
            jsessionid,
            domain="intl.fusionsolar.huawei.com",
            path="/",
        )

        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://intl.fusionsolar.huawei.com",
            "Referer": "https://intl.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-7-5c65c6ee-49c2-4032-ae36-222b03f97b37",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })

    def _extract_cookie_value(self, cookie_header: str, key: str) -> Optional[str]:
        parts = [p.strip() for p in cookie_header.split(";")]
        for p in parts:
            if p.startswith(key + "="):
                return p.split("=", 1)[1]
        return None

    def _request(self, method: str, path: str, *, json: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"

        print("SENDING COOKIES:", self.session.cookies.get_dict())
        print("REQUEST URL:", url)

        resp = self.session.request(method, url, json=json, timeout=45, allow_redirects=False)

        print("RESPONSE STATUS:", resp.status_code)
        print("RESPONSE CT:", resp.headers.get("content-type", ""))
        print("RESPONSE LOCATION:", resp.headers.get("location"))
        print("FINAL URL:", resp.url)

        ct = resp.headers.get("content-type", "")

        if resp.status_code in (301, 302, 303, 307, 308):
            raise RuntimeError(f"Redirected to {resp.headers.get('location')} (session not accepted)")

        if resp.status_code in (401, 403):
            raise RuntimeError("Not authorized (401/403). JSESSIONID is invalid/expired or missing required auth.")

        resp.raise_for_status()

        if "application/json" not in ct.lower():
            raise RuntimeError(f"Non-JSON from {url}. status={resp.status_code} ct={ct} body={resp.text[:200]}")

        return resp.json()

    def get_plants(self, page_no: int = 1, page_size: int = 200) -> List[Dict[str, Any]]:
        payload = {"curPage":1,"pageSize":10,"gridConnectedTime":"","queryTime":1771776000000,"timeZone":8,"sortId":"createTime","sortDir":"DESC","locale":"en_US"}
        data = self._request(
            "POST",
            "/rest/pvms/web/station/v1/station/station-list",
            json=payload,
        )

        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict) and "list" in data["data"]:
            return data["data"]["list"]
        if isinstance(data, dict) and "list" in data:
            return data["list"]

        raise RuntimeError(f"Unexpected response shape: {data}")
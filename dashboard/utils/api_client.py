"""Thin HTTP client wrapping the AITraderPro API, with automatic token refresh."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    # --- session helpers ---------------------------------------------------
    @staticmethod
    def _tokens() -> dict[str, str] | None:
        return st.session_state.get("tokens")

    @staticmethod
    def _store(tokens: dict[str, Any]) -> None:
        st.session_state["tokens"] = tokens

    @staticmethod
    def clear_session() -> None:
        for key in ("tokens", "user"):
            st.session_state.pop(key, None)

    def _headers(self) -> dict[str, str]:
        tokens = self._tokens()
        if not tokens:
            return {}
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # --- transport ---------------------------------------------------------
    def _request(
        self, method: str, path: str, *, retry_on_401: bool = True, **kwargs: Any
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=TIMEOUT) as http:
                resp = http.request(method, url, headers=self._headers(), **kwargs)
        except httpx.RequestError as exc:
            raise ApiError(f"Cannot reach the API at {self.base_url}: {exc}") from exc

        should_retry = resp.status_code == 401 and retry_on_401 and bool(self._tokens())
        if should_retry and self.refresh():
            return self._request(method, path, retry_on_401=False, **kwargs)

        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]["message"]
            except Exception:
                detail = resp.text or resp.reason_phrase
            raise ApiError(detail, resp.status_code)

        return resp.json() if resp.content else None

    # --- auth ----------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", retry_on_401=False)

    def login(self, email: str, password: str) -> dict[str, Any]:
        tokens = self._request(
            "POST",
            "/auth/login",
            retry_on_401=False,
            json={"email": email, "password": password},
        )
        self._store(tokens)
        user = self.me()
        st.session_state["user"] = user
        return user

    def register(self, email: str, password: str, full_name: str | None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/register",
            retry_on_401=False,
            json={"email": email, "password": password, "full_name": full_name},
        )

    def refresh(self) -> bool:
        tokens = self._tokens()
        if not tokens:
            return False
        try:
            with httpx.Client(timeout=TIMEOUT) as http:
                resp = http.post(
                    f"{self.base_url}/auth/refresh",
                    json={"refresh_token": tokens["refresh_token"]},
                )
        except httpx.RequestError:
            return False

        if resp.status_code != 200:
            self.clear_session()
            return False

        self._store(resp.json())
        return True

    def logout(self) -> None:
        try:
            self._request("POST", "/auth/logout", retry_on_401=False)
        except ApiError:
            pass
        finally:
            self.clear_session()

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/auth/me")

    def change_password(self, current: str, new: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/users/me/password",
            json={"current_password": current, "new_password": new},
        )

    def update_profile(self, full_name: str) -> dict[str, Any]:
        return self._request("PATCH", "/users/me", json={"full_name": full_name})

    def list_users(self, skip: int = 0, limit: int = 50) -> dict[str, Any]:
        return self._request("GET", "/users", params={"skip": skip, "limit": limit})

    # --- broker (Phase 2) ------------------------------------------------------
    def broker_status(self) -> dict[str, Any]:
        return self._request("GET", "/broker/status")

    def kite_login_url(self) -> str:
        return self._request("GET", "/broker/kite/login-url")["login_url"]

    def kite_complete_login(self, request_token: str) -> dict[str, Any]:
        return self._request(
            "POST", "/broker/kite/session", json={"request_token": request_token}
        )

    def kite_disconnect(self) -> None:
        self._request("DELETE", "/broker/kite/session")

    def positions(self, paper: bool | None = None) -> list[dict[str, Any]]:
        return self._request("GET", "/broker/positions", params=_paper(paper))

    def holdings(self, paper: bool | None = None) -> list[dict[str, Any]]:
        return self._request("GET", "/broker/holdings", params=_paper(paper))

    def margins(self, paper: bool | None = None) -> dict[str, Any]:
        return self._request("GET", "/broker/margins", params=_paper(paper))

    def quotes(self, symbols: list[str], paper: bool | None = None) -> dict[str, Any]:
        params = {"symbols": ",".join(symbols), **_paper(paper)}
        return self._request("GET", "/broker/quotes", params=params)

    def reset_paper(self) -> dict[str, Any]:
        return self._request("POST", "/broker/paper/reset")

    # --- orders (Phase 2) --------------------------------------------------------
    def place_order(self, **payload: Any) -> dict[str, Any]:
        return self._request("POST", "/orders", json=payload)

    def orders(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._request("GET", "/orders", params={"limit": limit})

    def order(self, order_id: int) -> dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}")

    def cancel_order(self, order_id: int) -> dict[str, Any]:
        return self._request("DELETE", f"/orders/{order_id}")

    # --- analysis: technical agent, decision engine, Pine (Phase 3/4) ------------
    def analyze_technical(self, symbol: str, candles: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request(
            "POST", "/analysis/technical", json={"symbol": symbol, "candles": candles}
        )

    def analyze_decide(
        self,
        symbol: str,
        candles: list[dict[str, Any]],
        equity: float,
        lot_size: int = 1,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/analysis/decide",
            json={
                "symbol": symbol,
                "candles": candles,
                "equity": equity,
                "lot_size": lot_size,
            },
        )

    def pine_templates(self) -> list[str]:
        return self._request("GET", "/analysis/pine/templates")["templates"]

    def generate_pine(self, scanner: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/analysis/pine", json={"scanner": scanner, "params": params}
        )

    # --- research: fundamentals, news, market context (Phase 4a) -----------------
    def fundamental(self, symbol: str) -> dict[str, Any]:
        return self._request("GET", f"/research/fundamental/{symbol}")

    def news(self, symbol: str, days: int = 7) -> dict[str, Any]:
        return self._request("GET", f"/research/news/{symbol}", params={"days": days})

    def market_context(self) -> dict[str, Any]:
        return self._request("GET", "/research/context")


def _paper(paper: bool | None) -> dict[str, Any]:
    return {} if paper is None else {"paper": str(paper).lower()}


api = ApiClient()

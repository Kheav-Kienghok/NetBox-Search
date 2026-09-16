from typing import Iterator

import httpx


class NetBoxClient:
    """Minimal read-only client for the NetBox REST API (token auth, auto-pagination)."""

    def __init__(self, base_url: str, token: str, verify_ssl: bool = True, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Token {token}",
                "Accept": "application/json",
            },
            verify=verify_ssl,
            timeout=timeout,
        )

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        params = dict(params or {})
        params.setdefault("limit", 500)

        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        data = resp.json()
        yield from data.get("results", [])

        next_url = data.get("next")
        while next_url:
            # NetBox returns absolute URLs in "next"; httpx.Client.get() will
            # follow an absolute URL as-is, ignoring base_url.
            resp = self._client.get(next_url)
            resp.raise_for_status()
            data = resp.json()
            yield from data.get("results", [])
            next_url = data.get("next")

    def get_virtual_machines(self) -> list[dict]:
        return list(self._paginate("/api/virtualization/virtual-machines/"))

    def get_vm_interfaces(self) -> list[dict]:
        return list(self._paginate("/api/virtualization/interfaces/"))

    def get_ip_addresses(self) -> list[dict]:
        return list(self._paginate("/api/ipam/ip-addresses/"))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "NetBoxClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

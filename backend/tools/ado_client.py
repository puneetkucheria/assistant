"""Thin async client for the Azure DevOps REST API (WIT area).

Authenticates with a Personal Access Token via HTTP Basic auth (empty
username + PAT). All calls are project-scoped:
``https://dev.azure.com/{org}/{project}/_apis/...``

Note the two distinct Content-Type quirks of this API:
* Wiql, comments, batch endpoints use ``application/json``.
* Work-item PATCH (create/update) uses ``application/json-patch+json``.
* Comments endpoint is on a *preview* api-version (``7.1-preview.4``)
  while the rest are on GA ``7.1``.

Errors from ADO are surfaced as ``ADOClientError`` with the original
HTTP status and message so tools can produce clear replies to the LLM.
"""
from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from backend.config import get_settings

API_VERSION = "7.1"
COMMENTS_API_VERSION = "7.1-preview.4"


class ADOClientError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"ADO API {status}: {message}")


class ADOClient:
    """Async wrapper around the parts of the ADO REST API the agent uses.

    Each method returns plain JSON-decoded Python objects. The tools in
    ``ado_tools`` shape and validate higher-level inputs; this layer keeps
    a faithful, low-level surface.
    """

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.azure_devops_is_configured:
            raise ADOClientError(
                0, "Azure DevOps is not configured (AZURE_DEVOPS_ORG/PROJECT/PAT required)."
            )
        org = quote(self.settings.azure_devops_org.strip())
        project = quote(self.settings.azure_devops_project.strip())
        self.base_url = f"https://dev.azure.com/{org}/{project}/_apis"
        token = f":{self.settings.azure_devops_pat}".encode("ascii")
        self._auth = "Basic " + base64.b64encode(token).decode("ascii")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": self._auth,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ADOClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        try:
            body = resp.json()
            msg = body.get("message") if isinstance(body, dict) else str(body)
            if not msg:
                msg = resp.text[:500]
        except Exception:
            msg = resp.text[:500]
        raise ADOClientError(resp.status_code, msg)

    # ---- Work items --------------------------------------------------

    async def get_work_item(self, work_item_id: int) -> dict[str, Any]:
        """GET a single work item by ID, with fields expanded."""
        resp = await self._client.get(
            f"wit/workitems/{int(work_item_id)}",
            params={"api-version": API_VERSION, "$expand": "fields"},
        )
        self._raise(resp)
        return resp.json()

    async def get_work_items_batch(self, ids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Fetch multiple work items in one call. hydrates WIQL results."""
        if not ids:
            return []
        body: dict[str, Any] = {"ids": [int(i) for i in ids], "$expand": "fields"}
        if fields:
            body["fields"] = fields
        resp = await self._client.post(
            "wit/workitemsbatch",
            params={"api-version": API_VERSION},
            json=body,
        )
        self._raise(resp)
        return resp.json().get("value", [])

    # ---- Wiql -------------------------------------------------------

    async def query_wiql(self, wiql: str, top: int = 50) -> list[int]:
        """Run a WIQL query, return the list of IDs (fields not included)."""
        resp = await self._client.post(
            "wit/wiql",
            params={"api-version": API_VERSION, "$top": top},
            json={"query": wiql},
        )
        self._raise(resp)
        data = resp.json()
        work_items = data.get("workItems", [])
        return [int(wi["id"]) for wi in work_items]

    # ---- Update / Create --------------------------------------------

    async def update_work_item(
        self,
        work_item_id: int,
        patch_ops: list[dict[str, Any]],
        bypass_rules: bool = False,
    ) -> dict[str, Any]:
        """PATCH a work item with a JSON-Patch body.

        ``patch_ops`` is a list of RFC 6902 operations such as
        ``{"op": "add", "path": "/fields/System.Title", "value": "..."}``.
        Content-Type MUST be ``application/json-patch+json``.
        """
        params = {"api-version": API_VERSION}
        if bypass_rules:
            params["bypassRules"] = "true"
        resp = await self._client.request(
            "PATCH",
            f"wit/workitems/{int(work_item_id)}",
            params=params,
            headers={"Content-Type": "application/json-patch+json"},
            json=patch_ops,
        )
        self._raise(resp)
        return resp.json()

    async def create_work_item(
        self,
        work_item_type: str,
        patch_ops: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST a new work item of the given type. Type is URL-encoded."""
        type_segment = quote(work_item_type, safe="")
        resp = await self._client.post(
            f"wit/workitems/{type_segment}",
            params={"api-version": API_VERSION},
            headers={"Content-Type": "application/json-patch+json"},
            json=patch_ops,
        )
        self._raise(resp)
        return resp.json()

    # ---- Comments ---------------------------------------------------

    async def add_work_item_comment(self, work_item_id: int, text: str) -> dict[str, Any]:
        """Add a threaded discussion comment to a work item."""
        resp = await self._client.post(
            f"wit/workItems/{int(work_item_id)}/comments",
            params={"api-version": COMMENTS_API_VERSION},
            json={"text": text},
        )
        self._raise(resp)
        return resp.json()

    async def list_comments(self, work_item_id: int, top: int = 20) -> list[dict[str, Any]]:
        resp = await self._client.get(
            f"wit/workItems/{int(work_item_id)}/comments",
            params={"api-version": COMMENTS_API_VERSION, "$top": top},
        )
        self._raise(resp)
        return resp.json().get("comments", [])

    # ---- Project / metadata helpers ---------------------------------

    async def ping_project(self) -> bool:
        """Lightweight reachability check — returns True on a successful GET.

        Uses the org-scoped projects endpoint (not project-scoped) so it
        works regardless of the configured base URL.
        """
        org = quote(self.settings.azure_devops_org.strip())
        project = quote(self.settings.azure_devops_project.strip())
        url = (
            f"https://dev.azure.com/{org}/_apis/projects/{project}"
            f"?api-version={API_VERSION}"
        )
        try:
            resp = await self._client.get(url)
            return resp.is_success
        except httpx.HTTPError:
            return False

    async def get_work_item_type_states(self, work_item_type: str) -> list[str]:
        """Return the list of state values allowed for the given work item type.

        ADO exposes per-type state via the classification API. The most
        reliable approach is to fetch one representative work item of the
        type if it exists, but for the MVP we use the documented field
        metadata endpoint. Falls back to an empty list on error.
        """
        org = quote(self.settings.azure_devops_org.strip())
        project = quote(self.settings.azure_devops_project.strip())
        type_segment = quote(work_item_type, safe="")
        url = (
            f"https://dev.azure.com/{org}/{project}/_apis/wit/workitemtypes"
            f"/{type_segment}/fields/System.State?api-version={API_VERSION}"
        )
        try:
            resp = await self._client.get(url)
            if not resp.is_success:
                return []
            data = resp.json()
            return [str(v) for v in data.get("allowedValues", [])]
        except (httpx.HTTPError, ValueError):
            return []

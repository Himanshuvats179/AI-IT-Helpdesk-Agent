"""Endpoint management backend (mock Intune/MDM + diagnostics)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.exceptions import ToolExecutionError

# Software the agent is allowed to auto-propose for install (still needs approval).
APPROVED_SOFTWARE_CATALOG = {
    "vpn-client",
    "office365",
    "slack",
    "zoom",
    "chrome",
    "7zip",
    "acrobat-reader",
}


@runtime_checkable
class EndpointBackend(Protocol):
    async def run_diagnostic(self, asset_id: str, check: str) -> dict: ...
    async def install_software(self, asset_id: str, package_id: str) -> dict: ...


class MockEndpointBackend:
    @staticmethod
    def _guard(asset_id: str) -> None:
        if "fail" in (asset_id or "").lower():
            raise ToolExecutionError(f"Endpoint {asset_id} is unreachable")

    async def run_diagnostic(self, asset_id: str, check: str) -> dict:
        self._guard(asset_id)
        check = (check or "general").lower()
        base = {"asset_id": asset_id or "unknown", "check": check, "status": "ok"}
        if check == "vpn":
            base.update(
                {
                    "vpn_client_version": "5.2.1",
                    "profile_installed": True,
                    "gateway_reachable": True,
                    "last_error": "stale_profile",
                    "recommendation": "Re-import the corp VPN profile and reconnect.",
                }
            )
        elif check in ("connectivity", "network"):
            base.update({"dns_ok": True, "gateway_ms": 14, "packet_loss_pct": 0})
        elif check == "disk":
            base.update({"free_gb": 42, "total_gb": 256, "status": "ok"})
        else:
            base.update({"cpu_pct": 18, "mem_pct": 53, "pending_reboot": False})
        return base

    async def install_software(self, asset_id: str, package_id: str) -> dict:
        self._guard(asset_id)
        if package_id not in APPROVED_SOFTWARE_CATALOG:
            raise ToolExecutionError(f"Package '{package_id}' is not in the approved catalog")
        return {"status": "queued", "asset_id": asset_id, "package_id": package_id, "eta_minutes": 5}

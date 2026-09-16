import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import replace_search_index, set_meta
from app.netbox_client import NetBoxClient
from app.search import search_cache

logger = logging.getLogger("netbox_search.sync")


def _status_label(obj: dict | None) -> str:
    if not obj:
        return ""
    status = obj.get("status")
    if isinstance(status, dict):
        return status.get("label") or status.get("value") or ""
    return status or ""


def _tag_names(obj: dict | None) -> str:
    if not obj:
        return ""
    return ", ".join(t.get("name", "") for t in obj.get("tags") or [])


def _custom_field_value(cf: dict, keyword: str):
    """Find a custom field's value by keyword when the exact slug is unknown
    (e.g. RAM/Disk recorded in a 'Customizer' custom field group rather than
    NetBox's built-in memory/disk properties)."""
    for k, v in cf.items():
        if keyword in k.lower() and v not in (None, ""):
            return v
    return None


def _wazuh_installed(vm: dict | None) -> str:
    """Read the 'Wazuh Installed' custom field. Tries the expected slug first,
    then falls back to any custom field whose key mentions 'wazuh', since the
    exact slug depends on how the custom field was named in NetBox.
    """
    cf = (vm or {}).get("custom_fields") or {}
    val = cf.get("wazuh_installed")
    if val is None:
        val = _custom_field_value(cf, "wazuh")
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, dict):
        return val.get("label") or val.get("value") or ""
    return str(val)


def _vm_ram_gib(vm: dict) -> str:
    """Prefer NetBox's built-in `memory` field (stored in MB, convert to GiB).
    Falls back to a custom field (e.g. a 'Customizer' group) when `memory`
    isn't populated - assumed to already be in GiB there, since that's how
    it's entered/displayed in the NetBox UI's custom column."""
    memory_mb = vm.get("memory")
    if memory_mb:
        return round(memory_mb / 1024, 1)
    custom = _custom_field_value(vm.get("custom_fields") or {}, "ram") \
        or _custom_field_value(vm.get("custom_fields") or {}, "memory")
    return custom if custom is not None else ""


def _vm_disk_gib(vm: dict) -> str:
    """Prefer NetBox's built-in `disk` field (already GB). Falls back to a
    custom field (e.g. 'Customizer' group) when `disk` isn't populated."""
    disk = vm.get("disk")
    if disk:
        return disk
    custom = _custom_field_value(vm.get("custom_fields") or {}, "disk") \
        or _custom_field_value(vm.get("custom_fields") or {}, "storage")
    return custom if custom is not None else ""


def _vm_fields(vm: dict | None) -> dict:
    if not vm:
        return {
            "vm_id": None, "vm_name": "", "vm_status": "", "vm_vcpus": "",
            "vm_memory_gib": "", "vm_disk_gib": "", "vm_tags": "",
            "vm_wazuh_installed": "", "vm_comments": "",
        }
    return {
        "vm_id": vm.get("id"),
        "vm_name": vm.get("name", ""),
        "vm_status": _status_label(vm),
        "vm_vcpus": vm.get("vcpus") or "",
        "vm_memory_gib": _vm_ram_gib(vm),
        "vm_disk_gib": _vm_disk_gib(vm),
        "vm_tags": _tag_names(vm),
        "vm_wazuh_installed": _wazuh_installed(vm),
        "vm_comments": vm.get("comments", "") or "",
    }



def _strip_mask(address: str | None) -> str:
    """NetBox stores IPs with a CIDR mask ('10.0.0.5/32'); display/search
    just the address itself."""
    return (address or "").split("/")[0]


def _search_text(row: dict) -> str:
    return " ".join(
        str(v) for v in (
            row.get("ip_address"), row.get("dns_name"),
            row.get("vm_name"), row.get("vm_status"), row.get("vm_tags"),
            row.get("vm_wazuh_installed"), row.get("vm_comments"),
            row.get("interface_name"), row.get("mac_address"),
            row.get("description"),
        ) if v
    ).lower()


def _vm_interface_row(vm: dict | None, iface: dict, ip: dict | None, base: str) -> dict:
    vm_fields = _vm_fields(vm)
    row = {
        "record_type": "vm_interface",
        "ip_address": _strip_mask(ip.get("address")) if ip else "",
        "dns_name": ip.get("dns_name", "") if ip else "",
        **vm_fields,
        "interface_id": iface["id"],
        "interface_name": iface.get("name", ""),
        "interface_enabled": 1 if iface.get("enabled") else 0,
        "mac_address": iface.get("mac_address") or "",
        "description": iface.get("description", "") or (ip.get("description", "") if ip else ""),
        "netbox_url": f"{base}/virtualization/virtual-machines/{vm_fields['vm_id']}/" if vm_fields["vm_id"] else "",
    }
    row["search_text"] = _search_text(row)
    return row


def _standalone_ip_row(ip: dict, base: str) -> dict:
    assigned = ip.get("assigned_object") or {}
    row = {
        "record_type": "ip_address",
        "ip_address": _strip_mask(ip.get("address")),
        "dns_name": ip.get("dns_name", ""),
        "vm_id": None, "vm_name": "", "vm_status": "", "vm_vcpus": "",
        "vm_memory_gib": "", "vm_disk_gib": "", "vm_tags": "",
        "vm_wazuh_installed": "", "vm_comments": "",
        "interface_id": assigned.get("id"),
        "interface_name": assigned.get("name", ""),
        "interface_enabled": None,
        "mac_address": "",
        "description": ip.get("description", "") or "",
        "netbox_url": f"{base}/ipam/ip-addresses/{ip['id']}/",
    }
    row["search_text"] = _search_text(row)
    return row


def _build_rows(vms: list[dict], interfaces: list[dict], ip_addresses: list[dict]) -> list[dict]:
    base = settings.netbox_url.rstrip("/")
    vms_by_id = {vm["id"]: vm for vm in vms}

    ips_by_interface_id: dict[int, list[dict]] = {}
    standalone_ips: list[dict] = []
    for ip in ip_addresses:
        assigned_type = ip.get("assigned_object_type")
        assigned_id = ip.get("assigned_object_id")
        if assigned_type == "virtualization.vminterface" and assigned_id is not None:
            ips_by_interface_id.setdefault(assigned_id, []).append(ip)
        else:
            standalone_ips.append(ip)

    rows: list[dict] = []

    # One row per (VM interface, IP) pair, so each IP keeps its own DNS name.
    # An interface with no IP assigned still gets a row (empty IP/DNS).
    for iface in interfaces:
        vm_ref = iface.get("virtual_machine") or {}
        vm = vms_by_id.get(vm_ref.get("id"))

        iface_ips = ips_by_interface_id.get(iface["id"], [])
        if iface_ips:
            for ip in iface_ips:
                rows.append(_vm_interface_row(vm, iface, ip, base))
        else:
            rows.append(_vm_interface_row(vm, iface, None, base))

    # IPs not attached to any VM interface (device interfaces, unassigned
    # pool addresses, etc.) still get a searchable row of their own.
    for ip in standalone_ips:
        rows.append(_standalone_ip_row(ip, base))

    return rows


def run_sync() -> int:
    """Fetch fresh data from NetBox, rebuild the combined index, refresh the cache.

    Returns the number of rows indexed. Raises on failure so callers/schedulers
    can log and retry on the next interval without crashing the app.
    """
    logger.info("Starting NetBox sync against %s", settings.netbox_url)
    with NetBoxClient(
        settings.netbox_url, settings.netbox_token, settings.netbox_verify_ssl, settings.netbox_timeout
    ) as client:
        vms = client.get_virtual_machines()
        interfaces = client.get_vm_interfaces()
        ip_addresses = client.get_ip_addresses()

    rows = _build_rows(vms, interfaces, ip_addresses)
    replace_search_index(rows)
    search_cache.reload()

    now = datetime.now(timezone.utc).isoformat()
    set_meta("last_sync_at", now)
    set_meta("last_sync_count", str(len(rows)))
    logger.info("NetBox sync complete: %d rows indexed", len(rows))
    return len(rows)

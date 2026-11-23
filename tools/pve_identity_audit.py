#!/usr/bin/env python3
"""Read-only PVE/Windows identity audit. Run on the PVE node containing the VMs."""
import argparse
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path


def run(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {arguments[0]}")
    return result.stdout


def fields(value):
    return dict(part.split("=", 1) for part in value.split(",") if "=" in part)


def parse_config(text):
    config = {}
    for line in text.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            config[key] = value
    smbios = fields(config.get("smbios1", ""))
    network = {}
    disks = {}
    for key, value in config.items():
        if re.fullmatch(r"net\d+", key):
            first = value.split(",", 1)[0]
            network[key] = first.split("=", 1)[-1]
        if re.fullmatch(r"(?:scsi|sata|ide|virtio)\d+", key) and "media=cdrom" not in value:
            disks[key] = {"serial": fields(value).get("serial"), "configured": value.split(",", 1)[0]}
    return {"name": config.get("name"), "smbios": smbios,
            "vmgenid": config.get("vmgenid"), "network_mac": network, "disks": disks}


def duplicate_groups(records, field):
    groups = defaultdict(list)
    for record in records:
        value = field(record)
        if value:
            groups[str(value).strip().lower()].append(record["vmid"])
    return [ids for ids in groups.values() if len(ids) > 1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vmids", type=int, nargs="+")
    parser.add_argument("--guest", action="store_true", help="Read Windows CIM IDs through an already-enabled QEMU guest agent")
    parser.add_argument("--output", type=Path, required=True, help="Private audit JSON path; never commit this report")
    args = parser.parse_args()
    if any(v <= 0 for v in args.vmids) or len(set(args.vmids)) != len(args.vmids):
        parser.error("VMIDs must be distinct positive integers")
    if args.output.exists():
        parser.error("Refusing to overwrite an existing report")
    script = Path(__file__).with_name("windows_identity.ps1").read_text(encoding="utf-8-sig")
    records = []
    for vmid in args.vmids:
        print(f"Reading VM {vmid} configuration", flush=True)
        entry = {"vmid": vmid, **parse_config(run("qm", "config", str(vmid), "--current", "1"))}
        if args.guest:
            try:
                response = json.loads(run("qm", "guest", "exec", str(vmid), "--timeout", "30", "--",
                                          "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script))
                if response.get("exitcode") != 0:
                    raise RuntimeError("Guest identity command did not exit successfully")
                entry["windows"] = json.loads(response.get("out-data", "").lstrip("\ufeff"))
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                entry["guest_error"] = str(error)
        records.append(entry)
    duplicates = {
        "configured_smbios_uuid": duplicate_groups(records, lambda r: r["smbios"].get("uuid")),
        "vm_generation_id": duplicate_groups(records, lambda r: r.get("vmgenid")),
        "guest_system_uuid": duplicate_groups(records, lambda r: r.get("windows", {}).get("SystemUUID")),
        "guest_windows_machine_guid": duplicate_groups(records, lambda r: r.get("windows", {}).get("WindowsMachineGuid")),
        "guest_bios_serial": duplicate_groups(records, lambda r: r.get("windows", {}).get("BIOSSerial")),
        "guest_baseboard_serial": duplicate_groups(records, lambda r: r.get("windows", {}).get("BaseboardSerial")),
    }
    report = {"read_only": True, "virtual_machines": records, "duplicates": duplicates}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print("Duplicate groups (VMIDs only):", json.dumps(duplicates))
    print(f"Private report saved: {args.output}")
    print("No VM, Windows, or UU settings have been modified.")


if __name__ == "__main__":
    main()

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("pve_audit", Path(__file__).resolve().parents[1] / "tools/pve_identity_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PVEAuditTests(unittest.TestCase):
    def test_extracts_uuid_and_nic_without_mistaking_disk_paths_for_ids(self):
        result = audit.parse_config("""name: windows-one
smbios1: uuid=11111111-1111-4111-8111-111111111111,serial=existing-serial
net0: virtio=02:00:00:00:00:01,bridge=vmbr0,firewall=1
scsi0: storage:vm-101-disk-0,serial=vm101disk
ide2: none,media=cdrom
""")
        self.assertEqual(result["smbios"]["serial"], "existing-serial")
        self.assertEqual(result["network_mac"]["net0"], "02:00:00:00:00:01")
        self.assertEqual(result["disks"]["scsi0"]["serial"], "vm101disk")
        self.assertNotIn("ide2", result["disks"])

    def test_duplicate_detection_ignores_missing_values_and_normalizes_case(self):
        records = [{"vmid": 101, "uuid": " ABC "}, {"vmid": 102, "uuid": "abc"},
                   {"vmid": 103, "uuid": "unique"}, {"vmid": 104, "uuid": None},
                   {"vmid": 105, "uuid": ""}]
        self.assertEqual(audit.duplicate_groups(records, lambda r: r["uuid"]), [[101, 102]])


if __name__ == "__main__":
    unittest.main()

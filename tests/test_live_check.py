import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import uu_remote_multi as tool


class LiveCheckTests(unittest.TestCase):
    def run_check(self, original_signed_in=True, same_account=False, extra_original=False):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "Original.app"
            copy = Path(folder) / "Copy.app"
            (copy / "Contents/Resources").mkdir(parents=True)
            (copy / "Contents/Resources/uu-multi-build.json").write_text(json.dumps({"tool": "uu-remote-multi"}))

            def query(arguments, **kwargs):
                original = "Original.app" in arguments[0]
                operation = tuple(arguments[1:-1])
                if operation == ("status",):
                    data = {"isLoggedIn": original_signed_in if original else True}
                elif operation == ("user", "info"):
                    data = {"userId": "private-account-one" if original or same_account else "private-account-two"}
                else:
                    data = {"assistId": "private-device-one" if original else "private-device-two"}
                return SimpleNamespace(stdout=json.dumps({"success": True, "data": data}).encode(), returncode=0)

            rows = f"1 {source}/Contents/MacOS/UURemote\n2 {copy}/Contents/MacOS/UURemote\n3 {source}/Contents/MacOS/UURemoteService\n"
            if extra_original:
                rows += f"4 {source}/Contents/MacOS/UURemote\n"
            with patch.object(tool, "validate_source", return_value=(source, {})), \
                 patch.object(tool, "command", side_effect=lambda *args: rows.encode() if args[0] == "/bin/ps" else b""), \
                 patch.object(tool.subprocess, "run", side_effect=query):
                return tool.check_running(source, copy)

    def test_success_report_does_not_disclose_account_or_device_identifiers(self):
        result = self.run_check()
        self.assertTrue(result["all_checks_passed"])
        self.assertNotIn("private-", json.dumps(result))

    def test_cached_account_data_does_not_override_live_signed_out_state(self):
        result = self.run_check(original_signed_in=False)
        self.assertFalse(result["checks"]["original_signed_in"])
        self.assertFalse(result["all_checks_passed"])

    def test_same_account_or_multiple_original_processes_fail_parallel_check(self):
        self.assertFalse(self.run_check(same_account=True)["all_checks_passed"])
        result = self.run_check(extra_original=True)
        self.assertFalse(result["checks"]["one_original_main_process"])
        self.assertFalse(result["all_checks_passed"])


if __name__ == "__main__":
    unittest.main()

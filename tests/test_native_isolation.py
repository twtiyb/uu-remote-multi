import os
import platform
import plistlib
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


@unittest.skipUnless(platform.system() == "Darwin" and platform.machine() == "arm64", "Apple Silicon macOS required")
class NativeIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="uu-isolation-test-")
        folder = Path(cls.scratch.name)
        cls.library = folder / "Isolation.dylib"
        bundle = folder / "Probe.app/Contents"
        (bundle / "MacOS").mkdir(parents=True)
        (bundle / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.netease.uualt002", "CFBundleExecutable": "Probe",
            "CFBundlePackageType": "APPL", "CFBundleName": "Probe"}))
        cls.probe = bundle / "MacOS/Probe"
        root = Path(__file__).resolve().parents[1]
        common = ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "Security", "-framework", "IOKit"]
        subprocess.run(common + ["-dynamiclib", str(root / "profile_isolation.m"), "-o", str(cls.library)], check=True, capture_output=True)
        subprocess.run(common + [str(root / "tests/native_probe.m"), "-o", str(cls.probe)], check=True, capture_output=True)
        cls.isolated_environment = dict(os.environ, DYLD_INSERT_LIBRARIES=str(cls.library))

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def probe_run(self, *args, isolated=False):
        return subprocess.run([str(self.probe), *args], capture_output=True,
                              env=self.isolated_environment if isolated else None)

    def test_hardware_uuid_is_distinct_and_stable(self):
        real = self.probe_run("uuid")
        first = self.probe_run("uuid", isolated=True)
        second = self.probe_run("uuid", isolated=True)
        self.assertEqual((real.returncode, first.returncode, second.returncode), (0, 0, 0))
        self.assertNotEqual(real.stdout.strip(), first.stdout.strip())
        self.assertEqual(first.stdout.strip(), second.stdout.strip())

    def test_keychain_copy_add_and_delete_do_not_touch_original_namespace(self):
        service = "uu-multi-selftest-" + uuid.uuid4().hex
        try:
            self.assertEqual(self.probe_run("add", service, "original-test-value").returncode, 0)
            self.assertEqual(self.probe_run("get", service, isolated=True).returncode, 7)
            self.assertEqual(self.probe_run("add", service, "isolated-test-value", isolated=True).returncode, 0)
            self.assertEqual(self.probe_run("get", service).stdout.strip(), b"original-test-value")
            self.assertEqual(self.probe_run("get", service, isolated=True).stdout.strip(), b"isolated-test-value")
            self.assertEqual(self.probe_run("delete", service, isolated=True).returncode, 0)
            self.assertEqual(self.probe_run("get", service).stdout.strip(), b"original-test-value")
        finally:
            self.probe_run("delete", service)
            self.probe_run("delete", service, isolated=True)

    def test_transient_shared_file_creation_is_redirected(self):
        name = ".uu-multi-selftest-" + uuid.uuid4().hex
        original = Path("/Users/Shared/UURemote") / name
        isolated = Path("/Users/Shared/UUSecond") / name
        isolated.parent.mkdir(exist_ok=True)
        try:
            result = self.probe_run("file", str(original), isolated=True)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(original.exists())
            self.assertEqual(isolated.read_bytes(), b"isolated")
        finally:
            if isolated.exists():
                isolated.unlink()


if __name__ == "__main__":
    unittest.main()

import hashlib
import plistlib
import tempfile
import unittest
from pathlib import Path

import uu_remote_multi as tool


class SafetyTests(unittest.TestCase):
    def test_rejects_unknown_executable_before_patching(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            tool.patch_main(b"not a supported UU executable")

    def test_rejects_different_application(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Other.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.example.other",
                "CFBundleShortVersionString": "4.48.3", "CFBundleVersion": "635"}))
            with self.assertRaisesRegex(ValueError, "original"):
                tool.validate_source(app)

    def test_rejects_new_version_without_reading_or_mutating_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "UURemote.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            binary = app / "Contents/MacOS/UURemote"
            sentinel = b"must remain unchanged"
            binary.write_bytes(sentinel)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": tool.SOURCE_ID.decode(),
                "CFBundleShortVersionString": "99.0", "CFBundleVersion": "999"}))
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                tool.validate_source(app)
            self.assertEqual(binary.read_bytes(), sentinel)

    def test_supported_binary_patch_is_limited_to_verified_instructions(self):
        app = Path("/Applications/UURemote.app")
        binary = app / "Contents/MacOS/UURemote"
        if not binary.exists():
            self.skipTest("Supported original client is not installed")
        original = binary.read_bytes()
        if hashlib.sha256(original).hexdigest() != tool.SOURCE_SHA256:
            self.skipTest("Installed original is not the supported build")
        result = tool.patch_main(original)
        allowed = {i for start in tool.DIRECTORY_OFFSETS for i in range(start, start + 16)}
        changed = {i for i, (a, b) in enumerate(zip(original, result)) if a != b}
        self.assertTrue(changed)
        self.assertLessEqual(changed, allowed)
        self.assertEqual(len(result), len(original))
        self.assertEqual(binary.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

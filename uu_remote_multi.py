#!/usr/bin/env python3
"""Create an independently namespaced local UU Remote controller copy.

This tool contains no vendor binary or account data. It requires an installed,
exactly supported original client and never modifies it.
"""
import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

SOURCE_ID = b"com.netease.uuremote"
PROFILE_ID = b"com.netease.uualt002"
SOURCE_SHA256 = "1eaf621a2cf3afdfbb63dbd901ba28af7609b40ab25cd9176a710647ade54f88"
SUPPORTED_VERSION = ("4.48.3", "635")
DIRECTORY_OFFSETS = (0x2ACFDAC, 0x2AD0530)
PROFILE_DIRECTORY = b"UUSecond"


def command(*args):
    result = subprocess.run([str(x) for x in args], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def arm64_string(value):
    """Encode an eight-byte Swift small string loaded into register x0."""
    if len(value) != 8:
        raise ValueError("An eight-byte string is required")
    return b"".join(struct.pack("<I", (0xD2800000 if j == 0 else 0xF2800000)
                                | (j << 21)
                                | (int.from_bytes(value[j*2:j*2+2], "little") << 5))
                    for j in range(4))


def validate_source(source):
    source = Path(source).resolve(strict=True)
    info = plistlib.loads((source / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != SOURCE_ID.decode():
        raise ValueError("Source must be the original com.netease.uuremote app")
    version = (info.get("CFBundleShortVersionString"), info.get("CFBundleVersion"))
    if version != SUPPORTED_VERSION:
        raise ValueError(f"Unsupported UU version {version}; supported: {SUPPORTED_VERSION}")
    data = (source / "Contents/MacOS/UURemote").read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unknown or modified executable; refusing version-specific patches")
    for offset in DIRECTORY_OFFSETS:
        if data[offset:offset+16] != arm64_string(b"UURemote"):
            raise ValueError(f"Unexpected instruction sequence at {offset:#x}")
    return source, info


def patch_main(data):
    # Guard the entire original executable before changing any instructions.
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Executable checksum mismatch")
    for offset in DIRECTORY_OFFSETS:
        if data[offset:offset+16] != arm64_string(b"UURemote"):
            raise ValueError("Shared-state instruction mismatch")
        data = data[:offset] + arm64_string(PROFILE_DIRECTORY) + data[offset+16:]
    return data


def add_isolation_library(data):
    """Append LC_LOAD_DYLIB inside verified zero header padding of arm64 Mach-O."""
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected a thin 64-bit Mach-O")
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    name = b"@executable_path/../Frameworks/UUProfileIsolation.dylib\0"
    size = (24 + len(name) + 7) & ~7
    entry = struct.pack("<6I", 0xC, size, 24, 0, 0x10000, 0x10000) + name
    entry += bytes(size - len(entry))
    end = 32 + sizeofcmds
    if data[end:end+size] != bytes(size):
        raise ValueError("Not enough zeroed Mach-O header padding")
    result = bytearray(data)
    result[end:end+size] = entry
    struct.pack_into("<II", result, 16, ncmds + 1, sizeofcmds + size)
    return bytes(result)


def build(source, destination):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This version supports Apple Silicon macOS only")
    source, info = validate_source(source)
    destination = Path(destination).expanduser().resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Destination must be outside the original app")
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    if destination.suffix != ".app":
        raise ValueError("Destination must end in .app")
    command("/usr/bin/codesign", "--verify", "--deep", "--strict", source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    changes = []
    # Publish the copy only after all edits and signature validation succeed.
    with tempfile.TemporaryDirectory(prefix=".uu-multi-", dir=destination.parent) as scratch:
        staged = Path(scratch) / destination.name
        shutil.copytree(source, staged, symlinks=True)
        main_path = staged / "Contents/MacOS/UURemote"
        main_path.write_bytes(patch_main(main_path.read_bytes()))
        for path in staged.rglob("*"):
            if not path.is_file() or path.is_symlink() or "_CodeSignature" in path.parts:
                continue
            data = path.read_bytes()
            count = data.count(SOURCE_ID)
            paths = data.count(b"/Users/Shared/UURemote/")
            if not count and not paths:
                continue
            data = data.replace(SOURCE_ID, PROFILE_ID)
            data = data.replace(b"/Users/Shared/UURemote/", b"/Users/Shared/UUSecond/")
            path.write_bytes(data)
            changes.append({"path": str(path.relative_to(staged)),
                            "identifier_replacements": count,
                            "shared_path_replacements": paths})
        for path in sorted(staged.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if SOURCE_ID.decode() in path.name:
                path.rename(path.with_name(path.name.replace(SOURCE_ID.decode(), PROFILE_ID.decode())))
        info["CFBundleIdentifier"] = PROFILE_ID.decode()
        info["CFBundleName"] = "UU Remote Account 2"
        info["CFBundleDisplayName"] = "UU 远程 · 账户 2"
        info["LSRequiresNativeExecution"] = True
        for item in info.get("CFBundleURLTypes", []):
            item["CFBundleURLSchemes"] = ["uualt002"]
        (staged / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        for path in staged.glob("Contents/Resources/*.lproj/InfoPlist.strings"):
            try:
                localized = plistlib.loads(command("/usr/bin/plutil", "-convert", "xml1", "-o", "-", path))
            except (plistlib.InvalidFileException, ValueError):
                continue
            for key in ("CFBundleDisplayName", "CFBundleName"):
                if key in localized:
                    localized[key] = "UU 远程 · 账户 2"
            path.write_bytes(plistlib.dumps(localized))
        # Only arm64 directory routines have been verified. Remove the unpatched
        # Intel slice so Rosetta cannot accidentally reuse original shared state.
        thin_path = Path(scratch) / "UURemote-arm64"
        command("/usr/bin/lipo", main_path, "-thin", "arm64", "-output", thin_path)
        main_path.write_bytes(add_isolation_library(thin_path.read_bytes()))
        library = staged / "Contents/Frameworks/UUProfileIsolation.dylib"
        command("/usr/bin/xcrun", "clang", "-dynamiclib", "-fobjc-arc",
                "-arch", "arm64", "-framework", "Foundation", "-framework", "Security",
                "-framework", "IOKit", Path(__file__).with_name("profile_isolation.m"), "-o", library)
        manifest = {"tool": "uu-remote-multi", "profile_id": PROFILE_ID.decode(),
                    "source_version": list(SUPPORTED_VERSION),
                    "source_sha256": SOURCE_SHA256, "architecture": "arm64",
                    "changes": changes}
        (staged / "Contents/Resources/uu-multi-build.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        command("/usr/bin/codesign", "--force", "--deep", "--sign", "-", staged)
        command("/usr/bin/codesign", "--verify", "--deep", "--strict", staged)
        # Confirm that the original executable was not changed during the build.
        validate_source(source)
        os.rename(staged, destination)
    return destination


def check_running(source, destination):
    """Check both live app profiles using the vendor's CLI, without printing IDs."""
    source, _ = validate_source(source)
    destination = Path(destination).expanduser().resolve(strict=True)
    manifest = json.loads((destination / "Contents/Resources/uu-multi-build.json").read_text())
    if manifest.get("tool") != "uu-remote-multi":
        raise ValueError("Destination is not a generated UU Multi copy")
    command("/usr/bin/codesign", "--verify", "--deep", "--strict", destination)

    def query(app, *arguments):
        result = subprocess.run([str(app / "Contents/Helpers/uuyc-cli"), *arguments, "--json"],
                                capture_output=True, timeout=20)
        try:
            document = json.loads(result.stdout)
        except ValueError:
            return {}
        if not document.get("success"):
            return {}
        return document.get("data") or {}

    original_status = query(source, "status")
    second_status = query(destination, "status")
    original_user = query(source, "user", "info")
    second_user = query(destination, "user", "info")
    original_id = query(source, "assist", "id").get("assistId")
    second_id = query(destination, "assist", "id").get("assistId")
    original_user_id = original_user.get("userId")
    second_user_id = second_user.get("userId")
    rows = command("/bin/ps", "-axo", "pid,comm").decode().splitlines()

    def count(app):
        executable = (app / "Contents/MacOS/UURemote").resolve()
        return sum(len(parts) == 2 and Path(parts[1]).is_absolute()
                   and Path(parts[1]).resolve() == executable
                   for parts in (row.strip().split(None, 1) for row in rows))

    # Deliberately return booleans, never account identifiers or assist codes.
    checks = {
        "original_signed_in": original_status.get("isLoggedIn") is True,
        "second_signed_in": second_status.get("isLoggedIn") is True,
        "different_accounts": bool(original_user_id and second_user_id and original_user_id != second_user_id),
        "different_device_ids": bool(original_id and second_id and original_id != second_id),
        "one_original_main_process": count(source) == 1,
        "one_second_main_process": count(destination) == 1,
    }
    return {"checks": checks, "all_checks_passed": all(checks.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/Applications/UURemote.app"))
    parser.add_argument("--output", type=Path,
                        default=Path.home() / "Applications/UU Remote Account 2.app")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check the two live profiles without displaying account or device IDs")
    args = parser.parse_args()
    try:
        if args.check:
            result = check_running(args.source, args.output)
            print(json.dumps(result, indent=2))
            return 0 if result["all_checks_passed"] else 1
        app = build(args.source, args.output)
        print(f"Created: {app}")
        if args.launch:
            command("/usr/bin/open", "-n", app)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

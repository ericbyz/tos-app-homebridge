#!/usr/bin/env python3
"""Unpack a built .deb and verify structure without dpkg (pure stdlib).

Checks (per platform):
  - ar members: debian-binary / control.tar.gz / data.tar.xz
  - control.tar members live at the tar ROOT (./control — not ./DEBIAN/control)
  - control fields: Package / Version / Architecture match the build
  - payload carries the verbatim upstream tree (start.sh, bundled node,
    storage homebridge package) + our TOS overlay (config.ini/lang/icon/unit)
  - symlink integrity: /opt/homebridge/bin/{npm,npx,corepack,hb-service} are
    SYMTYPE entries with the expected upstream targets
  - every ELF in the payload has the expected machine type
    (x86_64 -> EM_X86_64=0x3e, aarch64 -> EM_AARCH64=0xb7)

Usage: unpack_check.py <file.deb> <x86_64|aarch64> [expected_version]
Exit code 0 = pass.
"""
import io
import lzma
import re
import sys
import tarfile

ELF_MACHINE = {"x86_64": 0x3E, "aarch64": 0xB7}

EXPECTED_SYMLINKS = {
    "./opt/homebridge/bin/npm": "../lib/node_modules/npm/bin/npm-cli.js",
    "./opt/homebridge/bin/npx": "../lib/node_modules/npm/bin/npx-cli.js",
    "./opt/homebridge/bin/corepack": "../lib/node_modules/corepack/dist/corepack.js",
    "./opt/homebridge/bin/hb-service":
        "../lib/node_modules/homebridge-config-ui-x/dist/bin/hb-service.js",
}

REQUIRED_FILES = [
    "./opt/homebridge/start.sh",
    "./opt/homebridge/source.sh",
    "./opt/homebridge/bin/node",
    "./opt/homebridge/config.ini",
    "./opt/homebridge/homebridge.lang",
    "./opt/homebridge/init.d/homebridge.service",
    "./opt/homebridge/images/icons/homebridge.svg",
    "./var/lib/homebridge/package.json",
    "./var/lib/homebridge/node_modules/homebridge/package.json",
    "./lib/systemd/system/homebridge.service",
    "./etc/hb-service/homebridge/prestart.d/10-fix-permissions",
    "./usr/share/polkit-1/rules.d/homebridge.rules",
    "./usr/share/doc/homebridge/copyright",
    "./usr/share/doc/homebridge/changelog.gz",
]


def err(msg):
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    deb, platform = sys.argv[1], sys.argv[2]
    version = sys.argv[3] if len(sys.argv) > 3 else None
    if platform not in ELF_MACHINE:
        return err(f"unknown platform {platform}")
    app_id = "homebridge"

    data = open(deb, "rb").read()
    if data[:8] != b"!<arch>\n":
        return err("not an ar archive")

    members = {}
    off = 8
    while off < len(data):
        hdr = data[off:off + 60]
        if len(hdr) < 60:
            return err("truncated ar header")
        name = hdr[0:16].decode().rstrip()
        size = int(hdr[48:58].decode().strip())
        members[name] = data[off + 60:off + 60 + size]
        off += 60 + size + (size % 2)

    for m in ("debian-binary", "control.tar.gz", "data.tar.xz"):
        if m not in members:
            return err(f"missing ar member {m}")
    if members["debian-binary"] != b"2.0\n":
        return err("debian-binary != 2.0")

    with tarfile.open(fileobj=io.BytesIO(members["control.tar.gz"])) as tf:
        names = tf.getnames()
        ctl_txt = tf.extractfile("./control").read().decode()
    if "./control" not in names:
        return err(f"control.tar members not at root: {names[:5]}")
    if "DEBIAN" in "".join(names):
        return err(f"control.tar must not carry a DEBIAN/ prefix: {names}")

    want_arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform]
    fields = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", ctl_txt, re.M))
    if fields.get("Package") != app_id:
        return err(f"Package != {app_id}: {fields.get('Package')}")
    if fields.get("Architecture") != want_arch:
        return err(f"Architecture != {want_arch}: {fields.get('Architecture')}")
    if version and fields.get("Version") != version:
        return err(f"Version != {version}: {fields.get('Version')}")
    if "jq" not in (fields.get("Depends") or ""):
        return err("Depends must include jq (start.sh uses it to guard package.json)")

    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(members["data.tar.xz"]))) as tf:
        payloads = {m.name: m for m in tf.getmembers()}
        for need in REQUIRED_FILES:
            if need not in payloads:
                return err(f"data.tar missing {need}")
        if payloads["./lib/systemd/system/homebridge.service"].size == 0:
            return err("shipped unit is empty (upstream replacement failed?)")

        # our unit must be the TOS-hardened one, not upstream's
        our_unit = tf.extractfile("./lib/systemd/system/homebridge.service").read().decode()
        if "start.sh" not in our_unit or "TOS" not in our_unit:
            return err("./lib/systemd/system/homebridge.service is not the TOS-hardened unit")

        # symlink integrity (npm/npx/corepack/hb-service are relative symlinks)
        for path, target in EXPECTED_SYMLINKS.items():
            m = payloads.get(path)
            if m is None:
                return err(f"missing symlink {path}")
            if not m.issym() or m.linkname != target:
                return err(f"{path}: expected symlink -> {target}, got "
                           f"{'symlink -> ' + m.linkname if m.issym() else tarfile.type_repr(m.type)}")

        # start.sh + node executable bits
        for path in ("./opt/homebridge/start.sh", "./opt/homebridge/bin/node"):
            if not (payloads[path].mode & 0o111):
                return err(f"{path} not executable (mode {oct(payloads[path].mode)})")

        # config.ini sanity
        cfg = tf.extractfile("./opt/homebridge/config.ini").read().decode()
        import json
        c = json.loads(cfg)
        if c.get("platform") != platform:
            return err(f"config.ini platform != {platform}: {c.get('platform')}")
        if "18246" not in c.get("path", ""):
            return err(f"config.ini path port != 18246: {c.get('path')}")

        # ELF machine scan. Upstream legitimately ships multiarch prebuilds
        # (node-pty: linux-x64/arm64/arm/ia32 all in ONE package), so ELFs
        # under a /prebuilds/ directory are exempt from the machine check —
        # everything else must match the build platform.
        elfs = []
        node_machine = None
        foreign = []
        for m in payloads.values():
            if not m.isfile():
                continue
            f = tf.extractfile(m)
            head = f.read(20)
            if head[:4] == b"\x7fELF" and head[4] == 2:  # ELF64
                f.seek(18)
                machine = int.from_bytes(f.read(2), "little")
                elfs.append((m.name, machine))
                if m.name == "./opt/homebridge/bin/node":
                    node_machine = machine
                elif machine != ELF_MACHINE[platform]:
                    foreign.append((m.name, machine))
        if not elfs:
            return err("no ELF64 binaries found in payload (bundled node missing?)")
        if node_machine != ELF_MACHINE[platform]:
            return err(f"bundled node machine 0x{node_machine:x} != "
                       f"{ELF_MACHINE[platform]:x} ({platform})")
        for name, machine in foreign:
            if "/prebuilds/" not in name:
                return err(f"{name}: ELF machine 0x{machine:x} != "
                           f"{ELF_MACHINE[platform]:x} ({platform}) — not a prebuild")
        # platform-matching node-pty prebuild must exist (UI terminal feature)
        want_pre, want_machine = {
            "x86_64": ("/prebuilds/linux-x64/", 0x3E),
            "aarch64": ("/prebuilds/linux-arm64/", 0xB7),
        }[platform]
        matching_pre = [n for n, mch in elfs if want_pre in n and mch == want_machine]
        if not matching_pre:
            return err(f"no {platform} node-pty prebuild found under {want_pre}")

    for s in ("postinst", "prerm", "postrm"):
        if f"./{s}" not in names:
            return err(f"control.tar missing ./{s}")

    print(f"OK {deb} [{platform}]")
    print(f"  control: Package={fields.get('Package')} Version={fields.get('Version')} "
          f"Architecture={fields.get('Architecture')}")
    print(f"  payload: {len(payloads)} entries, {len(elfs)} ELF64 ({platform}) machine-ok, "
          f"{len(EXPECTED_SYMLINKS)} symlinks verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Minimal dpkg-deb-compatible .deb packer (pure stdlib).

Produces the standard Debian binary package format:
    ar archive { debian-binary, control.tar.gz, data.tar.xz }

Why not dpkg-deb: this project must build identically on Windows dev
machines (no dpkg) and in CI. The output is a normal deb accepted by
dpkg -i, dpkg-deb -c/-I and lintian.

Homebridge mode (--upstream-deb <file.deb>):
    The upstream homebridge-apt-pkg payload (24k+ files, 23 symlinks,
    bundled node) is streamed member-by-member into our data.tar.xz —
    verbatim, preserving symlinks, modes and mtimes — WITHOUT staging it
    on disk. Windows dev machines cannot reliably represent the ELF's
    relative symlinks (bin/npm -> ../lib/node_modules/npm/bin/npm-cli.js),
    so no filesystem staging of the upstream tree ever happens.
    Members under --replace-with paths are dropped and replaced by our
    staged versions (staging/add/), e.g. the TOS-hardened systemd unit.

Staging layout:
    staging/DEBIAN/   control + maintainer scripts (control.tar.gz, at tar ROOT)
    staging/add/      our extra data files (merged into data.tar.xz)

Determinism rules (staged files):
  - fixed mtime (SOURCE_DATE_EPOCH if set, else 0)
  - sorted entry order, dirs before their contents
  - fixed uid/gid 0, uname/gname root
  - rule-based permissions (maintainer scripts 0755, rest 0644)
"""
import argparse
import io
import lzma
import os
import sys
import tarfile
import time

MAINT_SCRIPTS = {"preinst", "postinst", "prerm", "postrm", "config"}
DIR_MODE = 0o755
FILE_MODE = 0o644
EXEC_MODE = 0o755


def _mtime() -> int:
    v = os.environ.get("SOURCE_DATE_EPOCH")
    return int(v) if v and v.isdigit() else 0


def _add_tree(tf: tarfile.TarFile, root: str, arc_prefix: str) -> None:
    """Add `root` dir tree into tar with names `arc_prefix/<rel>`."""
    all_entries = []
    for cur, dirs, files in os.walk(root):
        dirs.sort()
        for d in dirs:
            all_entries.append(("dir", os.path.join(cur, d)))
        for f in sorted(files):
            all_entries.append(("file", os.path.join(cur, f)))
    all_entries.sort(key=lambda e: e[1])

    mtime = _mtime()
    for kind, abs_path in all_entries:
        rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
        arc = f"{arc_prefix}/{rel}"
        info = tarfile.TarInfo(arc)
        info.mtime = mtime
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        if kind == "dir":
            info.type = tarfile.DIRTYPE
            info.mode = DIR_MODE
            info.size = 0
            tf.addfile(info)
        else:
            st = os.stat(abs_path)
            exec_ok = os.path.basename(rel) in MAINT_SCRIPTS
            info.size = st.st_size
            info.mode = EXEC_MODE if exec_ok else FILE_MODE
            with open(abs_path, "rb") as f:
                tf.addfile(info, f)


def _copy_upstream_members(src_tf: tarfile.TarFile, dst_tf: tarfile.TarFile,
                           replace_paths: set) -> int:
    """Stream upstream members verbatim into dst_tf. Returns count."""
    count = 0
    for m in src_tf.getmembers():
        if m.name in replace_paths:
            print(f"  upstream member replaced: {m.name}")
            continue
        info = tarfile.TarInfo(m.name)
        info.type = m.type
        info.mode = m.mode
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        info.mtime = m.mtime
        info.linkname = m.linkname
        info.size = m.size
        if m.isfile():
            dst_tf.addfile(info, src_tf.extractfile(m))
        else:
            dst_tf.addfile(info)
        count += 1
    return count


def _ar_header(name: str, size: int) -> bytes:
    hdr = f"{name:<16}{_mtime():<12}{'0':<6}{'0':<6}{'100644':<8}{size:<10}".encode("ascii")
    assert len(hdr) == 58, len(hdr)
    return hdr + b"\x60\x0a"  # 60 bytes total


def gzip_bytes(data: bytes) -> bytes:
    import gzip as _gzip
    out = io.BytesIO()
    with _gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as g:
        g.write(data)
    return out.getvalue()


def build_deb(staging: str, output: str, upstream_deb,
              replace_paths) -> None:
    debian_dir = os.path.join(staging, "DEBIAN")
    if not os.path.isdir(debian_dir):
        raise SystemExit(f"ERROR: {debian_dir} not found in staging directory")

    # ---- data member ----
    data_buf = io.BytesIO()
    with tarfile.open(fileobj=data_buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        if upstream_deb:
            data = open(upstream_deb, "rb").read()
            off = 8
            upstream_data = None
            while off < len(data):
                hdr = data[off:off + 60]
                name = hdr[0:16].decode().rstrip()
                size = int(hdr[48:58].decode().strip())
                if name == "data.tar.xz":
                    upstream_data = data[off + 60:off + 60 + size]
                    break
                off += 60 + size + (size % 2)
            if upstream_data is None:
                raise SystemExit("ERROR: upstream deb has no data.tar.xz member")
            with tarfile.open(fileobj=io.BytesIO(lzma.decompress(upstream_data))) as src:
                n = _copy_upstream_members(src, tf, replace_paths)
            print(f"  streamed {n} upstream members verbatim")

        add_dir = os.path.join(staging, "add")
        if os.path.isdir(add_dir):
            # direct merge: _add_tree emits dir entries for every level, so
            # parents are covered; files get FILE_MODE (all overlay data is 0644)
            _add_tree(tf, add_dir, ".")

    filters = [{"id": lzma.FILTER_LZMA2, "preset": 6}]
    data_xz = lzma.compress(data_buf.getvalue(), format=lzma.FORMAT_XZ, filters=filters)

    # ---- control member: dpkg expects control files at the tar ROOT ----
    control_buf = io.BytesIO()
    with tarfile.open(fileobj=control_buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        root_info = tarfile.TarInfo("./")
        root_info.type = tarfile.DIRTYPE
        root_info.mode = DIR_MODE
        root_info.mtime = _mtime()
        root_info.uid = root_info.gid = 0
        root_info.uname = root_info.gname = "root"
        tf.addfile(root_info)
        _add_tree(tf, debian_dir, ".")
    control_gz = gzip_bytes(control_buf.getvalue())

    members = [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_gz),
        ("data.tar.xz", data_xz),
    ]
    with open(output, "wb") as out:
        out.write(b"!<arch>\n")
        for name, payload in members:
            out.write(_ar_header(name, len(payload)))
            out.write(payload)
            if len(payload) % 2:
                out.write(b"\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staging", required=True, help="staging dir containing DEBIAN/ and add/")
    ap.add_argument("--output", required=True, help="output .deb path")
    ap.add_argument("--upstream-deb", default=None,
                    help="upstream .deb whose data.tar.xz members are streamed verbatim")
    ap.add_argument("--replace", action="append", default=[],
                    help="upstream member path to drop (replaced by staged add/ file), "
                         "e.g. ./lib/systemd/system/homebridge.service")
    args = ap.parse_args()
    t0 = time.time()
    build_deb(args.staging, args.output, args.upstream_deb, set(args.replace))
    size = os.path.getsize(args.output)
    print(f"built {args.output} ({size/1024/1024:.1f} MB) in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

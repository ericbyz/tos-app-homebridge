# tos-app-homebridge

TOS App Center packaging of [Homebridge](https://github.com/homebridge/homebridge)
(HomeKit bridge, Apache-2.0) from the **official `homebridge-apt-pkg` deb**.

Bridges hundreds of smart-home accessories that don't natively support HomeKit
into Apple Home, with the full web UI (plugin marketplace, pairing, logs,
backup) at `http://<NAS>:18246`.

## Why this upstream is safe on TOS 7

The official deb bundles its own **Node.js 22 runtime** whose highest glibc
symbol requirement is 2.28 — compatible with TOS 7's glibc 2.35, unlike
Domoticz (needs 2.36) and NanoMQ (needs 2.38), both archived for that reason.

## Packaging strategy (differs from other repos in this pipeline)

Upstream `start.sh` **hardcodes** `/opt/homebridge` (node, hb-service,
npm_config_prefix) and `/var/lib/homebridge` (storage is cwd-relative), and
npm/npm/corepack are **relative symlinks** into the bundled node_modules.
Therefore:

- the upstream payload ships **verbatim** (24 246 members streamed
  member-by-member from the upstream `data.tar.xz` — never staged on disk,
  because Windows cannot represent `bin/npm -> ../lib/node_modules/...`
  symlinks; `scripts/build_deb.py --upstream-deb` does the in-memory merge);
- paths stay at `/opt/homebridge` + `/var/lib/homebridge` (deviation from the
  usual `/usr/local/<app>` convention, documented in NOTICE);
- only the systemd unit (TOS-hardened, UI port 18246), TOS metadata
  (config.ini / homebridge.lang / icon) and docs are added.

The UI port comes from the `platform: config` block of
`/var/lib/homebridge/config.json` — seeded deterministically by postinst
(18246), with `/etc/hb-ui-port` written as upstream-parity fallback.

## Verification checklist

- [x] `scripts/validate.py` — metadata rules (guide ch.4/8/14), port 18246
      consistency config.ini ↔ seed ↔ postinst ↔ unit, no port collisions
- [x] `scripts/unpack_check.py` — ar/control-tar-root/ELF machine scan
      (bundled node = platform arch; foreign-arch ELFs allowed only under
      `/prebuilds/` — upstream node-pty ships 4 arches in one package),
      4 symlink targets, executable bits, platform-matching node-pty prebuild
- [x] dual-arch build: `build.sh` → `build/output/homebridge_{x86_64,aarch64}.deb`
- [x] VM install + App Center flow + browser test on port 18246
      (see `docs/` in the pipeline workspace for the runbook)

## Hardening notes

- `NoNewPrivileges/ProtectSystem=strict/ProtectHome/PrivateTmp/...` with
  `ReadWritePaths=/opt/homebridge /var/lib/homebridge` (UI self-update +
  plugin installs need both writable).
- **No `MemoryDenyWriteExecute`**: Node/V8 JIT needs RWX pages on this kernel
  family (same crash class as the go2rtc/owncast Go runtimes).
- **No `Restart=`**: service lifecycle is managed by the TOS platform.
- **No avahi dependency**: Homebridge uses its own bundled multicast-dns.

## Layout

```
config.ini               TOS App Center metadata (JSON; port 18246)
homebridge.lang          26-locale descriptions (generated: scripts/make_lang.py)
UPSTREAM                 version + sha256 pins (single source of truth)
DEBIAN/                  control + postinst/prerm/postrm
init.d/homebridge.service  TOS-hardened unit (ships at /lib/systemd/system/
                           replacing the upstream member, + /opt copy)
images/icons/            SVG icon
packaging-extras/        homebridge.config.seed (UI port source of truth)
scripts/                 fetch_upstream / build_deb / unpack_check / validate / make_lang
.upstream-cache/         pinned upstream debs (git-ignored)
```

## Build

```bash
./build.sh                 # both arches (downloads + sha256-verifies via fetch_upstream.sh)
python3 scripts/validate.py
```

## License

Upstream Apache-2.0 (see UPSTREAM / NOTICE). Packaging scripts in this repo:
same license as the pipeline (MIT).

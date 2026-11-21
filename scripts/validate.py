#!/usr/bin/env python3
"""Validate TOS package metadata for homebridge (official rules, guide ch.4/8/14).

open_path mode (external browser tab): checks config.ini required fields,
id charset rules, category limits (official category IDs), lang coverage
(26 documented languages, advisory), icon SVG validity, and port 18246
consistency across config.ini path / postinst seed / unit / UPSTREAM pin.
Also guards the homebridge-specific invariants: verbatim upstream payload
(no path rebase), jq dependency, seed JSON validity.
Exit code 0 = pass.
"""
import json
import os
import re
import sys

REQUIRED = ["id", "icon", "publisher", "exec", "version", "help",
            "category", "platform", "application_type", "user"]
LANG_BASELINE = [
    "zh-cn", "zh-hk", "en-us", "ko-kr", "ja-jp", "de-de", "fr-fr", "it-it",
    "es-es", "hu-hu", "pl-pl", "tr-tr", "ru-ru", "pt-pt", "cs-cz", "da-dk",
    "nl-nl", "nb-no", "sv-se", "el-gr", "ro-ro", "th-th", "vi-vn", "id-id",
    "ar-sa", "he-il",
]
OFFICIAL_CATEGORIES = {
    "Audio_Video_Entertainment", "Photography_Video", "Backup_Sync",
    "Development_Tools", "Utilities", "Web_Services", "Security",
    "Download", "Driver", "Artificial_Intelligence",
}
ID_FORBIDDEN_PREFIX = "tos"
ID_FORBIDDEN_WORDS = {"docker", "bin", "api", "admin"}
RESERVED_PORTS = {22, 80, 443, 445, 3306, 5050, 5432, 6379, 8181, 8443}
# registered ports of sibling TOS apps (port registry, vm/runbook.md)
TAKEN_PORTS = {15280, 18231, 18233, 18234, 18235, 18236, 18238, 18239,
               18240, 18241, 18242, 18243, 18244, 18245}

errors: list = []
advisories: list = []


def err(msg: str) -> None:
    errors.append(msg)


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    cfg = json.load(open("config.ini", encoding="utf-8"))

    for field in REQUIRED:
        if field not in cfg:
            err(f"missing required field: {field}")

    app_id = cfg.get("id", "")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,49}", app_id):
        err(f"id '{app_id}' violates charset rules (lowercase letters/digits/"
            "hyphen, must start with a letter, <=50 chars)")
    if app_id.startswith(ID_FORBIDDEN_PREFIX):
        err(f"id must not start with reserved prefix '{ID_FORBIDDEN_PREFIX}'")
    if app_id in ID_FORBIDDEN_WORDS:
        err(f"id must not be a generic keyword: {app_id}")

    if cfg.get("application_type") != "deb":
        err(f"application_type must be 'deb', got {cfg.get('application_type')!r}")
    if cfg.get("platform") not in ("x86_64", "aarch64"):
        err(f"platform must be x86_64 or aarch64, got {cfg.get('platform')!r}")
    if len(cfg.get("category", [])) > 3:
        err("category must have at most 3 entries")
    for c in cfg.get("category", []):
        if c not in OFFICIAL_CATEGORIES:
            advisories.append(f"category '{c}' is not an official category ID "
                              "(Appendix A) — may need pre-approval")
    if "type" in cfg and cfg.get("open_path"):
        err("type and open_path are mutually exclusive — choose only one")
    if not cfg.get("help"):
        err("help URL is mandatory and cannot be empty")

    # UI mode: open_path (web UI in new tab)
    path = cfg.get("path", "")
    web_port = None

    if cfg.get("open_path"):
        m = re.match(r"^http://\$\{ip\}:(\d+)$", path)
        if not m:
            err(f"open_path mode expects path like http://${{ip}}:<port>, got {path!r}")
        else:
            web_port = int(m.group(1))
            if web_port in RESERVED_PORTS:
                err(f"port {web_port} is a TOS reserved port")
            if web_port in TAKEN_PORTS:
                err(f"port {web_port} is already taken by another TOS app (registry)")
            if not (8000 <= web_port <= 19999):
                advisories.append(f"port {web_port} is outside the recommended 8000-19999 range")
    else:
        err("homebridge must use open_path mode (web UI port)")

    # config.json seed (single source of the UI port)
    seed_path = "packaging-extras/homebridge.config.seed"
    if not os.path.exists(seed_path):
        err(f"missing {seed_path}")
    else:
        try:
            seed = json.load(open(seed_path, encoding="utf-8"))
        except json.JSONDecodeError as e:
            seed = None
            err(f"{seed_path}: invalid JSON: {e}")
        if seed is not None:
            blocks = [p for p in seed.get("platforms", []) if p.get("platform") == "config"]
            if not blocks:
                err(f"{seed_path}: missing 'platform': 'config' block")
            elif blocks[0].get("port") != web_port:
                err(f"{seed_path}: UI port {blocks[0].get('port')} != config.ini path port {web_port}")
            if "bridge" in seed:
                advisories.append(f"{seed_path}: bridge block present — should be omitted "
                                  "(hb-service generates a complete one on first run)")

    # postinst must seed the same port deterministically
    postinst_path = "DEBIAN/postinst"
    if not os.path.exists(postinst_path):
        err(f"missing {postinst_path}")
    else:
        post = open(postinst_path, encoding="utf-8").read()
        if web_port is not None and f'"port": {web_port}' not in post:
            err(f"{postinst_path}: does not seed port {web_port} into config.json")
        if "/var/lib/homebridge/config.json" not in post:
            err(f"{postinst_path}: must seed /var/lib/homebridge/config.json")
        if "useradd" not in post:
            err(f"{postinst_path}: must create the '{app_id}' system user")
        if "chown -R" not in post:
            err(f"{postinst_path}: must chown app dir + storage")

    # service unit
    svc_path = "init.d/homebridge.service"
    if not os.path.exists(svc_path):
        err(f"missing {svc_path}")
    else:
        svc = open(svc_path, encoding="utf-8").read()
        if "ExecStart=/opt/homebridge/start.sh" not in svc:
            err(f"{svc_path}: ExecStart must be the upstream start.sh "
                "(payload is verbatim; start.sh hardcodes /opt/homebridge)")
        if "WorkingDirectory=/var/lib/homebridge" not in svc:
            err(f"{svc_path}: WorkingDirectory must be the storage path (cwd-relative)")
        if "User=homebridge" not in svc:
            err(f"{svc_path}: must run as the dedicated homebridge user")
        if "ReadWritePaths=/opt/homebridge /var/lib/homebridge" not in svc:
            err(f"{svc_path}: ReadWritePaths whitelist missing (app dir + storage)")
        if "MemoryDenyWriteExecute=true" in svc:
            err(f"{svc_path}: MemoryDenyWriteExecute breaks Node/V8 JIT (go2rtc precedent)")
        if "Requires=" in svc:
            err(f"{svc_path}: Requires= must not be used (hard dep may be absent on TOS)")
        if re.search(r"^Restart=", svc, re.M):
            err(f"{svc_path}: Restart= must be omitted (platform manages lifecycle)")

    # lang coverage
    lang_path = f"{app_id}.lang"
    if not os.path.exists(lang_path):
        err(f"missing {lang_path}")
    else:
        content = open(lang_path, encoding="utf-8-sig").read()
        if "\r\n" in content:
            advisories.append("lang file should use LF endings")
        missing = [l for l in LANG_BASELINE if f"[{l}]" not in content]
        if missing:
            advisories.append(f"{len(missing)} documented languages missing: {', '.join(missing)}")
        if web_port is not None:
            stale = re.findall(r":1[0-9]{4}", content)
            wrong = [p for p in set(stale) if not p.endswith(str(web_port))]
            if wrong:
                err(f"{lang_path}: stale port refs {wrong} (expected :{web_port})")
        for section in re.split(r"\n(?=\[)", content):
            sm = re.match(r"\[([a-z-]+)\]", section)
            if not sm:
                continue
            loc = sm.group(1)
            for key in ("name", "auth", "descript"):
                km = re.search(rf'^{key}\s*=\s*"([^"]*)"', section, re.M)
                if km is None or not km.group(1).strip():
                    err(f"{lang_path}: [{loc}] has empty or missing {key}")

    # icon
    icon_rel = cfg.get("icon", "").lstrip("/")
    if not os.path.exists(icon_rel):
        err(f"icon not found: {icon_rel}")
    else:
        svg = open(icon_rel, encoding="utf-8").read()
        if "<svg" not in svg or "</svg>" not in svg:
            err(f"{icon_rel} is not a valid SVG")
        if "viewBox" not in svg:
            err(f"{icon_rel} missing viewBox attribute")
        expected = f"{app_id}.svg"
        if os.path.basename(icon_rel) != expected:
            err(f"icon filename {os.path.basename(icon_rel)} should be {expected}")

    # UPSTREAM pin hygiene
    up = open("UPSTREAM", encoding="utf-8").read()
    if "REPLACE_WITH_UPSTREAM_SHA256" in up:
        err("UPSTREAM: unpinned sha256 placeholder")
    for plat in ("x86_64", "aarch64"):
        if not re.search(rf"^SHA256_{plat}=[0-9a-f]{{64}}", up, re.M):
            err(f"UPSTREAM: missing SHA256_{plat} pin")

    # control hygiene
    ctl = open("DEBIAN/control", encoding="utf-8").read()
    if "jq" not in ctl:
        err("DEBIAN/control: Depends must include jq (start.sh guard)")

    for e in errors:
        print(f"ERROR: {e}")
    for a in advisories:
        print(f"ADVISORY: {a}")
    if errors:
        print(f"\n{len(errors)} error(s), {len(advisories)} advisory(ies)")
        return 1
    print("All validations passed" + (f" ({len(advisories)} advisories)" if advisories else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

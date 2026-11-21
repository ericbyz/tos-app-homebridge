#!/usr/bin/env bash
# ============================================================
# Build TOS deb packages for homebridge (x86_64 + aarch64)
# ============================================================
# Strategy: the official homebridge-apt-pkg payload ships VERBATIM
# (streamed member-by-member from the upstream deb's data.tar.xz —
# 24k+ files, 23 relative symlinks, bundled node; never staged on disk
# because Windows cannot represent bin/npm -> ../lib/node_modules/...
# symlinks reliably). We only:
#   * replace its systemd unit with a TOS-hardened one (UI port 18246)
#   * add TOS metadata (config.ini/lang/icon) under /opt/homebridge/
# Upstream paths stay at /opt/homebridge + /var/lib/homebridge (start.sh
# hardcodes them; storage is cwd-relative per upstream convention).
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_ROOT}"

BUILD_DIR="build"
OUTPUT_DIR="${BUILD_DIR}/output"
mkdir -p "${OUTPUT_DIR}"

declare -A PIN
while IFS='=' read -r key value; do
    [[ -z "${key}" || "${key}" =~ ^# ]] && continue
    PIN["${key}"]="${value}"
done < UPSTREAM

APP_ID="homebridge"
VERSION="${PIN[UPSTREAM_VERSION]}"
TAG="${PIN[UPSTREAM_TAG]}"

CONFIG_VERSION=$(python3 -c "import json; print(json.load(open('config.ini'))['version'])")
if [[ "${CONFIG_VERSION}" != "${VERSION}" ]]; then
    echo "ERROR: config.ini version (${CONFIG_VERSION}) != UPSTREAM version (${VERSION})" >&2
    echo "  update config.ini + UPSTREAM together" >&2
    exit 1
fi

EVALS="$(bash scripts/fetch_upstream.sh)"
X64_FILE="$(sed -n 's/^FETCHED_X64=//p' <<< "${EVALS}")"
A64_FILE="$(sed -n 's/^FETCHED_A64=//p' <<< "${EVALS}")"
declare -A ASSET_FILE=( [x86_64]="${X64_FILE}" [aarch64]="${A64_FILE}" )

platform_to_dpkg() {
    case "$1" in
        x86_64)  echo "amd64" ;;
        aarch64) echo "arm64" ;;
        *) echo "ERROR: unknown platform $1" >&2; exit 1 ;;
    esac
}

build_platform() {
    local platform="$1"
    local dpkg_arch
    dpkg_arch="$(platform_to_dpkg "${platform}")"
    local staging="${BUILD_DIR}/${platform}/staging"

    echo "=== Building ${APP_ID} v${VERSION} for ${platform} (${dpkg_arch}) ==="
    rm -rf "${BUILD_DIR}/${platform}"
    mkdir -p "${staging}/add/opt/homebridge/images/icons" \
             "${staging}/add/opt/homebridge/init.d" \
             "${staging}/add/lib/systemd/system" \
             "${staging}/add/usr/share/doc/${APP_ID}" \
             "${staging}/DEBIAN"

    # ---- our overlay files ----
    install -m 644 images/icons/homebridge.svg \
        "${staging}/add/opt/homebridge/images/icons/homebridge.svg"

    python3 - "$platform" "${staging}/add/opt/homebridge/config.ini" <<'PYEOF'
import json, sys
platform, out = sys.argv[1], sys.argv[2]
cfg = json.load(open("config.ini", encoding="utf-8"))
cfg["platform"] = platform
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"  config.ini platform={platform}")
PYEOF
    python3 - "${platform}" "${staging}/add/opt/homebridge/homebridge.lang" <<'PYEOF'
# render homebridge.lang with the per-platform web port (kept in sync with
# config.ini path / unit / postinst seed by validate.py)
import sys
platform, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, "scripts")
import make_lang
make_lang.render(out)
PYEOF

    # TOS-hardened unit: shipped BOTH at the systemd path (replacing the
    # upstream member) and inside the app dir (unpack_check + forensic copy)
    install -m 644 init.d/homebridge.service "${staging}/add/lib/systemd/system/homebridge.service"
    install -m 644 init.d/homebridge.service "${staging}/add/opt/homebridge/init.d/homebridge.service"

    cat > "${staging}/add/usr/share/doc/${APP_ID}/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Homebridge
Upstream-Homepage: ${PIN[UPSTREAM_REPO]}
Source: ${PIN[UPSTREAM_REPO]} (homebridge-apt-pkg, official deb)

Files: *
Copyright: $(date +%Y) Homebridge contributors
License: Apache-2.0
 The complete text of the Apache-2.0 license ships in the package
 (upstream LICENSE). The bundled Node.js runtime carries its own license
 (see /opt/homebridge/LICENSE).
EOF
    {
        echo "homebridge (${VERSION}) upstream; urgency=low"
        echo
        echo "  * Repackaged the official homebridge-apt-pkg ${TAG} deb for TOS"
        echo "    (payload streamed verbatim; paths kept at /opt/homebridge per"
        echo "    upstream convention; systemd unit replaced with a TOS-hardened"
        echo "    one, UI port 18246). Upstream deb sha256 pinned in UPSTREAM."
        echo
        echo " -- ericbyz <ericbyz@users.noreply.github.com>  $(date -R)"
    } | gzip -9 > "${staging}/add/usr/share/doc/${APP_ID}/changelog.gz"

    # ---- DEBIAN control (Architecture templated) ----
    sed "s/^Architecture:.*$/Architecture: ${dpkg_arch}/" DEBIAN/control \
        > "${staging}/DEBIAN/control"
    for s in postinst prerm postrm; do
        install -m 755 "DEBIAN/${s}" "${staging}/DEBIAN/${s}"
    done

    local out="${OUTPUT_DIR}/${APP_ID}_${platform}.deb"
    python3 scripts/build_deb.py \
        --staging "${staging}" \
        --output "${out}" \
        --upstream-deb "${ASSET_FILE[${platform}]}" \
        --replace "./lib/systemd/system/homebridge.service"

    (cd "${OUTPUT_DIR}" && sha256sum "$(basename "${out}")" > "$(basename "${out}").sha256")

    python3 scripts/unpack_check.py "${out}" "${platform}" "${VERSION}"
    echo "=== done: ${out}"
}

PLATFORMS=("$@")
[[ ${#PLATFORMS[@]} -eq 0 ]] && PLATFORMS=(x86_64 aarch64)
for p in "${PLATFORMS[@]}"; do
    build_platform "${p}"
done

echo
echo "=== Artifacts ==="
ls -lh "${OUTPUT_DIR}"

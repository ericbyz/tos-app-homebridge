#!/usr/bin/env bash
# Fetch pinned upstream homebridge-apt-pkg release debs and verify SHA256.
# Usage: ./scripts/fetch_upstream.sh [cache-dir]
# curl to github.com release assets is flaky from some networks (RST) —
# falls back to `gh release download` (API channel) automatically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${1:-${REPO_ROOT}/.upstream-cache}"
mkdir -p "${CACHE}"

PIN_FILE="${REPO_ROOT}/UPSTREAM"
declare -A PIN
while IFS='=' read -r key value; do
    [[ -z "${key}" || "${key}" =~ ^# ]] && continue
    PIN["${key}"]="${value}"
done < "${PIN_FILE}"

TAG="${PIN[UPSTREAM_TAG]:?UPSTREAM_TAG missing}"
BASE_URL="${PIN[UPSTREAM_REPO]:?UPSTREAM_REPO missing}/releases/download/${TAG}"

sha256_of() {
    python3 - "$1" <<'ENDPY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())
ENDPY
}

fetch_one() {
    local platform="$1" asset="$2" expect="$3"
    local url="${BASE_URL}/${asset}"
    local out="${CACHE}/${asset}"

    if [[ -n "${UPSTREAM_DIST_DIR:-}" && -f "${UPSTREAM_DIST_DIR}/${asset}" ]]; then
        echo "== using local dist asset ${UPSTREAM_DIST_DIR}/${asset}" >&2
        cp "${UPSTREAM_DIST_DIR}/${asset}" "${out}"
    elif [[ -f "${out}" && -f "${out}.verified" && "$(cat "${out}.verified")" == "${expect}" ]]; then
        echo "== ${asset}: cached (sha256 ok)" >&2
    else
        echo "== downloading ${url}" >&2
        local ok=0
        for attempt in 1 2 3; do
            rm -f "${out}.incomplete"
            if curl -fsSL --retry 2 --connect-timeout 20 -o "${out}.incomplete" "${url}" 2>/dev/null; then
                ok=1; break
            fi
            echo "  curl attempt ${attempt} failed, falling back to gh release download" >&2
            if command -v gh >/dev/null 2>&1; then
                rm -f "${CACHE}/${asset}"
                if gh release download "${TAG}" -R "${PIN[UPSTREAM_REPO]}" -p "${asset}" -D "${CACHE}"; then
                    ok=1; break
                fi
            fi
        done
        [[ "${ok}" == 1 ]] || { echo "ERROR: download failed for ${asset}" >&2; exit 1; }
        # integrity gate: full read-back + re-hash (guards truncated downloads)
        [[ -f "${out}.incomplete" ]] || [[ -f "${out}" ]] || { echo "ERROR: no file after download" >&2; exit 1; }
        [[ -f "${out}" ]] || mv "${out}.incomplete" "${out}"
        rm -f "${out}.incomplete"
        local actual
        actual="$(sha256_of "${out}")"
        if [[ "${expect}" == REPLACE_WITH_UPSTREAM_SHA256 || -z "${expect}" ]]; then
            echo "WARNING: no pinned sha256 for ${platform} — recording observed value" >&2
            echo "  observed sha256: ${actual}" >&2
            echo "  (pin it in UPSTREAM before submitting)" >&2
        elif [[ "${actual}" != "${expect}" ]]; then
            echo "ERROR: sha256 mismatch for ${asset}" >&2
            echo "  expected: ${expect}" >&2
            echo "  actual:   ${actual}" >&2
            exit 1
        fi
        printf '%s' "${actual}" > "${out}.verified"
    fi
    printf '%s\n' "${out}"
}

X64_ASSET="${PIN[ASSET_x86_64]:?}"
A64_ASSET="${PIN[ASSET_aarch64]:?}"

X64_FILE=$(fetch_one x86_64 "${X64_ASSET}" "${PIN[SHA256_x86_64]:-}")
A64_FILE=$(fetch_one aarch64 "${A64_ASSET}" "${PIN[SHA256_aarch64]:-}")

echo "FETCHED_X64=${X64_FILE}"
echo "FETCHED_A64=${A64_FILE}"

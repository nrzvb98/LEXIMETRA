#!/usr/bin/env bash
set -euo pipefail

FFMPEG_VERSION="${FFMPEG_VERSION:-8.0.1}"
TARGET_ARCH="${TARGET_ARCH:-arm64}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_ROOT="${ROOT_DIR}/build/ffmpeg/ffmpeg-${FFMPEG_VERSION}-${TARGET_ARCH}"
SOURCE_URL="https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"
SOURCE_ARCHIVE="${BUILD_ROOT}/ffmpeg-${FFMPEG_VERSION}.tar.xz"
SOURCE_DIR="${BUILD_ROOT}/src/ffmpeg-${FFMPEG_VERSION}"
PREFIX="${FFMPEG_PREFIX:-${BUILD_ROOT}/install}"
LICENSE_DIR="${PREFIX}/licenses/ffmpeg"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "This FFmpeg build script must be run on macOS." >&2
    exit 1
fi

if [[ "${TARGET_ARCH}" != "arm64" && "${TARGET_ARCH}" != "x86_64" ]]; then
    echo "Unsupported FFmpeg target architecture: ${TARGET_ARCH}" >&2
    echo "Supported values: arm64, x86_64" >&2
    exit 1
fi

if [[ "${HALA_REBUILD_FFMPEG:-0}" == "1" ]]; then
    rm -rf "${BUILD_ROOT}"
fi

mkdir -p "${BUILD_ROOT}" "${PREFIX}"

download_source() {
    if [[ -f "${SOURCE_ARCHIVE}" ]]; then
        return
    fi

    echo "Downloading FFmpeg ${FFMPEG_VERSION} source..."
    curl --fail --location --retry 3 --output "${SOURCE_ARCHIVE}" "${SOURCE_URL}"
}

extract_source() {
    if [[ -d "${SOURCE_DIR}" ]]; then
        return
    fi

    mkdir -p "${BUILD_ROOT}/src"
    tar -xJf "${SOURCE_ARCHIVE}" -C "${BUILD_ROOT}/src"
}

assert_binary_ok() {
    local binary="$1"
    local version_output

    if [[ ! -x "${binary}" ]]; then
        echo "Expected executable FFmpeg binary missing: ${binary}" >&2
        exit 1
    fi

    if ! file "${binary}" | grep -q "${TARGET_ARCH}"; then
        file "${binary}" >&2
        echo "Expected ${binary} to be a ${TARGET_ARCH} binary." >&2
        exit 1
    fi

    if otool -L "${binary}" | grep -Eq "/opt/homebrew|/usr/local/(Cellar|opt|lib)"; then
        otool -L "${binary}" >&2
        echo "Bundled FFmpeg must not depend on Homebrew libraries." >&2
        exit 1
    fi

    version_output="$("${binary}" -version)"
    if grep -Eq -- "--enable-(gpl|nonfree)" <<<"${version_output}"; then
        echo "${version_output}" >&2
        echo "Bundled FFmpeg must not be configured with GPL or nonfree flags." >&2
        exit 1
    fi
}

write_license_files() {
    mkdir -p "${LICENSE_DIR}"
    cp "${SOURCE_DIR}/LICENSE.md" "${LICENSE_DIR}/"
    cp "${SOURCE_DIR}/COPYING.LGPLv2.1" "${LICENSE_DIR}/"
    cp "${SOURCE_DIR}/COPYING.LGPLv3" "${LICENSE_DIR}/"
    "${PREFIX}/bin/ffmpeg" -version > "${LICENSE_DIR}/ffmpeg-version.txt"
    cat > "${LICENSE_DIR}/README.md" <<EOF
# Bundled FFmpeg

HALA RT bundles FFmpeg ${FFMPEG_VERSION} for local audio decoding in the
packaged macOS app. This build is configured without GPL or nonfree flags.

This notice is provided for engineering compliance hygiene and is not legal
advice. See LICENSE.md and the LGPL license files in this directory.
EOF
}

if [[ -x "${PREFIX}/bin/ffmpeg" && -x "${PREFIX}/bin/ffprobe" ]]; then
    assert_binary_ok "${PREFIX}/bin/ffmpeg"
    assert_binary_ok "${PREFIX}/bin/ffprobe"
    write_license_files
    echo "Using existing FFmpeg build: ${PREFIX}"
    exit 0
fi

download_source
extract_source

echo "Configuring FFmpeg ${FFMPEG_VERSION}..."
cd "${SOURCE_DIR}"

CONFIGURE_FLAGS=(
    --prefix="${PREFIX}"
    --arch="${TARGET_ARCH}"
    --target-os=darwin
    --cc=clang
    --extra-cflags="-arch ${TARGET_ARCH} -mmacosx-version-min=11.0"
    --extra-ldflags="-arch ${TARGET_ARCH} -mmacosx-version-min=11.0"
    --enable-static
    --disable-shared
    --disable-autodetect
    --disable-network
    --disable-doc
    --disable-debug
    --disable-ffplay
    --disable-devices
    --disable-avdevice
)
if [[ "${TARGET_ARCH}" == "x86_64" ]]; then
    CONFIGURE_FLAGS+=(--disable-x86asm)
fi

export PKG_CONFIG=false
./configure "${CONFIGURE_FLAGS[@]}"

if grep -Eq -- "--enable-(gpl|nonfree)" config.h ffbuild/config.log 2>/dev/null; then
    echo "FFmpeg configure unexpectedly enabled GPL or nonfree flags." >&2
    exit 1
fi

echo "Building FFmpeg ${FFMPEG_VERSION}..."
BUILD_JOBS="${HALA_BUILD_JOBS:-}"
if [[ -z "${BUILD_JOBS}" ]]; then
    BUILD_JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
fi
if ! [[ "${BUILD_JOBS}" =~ ^[1-9][0-9]*$ ]]; then
    BUILD_JOBS="4"
fi
make -j "${BUILD_JOBS}"
make install

assert_binary_ok "${PREFIX}/bin/ffmpeg"
assert_binary_ok "${PREFIX}/bin/ffprobe"
write_license_files

echo "Built FFmpeg: ${PREFIX}"

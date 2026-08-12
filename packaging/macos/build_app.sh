#!/usr/bin/env bash
set -euo pipefail

APP_NAME="HALA RT"
BUNDLE_IDENTIFIER="com.nrzvb98.halart"
TARGET_ARCH="${TARGET_ARCH:-arm64}"
FFMPEG_VERSION="${FFMPEG_VERSION:-8.0.1}"
HALA_BUNDLE_FFMPEG="${HALA_BUNDLE_FFMPEG:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_VENV_DIR="${ROOT_DIR}/.venv"
if [[ "${TARGET_ARCH}" != "arm64" ]]; then
    DEFAULT_VENV_DIR="${ROOT_DIR}/.venv-${TARGET_ARCH}"
fi
VENV_PYTHON="${VENV_PYTHON:-${DEFAULT_VENV_DIR}/bin/python}"
FFMPEG_PREFIX="${FFMPEG_PREFIX:-${ROOT_DIR}/build/ffmpeg/ffmpeg-${FFMPEG_VERSION}-${TARGET_ARCH}/install}"

cd "${ROOT_DIR}"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "This build script must be run on macOS." >&2
    exit 1
fi

if [[ "${TARGET_ARCH}" != "arm64" && "${TARGET_ARCH}" != "x86_64" ]]; then
    echo "Unsupported target architecture: ${TARGET_ARCH}" >&2
    echo "Supported values: arm64, x86_64" >&2
    exit 1
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Python virtualenv not found at ${VENV_PYTHON}" >&2
    echo "Create it and install the project first, then rerun this script." >&2
    exit 1
fi

PYTHON_ARCH="$(file "${VENV_PYTHON}")"
if ! grep -q "${TARGET_ARCH}" <<<"${PYTHON_ARCH}"; then
    echo "Virtualenv Python architecture does not match TARGET_ARCH=${TARGET_ARCH}:" >&2
    echo "${PYTHON_ARCH}" >&2
    exit 1
fi

PYTHON_CMD=("${VENV_PYTHON}")
if [[ "${TARGET_ARCH}" == "x86_64" && "$(uname -m)" == "arm64" ]]; then
    PYTHON_CMD=(arch -x86_64 "${VENV_PYTHON}")
fi

PYTHON_MACHINE="$("${PYTHON_CMD[@]}" -c 'import platform; print(platform.machine())')"
if [[ "${PYTHON_MACHINE}" != "${TARGET_ARCH}" ]]; then
    echo "Virtualenv Python runs as ${PYTHON_MACHINE}, expected ${TARGET_ARCH}." >&2
    echo "Use a ${TARGET_ARCH} Python environment or run with Rosetta when targeting x86_64." >&2
    exit 1
fi

if ! "${PYTHON_CMD[@]}" -m PyInstaller --version >/dev/null 2>&1; then
    echo "PyInstaller is not installed in ${VENV_PYTHON}." >&2
    echo "Install it with: ${VENV_PYTHON} -m pip install pyinstaller" >&2
    exit 1
fi

VERSION="$("${PYTHON_CMD[@]}" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
ZIP_NAME="HALA_RT_${VERSION}_macos_${TARGET_ARCH}.zip"
BUILD_DIR="${ROOT_DIR}/build/macos/${TARGET_ARCH}"
DIST_DIR="${ROOT_DIR}/dist"
APP_PATH="${DIST_DIR}/${APP_NAME}.app"
RAW_DIST_PATH="${DIST_DIR}/${APP_NAME}"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"
LAUNCHER="${SCRIPT_DIR}/hala_rt_launcher.py"
APP_RESOURCES_DIR="${APP_PATH}/Contents/Resources"
APP_ICON="${SCRIPT_DIR}/icons/hala-rt-icon.icns"

echo "Building ${APP_NAME} ${VERSION} for macOS ${TARGET_ARCH}..."

rm -rf "${BUILD_DIR}" "${APP_PATH}" "${RAW_DIST_PATH}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"
export PYINSTALLER_CONFIG_DIR="${BUILD_DIR}/pyinstaller_config"

"${PYTHON_CMD[@]}" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name "${APP_NAME}" \
    --icon "${APP_ICON}" \
    --target-arch "${TARGET_ARCH}" \
    --osx-bundle-identifier "${BUNDLE_IDENTIFIER}" \
    --paths "${ROOT_DIR}/src" \
    --workpath "${BUILD_DIR}/work" \
    --specpath "${BUILD_DIR}/spec" \
    --distpath "${DIST_DIR}" \
    --collect-data "_soundfile_data" \
    --collect-binaries "_soundfile_data" \
    --collect-data "_sounddevice_data" \
    --collect-binaries "_sounddevice_data" \
    "${LAUNCHER}"

if [[ ! -d "${APP_PATH}" ]]; then
    echo "Expected app bundle was not created: ${APP_PATH}" >&2
    exit 1
fi

rm -rf "${RAW_DIST_PATH}"

INFO_PLIST="${APP_PATH}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VERSION}" "${INFO_PLIST}"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${VERSION}" "${INFO_PLIST}" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string ${VERSION}" "${INFO_PLIST}"

if [[ "${HALA_BUNDLE_FFMPEG}" != "0" ]]; then
    echo "Building or reusing bundled FFmpeg ${FFMPEG_VERSION}..."
    FFMPEG_VERSION="${FFMPEG_VERSION}" \
        TARGET_ARCH="${TARGET_ARCH}" \
        FFMPEG_PREFIX="${FFMPEG_PREFIX}" \
        "${SCRIPT_DIR}/build_ffmpeg.sh"

    BUNDLED_BIN_DIR="${APP_RESOURCES_DIR}/bin"
    BUNDLED_LICENSE_DIR="${APP_RESOURCES_DIR}/licenses"
    mkdir -p "${BUNDLED_BIN_DIR}" "${BUNDLED_LICENSE_DIR}"

    install -m 755 "${FFMPEG_PREFIX}/bin/ffmpeg" "${BUNDLED_BIN_DIR}/ffmpeg"
    install -m 755 "${FFMPEG_PREFIX}/bin/ffprobe" "${BUNDLED_BIN_DIR}/ffprobe"
    rm -rf "${BUNDLED_LICENSE_DIR}/ffmpeg"
    cp -R "${FFMPEG_PREFIX}/licenses/ffmpeg" "${BUNDLED_LICENSE_DIR}/ffmpeg"

    file "${BUNDLED_BIN_DIR}/ffmpeg"
    file "${BUNDLED_BIN_DIR}/ffprobe"
    if otool -L "${BUNDLED_BIN_DIR}/ffmpeg" "${BUNDLED_BIN_DIR}/ffprobe" | grep -Eq "/opt/homebrew|/usr/local/(Cellar|opt|lib)"; then
        echo "Bundled FFmpeg binaries must not depend on Homebrew libraries." >&2
        exit 1
    fi
    if "${BUNDLED_BIN_DIR}/ffmpeg" -version | grep -Eq -- "--enable-(gpl|nonfree)"; then
        echo "Bundled FFmpeg must not be configured with GPL or nonfree flags." >&2
        exit 1
    fi

    codesign --force --sign - "${BUNDLED_BIN_DIR}/ffmpeg"
    codesign --force --sign - "${BUNDLED_BIN_DIR}/ffprobe"
else
    echo "Skipping bundled FFmpeg because HALA_BUNDLE_FFMPEG=0."
fi

echo "Ad-hoc signing app bundle..."
codesign --force --deep --sign - "${APP_PATH}"
codesign --verify --deep --strict "${APP_PATH}"

echo "Creating distributable archive..."
ditto -c -k --sequesterRsrc --keepParent "${APP_PATH}" "${ZIP_PATH}"

echo "Built app: ${APP_PATH}"
echo "Built archive: ${ZIP_PATH}"

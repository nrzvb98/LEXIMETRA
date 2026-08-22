#!/usr/bin/env bash
set -euo pipefail

APP_NAME="LEXIMETRA"
BUNDLE_IDENTIFIER="com.nrzvb98.leximetra"
TARGET_ARCH="${TARGET_ARCH:-arm64}"
FFMPEG_VERSION="${FFMPEG_VERSION:-8.0.1}"
LEXIMETRA_BUNDLE_FFMPEG="${LEXIMETRA_BUNDLE_FFMPEG:-1}"

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

# Automatic analysis is optional. It needs torch, for which there are no macOS
# x86_64 wheels at the versions this pipeline pins, so an Intel build ships
# without it and the app reports the capability as unavailable.
if "${PYTHON_CMD[@]}" -c 'import torch' >/dev/null 2>&1; then
    BUNDLE_PROCESSING=1
    echo "Automatic analysis: bundling (torch found)."
else
    BUNDLE_PROCESSING=0
    echo "Automatic analysis: NOT bundled (torch is not installed in ${VENV_PYTHON})."
    echo "  The app will still build and run; trials must be cut manually."
    echo "  To include it: ${VENV_PYTHON} -m pip install -e \".[processing]\""
fi

if [[ "${BUNDLE_PROCESSING}" == "1" && ! -f "${ROOT_DIR}/src/leximetra/processing/silero/hubconf.py" ]]; then
    echo "Silero VAD is not vendored, so the packaged app would try to download" >&2
    echo "it from GitHub on first run." >&2
    echo "Vendor it with: ${VENV_PYTHON} tools/vendor_silero.py --apply" >&2
    exit 1
fi

VERSION="$("${PYTHON_CMD[@]}" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
ZIP_NAME="LEXIMETRA_${VERSION}_macos_${TARGET_ARCH}.zip"
BUILD_DIR="${ROOT_DIR}/build/macos/${TARGET_ARCH}"
DIST_DIR="${ROOT_DIR}/dist"
APP_PATH="${DIST_DIR}/${APP_NAME}.app"
RAW_DIST_PATH="${DIST_DIR}/${APP_NAME}"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"
LAUNCHER="${SCRIPT_DIR}/leximetra_launcher.py"
APP_RESOURCES_DIR="${APP_PATH}/Contents/Resources"
APP_ICON="${SCRIPT_DIR}/icons/leximetra-icon.icns"

echo "Building ${APP_NAME} ${VERSION} for macOS ${TARGET_ARCH}..."

rm -rf "${BUILD_DIR}" "${APP_PATH}" "${RAW_DIST_PATH}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"
export PYINSTALLER_CONFIG_DIR="${BUILD_DIR}/pyinstaller_config"

PROCESSING_ARGS=()
if [[ "${BUNDLE_PROCESSING}" == "1" ]]; then
    PROCESSING_SRC="${ROOT_DIR}/src/leximetra/processing"
    PROCESSING_ARGS=(
        --collect-all "torch"
        # Silero's utils_vad.py imports torchaudio and packaging, but it ships
        # as data (torch.hub loads it by path), so PyInstaller never scans it
        # for imports. Without these the app builds and then fails at analysis.
        --collect-all "torchaudio"
        --hidden-import "packaging.version"
        --add-data "${PROCESSING_SRC}/templates:leximetra/processing/templates"
        --add-data "${PROCESSING_SRC}/silero:leximetra/processing/silero"
        --add-data "${PROCESSING_SRC}/VERSION:leximetra/processing"
    )
fi

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
    "${PROCESSING_ARGS[@]}" \
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

if [[ "${LEXIMETRA_BUNDLE_FFMPEG}" != "0" ]]; then
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
    echo "Skipping bundled FFmpeg because LEXIMETRA_BUNDLE_FFMPEG=0."
fi

if [[ "${BUNDLE_PROCESSING}" == "1" ]]; then
    # torch ships C++ headers and unit tests that are never used at runtime --
    # roughly 70 MB of an archive users have to download. Pruned here rather
    # than with --exclude-module: these are data, not modules, and excluding
    # torch submodules risks import errors at runtime.
    #
    # torch/bin is deliberately NOT pruned: torch/__init__.py resolves
    # torch_shm_manager there while importing, so removing it breaks every
    # analysis with a RuntimeError. The self-test below exists to catch
    # exactly this.
    echo "Pruning bundled torch..."
    SIZE_BEFORE="$(du -sm "${APP_PATH}" | cut -f1)"
    # Each of these exists twice: real in one of Resources/Frameworks and a
    # symlink in the other. Both paths must go -- deleting only the real one
    # leaves a dangling symlink, and codesign --deep rejects the bundle with a
    # bare "No such file or directory".
    for relative in "torch/include" "torch/test"; do
        for root in "${APP_RESOURCES_DIR}" "${APP_PATH}/Contents/Frameworks"; do
            target="${root}/${relative}"
            if [[ -e "${target}" || -L "${target}" ]]; then
                rm -rf "${target}"
            fi
        done
    done
    if find "${APP_PATH}" -type l ! -exec test -e {} \; -print | grep -q .; then
        echo "Pruning left dangling symlinks in the bundle:" >&2
        find "${APP_PATH}" -type l ! -exec test -e {} \; -print >&2
        exit 1
    fi
    SIZE_AFTER="$(du -sm "${APP_PATH}" | cut -f1)"
    echo "  ${SIZE_BEFORE} MB -> ${SIZE_AFTER} MB"
fi

echo "Ad-hoc signing app bundle..."
codesign --force --deep --sign - "${APP_PATH}"
codesign --verify --deep --strict "${APP_PATH}"

if [[ "${BUNDLE_PROCESSING}" == "1" ]]; then
    # Run the packaged binary and make it import the pipeline and load the VAD
    # model for real. Bundling fails in ways the source tests cannot see, and
    # every one of them otherwise surfaces the first time a user loads a
    # recording.
    echo "Self-testing the packaged app..."
    if ! PYTHONUNBUFFERED=1 LEXIMETRA_SELF_TEST=1 "${APP_PATH}/Contents/MacOS/${APP_NAME}" 2>&1 | grep -q "^SELF-TEST OK"; then
        echo "The packaged app cannot run an analysis. Output:" >&2
        PYTHONUNBUFFERED=1 LEXIMETRA_SELF_TEST=1 "${APP_PATH}/Contents/MacOS/${APP_NAME}" 2>&1 | tail -20 >&2
        exit 1
    fi
    echo "  OK"
fi

echo "Creating distributable archive..."
ditto -c -k --sequesterRsrc --keepParent "${APP_PATH}" "${ZIP_PATH}"

echo "Built app: ${APP_PATH} ($(du -sh "${APP_PATH}" | cut -f1))"
echo "Built archive: ${ZIP_PATH} ($(du -sh "${ZIP_PATH}" | cut -f1))"
if [[ "${BUNDLE_PROCESSING}" == "1" ]]; then
    echo "Automatic analysis is bundled (Silero VAD included; no network needed)."
else
    echo "Automatic analysis is NOT bundled; trials must be cut manually."
fi

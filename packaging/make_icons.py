"""Build the platform icon files from the LEXIMETRA source artwork.

The source PNG is a rounded square painted edge to edge on an opaque black
canvas, so its corners are black rather than transparent -- dropped into a Dock
or a taskbar as-is, it shows four black wedges. This script cuts the artwork out
against transparency and lays it out the way each platform expects:

* macOS wants the mark on the Big Sur grid -- 824x824 of artwork centred in a
  1024x1024 canvas, corner radius 185 -- so it sits at the same visual size as
  every other icon in the Dock.
* Windows wants it edge to edge, keeping the source's own corner radius.

Run it after changing the artwork:

    .venv/bin/python packaging/make_icons.py
"""

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter, QPainterPath

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packaging/icons/leximetra-icon-source.png"
MACOS_ICONS = ROOT / "packaging/macos/icons"
WINDOWS_ICONS = ROOT / "packaging/windows/icons"

# macOS Big Sur grid: artwork inset in the canvas, Apple's corner radius.
MACOS_CANVAS = 1024
MACOS_ARTWORK = 824
MACOS_RADIUS = 185

# Windows icons run edge to edge; keep the radius the artwork was drawn with.
WINDOWS_CANVAS = 1024
WINDOWS_RADIUS = 200

ICNS_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def downscale(image: QImage, size: int) -> QImage:
    """Halve repeatedly before the final step.

    A single smooth scale from 1024 to 16 samples too sparsely and turns the
    wordmark into grey mush; halving keeps every pixel contributing.
    """
    current = image
    while current.width() // 2 > size:
        current = current.scaled(
            current.width() // 2,
            current.height() // 2,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return current.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def compose(source: QImage, canvas: int, artwork: int, radius: float) -> QImage:
    """Place the artwork on transparency and round off the corners."""
    scaled = downscale(source, artwork)

    out = QImage(canvas, canvas, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)

    offset = (canvas - artwork) / 2
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # Clip to the rounded square, so the source's black corners never land.
    path = QPainterPath()
    path.addRoundedRect(offset, offset, artwork, artwork, radius, radius)
    painter.setClipPath(path)
    painter.drawImage(int(offset), int(offset), scaled)
    painter.end()
    return out


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(master: QImage, path: Path) -> None:
    """Pack PNG-compressed frames into an .ico (Vista and later read these)."""
    frames = [png_bytes(downscale(master, size)) for size in ICO_SIZES]

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, payload = [], []
    for size, data in zip(ICO_SIZES, frames):
        dimension = 0 if size >= 256 else size  # 0 means 256 in the directory
        entries.append(
            struct.pack(
                "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
            )
        )
        payload.append(data)
        offset += len(data)

    path.write_bytes(header + b"".join(entries) + b"".join(payload))


def write_icns(master: QImage, path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "leximetra.iconset"
        iconset.mkdir()
        for name, size in ICNS_SIZES:
            downscale(master, size).save(str(iconset / name), "PNG")
        subprocess.run(
            ["iconutil", "--convert", "icns", "--output", str(path), str(iconset)],
            check=True,
        )


def main() -> int:
    if not SOURCE.is_file():
        print(f"Source artwork not found: {SOURCE}")
        return 1

    source = QImage(str(SOURCE))
    if source.isNull():
        print(f"Could not read {SOURCE}")
        return 1

    MACOS_ICONS.mkdir(parents=True, exist_ok=True)
    WINDOWS_ICONS.mkdir(parents=True, exist_ok=True)

    macos_master = compose(source, MACOS_CANVAS, MACOS_ARTWORK, MACOS_RADIUS)
    macos_png = MACOS_ICONS / "leximetra-icon.png"
    macos_master.save(str(macos_png), "PNG")
    print(f"wrote {macos_png.relative_to(ROOT)}")

    icns = MACOS_ICONS / "leximetra-icon.icns"
    write_icns(macos_master, icns)
    print(f"wrote {icns.relative_to(ROOT)}")

    windows_master = compose(source, WINDOWS_CANVAS, WINDOWS_CANVAS, WINDOWS_RADIUS)
    ico = WINDOWS_ICONS / "leximetra-icon.ico"
    write_ico(windows_master, ico)
    print(f"wrote {ico.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

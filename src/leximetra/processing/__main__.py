"""CLI: python -m leximetra.processing INPUT.wav [-o OUTDIR] [--config cfg.json]"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import LeximetraConfig
from .pipeline import process_audio


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="leximetra.processing",
        description="HALA reaction-time pipeline: audio in, per-trial RT/hesitation CSVs out.",
    )
    parser.add_argument("input", nargs="?", help="Audio file (.wav/.m4a/.mp3/.flac)")
    parser.add_argument("-o", "--output-dir", default=".",
                        help="Directory for CSVs and HALA_Slices/ (default: current directory)")
    parser.add_argument("--config", help="JSON config file (see --dump-config)")
    parser.add_argument("--dump-config", action="store_true",
                        help="Print the default configuration as JSON and exit")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only warnings and errors")
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-candidate detection detail")
    args = parser.parse_args(argv)

    if args.dump_config:
        print(LeximetraConfig().to_json())
        return 0
    if not args.input:
        parser.error("input audio file is required (or use --dump-config)")

    level = logging.WARNING if args.quiet else (logging.DEBUG if args.verbose else logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")

    cfg = LeximetraConfig.from_json(args.config) if args.config else LeximetraConfig()
    result = process_audio(args.input, cfg, output_dir=args.output_dir)

    if not args.quiet:
        print(f"\n{len(result.df_full)} trials processed.")
        for kind, path in result.csv_paths.items():
            print(f"  {kind}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

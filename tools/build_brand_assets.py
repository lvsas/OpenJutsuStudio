"""Derive static studio favicons from the canonical lime landing G.

Run with Python; --output-dir allows a byte-for-byte regeneration check without
modifying shipped assets. No app imports, image libraries or runtime templating.
"""
import argparse
from pathlib import Path


BRAND = Path(__file__).resolve().parents[1] / "src/static/brand"
ACCENTS = {
    "favicon.svg": "#d8ff3e",
    "favicon-ltx.svg": "#22d3ee",
    "favicon-h3.svg": "#ff4f2e",
    "favicon-timeline.svg": "#bc5cff",
}


def build(output_dir: Path) -> None:
    master = (BRAND / "favicon.svg").read_bytes()
    token = b'stroke="#d8ff3e"'
    if master.count(token) != 1:
        raise ValueError("Canonical master must contain exactly one lime G stroke")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, accent in ACCENTS.items():
        content = master.replace(token, f'stroke="{accent}"'.encode("ascii"))
        target = output_dir / name
        if not target.exists() or target.read_bytes() != content:
            target.write_bytes(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=BRAND)
    build(parser.parse_args().output_dir)

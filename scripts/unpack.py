"""Extract the kits:  uv run python scripts/unpack.py [--password PW]   ->  data/<kit-name>/"""

import argparse
import getpass
from pathlib import Path

import py7zr

root = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--password")
password = ap.parse_args().password or getpass.getpass("Kit password: ")

for archive in sorted(root.glob("*.7z")):
    dest = root / "data" / archive.stem
    with py7zr.SevenZipFile(archive, mode="r", password=password) as z:
        z.extractall(path=dest)
    print(f"\n{archive.name} -> {dest.relative_to(root)}")
    for f in sorted(p for p in dest.rglob("*") if p.is_file()):
        print(f"  {f.relative_to(dest)}")

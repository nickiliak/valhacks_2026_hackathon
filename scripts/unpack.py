"""Extract the training kit:  uv run python scripts/unpack.py [--password PW]
.py files -> scripts/, everything else (e.g. train.csv) -> data/
"""

import argparse
import getpass
import shutil
import tempfile
from pathlib import Path

import py7zr

root = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--password")
password = ap.parse_args().password or getpass.getpass("Kit password: ")

archive = root / "challenge_files" / "train-template-kit.7z"
with tempfile.TemporaryDirectory() as tmp:
    with py7zr.SevenZipFile(archive, mode="r", password=password) as z:
        z.extractall(path=tmp)
    for src in sorted(p for p in Path(tmp).rglob("*") if p.is_file()):
        dest = root / ("scripts" if src.suffix == ".py" else "data") / src.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(src, dest)
        print(f"{src.name} -> {dest.relative_to(root)}")

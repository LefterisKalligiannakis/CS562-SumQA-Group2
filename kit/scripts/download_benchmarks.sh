#!/usr/bin/env bash
# QALD-9-plus and LC-QuAD 1.0 are already in data/benchmarks/raw. This script adds DBLP-QuAD
# from the original Zenodo archive and then converts all benchmarks.
#   bash scripts/download_benchmarks.sh
set -euo pipefail
RAW=data/benchmarks/raw
mkdir -p $RAW/dblp_quad
python - <<'PY'
import io
import json
from pathlib import Path
from zipfile import ZipFile

import requests

# This is the archive used by awalesushil/DBLP-QuAD's Hugging Face loader.
# Fetch the JSON directly: recent datasets versions no longer run dataset scripts.
url = "https://zenodo.org/records/7643971/files/DBLP-QuAD.zip"
response = requests.get(url, timeout=60)
response.raise_for_status()
with ZipFile(io.BytesIO(response.content)) as archive:
    for split in ("train", "valid", "test"):
        with archive.open(f"DBLP-QuAD/{split}/questions.json") as source:
            rows = json.load(source)["questions"]
        target = Path(f"data/benchmarks/raw/dblp_quad/{split}.json")
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(rows, output, ensure_ascii=False)
        temporary.replace(target)
        print(split, len(rows), "fields:", sorted(rows[0]) if rows else [])
PY
python -m sumqa.prepare_benchmarks --raw $RAW --out data/benchmarks

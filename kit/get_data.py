"""Download the data of HY562 Project B, SumQA (data update of November 2026).

    python get_data.py check                       # 1 minute: can you reach every source?
    python get_data.py projectB                    # ORKG + SciQA (about 15 MB) and dblp 2022-08 (2.8 GB)

Run it in the `kit` folder of your project. Standard library only (Python 3.9+): it runs in the
course container and directly on Windows, macOS or Linux. Interrupted downloads resume when you
run the same command again. Every file is checked against its published MD5 where one exists,
and MANIFEST.tsv records source, size and MD5 of every file.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

UA = "Mozilla/5.0 (X11; Linux x86_64) HY562-course-downloader/1.1"

# Project A: dblp monthly RDF releases, Schloss Dagstuhl DROPS, CC0 1.0
# https://drops.dagstuhl.de/entities/collection/10.4230/dblp.rdf.ntriples
DBLP_RELEASES = [
    ("dblp-2026-09-01.nt.gz", "https://drops.dagstuhl.de/storage/artifacts/dblp/rdf/2026/dblp-2026-09-01.nt.gz",
     "45c45d890f0ad9e725a7c867de85c5f3"),
    ("dblp-2026-10-03.nt.gz", "https://drops.dagstuhl.de/storage/artifacts/dblp/rdf/2026/dblp-2026-10-03.nt.gz",
     "2dcbef45683cf695ccc693fd2a1d297f"),
    ("dblp-2026-11-01.nt.gz", "https://drops.dagstuhl.de/storage/artifacts/dblp/rdf/2026/dblp-2026-11-01.nt.gz",
     "04a344210b309ca5a175b9fc3d9b5cde"),
]

# Project B: SciQA benchmark and the ORKG RDF dump it was built on (Zenodo 10.5281/zenodo.7744048, CC BY 4.0)
SCIQA_ZIP = ("SciQA-dataset.zip", "https://zenodo.org/records/7744048/files/SciQA-dataset.zip?download=1",
             "efe2c09d9affb0e3cb0202e645eb7a28")
ORKG_ZIP = ("orkg-rdf-dump-2023-02-14.zip",
            "https://zenodo.org/records/7744048/files/ORKG%20RDF%20dump%2014.02.2023.zip?download=1",
            "ec4240d33906c44fd40bf3402f0ff20e")
# dblp dump of 2022-08-01, the KG of DBLP-QuAD (Zenodo 10.5281/zenodo.7638511, CC BY 4.0)
DBLP2022 = ("dblp.nt.gz", "https://zenodo.org/records/7638511/files/dblp.nt.gz?download=1", None)


def _req(url, headers=None, timeout=60):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)


def probe(url):
    try:
        with _req(url, headers={"Range": "bytes=0-0"}, timeout=25) as r:
            cr = r.headers.get("Content-Range", "")
            size = int(cr.rsplit("/", 1)[1]) if "/" in cr and cr.rsplit("/", 1)[1].isdigit() else None
            return True, r.status, size
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:70]}", None


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, path, retries=6):
    part = path + ".part"
    for attempt in range(1, retries + 1):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        try:
            with _req(url, headers={"Range": f"bytes={have}-"} if have else {}, timeout=120) as r:
                if have and r.status != 206:
                    have = 0
                total = None
                cr = r.headers.get("Content-Range", "")
                if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
                    total = int(cr.rsplit("/", 1)[1])
                elif r.headers.get("Content-Length", "").isdigit():
                    total = int(r.headers["Content-Length"]) + have
                t0, done, last = time.time(), have, 0.0
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if time.time() - last > 2:
                            last = time.time()
                            pct = f"{100 * done / total:5.1f}%" if total else ""
                            mbs = (done - have) / max(1e-6, time.time() - t0) / 1e6
                            print(f"\r      {done / 1e9:6.2f} GB {pct} {mbs:5.1f} MB/s", end="", flush=True)
                print()
            if total and os.path.getsize(part) < total:
                raise IOError(f"incomplete: {os.path.getsize(part)} of {total} bytes (will resume)")
            os.replace(part, path)
            return
        except Exception as e:
            print(f"\n      attempt {attempt} failed: {type(e).__name__}: {str(e)[:120]}")
            if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404, 410):
                break
            time.sleep(min(60, 5 * attempt))
    raise IOError(f"could not download {url}")


def fetch(name, url, digest, folder, manifest):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        print(f"  {name} <- {url}")
        try:
            download(url, path)
        except IOError as e:
            print(f"  FAILED: {e}")
            return None
    else:
        print(f"  have {path}")
    print(f"  checking MD5 of {name} ...", flush=True)
    got = md5(path)
    if digest and got != digest:
        print(f"  MD5 MISMATCH for {name}: the file was removed, run the command again")
        os.remove(path)
        return None
    manifest.append((path, url, os.path.getsize(path), got))
    return path


def write_manifest(folder, manifest, ok):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "MANIFEST.tsv"), "w") as f:
        f.write("file\tsource\tbytes\tmd5\n")
        for row in manifest:
            f.write("\t".join(map(str, row)) + "\n")
    print(f"\n{'ALL FILES OK' if ok else 'SOME FILES FAILED: run the same command again'}; "
          f"manifest: {os.path.join(folder, 'MANIFEST.tsv')}")


def cmd_check():
    tests = [("A dblp release 2026-09-01", DBLP_RELEASES[0][1]),
             ("A dblp release 2026-10-03", DBLP_RELEASES[1][1]),
             ("A dblp release 2026-11-01", DBLP_RELEASES[2][1]),
             ("B SciQA questions (Zenodo)", SCIQA_ZIP[1]),
             ("B ORKG dump (Zenodo)", ORKG_ZIP[1]),
             ("B dblp 2022-08 (Zenodo)", DBLP2022[1]),
             ("B DBLP-QuAD (Hugging Face)", "https://huggingface.co/datasets/awalesushil/DBLP-QuAD/resolve/main/README.md")]
    print(f"python {sys.version.split()[0]}, {time.strftime('%Y-%m-%d %H:%M')}")
    tests = [t for t in tests if t[0].startswith("B ")]
    for name, url in tests:
        ok, status, size = probe(url)
        print(f"[{'OK ' if ok else 'NO '}] {name:30s} {status}" + (f" ({size / 1e6:,.0f} MB)" if size else ""))


def cmd_project_a():
    folder, manifest, ok = os.path.join("data", "dblp", "raw"), [], True
    for name, url, digest in DBLP_RELEASES:
        ok &= fetch(name, url, digest, folder, manifest) is not None
    write_manifest(folder, manifest, ok)
    return ok


def cmd_project_b():
    manifest, ok = [], True
    # ORKG dump -> data/kg/orkg2023/raw/*.nt
    kgdir = os.path.join("data", "kg", "orkg2023", "raw")
    z = fetch(*ORKG_ZIP, kgdir, manifest)
    if z:
        with zipfile.ZipFile(z) as zf:
            for m in zf.infolist():
                if m.is_dir():
                    continue
                target = os.path.join(kgdir, os.path.basename(m.filename).replace(" ", "_"))
                if not os.path.exists(target):
                    with zf.open(m) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                print(f"    unpacked {target} ({os.path.getsize(target) / 1e6:.1f} MB)")
    ok &= z is not None
    # SciQA -> data/benchmarks/raw/sciqa/{train,valid,test}/questions.json
    bdir = os.path.join("data", "benchmarks", "raw")
    z = fetch(*SCIQA_ZIP, bdir, manifest)
    if z:
        with zipfile.ZipFile(z) as zf:
            for m in zf.infolist():
                parts = m.filename.replace("\\", "/").split("/")
                if m.is_dir() or not parts[-1].endswith(".json") or len(parts) < 2:
                    continue
                split = parts[-2]
                target = os.path.join(bdir, "sciqa", split, parts[-1])
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"    unpacked {target}")
    ok &= z is not None
    # dblp 2022-08 -> data/kg/dblp2022/raw/dblp.nt.gz
    ok &= fetch(*DBLP2022, os.path.join("data", "kg", "dblp2022", "raw"), manifest) is not None
    write_manifest(os.path.join("data", "kg"), manifest, ok)
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        cmd_check()
    elif cmd == "projectB":
        sys.exit(0 if cmd_project_b() else 2)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

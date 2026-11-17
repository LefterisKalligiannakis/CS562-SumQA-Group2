# HY562 Project B (SumQA): data update (16 November 2026)

The DBpedia download servers (`downloads.dbpedia.org`, `data.dbpedia.org`) do not respond, and DBpedia has given
no date for when they will be back. Project B therefore replaces DBpedia 2016-10 with the **Open Research
Knowledge Graph (ORKG)** and its benchmark **SciQA**, both published on Zenodo. The second KG, dblp 2022-08 with
DBLP-QuAD, does not change. The research questions, the variants, the grading and the milestones stay the same;
only the data and a few kit files change.

| | Before | Now |
|---|---|---|
| KG 1 | DBpedia 2016-10 with QALD-9-plus and LC-QuAD 1.0 | ORKG dump of 14 Feb 2023 with SciQA (CC BY 4.0) |
| KG 2 | dblp 2022-08 with DBLP-QuAD | unchanged |

## Contents of this folder

| Path | What it is |
|---|---|
| `get_data.py` | Downloads ORKG, SciQA and dblp 2022-08 (`check`, `projectB`); resumes, verifies MD5, writes `MANIFEST.tsv` |
| `kit_patch/sumqa/` | Replace the kit files `common.py`, `prepare_benchmarks.py`, `run.py`, `build_schema.py` (ORKG and SciQA support) |
| `kit_patch/scripts/check_setup.py` | Replaces the kit file (checks ORKG and SciQA) |
| `ANNOUNCEMENT_el.md` | Text for the eLearn announcement |

## Step 0: apply the update to your kit (2 minutes)

Copy `get_data.py` into the `kit` folder of your repository, and copy the files of `kit_patch/` over your `kit`
folder, keeping the sub-folders (`sumqa/`, `scripts/`): they replace the files with the same name. Commit with
the message `data update 2026-11`. Then, in the `kit` folder:

```bash
python get_data.py check
```

All four lines must say `OK`. If one says `NO`, run it again later or from another network; if it still fails,
post the output in the eLearn forum.

## Step 1: download (ORKG and SciQA about 15 MB; dblp 2022-08 is 2.8 GB)

```bash
python get_data.py projectB
```

This writes `data/kg/orkg2023/raw/` (the unpacked ORKG dump), `data/benchmarks/raw/sciqa/{train,valid,test}/`
and `data/kg/dblp2022/raw/dblp.nt.gz`, plus `data/kg/MANIFEST.tsv`. It replaces `bash scripts/download_kgs.sh`
for both KGs. If it stops, run the same command again and it continues from where it stopped.

## Step 2: stores, schema and gold

This replaces steps 4 and 5 of `SETUP.md`:

```bash
# ORKG (a few minutes)
python -m sumqa.kgstore --store data/kg/orkg2023/store data/kg/orkg2023/raw/*.nt
python -m sumqa.kgstats --out data/kg/orkg2023/counts.json --parquet data/kg/orkg2023/parquet "data/kg/orkg2023/raw/*.nt"
python -m sumqa.build_schema --counts data/kg/orkg2023/counts.json --labels-store data/kg/orkg2023/store \
    --out data/kg/orkg2023/schema_elements.jsonl

# dblp 2022-08 (as before; long, run it overnight)
python -m sumqa.kgstore --store data/kg/dblp2022/store data/kg/dblp2022/raw/dblp.nt.gz
python -m sumqa.kgstats --out data/kg/dblp2022/counts.json --parquet data/kg/dblp2022/parquet --driver-memory 8g data/kg/dblp2022/raw/dblp.nt.gz
curl -fL -o data/kg/dblp2022/raw/schema.ttl https://dblp.org/rdf/schema.ttl
python -m sumqa.build_schema --ontology data/kg/dblp2022/raw/schema.ttl --counts data/kg/dblp2022/counts.json \
    --out data/kg/dblp2022/schema_elements.jsonl

# benchmarks and gold answers
export ORKG_ENDPOINT=oxigraph:data/kg/orkg2023/store
export DBLP_ENDPOINT=oxigraph:data/kg/dblp2022/store
bash scripts/download_benchmarks.sh               # adds DBLP-QuAD, then converts SciQA and DBLP-QuAD
python -m sumqa.gold --bench data/benchmarks/sciqa_test.jsonl --endpoint $ORKG_ENDPOINT
python -m sumqa.gold --bench data/benchmarks/dblpquad_test.jsonl --endpoint $DBLP_ENDPOINT
python scripts/check_setup.py
```

Commit `SETUP_REPORT.txt` and `data/kg/MANIFEST.tsv`, and post `MANIFEST.tsv` in the Project B thread of the
forum, so that we can see that all three teams have the same data.

## Notes

- In every command of the project description and the starter notebook, use `--kg orkg2023` with
  `data/benchmarks/sciqa_test.gold.jsonl` where it says `--kg dbpedia2016` with QALD-9-plus or LC-QuAD, and
  `ORKG_ENDPOINT` where it says `DBPEDIA_ENDPOINT`.
- The ORKG names its properties with codes (`orkgp:P31` means "has research contribution"). The new
  `--labels-store` option puts the labels into the schema elements, so the baselines show
  `property orkgp:P31 "has research contribution"`.
- SciQA queries refer to resources through their labels (`rdfs:label`), so for most SciQA questions the list of
  entity IRIs in the prompt is empty. This is the same for all settings and all teams.
- SciQA test has 513 questions. After the gold step, look at `data/benchmarks/sciqa_test.dropped.jsonl`; if
  more than a few dozen questions are dropped, post it in the forum.

## Changes to the project description (CS562_ProjectB_2026)

- Section 4: the two KGs are ORKG (dump of 14 Feb 2023) with SciQA, and dblp 2022-08 with DBLP-QuAD.
  QALD-9-plus and LC-QuAD 1.0 are dropped.
- Section 5 (minimum runs): "QALD-9-plus, LC-QuAD" becomes "SciQA"; the DBLP-QuAD row stays; the ablation runs
  on 40 SciQA questions.
- Team B1: compute the weak and strong summaries on the ORKG first and then on dblp 2022.
- Team B2: the question about `dbp:` infobox properties becomes: what the labels of the opaque ORKG predicate
  codes contribute to accuracy and size (summary with and without labels).
- Reading list: add S. Auer, D. A. C. Barone, C. Bartz, et al. "The SciQA Scientific Question Answering Benchmark
  for Scholarly Knowledge". Scientific Reports 13, 7240 (2023).

## Deadlines

The set-up report (`SETUP_REPORT.txt`) is due one week after this announcement. Checkpoint 2 stays on 30 November.

## Sources

- SciQA and the ORKG dump: https://zenodo.org/records/7744048 (CC BY 4.0)
- dblp 2022-08 (the KG of DBLP-QuAD): https://zenodo.org/records/7638511 (CC BY 4.0)
- DBpedia download outage: https://forum.dbpedia.org/t/ontology-viewer-and-data-download-links-down/4578

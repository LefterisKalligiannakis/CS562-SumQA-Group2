#!/usr/bin/env bash
# Knowledge graphs for Project B. Every team runs this on (at least) one machine; see SETUP.md.
#   bash scripts/download_kgs.sh dbpedia     # about 1.1 GB compressed
#   bash scripts/download_kgs.sh dblp        # about 2.8 GB compressed
set -euo pipefail
# Keep incomplete downloads separate so a later run does not skip them.
download() {
  local destination="$1" url="$2"
  [ -s "$destination" ] && return 0
  if curl -fL --connect-timeout 15 --retry 3 --retry-connrefused \
      --retry-max-time 120 -o "$destination.part" "$url"; then
    mv -- "$destination.part" "$destination"
  else
    echo "Download failed: $url" >&2
    echo "Check your network/VPN or retry later. The download server may be unavailable." >&2
    echo "For a mirror of the same release, set DBPEDIA_BASE_URL to its 2016-10 directory." >&2
    return 1
  fi
}

case "${1:-}" in
dbpedia)
  # DBpedia 2016-10, the release used by QALD-9 (CC BY-SA 3.0 / GFDL). Files from
  # https://downloads.dbpedia.org/2016-10/core-i18n/en/ and the ontology from /2016-10/
  D=data/kg/dbpedia2016/raw; mkdir -p $D
  R=${DBPEDIA_BASE_URL:-https://downloads.dbpedia.org/2016-10}
  R=${R%/}
  B=$R/core-i18n/en
  for f in instance_types_en.ttl.bz2 instance_types_transitive_en.ttl.bz2 mappingbased_objects_en.ttl.bz2 \
           mappingbased_literals_en.ttl.bz2 labels_en.ttl.bz2 infobox_properties_en.ttl.bz2; do
    download "$D/$f" "$B/$f"
  done
  download "$D/dbpedia_2016-10.nt" "$R/dbpedia_2016-10.nt"
  echo "next: python -m sumqa.kgstore --store data/kg/dbpedia2016/store $D/*.ttl.bz2 $D/dbpedia_2016-10.nt"
  echo "      python -m sumqa.kgstats --out data/kg/dbpedia2016/counts.json --parquet data/kg/dbpedia2016/parquet \"$D/*.ttl.bz2\""
  echo "      python -m sumqa.build_schema --ontology $D/dbpedia_2016-10.nt --counts data/kg/dbpedia2016/counts.json --out data/kg/dbpedia2016/schema_elements.jsonl"
  ;;
dblp)
  # dblp RDF dump of 1 Aug 2022, the KG version of DBLP-QuAD (CC BY 4.0), Zenodo 10.5281/zenodo.7638511
  D=data/kg/dblp2022/raw; mkdir -p $D
  [ -s $D/dblp.nt.gz ] || curl -fL --retry 3 -o $D/dblp.nt.gz "https://zenodo.org/records/7638511/files/dblp.nt.gz?download=1"
  # dblp schema (ontology); check the address on https://dblp.org/rdf/ if this fails
  [ -s $D/schema.ttl ] || curl -fL -H "Accept: text/turtle" -o $D/schema.ttl https://dblp.org/rdf/schema || echo "schema download failed: get it from https://dblp.org/rdf/"
  echo "next: python -m sumqa.kgstore --store data/kg/dblp2022/store $D/dblp.nt.gz"
  echo "      python -m sumqa.kgstats --out data/kg/dblp2022/counts.json --parquet data/kg/dblp2022/parquet --driver-memory 8g $D/dblp.nt.gz"
  echo "      python -m sumqa.build_schema --ontology $D/schema.ttl --counts data/kg/dblp2022/counts.json --out data/kg/dblp2022/schema_elements.jsonl"
  ;;
*) echo "usage: $0 dbpedia|dblp"; exit 1;;
esac

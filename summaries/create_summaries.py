"""Build a SumQA graph summary from a prepared knowledge graph directory."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from pyspark.sql import SparkSession, functions as F

SUMMARIES = Path(__file__).resolve().parents[1]
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


def type_sets(triples):
    resources = triples.where(F.col("okind").isin("iri", "bnode"))
    entities = triples.selectExpr("s as entity").union(resources.selectExpr("o as entity")).distinct()
    types = (triples.where((F.col("p") == RDF_TYPE) & (F.col("okind") == "iri"))
             .groupBy("s").agg(F.sort_array(F.collect_set("o")).alias("classes"))
             .withColumnRenamed("s", "entity"))
    return entities.join(types, "entity", "left").select(
        "entity", F.coalesce("classes", F.array().cast("array<string>")).alias("classes"))


def ancestors(cls, parents):
    seen = set()
    pending = list(parents[cls])
    while pending:
        parent = pending.pop()
        if parent not in seen:
            seen.add(parent)
            pending.extend(parents[parent] - seen)
    return seen


def abstat_members(triples, members):
    parents = defaultdict(set)
    hierarchy = triples.where((F.col("p") == SUBCLASS) & (F.col("okind") == "iri"))
    for child, parent in hierarchy.select("s", "o").distinct().collect():
        parents[child].add(parent)

    # Only class sets and their hierarchy are brought to the driver.
    groups = [r.classes for r in members.select("classes").distinct().collect()]
    above = {c: ancestors(c, parents) for c in {c for group in groups for c in group}}
    mapping = []
    for group in groups:
        # Drop strict ancestors, preserving equally specific classes and cycles.
        minimal = [c for c in group if not any(c in above[d] and d not in above[c] for d in group)]
        mapping.extend((group, [c]) for c in minimal)
        if not group:
            mapping.append(([], []))
    lookup = triples.sparkSession.createDataFrame(mapping, "classes array<string>, node array<string>")
    return members.join(lookup, "classes").selectExpr("entity", "node as classes")


def summarize(triples, method, directory):
    members = type_sets(triples)
    if method == "abstat":
        members = abstat_members(triples, members)
    members = members.cache()
    try:
        sizes = members.groupBy("classes").count().orderBy("classes").collect()
        nodes = [{"id": f"n{i}", "classes": r.classes, "size": r["count"]}
                 for i, r in enumerate(sizes, 1)]
        ids = {tuple(n["classes"]): n["id"] for n in nodes}

        facts = triples.where(~F.col("p").isin(RDF_TYPE, SUBCLASS))
        facts = facts.join(members.selectExpr("entity as s", "classes as src"), "s")
        links = (facts.where(F.col("okind").isin("iri", "bnode"))
                 .join(members.selectExpr("entity as o", "classes as dst"), "o")
                 .groupBy("src", "p", "dst").count().orderBy(F.desc("count"), "p", "src", "dst"))
        literals = (facts.where(F.col("okind") == "literal").groupBy("src", "p", "dt")
                    .count().orderBy(F.desc("count"), "p", "src", "dt"))

        edges = [{"source": ids[tuple(r.src)], "property": r.p, "target": ids[tuple(r.dst)], "count": r["count"]}
                 for r in links.collect()]
        attributes = [{"node": ids[tuple(r.src)], "property": r.p, "datatype": r.dt, "count": r["count"]}
                      for r in literals.collect()]
        return {"kg": directory.name, "team": "B2", "kind": method.replace("-", "_"),
                "nodes": nodes, "edges": edges, "attributes": attributes}
    finally:
        members.unpersist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="graph directory containing parquet/")
    parser.add_argument("method", choices=("type-based", "abstat"))
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    parquet = directory / "parquet"
    if not parquet.is_dir():
        parser.error(f"missing input directory: {parquet}")
    method = args.method
    spark = (SparkSession.builder.appName(f"B2-{method}").master("local[2]")
             .config("spark.sql.shuffle.partitions", "200").getOrCreate())
    try:
        start = perf_counter()
        triples = spark.read.parquet(str(parquet))
        summary = summarize(triples, method, directory)
        prefix = {"orkg2023": "orkg", "dblp2022": "dblp"}.get(directory.name, directory.name)
        output = SUMMARIES / f"{prefix}_{summary['kind']}.json"
        with TemporaryDirectory(dir=SUMMARIES) as tmp:
            staged = Path(tmp) / output.name
            staged.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            staged.replace(output)
        print(f"{output}: {len(summary['nodes'])} nodes, {len(summary['edges'])} edges, "
              f"{len(summary['attributes'])} attributes in {perf_counter() - start:.1f}s")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

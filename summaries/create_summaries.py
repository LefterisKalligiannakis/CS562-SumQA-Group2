"""Build a SumQA graph summary from a prepared knowledge graph directory."""

# =====================================================================================================
# COMMENTS ADDED FOR UNDERSTANDING. THE CODE ITSELF IS UNCHANGED.
#
# BIG PICTURE
#   Input : a folder that contains a `parquet/` subfolder with the KG as triples. From the code, its
#           columns are:
#             s      subject
#             p      predicate (property)
#             o      object
#             okind  what the object is: "iri", "bnode" (blank node) or "literal"
#             dt     datatype of the object (only meaningful for literals)
#   Output: one JSON file with a summary of the graph:
#             nodes      groups of entities that have the same type (e.g. "all Papers"), with their size
#             edges      how many triples go from one group to another through a given property
#             attributes how many literal values (text, numbers, ...) a group has for a given property
#
#   The two methods differ only in what a "group" (summary node) is:
#     type-based : the group is the FULL SET of classes of an entity, e.g. {Paper, Resource}.
#                  Every entity is in exactly one node.
#     abstat     : the group is ONE most specific ("minimal") class. Superclasses are dropped, and an
#                  entity with several minimal classes is counted in each of them.
# =====================================================================================================

import argparse
import json
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from pyspark.sql import SparkSession, functions as F

# Folder where the output JSON is written: the PARENT of the folder that contains this script
# (parents[0] is the script's own folder, parents[1] is the one above it).
SUMMARIES = Path(__file__).resolve().parents[1]
# Full IRIs of the two RDF/RDFS properties that carry the "schema" information.
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"          # "X is an instance of class C"
SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"          # "class C is a subclass of class D"


def type_sets(triples):
    """Return a table (entity, classes): every entity of the graph with the sorted list of its classes."""
    # Keep only triples whose object is a resource (an IRI or a blank node), not a literal value.
    resources = triples.where(F.col("okind").isin("iri", "bnode"))
    # "Entities" = every node of the graph: everything that is a subject plus everything that is an
    # object resource. union() stacks the two lists and distinct() removes duplicates.
    # (Note: class IRIs such as orkgc:Paper are objects of rdf:type, so they are entities too.)
    entities = triples.selectExpr("s as entity").union(resources.selectExpr("o as entity")).distinct()
    # For every subject, collect the classes it is declared to have (rdf:type triples with an IRI object).
    # collect_set removes duplicates; sort_array gives a stable order, so the same set of classes is
    # always the same list. This matters later, when lists are compared and grouped.
    types = (triples.where((F.col("p") == RDF_TYPE) & (F.col("okind") == "iri"))
             .groupBy("s").agg(F.sort_array(F.collect_set("o")).alias("classes"))
             .withColumnRenamed("s", "entity"))
    # Attach the classes to each entity. The LEFT join keeps entities that have no type; for them the
    # join gives NULL, and coalesce replaces it with an empty array, so "untyped" becomes classes = [].
    return entities.join(types, "entity", "left").select(
        "entity", F.coalesce("classes", F.array().cast("array<string>")).alias("classes"))


def ancestors(cls, parents):
    """All superclasses of `cls`: parents, parents of parents, and so on (parents[c] = direct superclasses)."""
    seen = set()                       # superclasses found so far (also protects against cycles)
    pending = list(parents[cls])       # stack of classes still to explore, starting with the direct parents
    while pending:
        parent = pending.pop()
        if parent not in seen:
            seen.add(parent)
            # Continue upwards, skipping classes that are already known.
            pending.extend(parents[parent] - seen)
    return seen


def abstat_members(triples, members):
    """ABSTAT-style: replace each entity's full class set by its MINIMAL classes (one node per minimal class)."""
    # Build the class hierarchy: parents[child] = set of direct superclasses, from the subClassOf triples.
    parents = defaultdict(set)
    hierarchy = triples.where((F.col("p") == SUBCLASS) & (F.col("okind") == "iri"))
    for child, parent in hierarchy.select("s", "o").distinct().collect():
        parents[child].add(parent)

    # Only class sets and their hierarchy are brought to the driver.
    # groups = every DISTINCT class set that occurs in the graph (a few thousand at most, not millions
    # of entities). This is what keeps the work on the driver small.
    groups = [r.classes for r in members.select("classes").distinct().collect()]
    # above[c] = all superclasses of c, computed once for every class that appears in some group.
    above = {c: ancestors(c, parents) for c in {c for group in groups for c in group}}
    # mapping = rows (full class set -> one minimal class), used below as a lookup table.
    mapping = []
    for group in groups:
        # Drop strict ancestors, preserving equally specific classes and cycles.
        # A class c is dropped if the same group contains a class d that is more specific:
        #   c is a superclass of d (c in above[d]) AND d is not also a superclass of c (d not in above[c]).
        # The second condition keeps classes that are equivalent to each other (cycles) instead of
        # dropping both of them.
        minimal = [c for c in group if not any(c in above[d] and d not in above[c] for d in group)]
        # One row per minimal class: an entity with two minimal classes will appear in two nodes.
        mapping.extend((group, [c]) for c in minimal)
        if not group:
            # Untyped entities (empty class set) map to the node with an empty class list.
            mapping.append(([], []))
    # Turn the small python list into a Spark table so it can be joined with the entities.
    lookup = triples.sparkSession.createDataFrame(mapping, "classes array<string>, node array<string>")
    # Join on the full class set; every entity gets one row per minimal class. The new `classes`
    # column now holds that single minimal class (as a one-element list), or [] for untyped entities.
    return members.join(lookup, "classes").selectExpr("entity", "node as classes")


def summarize(triples, method, directory):
    """Build the whole summary (nodes, edges, attributes) as a python dict, ready to be written as JSON."""
    # Step 1: which node(s) does each entity belong to? (`classes` identifies the node)
    members = type_sets(triples)
    if method == "abstat":
        members = abstat_members(triples, members)
    # cache() keeps the table in memory because it is used several times below.
    members = members.cache()
    try:
        # ---- NODES: one node per distinct `classes` value, with the number of entities in it.
        # orderBy makes the numbering (n1, n2, ...) the same on every run.
        # (r["count"] is used instead of r.count because Row.count is already a tuple method.)
        sizes = members.groupBy("classes").count().orderBy("classes").collect()
        nodes = [{"id": f"n{i}", "classes": r.classes, "size": r["count"]}
                 for i, r in enumerate(sizes, 1)]
        # Lookup: class list -> node id (a tuple, because lists cannot be dictionary keys).
        ids = {tuple(n["classes"]): n["id"] for n in nodes}

        # ---- FACTS: all triples except the schema ones (rdf:type, subClassOf), because those are
        # already described by the nodes themselves.
        facts = triples.where(~F.col("p").isin(RDF_TYPE, SUBCLASS))
        # Give every triple the node (`src`) of its subject. For abstat, a subject with two minimal
        # classes duplicates the triple once per node, so edge counts can exceed the number of triples.
        facts = facts.join(members.selectExpr("entity as s", "classes as src"), "s")
        # ---- EDGES: triples whose object is a resource. Attach the node of the object (`dst`), then
        # count how many triples exist for each (source node, property, target node). Sorted by count
        # (largest first) with ties broken by name, so the output is deterministic.
        links = (facts.where(F.col("okind").isin("iri", "bnode"))
                 .join(members.selectExpr("entity as o", "classes as dst"), "o")
                 .groupBy("src", "p", "dst").count().orderBy(F.desc("count"), "p", "src", "dst"))
        # ---- ATTRIBUTES: triples whose object is a literal. There is no target node, so count per
        # (source node, property, datatype), e.g. "Paper has 5000 xsd:string values for rdfs:label".
        literals = (facts.where(F.col("okind") == "literal").groupBy("src", "p", "dt")
                    .count().orderBy(F.desc("count"), "p", "src", "dt"))

        # Bring the (small) results to python and replace the class lists with node ids.
        edges = [{"source": ids[tuple(r.src)], "property": r.p, "target": ids[tuple(r.dst)], "count": r["count"]}
                 for r in links.collect()]
        attributes = [{"node": ids[tuple(r.src)], "property": r.p, "datatype": r.dt, "count": r["count"]}
                      for r in literals.collect()]
        # The summary that will be saved as JSON. "kind" is "type_based" or "abstat" (dash -> underscore).
        return {"kg": directory.name, "team": "B2", "kind": method.replace("-", "_"),
                "nodes": nodes, "edges": edges, "attributes": attributes}
    finally:
        # Always free the cached table, even if something failed above.
        members.unpersist()


def main():
    # Command line: python <this script> <graph directory> <type-based|abstat>
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="graph directory containing parquet/")
    parser.add_argument("method", choices=("type-based", "abstat"))
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    parquet = directory / "parquet"
    # Stop early with a clear message if the Parquet folder is not there.
    if not parquet.is_dir():
        parser.error(f"missing input directory: {parquet}")
    method = args.method
    # Local Spark with only 2 worker threads ("local[2]") and 200 shuffle partitions for joins/groupBys.
    spark = (SparkSession.builder.appName(f"B2-{method}").master("local[2]")
             .config("spark.sql.shuffle.partitions", "200").getOrCreate())
    try:
        # The timer covers reading the data and building the summary (not Spark start-up).
        start = perf_counter()
        triples = spark.read.parquet(str(parquet))
        summary = summarize(triples, method, directory)
        # Output name, e.g. orkg_type_based.json or dblp_abstat.json, inside SUMMARIES.
        prefix = {"orkg2023": "orkg", "dblp2022": "dblp"}.get(directory.name, directory.name)
        output = SUMMARIES / f"{prefix}_{summary['kind']}.json"
        # Safe write: first write to a temporary folder on the same disk, then move the finished file
        # into place in one step. If the program stops half-way, the old output is never left corrupted.
        with TemporaryDirectory(dir=SUMMARIES) as tmp:
            staged = Path(tmp) / output.name
            staged.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            staged.replace(output)
        # Report: file name, size of the summary and time taken (the time is needed for the report).
        print(f"{output}: {len(summary['nodes'])} nodes, {len(summary['edges'])} edges, "
              f"{len(summary['attributes'])} attributes in {perf_counter() - start:.1f}s")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

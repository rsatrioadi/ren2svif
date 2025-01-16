# File: main.py

import sys
import json
import argparse
import os

from convert import graphml_to_arcana
from graph import Graph
from transformations import (
    collect_structures_and_variables,
    collect_operations_and_macros,
    collect_files_and_associations,
    invert_parent_folder_edges,
    link_source_parentfolder_structures
)


def build_graph_from_nodes_edges(nodes, edges):
    """
    Helper that constructs a new Graph() instance
    from a list of Node objects and a list of Edge objects.
    """
    g = Graph()
    # Insert nodes
    for n in nodes:
        g.nodes[n.id] = n
    # Insert edges
    for e in edges:
        lbl = e.label_val  # or e.label() depending on your Edge class
        g.edges.setdefault(lbl, []).append(e)
    return g


def main():
    parser = argparse.ArgumentParser(
        description="Command-line tool to transform a .graphml or CyJSON (.json) file "
                    "into an Arcana/CyJSON graph, apply transformations, and write out the final JSON."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to the input file (.graphml or .json in CyJSON format)"
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to the output .json file (final transformed graph)"
    )
    parser.add_argument(
        "--ontology",
        "-t",
        required=False,
        help="Optional path to write ontology JSON"
    )
    parser.add_argument(
        "--no-ops",
        action="store_true",
        help="Skip the function/operation/macro transformations"
    )
    parser.add_argument(
        "--no-files",
        action="store_true",
        help="Skip the file-related transformations (SourceFile, HeaderFile, etc.)"
    )
    parser.add_argument(
        "--no-folders",
        action="store_true",
        help="Skip the folder-related transformations (ParentFolder edges, etc.)"
    )
    args = parser.parse_args()

    # 1) Determine input format by file extension
    input_file = args.input
    extension = os.path.splitext(input_file)[1].lower()

    # 2) Read the graph
    print(f"Reading input from {args.input} ...", file=sys.stderr)
    if extension == ".graphml":
        original_graph = graphml_to_arcana(input_file)  
    elif extension == ".json":
        # Treat this as CyJSON
        with open(input_file, "r", encoding="utf-8") as fin:
            cyjson_data = json.load(fin)
        original_graph = Graph(cyjson_data)
    else:
        raise ValueError(f"Unsupported input file extension '{extension}'. "
                         "Supported: .graphml or .json (CyJSON).")

    print(f"Done reading. Found {len(original_graph.find_nodes())} nodes and "
          f"{len(original_graph.find_edges())} edges in the original graph.",
          file=sys.stderr)

    # 3) Step A: Collect structures & variables
    print("Collecting structures & variables...", file=sys.stderr)
    s_nodes, s_edges, s_map = collect_structures_and_variables(original_graph)
    print(f"  -> structures/variables: {len(s_nodes)} nodes, {len(s_edges)} edges", file=sys.stderr)

    # 4) Step B: Collect operations & macros (unless --no-ops)
    o_nodes = []
    o_edges = []
    o_map = {}
    if not args.no_ops:
        print("Collecting operations & macros...", file=sys.stderr)
        o_nodes, o_edges, o_map = collect_operations_and_macros(original_graph, s_map)
        print(f"  -> operations/macros: {len(o_nodes)} nodes, {len(o_edges)} edges", file=sys.stderr)

    # Combine structure & operation mappings so file transformations can see them
    combined_map_1 = dict(s_map)
    combined_map_1.update(o_map)

    # 5) Step C: Collect files & associations (unless --no-files)
    f_nodes = []
    f_edges = []
    combo_map_2 = dict(combined_map_1)
    if not args.no_files:
        print("Collecting files & associations...", file=sys.stderr)
        f_nodes, f_edges, combo_map_2 = collect_files_and_associations(
            original_graph,
            combined_map_1,
            s_nodes + o_nodes
        )
        print(f"  -> files: {len(f_nodes)} nodes, {len(f_edges)} edges", file=sys.stderr)

    # 6) Step D: Invert parent folder edges (unless --no-folders)
    folder_nodes = []
    folder_edges = []
    combo_map_3 = dict(combo_map_2)
    if not args.no_folders:
        print("Inverting folder edges (ParentFolder->contains)...", file=sys.stderr)
        folder_nodes, folder_edges, combo_map_3 = invert_parent_folder_edges(
            original_graph,
            combo_map_2
        )
        print(f"  -> folders: {len(folder_nodes)} nodes, {len(folder_edges)} edges", file=sys.stderr)

    # 7) Step E: Link source->parentfolder structures
    extra_nest_edges = []
    if not args.no_folders and not args.no_files:
        print("Linking source->parentfolder->... structures...", file=sys.stderr)
        new_nodes_all = s_nodes + o_nodes + f_nodes + folder_nodes
        extra_nest_edges = link_source_parentfolder_structures(
            original_graph,
            combo_map_3,
            new_nodes_all
        )
        print(f"  -> extra nest edges: {len(extra_nest_edges)}", file=sys.stderr)

    # Combine everything
    all_nodes = s_nodes + o_nodes + f_nodes + folder_nodes
    all_edges = s_edges + o_edges + f_edges + folder_edges + extra_nest_edges

    final_graph = build_graph_from_nodes_edges(all_nodes, all_edges)
    final_graph.clean_up()

    print(f"Final graph: {len(final_graph.find_nodes())} nodes, {len(final_graph.find_edges())} edges.", file=sys.stderr)

    # If user wants an ontology
    if args.ontology:
        onto = final_graph.generate_ontology()
        with open(args.ontology, "w", encoding="utf-8") as f:
            json.dump(onto.to_dict(), f, indent=2)
        print(f"Wrote ontology to {args.ontology}", file=sys.stderr)

    # Write final JSON
    with open(args.output, "w", encoding="utf-8") as fout:
        json.dump(final_graph.to_dict(), fout, indent=2)
    print(f"Wrote final JSON to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

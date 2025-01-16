# File: convert.py

import networkx as nx
from graphviz import Digraph
from graph import Graph

def graphml_to_arcana(graphml_file):
    """
    Reads a .graphml file and converts it into our Graph (CyJSON-like) data structure.
    Uses networkx to parse the GraphML, then transforms each node and edge
    into the 'elements' format in 'cyjson', ultimately returning a Graph.
    """
    # Read the GraphML file
    g_nx = nx.read_graphml(graphml_file)
    
    cyjson = {
        "elements": {
            "nodes": [],
            "edges": []
        }
    }
    
    # Process nodes
    for node_id, node_data in g_nx.nodes(data=True):
        # If the networkx GraphML has an attribute 'labelV',
        # we treat that as the "primary label" for the node;
        # otherwise default to "UnknownNode".
        label = node_data.get('labelV', 'UnknownNode')
        
        cyjson_node = {
            "data": {
                "id": node_id,
                "labels": [label],
                "properties": {}
            }
        }
        # Include all other attributes as node properties
        for key, value in node_data.items():
            if key != 'labelV':
                cyjson_node["data"]["properties"][key] = value
        
        cyjson["elements"]["nodes"].append(cyjson_node)
    
    # Process edges
    for source, target, edge_data in g_nx.edges(data=True):
        # If there's an attribute 'labelE', treat that as the edge label
        # otherwise fallback to 'UnknownEdge'
        lbl = edge_data.get('labelE', 'UnknownEdge')
        
        cyjson_edge = {
            "data": {
                "source": source,
                "target": target,
                "label": lbl,
                "properties": {}
            }
        }
        # Include all other attributes as edge properties
        for key, value in edge_data.items():
            if key != 'labelE':
                cyjson_edge["data"]["properties"][key] = value
        
        cyjson["elements"]["edges"].append(cyjson_edge)
    
    return Graph(cyjson)

def create_labeled_digraph(graph):
    """
    Given our custom Graph, build a Graphviz Digraph with labeled edges for visualization.
    """
    dot = Digraph()
        
    # For edges with label(s)
    for label, edges in graph.edges.items():
        for e in edges:
            # We call e.label_val or e.label() depending on how Edge is implemented
            # In this code base, we do e.label() if it’s a method, or e.label_val directly if it’s an attribute
            lbl = e.label_val  
            dot.edge(e.source, e.target, label=lbl)
    
    return dot

# File: transformations.py

from collections import defaultdict
from graph import Node, Edge
from helpers import (
    rename_properties,
    merge_properties,
    parse_path_as_name,
    normalize_label_camelcase
)


def collect_structures_and_variables(original_graph):
    """
    Collect Structures and Variables (and handle merges + inherits) from CppDeclaration nodes.
    
    Includes:
      1) Merge any pairs connected by CppAlias (c->d), prioritizing c's properties.
      2) Classify each merged entity as either 'Structure' (if it has .targets("CppContains")
         or .targets("CppInherits")) or 'Variable' (otherwise).
      3) Create:
         - 'hasVariable' edges from Structure -> Variable for old 'CppContains' relationships.
         - 'contains' edges from Structure -> Structure (nested) for old 'CppContains'.
           (Also add "Container" label to the parent structure that contains another structure.)
      4) Transform 'CppInherits' into 'specializes' edges among Structures.

    Returns:
      (new_nodes_list, new_edges_list, id_mapping)
        new_nodes_list: [Node, ...]
        new_edges_list: [Edge, ...]
        id_mapping: { old_id -> new_id }
    """

    # 0) Gather relevant nodes
    cpp_decl_nodes    = original_graph.find_nodes(label="CppDeclaration")
    cpp_fwddecl_nodes = original_graph.find_nodes(label="CppForwardDeclaration")

    # Union-Find Preprocessing for CppAlias merges
    all_decl_ids = set(n.id for n in cpp_decl_nodes) | set(n.id for n in cpp_fwddecl_nodes)
    node_props   = {}
    parent       = {}
    merged_props = {}

    for n in (cpp_decl_nodes + cpp_fwddecl_nodes):
        node_props[n.id] = dict(n.properties)  # original props
    for old_id in all_decl_ids:
        parent[old_id] = old_id
        merged_props[old_id] = dict(node_props[old_id])  # start with local copy

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(main_id, other_id):
        rep_main = find(main_id)
        rep_other = find(other_id)
        if rep_main == rep_other:
            return
        parent[rep_other] = rep_main
        # Merging properties, prioritizing rep_main
        pm = merged_props[rep_main]
        po = merged_props[rep_other]
        for k, v in po.items():
            if k not in pm:
                pm[k] = v

    # Process CppAlias
    # alias_edges = original_graph.find_edges(label="CppAlias")
    # for e in alias_edges:
    #     c_id = e.source
    #     d_id = e.target
    #     if c_id in all_decl_ids and d_id in all_decl_ids:
    #         # "prioritize c" => union(d_id, c_id)
    #         union(c_id, d_id)

    # 1) Identify representative sets => final structure or variable
    comp_members = defaultdict(list)
    for old_id in all_decl_ids:
        rep = find(old_id)
        comp_members[rep].append(old_id)

    # We'll detect whether the group is a structure or variable by checking .targets("CppContains") etc.
    group_has_contains = defaultdict(bool)
    group_has_inherits = defaultdict(bool)

    # For each CppDeclaration, if it has n.targets("CppContains") or n.targets("CppInherits"), mark as structure
    for n in cpp_decl_nodes:
        rep = find(n.id)
        # Check if n has any CppContains
        if n.targets("CppContains"):
            group_has_contains[rep] = True
        # If also want to treat n.targets("CppInherits") or n.sources("CppInherits")
        if n.targets("CppInherits") or n.sources("CppInherits"):
            group_has_inherits[rep] = True

    new_nodes_dict = {}
    id_mapping     = {}

    # rename helper
    def rename_props_local(props):
        """Calls rename_properties from helpers.py, returning new dict."""
        return rename_properties(props)

    for rep_id, members in comp_members.items():
        # decide if structure or variable
        props_merged = merged_props[rep_id]
        props_renamed = rename_props_local(props_merged)

        if group_has_contains[rep_id] or group_has_inherits[rep_id]:
            # structure
            props_renamed["kind"] = "class/struct/template"
            new_labels = ["Structure"]
            node_id = f"class{rep_id}"
        else:
            # variable
            props_renamed["kind"] = "variable"
            new_labels = ["Variable"]
            node_id = f"variable{rep_id}"

        new_node = Node(node_id, *new_labels, **props_renamed)
        new_nodes_dict[node_id] = new_node

        for m in members:
            id_mapping[m] = node_id

    # 2) Build edges: hasVariable, contains, specializes
    new_edges_dict = defaultdict(list)

    # hasVariable / contains
    old_declarations = original_graph.find_nodes(label="CppDeclaration")
    for old_decl_node in old_declarations:
        parent_new_id   = id_mapping[old_decl_node.id]
        parent_new_node = new_nodes_dict[parent_new_id]
        if "Structure" not in parent_new_node.labels:
            # skip if not structure
            continue

        for child_n in old_decl_node.targets("CppContains"):
            if child_n.id not in id_mapping:
                continue
            child_new_id   = id_mapping[child_n.id]
            child_new_node = new_nodes_dict[child_new_id]

            if "Variable" in child_new_node.labels:
                # hasVariable
                e_hv = Edge(parent_new_id, child_new_id, "hasVariable", metaSrc="renaissance")
                new_edges_dict["hasVariable"].append(e_hv)
                # mark variable as 'field'
                child_new_node.properties["kind"] = "field"

            elif "Structure" in child_new_node.labels:
                # nested structure => 'contains' + label parent as Container
                parent_new_node.labels.add("Container")
                e_ct = Edge(parent_new_id, child_new_id, "contains", metaSrc="renaissance")
                new_edges_dict["contains"].append(e_ct)

    # specializes
    inherits_edges = original_graph.find_edges(label="CppInherits")
    for ed in inherits_edges:
        old_s = ed.source
        old_t = ed.target
        if (old_s in id_mapping) and (old_t in id_mapping):
            src_id = id_mapping[old_s]
            tgt_id = id_mapping[old_t]
            src_node = new_nodes_dict[src_id]
            tgt_node = new_nodes_dict[tgt_id]
            if "Structure" in src_node.labels and "Structure" in tgt_node.labels:
                e_sp = Edge(src_id, tgt_id, "specializes", metaSrc="renaissance")
                new_edges_dict["specializes"].append(e_sp)

    # finalize
    new_nodes_list = list(new_nodes_dict.values())
    new_edges_list = []
    for lbl, edge_list in new_edges_dict.items():
        new_edges_list.extend(edge_list)

    return (new_nodes_list, new_edges_list, id_mapping)


def collect_operations_and_macros(graph, structure_mapping):
    """
    1) Merge (CppFunctionDefinition -> CppFunctionDeclaration) into Operation nodes.
    2) Create single Operation nodes for leftover definitions/declarations that don't merge.
    3) Create Script nodes for CppMacroDefinition (kind="macro").
    4) If a function/macro is contained by a structure (old CppContains from that structure),
       then:
         - If it's an Operation, set 'kind'="method", else if it's a Script (macro), keep 'kind'="macro"
         - Create structure->(operation/script) edge labeled "hasScript".
    5) Convert CppCalls edges => "invoke" edges among these new nodes.
       (Because macros are “just like function declarations,” we handle them in calls too.)
    6) Return (new_nodes_list, new_edges_list, function_mapping).

    structure_mapping: old_id (of class/struct) -> new_id (of Structure)
    """

    # Gather function declarations/definitions/macros
    declarations = graph.find_nodes(label="CppFunctionDeclaration")
    definitions  = graph.find_nodes(label="CppFunctionDefinition")
    macros       = graph.find_nodes(label="CppMacroDefinition")

    decl_by_id = {n.id: n for n in declarations}
    defn_by_id = {n.id: n for n in definitions}
    macr_by_id = {n.id: n for n in macros}

    implements_edges = graph.find_edges(label="CppImplements")  # definition->declaration
    calls_edges      = graph.find_edges(label="CppCalls")
    contains_edges   = graph.find_edges(label="CppContains")

    # Build mapping def->decl
    decl_for_defn = defaultdict(list)
    defn_for_decl = defaultdict(list)
    for e in implements_edges:
        dfn_id = e.source
        dcl_id = e.target
        if dfn_id in defn_by_id and dcl_id in decl_by_id:
            decl_for_defn[dfn_id].append(dcl_id)
            defn_for_decl[dcl_id].append(dfn_id)

    new_nodes_dict   = {}
    new_edges_dict   = defaultdict(list)
    function_mapping = {}
    handled          = set()

    # Merge pass: def->decl => single Operation
    for def_id, def_node in defn_by_id.items():
        if def_id in handled:
            continue
        matched_decls = decl_for_defn.get(def_id, [])
        if not matched_decls:
            continue
        for dcl_id in matched_decls:
            if dcl_id in handled:
                continue
            dcl_node = decl_by_id[dcl_id]
            merged = merge_properties(def_node.properties, dcl_node.properties)
            new_op_id = f"function{def_id}_{dcl_id}"
            op_node = Node(new_op_id, "Operation", **merged)
            new_nodes_dict[new_op_id] = op_node
            handled.update([def_id, dcl_id])
            function_mapping[def_id] = new_op_id
            function_mapping[dcl_id] = new_op_id

    # leftover definitions => Operation
    for def_id, def_node in defn_by_id.items():
        if def_id not in handled:
            props = rename_properties(def_node.properties)
            new_id = f"funcdef{def_id}"
            op_node = Node(new_id, "Operation", **props)
            new_nodes_dict[new_id] = op_node
            handled.add(def_id)
            function_mapping[def_id] = new_id

    # leftover declarations => Operation
    for dcl_id, dcl_node in decl_by_id.items():
        if dcl_id not in handled:
            props = rename_properties(dcl_node.properties)
            new_id = f"funcdecl{dcl_id}"
            op_node = Node(new_id, "Operation", **props)
            new_nodes_dict[new_id] = op_node
            handled.add(dcl_id)
            function_mapping[dcl_id] = new_id

    # macros => Script
    for mac_id, mac_node in macr_by_id.items():
        if mac_id not in function_mapping:
            props = rename_properties(mac_node.properties)
            props["kind"] = "macro"
            script_id = f"macro{mac_id}"
            script_node = Node(script_id, "Script", **props)
            new_nodes_dict[script_id] = script_node
            function_mapping[mac_id] = script_id

    # Check containment => hasScript edges
    contains_map = defaultdict(list)
    for e in contains_edges:
        contains_map[e.target].append(e.source)

    all_func_ids = list(defn_by_id.keys()) + list(decl_by_id.keys()) + list(macr_by_id.keys())

    for old_id in all_func_ids:
        new_id = function_mapping.get(old_id)
        if not new_id or new_id not in new_nodes_dict:
            continue
        node_obj = new_nodes_dict[new_id]

        # If any parent is in structure_mapping => create structure->(op/script) = "hasScript"
        # and if it's an Operation => set kind=method
        parents = contains_map[old_id]
        is_method = False
        for p in parents:
            if p in structure_mapping:
                struct_new_id = structure_mapping[p]
                e_hs = Edge(struct_new_id, new_id, "hasScript")
                new_edges_dict["hasScript"].append(e_hs)
                if "Operation" in node_obj.labels:
                    node_obj.properties["kind"] = "method"

        # If it's an Operation and not method => kind=function
        if "Operation" in node_obj.labels:
            if node_obj.properties.get("kind") != "method":
                node_obj.properties["kind"] = "function"
        # If it's a Script => keep "macro"

    # calls => invoke
    calls_map = defaultdict(set)
    for e in calls_edges:
        calls_map[e.source].add(e.target)

    invoke_pairs = set()
    for old_src, old_targets in calls_map.items():
        if old_src not in function_mapping:
            continue
        new_src = function_mapping[old_src]
        for ot in old_targets:
            if ot not in function_mapping:
                continue
            new_tgt = function_mapping[ot]
            if new_src != new_tgt:
                invoke_pairs.add((new_src, new_tgt))

    for (s, t) in invoke_pairs:
        e_invoke = Edge(s, t, "invoke")
        new_edges_dict["invoke"].append(e_invoke)

    new_nodes_list = list(new_nodes_dict.values())
    new_edges_list = []
    for lbl, elst in new_edges_dict.items():
        new_edges_list.extend(elst)

    return (new_nodes_list, new_edges_list, function_mapping)


def collect_files_and_associations(original_graph, existing_mapping, new_nodes_list):
    """
    Convert SourceFile, HeaderFile, OtherFile into Structure(kinds) = 
      'source file', 'header file', 'other file'.
    Then:
      1) Invert 'Source' edges from variables/operations/scripts to files => 
         file->var/func => hasVariable/hasScript.
         If the same var/func references both a SourceFile and a HeaderFile,
         add a structure->structure edge (sourceFile->headerFile) = association.
      2) If a class/struct references a file by 'Source' => class->file = association.
      3) Convert 'CppUses' => 'uses' from file->someNode.

    Returns: (new_file_nodes_list, new_edges_list, combined_mapping)
    """

    # We want to look up new nodes from existing + new_nodes_list
    new_nodes_dict = {nd.id: nd for nd in new_nodes_list}

    from collections import defaultdict
    new_file_nodes_dict = {}
    new_edges_dict      = defaultdict(list)
    combined_mapping    = dict(existing_mapping)

    # Gather
    sfiles  = original_graph.find_nodes(label="SourceFile")
    hfiles  = original_graph.find_nodes(label="HeaderFile")
    ofiles  = original_graph.find_nodes(label="OtherFile")

    # parse_path helper => from helpers.py
    for old_node in sfiles:
        props = parse_path_as_name(old_node.properties, old_id=old_node.id)
        props["kind"] = "source file"
        new_id = f"file{old_node.id}"
        new_node = Node(new_id, "Structure", **props)
        new_file_nodes_dict[new_id] = new_node
        combined_mapping[old_node.id] = new_id

    for old_node in hfiles:
        props = parse_path_as_name(old_node.properties, old_id=old_node.id)
        props["kind"] = "header file"
        new_id = f"file{old_node.id}"
        new_node = Node(new_id, "Structure", **props)
        new_file_nodes_dict[new_id] = new_node
        combined_mapping[old_node.id] = new_id

    for old_node in ofiles:
        props = parse_path_as_name(old_node.properties, old_id=old_node.id)
        props["kind"] = "other file"
        new_id = f"file{old_node.id}"
        new_node = Node(new_id, "Structure", **props)
        new_file_nodes_dict[new_id] = new_node
        combined_mapping[old_node.id] = new_id

    # Source edges => invert
    var_func_to_files = defaultdict(set)
    source_edges = original_graph.find_edges(label="Source")

    def get_new_node_labels(old_id):
        # Look up new ID, then check either new_file_nodes_dict or new_nodes_dict
        nid = combined_mapping.get(old_id)
        if not nid:
            return set()
        if nid in new_file_nodes_dict:
            return new_file_nodes_dict[nid].labels
        if nid in new_nodes_dict:
            return new_nodes_dict[nid].labels
        return set()

    for e in source_edges:
        old_s = e.source
        old_t = e.target
        new_s = combined_mapping.get(old_s, None)
        new_t = combined_mapping.get(old_t, None)

        s_is_file = (new_s in new_file_nodes_dict)
        t_is_file = (new_t in new_file_nodes_dict)

        s_labels = get_new_node_labels(old_s)
        t_labels = get_new_node_labels(old_t)

        # var/func => file => invert => file->var/func
        if (not s_is_file) and t_is_file and new_s:
            file_id = new_t
            main_id = new_s
            # check if s_labels is "Variable", "Operation"/"Script", or "Structure"
            if "Variable" in s_labels:
                e_hv = Edge(file_id, main_id, "hasVariable")
                new_edges_dict["hasVariable"].append(e_hv)
                var_func_to_files[old_s].add(old_t)
            elif {"Operation", "Script"} & s_labels:
                e_hs = Edge(file_id, main_id, "hasScript")
                new_edges_dict["hasScript"].append(e_hs)
                var_func_to_files[old_s].add(old_t)
            elif "Structure" in s_labels:
                # class->file => association
                e_assoc = Edge(main_id, file_id, "association")
                new_edges_dict["association"].append(e_assoc)

        # file => var/func => invert => file->var/func
        elif s_is_file and (not t_is_file) and new_t:
            file_id = new_s
            main_id = new_t
            if "Variable" in t_labels:
                e_hv = Edge(file_id, main_id, "hasVariable")
                new_edges_dict["hasVariable"].append(e_hv)
                var_func_to_files[old_t].add(old_s)
            elif {"Operation", "Script"} & t_labels:
                e_hs = Edge(file_id, main_id, "hasScript")
                new_edges_dict["hasScript"].append(e_hs)
                var_func_to_files[old_t].add(old_s)
            elif "Structure" in t_labels:
                # class->file => association
                e_assoc = Edge(main_id, file_id, "association")
                new_edges_dict["association"].append(e_assoc)

    # If a single var/func references both SourceFile and HeaderFile => structure->structure
    for old_vf, file_ids in var_func_to_files.items():
        sfile_ids, hfile_ids = [], []
        for fid in file_ids:
            new_fid = combined_mapping.get(fid)
            if new_fid in new_file_nodes_dict:
                kindv = new_file_nodes_dict[new_fid].properties.get("kind","")
                if kindv == "source file":
                    sfile_ids.append(new_fid)
                elif kindv == "header file":
                    hfile_ids.append(new_fid)
        for sfid in sfile_ids:
            for hfid in hfile_ids:
                e_assoc = Edge(sfid, hfid, "association")
                new_edges_dict["association"].append(e_assoc)

    # CppUses => uses
    uses_edges = original_graph.find_edges(label="CppUses")
    for ee in uses_edges:
        old_f = ee.source
        old_t = ee.target
        new_f = combined_mapping.get(old_f)
        new_t = combined_mapping.get(old_t)
        if new_f in new_file_nodes_dict and new_t:
            e_uses = Edge(new_f, new_t, "uses")
            new_edges_dict["uses"].append(e_uses)

    # Build final
    new_file_nodes_list = list(new_file_nodes_dict.values())
    new_edges_list = []
    for el in new_edges_dict.values():
        new_edges_list.extend(el)

    return (new_file_nodes_list, new_edges_list, combined_mapping)


def invert_parent_folder_edges(original_graph, existing_mapping):
    """
    Invert 'ParentFolder' edges into 'contains' edges.

    - Convert 'Folder' -> Container(kind='folder').
    - For any other node not in existing_mapping, create a new 'Structure'(kind=normalized label).
    - parse name->qualifiedName, etc. from helpers
    - Then if a->b was labeled ParentFolder, we produce b'->a' labeled 'contains'.
    """
    new_nodes_dict = {}
    new_edges_dict = defaultdict(list)
    combined_mapping = dict(existing_mapping)

    pfolder_edges = original_graph.find_edges(label="ParentFolder")

    for e in pfolder_edges:
        old_a_id = e.source
        old_b_id = e.target

        if old_a_id not in original_graph.nodes or old_b_id not in original_graph.nodes:
            continue
        
        old_a = original_graph.nodes[old_a_id]
        old_b = original_graph.nodes[old_b_id]

        a_new_id = ensure_mapped_node_folder_or_structure(old_a, combined_mapping, new_nodes_dict)
        b_new_id = ensure_mapped_node_folder_or_structure(old_b, combined_mapping, new_nodes_dict)

        # invert => b'->a' labeled contains
        e_contains = Edge(b_new_id, a_new_id, "contains")
        new_edges_dict["contains"].append(e_contains)

    new_nodes_list = list(new_nodes_dict.values())
    new_edges_list = []
    for el in new_edges_dict.values():
        new_edges_list.extend(el)

    return (new_nodes_list, new_edges_list, combined_mapping)


def ensure_mapped_node_folder_or_structure(old_node, combined_mapping, new_nodes_dict):
    """
    If old_node.id already in combined_mapping, return that new ID.
    Otherwise:
      - If old_node is labeled 'Folder', => Container(kind='folder')
      - else => Structure(kind=normalize_label_camelcase)
      - parse path name
    """
    old_id = old_node.id
    if old_id in combined_mapping:
        return combined_mapping[old_id]

    from helpers import parse_path_as_name

    props = dict(old_node.properties)
    props = parse_path_as_name(props, old_id=old_id)

    if "Folder" in old_node.labels:
        new_label = "Container"
        props["kind"] = "folder"
        new_id = f"folder{old_id}"
    else:
        new_label = "Structure"
        # pick any label from old_node.labels to normalize
        first_lbl = sorted(old_node.labels)[0]
        norm = normalize_label_camelcase(first_lbl)
        props["kind"] = norm
        new_id = f"auto{old_id}"

    new_node = Node(new_id, new_label, **props)
    new_nodes_dict[new_id] = new_node
    combined_mapping[old_id] = new_id
    return new_id


def link_source_parentfolder_structures(original_graph, existing_mapping, new_nodes_list):
    """
    Looks for old 2-edge paths:
        (e) -[:Source]-> (f) -[:ParentFolder]-> (d)

    Then:
      1) (d') -[:contains]-> (e'), only if:
         - d' is labeled "Container"
         - e' is labeled "Container" or "Structure"

      2) (f') -[:nests]-> (e'), only if:
         - f' is labeled "Structure"
         - e' is labeled "Structure"
         => Actually we do f'->e' label="contains" & f' add label Container

    Returns a list of newly created Edge objects.
    """
    new_nodes_dict = {n.id: n for n in new_nodes_list}
    new_edge_list = []

    paths = original_graph.find_paths("Source", "ParentFolder")
    for path in paths:
        if len(path) != 2:
            continue
        e_source, e_folder = path
        old_e = e_source.source
        old_f = e_source.target
        old_d = e_folder.target

        if old_e not in existing_mapping or old_f not in existing_mapping or old_d not in existing_mapping:
            continue

        new_e = existing_mapping[old_e]
        new_f = existing_mapping[old_f]
        new_d = existing_mapping[old_d]

        d_node = new_nodes_dict.get(new_d)
        e_node = new_nodes_dict.get(new_e)
        f_node = new_nodes_dict.get(new_f)

        # (d') -contains->(e') if d' is Container, e' is Container or Structure
        if d_node and e_node:
            if "Container" in d_node.labels and ({"Container", "Structure"} & e_node.labels):
                e_cn = Edge(new_d, new_e, "contains")
                new_edge_list.append(e_cn)

        # (f') -nests->(e') => actually f'->e' labeled "contains" if both are structure
        if f_node and e_node:
            if "Structure" in f_node.labels and "Structure" in e_node.labels:
                f_node.labels.add("Container")
                e_nest = Edge(new_f, new_e, "contains")
                new_edge_list.append(e_nest)

    return new_edge_list

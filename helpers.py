# File: helpers.py

import re

def rename_properties(props):
    """
    Renames 'symbol' -> 'simpleName' and 'name' -> 'qualifiedName' (if present),
    and adds metaSrc='renaissance'.
    
    Modifies a copy of the dictionary so as not to alter the original in place.
    """
    props_new = dict(props)
    if "symbol" in props_new:
        props_new["simpleName"] = props_new.pop("symbol")
    if "name" in props_new:
        props_new["qualifiedName"] = props_new.pop("name")
    props_new["metaSrc"] = "renaissance"
    return props_new

def merge_properties(def_props, decl_props):
    """
    Creates a combined property dictionary:
      - Start with decl_props
      - Overwrite collisions with def_props
      - Then rename symbol->simpleName, name->qualifiedName
      - Add metaSrc='renaissance'
    """
    merged = dict(decl_props)
    merged.update(def_props)  # def_props overwrites collisions
    if "symbol" in merged:
        merged["simpleName"] = merged.pop("symbol")
    if "name" in merged:
        merged["qualifiedName"] = merged.pop("name")
    merged["metaSrc"] = "renaissance"
    return merged

def parse_path_as_name(props, old_id=None):
    """
    Interprets 'name' in props as a path, setting:
      props["qualifiedName"]   = entire path
      props["simpleName"]      = last segment of the path
    If there's no 'name', tries 'symbol' for simpleName,
    else uses old_id as fallback.
    """
    props = dict(props)  # copy

    path_val = props.pop("name", None)
    symbol_val = props.pop("symbol", None)

    if path_val is not None:
        props["qualifiedName"] = path_val
        # Convert backslashes to forward slashes for uniform splitting
        norm_path = path_val.replace("\\", "/")
        last_part = norm_path.split("/")[-1] or norm_path
        props["simpleName"] = last_part
    else:
        # Fallback
        if symbol_val:
            props["simpleName"] = symbol_val
            props["qualifiedName"] = symbol_val
        else:
            sid = old_id if old_id else "unknown"
            props["simpleName"] = sid
            props["qualifiedName"] = sid

    props["metaSrc"] = "renaissance"
    return props

def normalize_label_camelcase(lbl):
    """
    Convert a CamelCase label like 'HeaderFile' -> 'header file',
    'ProjectCOrCpp' -> 'project c or cpp', etc.
    """
    spaced = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', lbl)
    return spaced.lower()

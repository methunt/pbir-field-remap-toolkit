#!/usr/bin/env python3
"""
Apply PBIR field remap from a mapping CSV to all report JSON files.

Reusable for any Power BI PBIR-format report. Requires only a .Report folder
and a map.csv — no project-specific code.

Usage:
  python apply_field_remap.py <report_dir> --map <map.csv>              # dry-run (default)
  python apply_field_remap.py <report_dir> --map <map.csv> --apply      # write changes
  python apply_field_remap.py <report_dir> --map <map.csv> --apply --output-dir <dir>
    python apply_field_remap.py <report_dir> --map <map.csv> --scan-all-json

Arguments:
  report_dir        Path to the .Report folder (must end with .Report)
  --map             Path to the mapping CSV file
  --dry-run         Preview changes only, no files written (default)
    --apply           Write changes to files
  --output-dir      Folder for output CSVs (default: <report_dir>/remap_output)
    --scan-all-json   Recursively scan and remap field objects anywhere in JSON

map.csv required columns:
  From Table, From col, To table, To col

  - Rows with blank "To table" or "To col" are skipped (original value kept)
  - Rows where From == To are skipped (no-op)

Outputs (written to --output-dir):
  - remap_dryrun.csv      one row per proposed change (dry-run mode)
  - remap_applied.csv     one row per applied change  (apply mode)
  - remap_unresolved.csv  references not found in map (always written)

Remapping rules:
  - SourceRef.Entity and Property updated in all field object locations:
      projections, fieldParameters, sort, selectors, filterConfig, bookmarks
  - queryRef always rebuilt as "{new_entity}.{new_property}"
  - selector.metadata always rebuilt as "{new_entity}.{new_property}"
  - filter.From[].Entity and filter.Where[].Property updated together
"""

from __future__ import annotations

import argparse
import csv
import copy
import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Mapping = Dict[Tuple[str, str], Tuple[str, str]]   # (old_entity, old_prop) → (new_entity, new_prop)


@dataclass
class Change:
    file_path: str
    context_type: str
    json_path: str
    old_entity: str
    old_property: str
    new_entity: str
    new_property: str
    old_query_ref: str = ""
    new_query_ref: str = ""
    old_metadata: str = ""
    new_metadata: str = ""


@dataclass
class Unresolved:
    file_path: str
    context_type: str
    json_path: str
    entity: str
    property: str
    reason: str


# ---------------------------------------------------------------------------
# Load & normalise mapping
# ---------------------------------------------------------------------------

def load_mapping(csv_path: Path) -> Mapping:
    """
    Build lookup: (from_table, from_col) → (to_table, to_col).
    Rows where to_table or to_col is blank are excluded (keep-original).
    """
    mapping: Mapping = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            from_table = (row.get("From Table") or "").strip()
            from_col   = (row.get("From col")   or "").strip()
            to_table   = (row.get("To table")   or "").strip()
            to_col     = (row.get("To col")     or "").strip()

            if not from_table or not from_col:
                continue
            if not to_table or not to_col:
                continue  # keep-original rule

            key = (from_table, from_col)
            # Skip if same (no-op renames just add noise)
            if key == (to_table, to_col):
                continue
            mapping[key] = (to_table, to_col)

    return mapping


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def remap(entity: str, prop: str, mapping: Mapping) -> Tuple[str, str, bool]:
    """Return (new_entity, new_prop, changed)."""
    result = mapping.get((entity, prop))
    if result:
        new_entity, new_prop = result
        return new_entity, new_prop, (new_entity != entity or new_prop != prop)
    return entity, prop, False


def get_entity_property_from_field(field_obj: Any) -> Tuple[Optional[str], Optional[str], str]:
    """
    Return (entity, prop, kind) from a field object like:
    {"Column": {"Expression": {"SourceRef": {"Entity": "..."}}, "Property": "..."}}
    kind is "Column", "Measure", "HierarchyLevel", or "Aggregation".
    """
    if not isinstance(field_obj, dict):
        return None, None, ""
    for kind in ("Column", "Measure", "HierarchyLevel", "Aggregation"):
        ref = field_obj.get(kind)
        if not isinstance(ref, dict):
            continue
        prop = ref.get("Property")
        source_ref = (ref.get("Expression") or {}).get("SourceRef") or {}
        entity = source_ref.get("Entity")
        if isinstance(entity, str) and isinstance(prop, str):
            return entity, prop, kind
    return None, None, ""


def update_field_obj(field_obj: Any, mapping: Mapping) -> Tuple[str, str, str, str, str, bool]:
    """
    Update a field object in-place.
    Returns (old_entity, old_prop, new_entity, new_prop, kind, changed).
    """
    if not isinstance(field_obj, dict):
        return "", "", "", "", "", False
    for kind in ("Column", "Measure", "HierarchyLevel", "Aggregation"):
        ref = field_obj.get(kind)
        if not isinstance(ref, dict):
            continue
        prop = ref.get("Property")
        source_ref = (ref.get("Expression") or {}).get("SourceRef") or {}
        entity = source_ref.get("Entity")
        if not isinstance(entity, str) or not isinstance(prop, str):
            continue
        new_entity, new_prop, changed = remap(entity, prop, mapping)
        if changed:
            source_ref["Entity"] = new_entity
            ref["Property"] = new_prop
        return entity, prop, new_entity, new_prop, kind, changed
    return "", "", "", "", "", False


# ---------------------------------------------------------------------------
# Filter definition block updater (From[]/Where[])
# ---------------------------------------------------------------------------

def _walk_condition(node: Any, alias_remap: Dict[str, Tuple[str, str]], changes_local: List[Tuple]) -> None:
    """
    Recursively walk a filter condition node.
    alias_remap: {alias: (old_entity, new_entity)}  — updated in-place as we remap
    changes_local: accumulates (alias, old_prop, new_prop) tuples for logging
    """
    if isinstance(node, dict):
        # If this is a Column or Measure reference
        for kind in ("Column", "Measure"):
            ref = node.get(kind)
            if not isinstance(ref, dict):
                continue
            prop = ref.get("Property")
            source = (ref.get("Expression") or {}).get("SourceRef", {}).get("Source")
            if source is None or not isinstance(prop, str):
                continue
            if source not in alias_remap:
                continue
            old_entity, new_entity = alias_remap[source]
            # We need the full mapping to remap property; store info for caller
            changes_local.append((source, old_entity, new_entity, prop, ref))
            return

        for val in node.values():
            _walk_condition(val, alias_remap, changes_local)

    elif isinstance(node, list):
        for item in node:
            _walk_condition(item, alias_remap, changes_local)


def update_filter_definition(filter_def: Any, mapping: Mapping) -> List[Tuple[str, str, str, str]]:
    """
    Update filter.From[].Entity and corresponding Property references in Where[].
    Returns list of (old_entity, old_prop, new_entity, new_prop) changes.
    """
    if not isinstance(filter_def, dict):
        return []

    from_list = filter_def.get("From") or []
    where_list = filter_def.get("Where") or []

    # Build alias → entity map
    alias_to_entity: Dict[str, str] = {}
    for item in from_list:
        if isinstance(item, dict):
            name = item.get("Name")
            entity = item.get("Entity")
            if name and entity:
                alias_to_entity[name] = entity

    if not alias_to_entity:
        return []

    # Walk conditions to find (alias, old_entity, prop, ref_obj) tuples
    # We use a two-pass approach:
    # Pass 1: collect all property references per alias
    # Pass 2: remap and update both From and Where

    # Build alias_remap: initially identity (will update after remapping)
    alias_remap: Dict[str, Tuple[str, str]] = {
        alias: (entity, entity) for alias, entity in alias_to_entity.items()
    }

    changes: List[Tuple[str, str, str, str]] = []

    # For each Where condition, find column refs and remap
    for where_item in where_list:
        local_refs: List[Tuple] = []
        _walk_condition(where_item, alias_remap, local_refs)
        for (alias, old_entity, _new_entity, prop, ref_obj) in local_refs:
            new_entity, new_prop, changed = remap(old_entity, prop, mapping)
            if changed:
                ref_obj["Property"] = new_prop
                # Update alias_remap so From gets updated
                alias_remap[alias] = (old_entity, new_entity)
                changes.append((old_entity, prop, new_entity, new_prop))

    # Update From[] entity names
    for item in from_list:
        if isinstance(item, dict):
            alias = item.get("Name")
            if alias and alias in alias_remap:
                old_entity, new_entity = alias_remap[alias]
                if old_entity != new_entity:
                    item["Entity"] = new_entity

    return changes


# ---------------------------------------------------------------------------
# Per-file processors
# ---------------------------------------------------------------------------

def process_projections(
    file_rel: str, data: Dict, mapping: Mapping,
    changes: List[Change], unresolved: List[Unresolved]
) -> None:
    visual = (data.get("visual") or {})
    query  = (visual.get("query") or {})
    query_state = (query.get("queryState") or {})

    if not isinstance(query_state, dict):
        return

    for section, section_obj in query_state.items():
        projections = (section_obj.get("projections") or []) if isinstance(section_obj, dict) else []
        for p_idx, proj in enumerate(projections):
            if not isinstance(proj, dict):
                continue
            field = proj.get("field")
            old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(field, mapping)
            if not old_entity:
                continue
            json_path = f"$.visual.query.queryState.{section}.projections[{p_idx}].field"
            if changed:
                old_qref = str(proj.get("queryRef") or "")
                new_qref = f"{new_entity}.{new_prop}"
                proj["queryRef"] = new_qref
                changes.append(Change(
                    file_path=file_rel, context_type="visual_projection",
                    json_path=json_path,
                    old_entity=old_entity, old_property=old_prop,
                    new_entity=new_entity, new_property=new_prop,
                    old_query_ref=old_qref, new_query_ref=new_qref,
                ))
            else:
                if (old_entity, old_prop) not in mapping:
                    unresolved.append(Unresolved(
                        file_path=file_rel, context_type="visual_projection",
                        json_path=json_path,
                        entity=old_entity, property=old_prop,
                        reason="not_in_map",
                    ))

        # Also handle fieldParameters (e.g., in Series)
        field_params = (section_obj.get("fieldParameters") or []) if isinstance(section_obj, dict) else []
        for fp_idx, field_param in enumerate(field_params):
            if not isinstance(field_param, dict):
                continue
            param_expr = field_param.get("parameterExpr")
            if not isinstance(param_expr, dict):
                continue
            old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(param_expr, mapping)
            if not old_entity:
                continue
            json_path = f"$.visual.query.queryState.{section}.fieldParameters[{fp_idx}].parameterExpr"
            if changed:
                changes.append(Change(
                    file_path=file_rel, context_type="visual_field_parameter",
                    json_path=json_path,
                    old_entity=old_entity, old_property=old_prop,
                    new_entity=new_entity, new_property=new_prop,
                    old_query_ref="", new_query_ref="",
                ))
            else:
                if (old_entity, old_prop) not in mapping:
                    unresolved.append(Unresolved(
                        file_path=file_rel, context_type="visual_field_parameter",
                        json_path=json_path,
                        entity=old_entity, property=old_prop,
                        reason="not_in_map",
                    ))


def process_sort(
    file_rel: str, data: Dict, mapping: Mapping,
    changes: List[Change], unresolved: List[Unresolved]
) -> None:
    visual    = (data.get("visual") or {})
    query     = (visual.get("query") or {})
    sort_list = (query.get("sortDefinition") or {}).get("sort") or []

    for s_idx, sort_item in enumerate(sort_list):
        if not isinstance(sort_item, dict):
            continue
        field = sort_item.get("field")
        old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(field, mapping)
        if not old_entity:
            continue
        json_path = f"$.visual.query.sortDefinition.sort[{s_idx}].field"
        if changed:
            changes.append(Change(
                file_path=file_rel, context_type="visual_sort",
                json_path=json_path,
                old_entity=old_entity, old_property=old_prop,
                new_entity=new_entity, new_property=new_prop,
            ))


def process_selectors(
    file_rel: str, data: Dict, mapping: Mapping,
    changes: List[Change], unresolved: List[Unresolved]
) -> None:
    visual  = (data.get("visual") or {})
    objects = (visual.get("objects") or {})
    if not isinstance(objects, dict):
        return

    for obj_name, entries in objects.items():
        if not isinstance(entries, list):
            continue
        for e_idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            selector = entry.get("selector")
            if not isinstance(selector, dict):
                continue
            metadata = selector.get("metadata")
            if not isinstance(metadata, str) or "." not in metadata:
                continue
            left, right = metadata.split(".", 1)
            new_entity, new_prop, changed = remap(left, right, mapping)
            json_path = f"$.visual.objects.{obj_name}[{e_idx}].selector.metadata"
            if changed:
                new_meta = f"{new_entity}.{new_prop}"
                selector["metadata"] = new_meta
                changes.append(Change(
                    file_path=file_rel, context_type="visual_selector",
                    json_path=json_path,
                    old_entity=left, old_property=right,
                    new_entity=new_entity, new_property=new_prop,
                    old_metadata=metadata, new_metadata=new_meta,
                ))


def _walk_and_remap_field_objects(
    file_rel: str,
    node: Any,
    json_path: str,
    mapping: Mapping,
    changes: List[Change],
    unresolved: List[Unresolved],
    context_type: str,
) -> None:
    """
    Recursively remap nested field objects in arbitrary JSON trees.
    This is used for visual object expressions like FillRule inputs and
    selector.data scope comparisons.
    """
    if isinstance(node, dict):
        old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(node, mapping)
        if old_entity:
            if changed:
                changes.append(Change(
                    file_path=file_rel,
                    context_type=context_type,
                    json_path=json_path,
                    old_entity=old_entity,
                    old_property=old_prop,
                    new_entity=new_entity,
                    new_property=new_prop,
                ))
            elif (old_entity, old_prop) not in mapping:
                unresolved.append(Unresolved(
                    file_path=file_rel,
                    context_type=context_type,
                    json_path=json_path,
                    entity=old_entity,
                    property=old_prop,
                    reason="not_in_map",
                ))

        for key, value in node.items():
            _walk_and_remap_field_objects(
                file_rel=file_rel,
                node=value,
                json_path=f"{json_path}.{key}",
                mapping=mapping,
                changes=changes,
                unresolved=unresolved,
                context_type=context_type,
            )
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _walk_and_remap_field_objects(
                file_rel=file_rel,
                node=item,
                json_path=f"{json_path}[{idx}]",
                mapping=mapping,
                changes=changes,
                unresolved=unresolved,
                context_type=context_type,
            )


def process_visual_object_fields(
    file_rel: str, data: Dict, mapping: Mapping,
    changes: List[Change], unresolved: List[Unresolved]
) -> None:
    visual = (data.get("visual") or {})
    if not isinstance(visual, dict):
        return

    objects = visual.get("objects")
    if objects is not None:
        _walk_and_remap_field_objects(
            file_rel=file_rel,
            node=objects,
            json_path="$.visual.objects",
            mapping=mapping,
            changes=changes,
            unresolved=unresolved,
            context_type="visual_object_field",
        )

    container_objects = visual.get("visualContainerObjects")
    if container_objects is not None:
        _walk_and_remap_field_objects(
            file_rel=file_rel,
            node=container_objects,
            json_path="$.visual.visualContainerObjects",
            mapping=mapping,
            changes=changes,
            unresolved=unresolved,
            context_type="visual_container_object_field",
        )


def _walk_all_json_fields(
    file_rel: str,
    node: Any,
    json_path: str,
    mapping: Mapping,
    changes: List[Change],
) -> None:
    """
    Recursively scan arbitrary JSON and remap field objects.
    Used by --scan-all-json as a safety-net for unknown PBIR structures.
    """
    if isinstance(node, dict):
        # Handle container with explicit `field` and optional `queryRef`
        field_obj = node.get("field")
        if isinstance(field_obj, dict):
            old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(field_obj, mapping)
            if old_entity and changed:
                old_qref = str(node.get("queryRef") or "")
                new_qref = old_qref
                if isinstance(node.get("queryRef"), str):
                    new_qref = f"{new_entity}.{new_prop}"
                    node["queryRef"] = new_qref
                changes.append(Change(
                    file_path=file_rel,
                    context_type="scan_all_json_field",
                    json_path=f"{json_path}.field",
                    old_entity=old_entity,
                    old_property=old_prop,
                    new_entity=new_entity,
                    new_property=new_prop,
                    old_query_ref=old_qref,
                    new_query_ref=new_qref,
                ))

        # Handle raw field objects anywhere
        old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(node, mapping)
        if old_entity and changed:
            changes.append(Change(
                file_path=file_rel,
                context_type="scan_all_json_field",
                json_path=json_path,
                old_entity=old_entity,
                old_property=old_prop,
                new_entity=new_entity,
                new_property=new_prop,
            ))

        for key, value in node.items():
            _walk_all_json_fields(
                file_rel=file_rel,
                node=value,
                json_path=f"{json_path}.{key}",
                mapping=mapping,
                changes=changes,
            )
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _walk_all_json_fields(
                file_rel=file_rel,
                node=item,
                json_path=f"{json_path}[{idx}]",
                mapping=mapping,
                changes=changes,
            )


def process_all_json_fields(
    file_rel: str, data: Dict, mapping: Mapping,
    changes: List[Change]
) -> None:
    _walk_all_json_fields(
        file_rel=file_rel,
        node=data,
        json_path="$",
        mapping=mapping,
        changes=changes,
    )


def process_filter_config(
    file_rel: str, data: Dict, context_label: str,
    mapping: Mapping, changes: List[Change], unresolved: List[Unresolved]
) -> None:
    filter_config = data.get("filterConfig") or {}
    filters = filter_config.get("filters") or []

    for f_idx, filt in enumerate(filters):
        if not isinstance(filt, dict):
            continue

        # --- field reference ---
        field = filt.get("field")
        old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(field, mapping)
        json_path = f"$.filterConfig.filters[{f_idx}].field"
        if old_entity:
            if changed:
                changes.append(Change(
                    file_path=file_rel, context_type=context_label,
                    json_path=json_path,
                    old_entity=old_entity, old_property=old_prop,
                    new_entity=new_entity, new_property=new_prop,
                ))
            else:
                if (old_entity, old_prop) not in mapping:
                    unresolved.append(Unresolved(
                        file_path=file_rel, context_type=context_label,
                        json_path=json_path,
                        entity=old_entity, property=old_prop,
                        reason="not_in_map",
                    ))

        # --- filter definition block ---
        filter_def = filt.get("filter")
        if filter_def:
            fdef_changes = update_filter_definition(filter_def, mapping)
            for (oe, op, ne, np) in fdef_changes:
                changes.append(Change(
                    file_path=file_rel, context_type=f"{context_label}_definition",
                    json_path=f"$.filterConfig.filters[{f_idx}].filter",
                    old_entity=oe, old_property=op,
                    new_entity=ne, new_property=np,
                ))


def process_bookmark(
    file_rel: str, data: Dict, mapping: Mapping,
    changes: List[Change], unresolved: List[Unresolved]
) -> None:
    by_expr = (
        (data.get("explorationState") or {})
        .get("filters", {})
        .get("byExpr") or []
    )
    for idx, item in enumerate(by_expr):
        if not isinstance(item, dict):
            continue
        expression = item.get("expression")
        old_entity, old_prop, new_entity, new_prop, _kind, changed = update_field_obj(expression, mapping)
        if not old_entity:
            continue
        json_path = f"$.explorationState.filters.byExpr[{idx}].expression"
        if changed:
            changes.append(Change(
                file_path=file_rel, context_type="bookmark_filter",
                json_path=json_path,
                old_entity=old_entity, old_property=old_prop,
                new_entity=new_entity, new_property=new_prop,
            ))
        else:
            if (old_entity, old_prop) not in mapping:
                unresolved.append(Unresolved(
                    file_path=file_rel, context_type="bookmark_filter",
                    json_path=json_path,
                    entity=old_entity, property=old_prop,
                    reason="not_in_map",
                ))


# ---------------------------------------------------------------------------
# File-level dispatcher
# ---------------------------------------------------------------------------

def classify(path: Path) -> str:
    parts = path.parts
    if path.name == "visual.json" and "visuals" in parts:
        return "visual"
    if path.name == "page.json" and "pages" in parts:
        return "page"
    if path.name.endswith(".bookmark.json") and "bookmarks" in parts:
        return "bookmark"
    if path.name == "report.json":
        return "report"
    return "other"


def process_file(
    file_path: Path, report_dir: Path, mapping: Mapping,
    changes: List[Change], unresolved: List[Unresolved],
) -> Optional[Dict]:
    """
    Load JSON, apply all remaps in-place, return modified data dict.
    Returns None if file could not be parsed or is out of scope.
    """
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    file_rel = file_path.relative_to(report_dir).as_posix()
    ctx = classify(file_path)

    if ctx == "visual":
        process_projections(file_rel, data, mapping, changes, unresolved)
        process_sort(file_rel, data, mapping, changes, unresolved)
        process_selectors(file_rel, data, mapping, changes, unresolved)
        process_filter_config(file_rel, data, "visual_filter", mapping, changes, unresolved)

    elif ctx == "page":
        process_filter_config(file_rel, data, "page_filter", mapping, changes, unresolved)

    elif ctx == "report":
        process_filter_config(file_rel, data, "report_filter", mapping, changes, unresolved)

    elif ctx == "bookmark":
        process_bookmark(file_rel, data, mapping, changes, unresolved)

    else:
        return None  # skip non-binding files

    return data


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def write_changes_csv(rows: List[Change], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "file_path", "context_type", "json_path",
            "old_entity", "old_property", "new_entity", "new_property",
            "old_query_ref", "new_query_ref", "old_metadata", "new_metadata",
        ])
        writer.writeheader()
        for r in rows:
            writer.writerow(r.__dict__)


def write_unresolved_csv(rows: List[Unresolved], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Deduplicate by (entity, property)
    seen: set = set()
    deduped = []
    for r in rows:
        key = (r.entity, r.property)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "file_path", "context_type", "json_path", "entity", "property", "reason"
        ])
        writer.writeheader()
        for r in deduped:
            writer.writerow(r.__dict__)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(
    report_dir: Path,
    map_path: Path,
    apply: bool,
    output_dir: Optional[Path] = None,
    scan_all_json: bool = False,
) -> None:
    if output_dir is None:
        output_dir = report_dir / "remap_output"
    print(f"Report   : {report_dir}")
    print(f"Map      : {map_path}")
    print(f"Mode     : {'APPLY (will write files)' if apply else 'DRY-RUN (read-only)'}")
    print()

    mapping = load_mapping(map_path)
    print(f"Loaded {len(mapping)} mapping rules (blank-To rows excluded).")

    definition_dir = report_dir / "definition"
    json_files = sorted(definition_dir.rglob("*.json"))

    all_changes: List[Change]    = []
    all_unresolved: List[Unresolved] = []
    file_data: Dict[Path, Dict]  = {}

    for fp in json_files:
        # Work on a deep copy so dry-run never mutates the original object
        # For apply mode we'll re-parse; for now collect changes via in-place mutation on copy
        try:
            with fp.open("r", encoding="utf-8") as fh:
                original = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(original, dict):
            continue

        data_copy = copy.deepcopy(original)
        file_rel = fp.relative_to(report_dir).as_posix()
        ctx = classify(fp)

        changes_before = len(all_changes)

        if ctx == "visual":
            process_projections(file_rel, data_copy, mapping, all_changes, all_unresolved)
            process_sort(file_rel, data_copy, mapping, all_changes, all_unresolved)
            process_selectors(file_rel, data_copy, mapping, all_changes, all_unresolved)
            process_visual_object_fields(file_rel, data_copy, mapping, all_changes, all_unresolved)
            process_filter_config(file_rel, data_copy, "visual_filter", mapping, all_changes, all_unresolved)
        elif ctx == "page":
            process_filter_config(file_rel, data_copy, "page_filter", mapping, all_changes, all_unresolved)
        elif ctx == "report":
            process_filter_config(file_rel, data_copy, "report_filter", mapping, all_changes, all_unresolved)
        elif ctx == "bookmark":
            process_bookmark(file_rel, data_copy, mapping, all_changes, all_unresolved)
        else:
            continue

        if scan_all_json:
            process_all_json_fields(file_rel, data_copy, mapping, all_changes)

        if len(all_changes) > changes_before:
            file_data[fp] = data_copy  # only keep files that have changes

    output_dir.mkdir(parents=True, exist_ok=True)

    if apply:
        written = 0
        for fp, data in file_data.items():
            with fp.open("w", encoding="utf-8", newline="\n") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            written += 1

        out_csv = output_dir / "remap_applied.csv"
        write_changes_csv(all_changes, out_csv)
        print(f"Files written : {written}")
        print(f"Changes applied: {len(all_changes)}")
        print(f"Applied CSV  : {out_csv}")
    else:
        out_csv = output_dir / "remap_dryrun.csv"
        write_changes_csv(all_changes, out_csv)
        print(f"Changes found  : {len(all_changes)}")
        print(f"Dry-run CSV    : {out_csv}")

    unresolved_csv = output_dir / "remap_unresolved.csv"
    write_unresolved_csv(all_unresolved, unresolved_csv)
    print(f"Unresolved refs: {len(set((r.entity, r.property) for r in all_unresolved))} unique pairs")
    print(f"Unresolved CSV : {unresolved_csv}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply PBIR field remap from a mapping CSV to report JSON files."
    )
    parser.add_argument("report_directory", help="Path to .Report folder")
    parser.add_argument("--map", required=True, help="Path to mapping CSV file")
    parser.add_argument("--output-dir", default=None,
                        help="Folder for output CSVs (default: <report_dir>/remap_output)")
    parser.add_argument("--scan-all-json", action="store_true", default=False,
                        help="Recursively scan/remap field objects anywhere in JSON")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                      help="Preview changes only, do not write (default)")
    mode.add_argument("--apply", dest="apply", action="store_true", default=False,
                      help="Write changes to files")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_directory).resolve()
    map_path   = Path(args.map).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None

    if not report_dir.exists():
        print(f"Error: report directory not found: {report_dir}")
        return 1
    if not report_dir.name.lower().endswith(".report"):
        print("Error: report directory must end with .Report")
        return 1
    if not map_path.exists():
        print(f"Error: map file not found: {map_path}")
        return 1

    run(
        report_dir,
        map_path,
        apply=args.apply,
        output_dir=output_dir,
        scan_all_json=args.scan_all_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

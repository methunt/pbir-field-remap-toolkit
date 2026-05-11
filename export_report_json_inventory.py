#!/usr/bin/env python3
"""
Export PBIR report JSON inventory into CSV files.

Outputs:
  - FieldBindings.csv: Semantic binding references for mappings
  - AllScalars.csv: All scalar JSON paths for full attribute review

Usage:
  python export_report_json_inventory.py "d:/path/to/Global Programmatic.Report"

Requirements:
  Python 3.8+ (standard library only)
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class BindingRow:
    file_path: str
    page_id: str
    visual_id: str
    context_type: str
    json_path: str
    entity: str
    property: str
    query_ref: str
    native_query_ref: str
    selector_metadata: str
    display_name: str
    filter_name: str


def path_to_posix(path: Path) -> str:
    return path.as_posix()


def safe_get(mapping: Any, key: str, default: Any = None) -> Any:
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return default


def extract_entity_property(field_obj: Any) -> Tuple[str, str]:
    if not isinstance(field_obj, dict):
        return "", ""

    for kind in ("Column", "Measure", "HierarchyLevel", "Aggregation"):
        ref = field_obj.get(kind)
        if not isinstance(ref, dict):
            continue

        prop = ref.get("Property")
        expr = safe_get(ref, "Expression", {})
        source_ref = safe_get(expr, "SourceRef", {})
        entity = source_ref.get("Entity")

        if isinstance(entity, str) and isinstance(prop, str):
            return entity, prop

    return "", ""


def find_page_visual_ids(file_path: Path) -> Tuple[str, str]:
    page_id = ""
    visual_id = ""

    parts = file_path.parts
    if "pages" in parts:
        idx = parts.index("pages")
        if idx + 1 < len(parts):
            candidate = parts[idx + 1]
            if candidate != "pages.json":
                page_id = candidate

    if "visuals" in parts:
        idx = parts.index("visuals")
        if idx + 1 < len(parts):
            visual_id = parts[idx + 1]

    return page_id, visual_id


def iter_scalars(node: Any, path: str = "$") -> Iterable[Tuple[str, str, Any, str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}"
            yield from iter_scalars(value, child_path)
        return

    if isinstance(node, list):
        for index, value in enumerate(node):
            child_path = f"{path}[{index}]"
            yield from iter_scalars(value, child_path)
        return

    parent_path = path.rsplit(".", 1)[0] if "." in path else "$"
    key = path.split(".")[-1]
    value_type = type(node).__name__
    yield path, key, node, value_type, parent_path


def find_bindings_in_filters(
    file_rel: str,
    page_id: str,
    visual_id: str,
    base_path: str,
    filters: Any,
    context_type: str,
) -> List[BindingRow]:
    rows: List[BindingRow] = []
    if not isinstance(filters, list):
        return rows

    for idx, filt in enumerate(filters):
        if not isinstance(filt, dict):
            continue

        field = filt.get("field")
        entity, prop = extract_entity_property(field)
        if not entity and not prop:
            continue

        rows.append(
            BindingRow(
                file_path=file_rel,
                page_id=page_id,
                visual_id=visual_id,
                context_type=context_type,
                json_path=f"{base_path}[{idx}].field",
                entity=entity,
                property=prop,
                query_ref="",
                native_query_ref="",
                selector_metadata="",
                display_name=str(filt.get("displayName") or ""),
                filter_name=str(filt.get("name") or ""),
            )
        )

    return rows


def find_bindings_in_visual(file_rel: str, data: Dict[str, Any], page_id: str, visual_id: str) -> List[BindingRow]:
    rows: List[BindingRow] = []

    visual = safe_get(data, "visual", {})
    query = safe_get(visual, "query", {})
    query_state = safe_get(query, "queryState", {})

    if isinstance(query_state, dict):
        for section, section_obj in query_state.items():
            projections = safe_get(section_obj, "projections", [])
            if not isinstance(projections, list):
                continue

            for p_idx, projection in enumerate(projections):
                if not isinstance(projection, dict):
                    continue
                field = projection.get("field")
                entity, prop = extract_entity_property(field)
                if not entity and not prop:
                    continue

                rows.append(
                    BindingRow(
                        file_path=file_rel,
                        page_id=page_id,
                        visual_id=visual_id,
                        context_type="visual_projection",
                        json_path=f"$.visual.query.queryState.{section}.projections[{p_idx}].field",
                        entity=entity,
                        property=prop,
                        query_ref=str(projection.get("queryRef") or ""),
                        native_query_ref=str(projection.get("nativeQueryRef") or ""),
                        selector_metadata="",
                        display_name=str(projection.get("displayName") or ""),
                        filter_name="",
                    )
                )

    sort_list = safe_get(query, "sortDefinition", {}).get("sort", [])
    if isinstance(sort_list, list):
        for s_idx, sort_item in enumerate(sort_list):
            if not isinstance(sort_item, dict):
                continue
            field = sort_item.get("field")
            entity, prop = extract_entity_property(field)
            if not entity and not prop:
                continue
            rows.append(
                BindingRow(
                    file_path=file_rel,
                    page_id=page_id,
                    visual_id=visual_id,
                    context_type="visual_sort",
                    json_path=f"$.visual.query.sortDefinition.sort[{s_idx}].field",
                    entity=entity,
                    property=prop,
                    query_ref="",
                    native_query_ref="",
                    selector_metadata="",
                    display_name="",
                    filter_name="",
                )
            )

    objects = safe_get(visual, "objects", {})
    if isinstance(objects, dict):
        for obj_name, entries in objects.items():
            if not isinstance(entries, list):
                continue
            for e_idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                selector = safe_get(entry, "selector", {})
                metadata = selector.get("metadata") if isinstance(selector, dict) else None
                if not isinstance(metadata, str) or "." not in metadata:
                    continue

                left, right = metadata.split(".", 1)
                rows.append(
                    BindingRow(
                        file_path=file_rel,
                        page_id=page_id,
                        visual_id=visual_id,
                        context_type="visual_selector",
                        json_path=f"$.visual.objects.{obj_name}[{e_idx}].selector.metadata",
                        entity=left,
                        property=right,
                        query_ref="",
                        native_query_ref="",
                        selector_metadata=metadata,
                        display_name="",
                        filter_name="",
                    )
                )

    rows.extend(
        find_bindings_in_filters(
            file_rel=file_rel,
            page_id=page_id,
            visual_id=visual_id,
            base_path="$.filterConfig.filters",
            filters=safe_get(data, "filterConfig", {}).get("filters", []),
            context_type="visual_filter",
        )
    )

    return rows


def find_bindings_in_report_like(file_rel: str, data: Dict[str, Any], page_id: str, context_type: str) -> List[BindingRow]:
    return find_bindings_in_filters(
        file_rel=file_rel,
        page_id=page_id,
        visual_id="",
        base_path="$.filterConfig.filters",
        filters=safe_get(data, "filterConfig", {}).get("filters", []),
        context_type=context_type,
    )


def find_bindings_in_bookmark(file_rel: str, data: Dict[str, Any], page_id: str) -> List[BindingRow]:
    rows: List[BindingRow] = []
    by_expr = safe_get(data, "explorationState", {}).get("filters", {}).get("byExpr", [])
    if not isinstance(by_expr, list):
        return rows

    for idx, item in enumerate(by_expr):
        if not isinstance(item, dict):
            continue
        expression = item.get("expression")
        entity, prop = extract_entity_property(expression)
        if not entity and not prop:
            continue

        rows.append(
            BindingRow(
                file_path=file_rel,
                page_id=page_id,
                visual_id="",
                context_type="bookmark_filter",
                json_path=f"$.explorationState.filters.byExpr[{idx}].expression",
                entity=entity,
                property=prop,
                query_ref="",
                native_query_ref="",
                selector_metadata="",
                display_name="",
                filter_name=str(item.get("name") or ""),
            )
        )

    return rows


def write_field_bindings_csv(rows: List[BindingRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file_path",
                "page_id",
                "visual_id",
                "context_type",
                "json_path",
                "entity",
                "property",
                "query_ref",
                "native_query_ref",
                "selector_metadata",
                "display_name",
                "filter_name",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def write_all_scalars_csv(rows: List[Dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["file_path", "json_path", "key", "value", "value_type", "parent_path"],
        )
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        return None
    return None


def classify_context(path: Path) -> str:
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


def build_inventory(report_dir: Path) -> Tuple[List[BindingRow], List[Dict[str, str]], int]:
    definition_dir = report_dir / "definition"
    json_files = sorted(definition_dir.rglob("*.json"))

    all_bindings: List[BindingRow] = []
    all_scalars: List[Dict[str, str]] = []
    parsed_files = 0

    for file_path in json_files:
        data = load_json(file_path)
        if data is None:
            continue
        parsed_files += 1

        rel_file = path_to_posix(file_path.relative_to(report_dir))
        page_id, visual_id = find_page_visual_ids(file_path)
        context = classify_context(file_path)

        if context == "visual":
            all_bindings.extend(find_bindings_in_visual(rel_file, data, page_id, visual_id))
        elif context == "report":
            all_bindings.extend(find_bindings_in_report_like(rel_file, data, page_id, "report_filter"))
        elif context == "page":
            all_bindings.extend(find_bindings_in_report_like(rel_file, data, page_id, "page_filter"))
        elif context == "bookmark":
            all_bindings.extend(find_bindings_in_bookmark(rel_file, data, page_id))

        for json_path, key, value, value_type, parent_path in iter_scalars(data):
            all_scalars.append(
                {
                    "file_path": rel_file,
                    "json_path": json_path,
                    "key": key,
                    "value": "" if value is None else str(value),
                    "value_type": value_type,
                    "parent_path": parent_path,
                }
            )

    return all_bindings, all_scalars, parsed_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export PBIR report JSON inventory to CSV")
    parser.add_argument(
        "report_directory",
        help="Path to .Report directory (for example: Global Programmatic.Report)",
    )
    parser.add_argument(
        "--output-dir",
        default="inventory_export",
        help="Output folder relative to report directory (default: inventory_export)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_directory).resolve()

    if not report_dir.exists() or not report_dir.is_dir():
        print(f"Error: report directory not found: {report_dir}")
        return 1

    if not report_dir.name.lower().endswith(".report"):
        print("Error: report directory must end with .Report")
        return 1

    definition_dir = report_dir / "definition"
    if not definition_dir.exists():
        print(f"Error: missing definition directory: {definition_dir}")
        return 1

    output_dir = report_dir / args.output_dir
    bindings_path = output_dir / "FieldBindings.csv"
    scalars_path = output_dir / "AllScalars.csv"

    bindings, scalars, parsed_files = build_inventory(report_dir)

    write_field_bindings_csv(bindings, bindings_path)
    write_all_scalars_csv(scalars, scalars_path)

    print("Inventory export complete")
    print(f"Parsed JSON files : {parsed_files}")
    print(f"Binding rows      : {len(bindings)}")
    print(f"Scalar rows       : {len(scalars)}")
    print(f"FieldBindings CSV : {bindings_path}")
    print(f"AllScalars CSV    : {scalars_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

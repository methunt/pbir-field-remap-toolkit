<div align="center">

# PBIR Field Remap Toolkit

**Repoint every field reference in a Power BI report from one table or column to another, driven by a CSV.**

<p>
  <img alt="Python 3.8+" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Standard library only" src="https://img.shields.io/badge/dependencies-none,%20stdlib%20only-059669?style=flat-square">
  <img alt="Power BI PBIR" src="https://img.shields.io/badge/Power%20BI-PBIR-F2C811?style=flat-square&logo=powerbi&logoColor=black">
  <img alt="Writes in place" src="https://img.shields.io/badge/writes-in%20place,%20no%20preview-7C3AED?style=flat-square">
  <img alt="Licence MIT" src="https://img.shields.io/badge/licence-MIT-0891B2?style=flat-square">
</p>

</div>

> [!CAUTION]
> `apply_field_remap.py` **writes your report files in place, immediately, with no backup and no preview mode.** Commit the `.Report` folder — or copy it — before you run it. `export_report_json_inventory.py` is read-only and safe to run at any time.

## What problem this solves

Rename a column in the semantic model and every visual bound to it breaks. Power BI Desktop will not do the rename for you, and nothing tells you how many places are affected.

| | Without this toolkit | With this toolkit |
|---|---|---|
| **Finding what's affected** | No visibility — you find out a visual is broken when you open the page | A read-only inventory pass lists every semantic binding before you touch anything |
| **Doing the rename** | A field reference is not one string — it's `SourceRef.Entity`, `Property`, a `queryRef` that has to agree with both, and a `selector.metadata` string encoding the same pair again. Text-editor find-and-replace leaves `queryRef` disagreeing with the field it names. | The script updates the pair and rebuilds `queryRef` and `selector.metadata` from it, so the derived strings can't drift from the reference they describe |
| **Bookmarks** | A remap that only fixes visuals looks like it worked — the report opens, pages render, and the breakage surfaces the first time somebody clicks a bookmark | The recursive scan is unconditional for exactly this reason — see [What's inside](#whats-inside) for what that found on a real report |

## What's inside

| File | What it does |
|---|---|
| [`export_report_json_inventory.py`](export_report_json_inventory.py) | Read-only. Exports every semantic binding and every scalar value in a report to CSV — the safe way to build your mapping file |
| [`apply_field_remap.py`](apply_field_remap.py) | Writes in place. Repoints every reference from a CSV map — projections, sorts, conditional formatting, filters and bookmarks — in a single pass |
| [`SKILL.md`](SKILL.md) | The same workflow as an agent skill: takes a `report_folder` and a `mapping_csv`, validates both, and requires confirming the report folder is backed up before it runs anything |

## Step 1 — Inventory what is bound

```powershell
python export_report_json_inventory.py "D:\path\to\MyReport.Report"
```

Writes two CSVs to `<report_dir>/inventory_export`, or wherever `--output-dir` points. A **relative** `--output-dir` is resolved against the report folder here, not your working directory; an absolute one is used as given.

| File | What it is for |
|---|---|
| `FieldBindings.csv` | One row per semantic reference, with the `entity` and `property` you'll paste into the map. Carries `page_id`, `visual_id`, `context_type`, `json_path`, `query_ref`, `native_query_ref`, `selector_metadata`, `display_name` and `filter_name`, so you can tell *which* visual on *which* page a reference belongs to before renaming it. |
| `AllScalars.csv` | Every scalar value in the report, one row per JSON leaf, with its `json_path`, `key`, `value_type` and `parent_path`. Large, and the tool of last resort when a field reference is somewhere the binding export doesn't model. |

`context_type` in `FieldBindings.csv` is one of: `visual_projection` (a field on a visual), `visual_filter` (a filter on one visual), `visual_selector` (conditional formatting keyed to a field), `visual_sort` (a visual's sort order), or `page_filter` (a page-level filter).

`FieldBindings.csv` is almost the mapping file already — pull the distinct `entity`/`property` pairs into a sheet, add `To table` and `To col`, and leave the rows you don't want touched blank.

## Step 2 — Write the map, run it once

`map.csv` needs four columns. The header is matched **exactly**, and the capitalisation is inconsistent — copy it rather than typing it:

```csv
From Table,From col,To table,To col
Fact,user_email,fct_BigQueryJobs,user_email
Fact,region,fct_BigQueryJobs,region
dim_Date,Date,,
```

| Rule | Effect |
|---|---|
| blank `To table` **or** blank `To col` | row skipped, original kept — this is how you say "leave this one alone" |
| `From` identical to `To` | row skipped as a no-op |
| blank `From Table` or `From col` | row ignored entirely |
| the same `(From Table, From col)` twice | last row wins; the map is a dictionary keyed on that pair |

A UTF-8 BOM on the file is handled (read as `utf-8-sig`), so a CSV saved from Excel is fine.

```powershell
python apply_field_remap.py "D:\path\to\MyReport.Report" --map "C:\path\to\map.csv"
```

There is one mode. Every run does the full recursive scan and writes its changes; there's no flag to preview first and no flag to turn the deep scan off — it used to be opt-in, and on a real report the difference was not marginal: targeted passes alone found 54 changes across 26 files, the recursive scan found 119 across 36, and the two sets did not overlap at all. Every one of the extra 65 was a location the targeted passes never visit — most of them inside `.bookmark.json` files, whose per-visual saved state under `explorationState.sections.*.visualContainers.*` the targeted bookmark pass never looks at.

### Output

Both CSVs go to `--output-dir`, defaulting to `<report_dir>/remap_output`. Unlike the inventory script's, **this path is used as given** — a relative path lands in your working directory.

| File | Contents |
|---|---|
| `remap_applied.csv` | one row per change written: file, `context_type`, `json_path`, old and new entity/property, and the old and new `queryRef` / `selector.metadata` where those applied |
| `remap_unresolved.csv` | field references found in the report that your map didn't cover, deduplicated to one row per `(entity, property)` — the `file_path`/`json_path` on the row are the first place it was seen, not the only one |

`remap_unresolved.csv` is always written, as a header-only file when there's nothing to report. Its row count is the honest measure of how complete your map is.

Open the report in Power BI Desktop afterwards and check the pages and bookmarks — nothing validates the new names against the semantic model.

### What gets rewritten

Only `<report_dir>/definition/**/*.json` is ever read or written. `definition.pbir`, `.platform` and everything under `StaticResources` are untouched.

| Location | What changes |
|---|---|
| `visual.query.queryState.*.projections[].field` | `SourceRef.Entity` and `Property`, and **`queryRef` rebuilt** as `entity.property` |
| `visual.query.queryState.*.fieldParameters[].parameterExpr` | the entity/property pair |
| `visual.query.sortDefinition.sort[].field` | the entity/property pair |
| `visual.objects.*[].selector.metadata` | the string **rebuilt** as `entity.property` |
| `visual.objects` and `visual.visualContainerObjects`, recursively | field objects nested inside expressions — conditional-formatting fill rules and the like |
| `filterConfig.filters[]` on visuals, pages and `report.json` | the filter's `field`, plus `Where[]` properties and the matching `From[].Entity` |
| `explorationState.filters.byExpr[].expression` in bookmarks | the entity/property pair |
| anywhere else in the file | any field object, plus a sibling `queryRef` if the container has one — the recursive scan, which always runs |

A field object is recognised as `Column`, `Measure`, `HierarchyLevel` or `Aggregation` carrying both an `Expression.SourceRef.Entity` and a `Property`.

## Good to know

| | |
|---|---|
| **A wrong folder looks like a clean run** | The script requires the folder to end in `.Report` but never checks that `definition/` exists inside it. Point it at the wrong level and you get `Changes applied: 0` and exit code 0 — indistinguishable from "the map matched nothing". The inventory script does check, and exits 1. Run that first and you cannot make this mistake. |
| **Chained mappings apply transitively** | The recursive scan re-walks fields the targeted passes already remapped, so a map containing both `A → B` and `B → C` can land on `C`. Map to final names in one pass; never chain. |
| **`remap_unresolved.csv` misses two contexts** | Unresolved references are logged from projections, field parameters, filters, bookmarks and nested object fields — but **not** from `sort` or `selector.metadata`. A stale sort or a stale conditional-formatting selector won't appear there. `FieldBindings.csv` from step 1 lists both. |
| **Nothing validates against the model** | The script doesn't open the semantic model. Map a field to a name that doesn't exist and it writes it happily — you find out in Desktop, and the exit code is 0 either way. |

## Using it through an agent

[`SKILL.md`](SKILL.md) is an agent skill describing the same workflow: it takes a `report_folder` and a `mapping_csv` and validates both. Because the script writes immediately, the skill's safety gate requires confirming the report folder is committed or backed up first, and stops if that cannot be confirmed.

## Licence

[MIT](LICENSE).

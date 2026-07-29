---
name: pbir-field-remap
description: Operational workflow for remapping PBIR field references from map.csv. Always runs the deep recursive scan and writes changes in place; confirm source control backup before running.
repo_url: https://github.com/methunt/PowerBi/tree/main/PBIR%20Field%20Remap%20Toolkit
---

# PBIR Field Remap Skill

## Use this skill when

- User asks to remap Power BI PBIR field references using a mapping CSV.
- User wants the agent to run the script directly and apply the remap.

## Do not use this skill when

- Task is only inventory export (use `export_report_json_inventory.py`).
- User asks for model/schema design changes instead of JSON field remap.

## Required inputs

1. `report_folder`
- Absolute path to a folder ending with `.Report`.

2. `mapping_csv`
- Absolute path to CSV file.
- Header must include exactly these columns:
  - `From Table`
  - `From col`
  - `To table`
  - `To col`

## Optional inputs

- `output_dir` (optional): folder for output CSVs.

## Defaults

- Output folder default: `<report_folder>/remap_output`

## Safety gates

1. Validate paths and headers before running.
2. If path/header validation fails, stop and report exact issue.
3. The script writes report files in place with no backup and no preview mode. Before running, confirm with the user that `report_folder` is committed to source control (or otherwise backed up). If the user cannot confirm this, stop and do not run the script.

## Execution protocol

1. Validate inputs:
- `report_folder` exists and ends with `.Report`
- `mapping_csv` exists and has required headers

2. Confirm the report folder is committed/backed up (safety gate 3). Stop if not confirmed.

3. Run the remap:
- Run `python apply_field_remap.py "<report_folder>" --map "<mapping_csv>"`
- Report the summary of applied changes and unresolved pairs.

## Command templates

Default output folder:

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>"
```

With custom output folder:

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --output-dir "<output_dir>"
```

## Output contract (what to report)

Report:

- `files_written`
- `changes_applied`
- `remap_applied.csv` path
- `unresolved_unique_pairs`
- `remap_unresolved.csv` path

## Output files

Default output path: `<report_folder>/remap_output`

- `remap_applied.csv`
- `remap_unresolved.csv` (always written, header-only when there are no unresolved references; deduplicated to one row per (entity, property))

## Mapping behavior

- Blank `To table` or `To col` means keep original unchanged.
- No-op rows where From equals To are ignored.
- Writes always happen — there is no preview/dry-run mode.

## Failure handling

- If `.Report` folder is missing/invalid: return clear path error.
- If `map.csv` is missing: return clear path error.
- If headers are invalid: report required header names and stop.
- If the user cannot confirm the report folder is backed up: stop before running.

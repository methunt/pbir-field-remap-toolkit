---
name: pbir-field-remap
description: Operational workflow for remapping PBIR field references from map.csv. Ask if the user wants a dry run summary, otherwise run with scan-all-json directly.
repo_url: https://github.com/methunt/PowerBi/tree/main/PBIR%20Field%20Remap%20Toolkit
---

# PBIR Field Remap Skill

## Use this skill when

- User asks to remap Power BI PBIR field references using a mapping CSV.
- User wants the agent to run the script directly with optional dry-run summary.

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
- `scan_all_json` (optional): default `true` unless user asks otherwise.

## Defaults

- `scan_all_json = true`
- Output folder default: `<report_folder>/remap_output`

## Safety gates

1. Validate paths and headers before running.
2. If path/header validation fails, stop and report exact issue.

## Execution protocol

1. Validate inputs:
- `report_folder` exists and ends with `.Report`
- `mapping_csv` exists and has required headers

2. Ask the user if they want a dry run with summary.

3. If the user requests dry-run:
- Run `python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --dry-run --scan-all-json`
- Report summary of proposed changes and unresolved pairs.

4. If the user declines dry-run:
- Run `python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --apply --scan-all-json`
- Report that the remap was executed with scan-all-json.

## Command templates

Dry-run with summary:

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --dry-run --scan-all-json
```

Direct apply with scan-all-json:

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --apply --scan-all-json
```

Dry-run with custom output folder:

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --output-dir "<output_dir>" --dry-run --scan-all-json
```

Apply with custom output folder:

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --output-dir "<output_dir>" --apply --scan-all-json
```

## Output contract (what to report)

If dry-run is requested, report:

- `changes_found`
- `unresolved_unique_pairs`
- `remap_dryrun.csv` path when the dry-run output file is generated
- `remap_unresolved.csv` path when the unresolved file is generated

If apply is executed, report:

- that the remap run completed with scan-all-json
- `remap_applied.csv` path when the apply output file is generated
- `remap_unresolved.csv` path when the unresolved file is generated

## Output files

Default output path: `<report_folder>/remap_output`

- `remap_dryrun.csv`
- `remap_applied.csv`
- `remap_unresolved.csv`

## Mapping behavior

- Blank `To table` or `To col` means keep original unchanged.
- No-op rows where From equals To are ignored.
- Writes happen only in `--apply` mode.

## Failure handling

- If `.Report` folder is missing/invalid: return clear path error.
- If `map.csv` is missing: return clear path error.
- If headers are invalid: report required header names and stop.
- If dry-run command fails: do not continue to apply.

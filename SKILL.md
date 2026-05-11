---
name: pbir-field-remap
description: Operational workflow for remapping PBIR field references from map.csv with mandatory dry-run and explicit approval before apply.
---

# PBIR Field Remap Skill

## Use this skill when

- User asks to remap Power BI PBIR field references using a mapping CSV.
- User needs dry-run/apply execution with audit CSV outputs.

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
- Mode order: dry-run first, apply second.
- Output folder default: `<report_folder>/remap_output`

## Safety gates (mandatory)

1. Never run `--apply` before a dry-run has completed successfully.
2. Never run `--apply` without explicit user approval.
3. If path/header validation fails, stop and report exact issue.

## Execution protocol

1. Validate inputs:
- `report_folder` exists and ends with `.Report`
- `mapping_csv` exists and has required headers

2. Run dry-run:
- Use `--scan-all-json` unless user disables it.
- Capture:
  - changes found
  - unresolved unique pair count
  - output CSV paths

3. Report dry-run summary to user.

4. Ask for explicit apply approval.

5. If approved, run apply with same flags/options used for dry-run.

6. Report apply summary:
- files written
- changes applied
- output CSV paths

## Command templates

Dry-run (default recommended):

```powershell
python apply_field_remap.py "<report_folder>" --map "<mapping_csv>" --dry-run --scan-all-json
```

Apply (only after explicit approval):

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

After dry-run, report:

- `changes_found`
- `unresolved_unique_pairs`
- `remap_dryrun.csv` path
- `remap_unresolved.csv` path

After apply, report:

- `files_written`
- `changes_applied`
- `remap_applied.csv` path
- `remap_unresolved.csv` path

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

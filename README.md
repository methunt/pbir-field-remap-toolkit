# PBIR Field Remap Toolkit

This folder contains scripts to analyze and remap semantic field references in a Power BI PBIR report.

## What is included

- `apply_field_remap.py`
  - Remaps report JSON field references using a CSV mapping file.
  - Always performs a deep recursive scan of every JSON file and always writes changes in place (single mode, no dry-run).

- `SKILL.md`
  - AI skill instructions for running the remap workflow.
  - Defines required inputs (`report_folder`, `mapping_csv`) and command templates.

- `export_report_json_inventory.py`
  - Exports report JSON inventory to CSV for analysis.
  - Useful to discover current bindings before building `map.csv`.

## Repository structure

- `apply_field_remap.py`
- `export_report_json_inventory.py`
- `README.md`
- `SKILL.md`

## Requirements

- Python 3.8+
- PBIR report folder ending with `.Report`
- Mapping CSV (`map.csv`) with columns:
  - `From Table`
  - `From col`
  - `To table`
  - `To col`

## Mapping rules

- Rows with blank `To table` or `To col` are skipped (original value is kept).
- Rows where source and target are identical are skipped (no-op).
- Mapping key is `(From Table, From col)`.

## Quick start

**Warning:** the script writes report files in place with no backup and no preview mode. Commit or otherwise back up the `.Report` folder before running.

From this folder:

```powershell
python apply_field_remap.py "D:\path\to\MyReport.Report" --map "C:\path\to\map.csv"
```

## Output files

By default, outputs are written to `<report_dir>/remap_output`:

- `remap_applied.csv`
- `remap_unresolved.csv` (always written, header-only when no unresolved references are found)

You can override output location:

```powershell
python apply_field_remap.py "D:\path\to\MyReport.Report" --map "C:\path\to\map.csv" --output-dir "D:\temp\remap_logs"
```

## Inventory export usage

```powershell
python export_report_json_inventory.py "D:\path\to\MyReport.Report"
```

Default inventory output folder is `inventory_export` under the report directory:

- `FieldBindings.csv`
- `AllScalars.csv`

## Recommended workflow

1. Validate the `.Report` folder and `map.csv` path.
2. Confirm the report folder is committed to source control (or otherwise backed up) — the script writes in place with no backup.
3. Run the remap:
   `python apply_field_remap.py "<report_folder>" --map "<mapping_csv>"`
4. Open report in Power BI Desktop and validate visuals/pages.

## Using the AI skill

The skill file is in this repository root as `SKILL.md`.

When using an AI assistant that supports skills, ask it to use this skill and provide:

1. `report_folder` (path to `.Report` folder)
2. `mapping_csv` (path to `map.csv`)

Example prompt:

```text
Use the PBIR field remap skill in SKILL.md.
report_folder: D:\Project\Git\Local\dsp_refactor\Global Programmatic Dashboard\Global Programmatic.Report
mapping_csv: C:\Users\Methun.Thirumurthy\Downloads\map.csv
Run the remap and show a summary.
```

## Notes

- The script edits JSON files in-place, always.
- No automatic backup is created by the current version.
- Keep your own copy or use source control before running, if needed.

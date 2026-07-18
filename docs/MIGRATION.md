# Migration notes

- Old category JSONs were merged by ticker.
- A ticker can now belong to multiple classifications.
- `expense_ratio` was migrated as an explicit override metric.
- Legacy `dividend` values were not migrated because their meaning was inconsistent across files.
- `fixed_start_date` is replaced by pipeline state and available price history.
- WordPress now consumes JSON instead of CSV/PapaParse.

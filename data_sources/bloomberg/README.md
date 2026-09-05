# Bloomberg / FactSet full-history exports

Drop a `<column>.csv` here (a date column plus one value column) to extend a
signal whose free source is restricted. The extraction pipeline reads it and
back-fills the dates its automated source leaves blank.

| File | Covers |
|---|---|
| `credit_spread_hy.csv` | US high-yield OAS. FRED only serves this from 2023-09 due to ICE licensing; export the full history from Bloomberg (`LF98OAS Index`) or FactSet and save it here as a CSV with a date column and one value column. |

Format: any Bloomberg-style history export works as-is. The date column is
recognised case-insensitively (`date`, `Date`, `Dates`, `trade date`, …), or
falls back to the first column when it parses as dates; the value column is
any one numeric column — `PX_LAST` is the usual Bloomberg field. Date+time
strings and a UTF-8 BOM are tolerated. A missing, unreadable, or malformed
file is skipped silently — this directory is optional.

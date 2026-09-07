# Uploading Bloomberg exports

The dashboard accepts Bloomberg's original CSV history exports, one file per
security, and joins all fields on date. Do not rename columns, substitute fields
or manually convert the files into a separate signal-CSV format.

## What to export

Export the histories needed for the analysis as CSV. Each file carries a
metadata block, a blank line, and a table whose first column is `Date`. Every
additional field is preserved. `PX_LAST`, `PX_BID`,
`TOT_RETURN_INDEX_GROSS_DVDS` and other numeric Bloomberg fields can coexist.

A CSV export is the metadata block, a blank line, then the table:

```
Security,SPX Index
Start Date,1/1/2016
End Date,12/31/2025
Period,Daily

Date,PX_LAST,PX_BID
1/4/2016,2012.66,#N/A N/A
```

Trailing empty metadata cells, such as `Security,SPX Index,`, are accepted.
Placeholder-only fields are removed after merging because they carry no data.

## Converting

On the **Data** page, drop every CSV export into the one multi-file uploader.
The page joins them on date, labels fields by security, validates their generic
shape and reports gaps and statistically unusual moves. Nothing needs a command
line and no temporary signal CSV is produced.

**Dates in a CSV export** are `m/d/yyyy` or `d/m/yyyy` depending on the
terminal's locale, and for any day up to the 12th the two look the same. The
reader settles the order once per file from every date in it, the metadata's
start and end dates included: a day above 12 anywhere decides it, and a file
with none is read month first, Bloomberg's default. A file that mixes the two
is refused rather than guessed. If a merged file's dates look a month out,
check the terminal's date format setting.

The merged Bloomberg CSV is downloadable directly. Fama-French factors are
downloaded only when requested, cached by content hash, and can then be
downloaded separately or alongside Bloomberg data in a workbook.

### What it does not do

**Gaps are left as gaps.** Different indices keep different trading calendars.
Across a real ten-year pull the union was 2,610 dates with all signals present
on only 2,499 of them — `spx_close` missing 97, `vix` 65, the spreads around 80.
Those cells are left empty, which the contract treats as missing data. Filling
them here would hide from the data quality report the very thing it exists to
report; forward-filling happens later, capped and counted.

**Range breaches are flagged, not corrected.** If almost every value in a column
falls outside its documented range, the converter says so — that pattern means
the wrong field was exported. A handful of breaches is left alone, because a
genuine market dislocation looks a lot like an outlier.

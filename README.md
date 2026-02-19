# GPS Collar Telemetry Converter

A desktop application that converts GPS collar telemetry data from virtually any vendor format (Vectronic, Lotek, etc.) into a standardised four-column CSV:

```
serialnumber;time;latitude;longitude
```

The output uses semicolon-separated, quoted values and is ready for direct import into analysis pipelines such as [Movement Diagnostic](http://tkuerschner.shinyapps.io/movement-diagnostic).

## Features

- **Auto-detect delimiters** – Automatically sniffs CSV delimiters (comma, semicolon, tab, pipe).
- **Column mapping** – Map any source columns to the four target fields, with auto-guessing of common column names.
- **Custom timestamp parsing** – Optionally provide a `strftime` format string for non-standard date formats.
- **Date filtering** – Set a global start date or per-individual start dates to discard pre-deployment junk fixes.
- **Duplicate timestamp handling** – Automatically offsets duplicate timestamps by 1-second increments.
- **Preview** – Inspect the first 500 converted rows before exporting.
- **Simple GUI** – Built with Tkinter for a lightweight, dependency-minimal interface.

## Requirements

- Python 3.10+
- [pandas](https://pandas.pydata.org/)

## Usage

```bash
python converter.py
```

1. **Load** – Click *Browse…* to select your raw GPS data file (CSV or TXT).
2. **Map** – Verify or correct the auto-detected column mappings for Serial Number, Timestamp, Latitude, and Longitude.
3. **Filter** *(optional)* – Set global or per-individual start dates to exclude pre-deployment data.
4. **Options** – Toggle duplicate timestamp fixing as needed.
5. **Convert & Preview** – Click to apply the conversion and inspect the results.
6. **Export** – Click *Export CSV…* to save the standardised output.

## Output Format

| Column         | Description                          |
|----------------|--------------------------------------|
| `serialnumber` | Collar / device / animal identifier  |
| `time`         | Timestamp in `YYYY-MM-DD HH:MM:SS`  |
| `latitude`     | Decimal degrees (7 decimal places)   |
| `longitude`    | Decimal degrees (7 decimal places)   |

## Author

Tobias Kürschner, 2026

"""
GPS Collar Telemetry Data Converter
Converts virtually any GPS collar CSV data into a standardised format:
    serialnumber;time;latitude;longitude
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import csv
import os
import webbrowser
from datetime import datetime


# ─── helpers ────────────────────────────────────────────────────────────────────

def detect_delimiter(filepath: str) -> str:
    """Sniff the delimiter of a CSV file."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        sample = f.read(8192)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def load_csv(filepath: str) -> pd.DataFrame:
    """Load a CSV with auto-detected delimiter."""
    sep = detect_delimiter(filepath)
    df = pd.read_csv(filepath, sep=sep, encoding="utf-8-sig", low_memory=False)
    return df


def convert_data(
    df: pd.DataFrame,
    col_serial: str,
    col_time: str,
    col_lat: str,
    col_lon: str,
    time_format: str | None,
    global_start: datetime | None,
    per_individual_starts: dict[str, datetime] | None,
    fix_duplicates: bool,
) -> pd.DataFrame:
    """
    Map columns, filter by date, handle duplicate timestamps, and return a
    DataFrame in the target schema.
    """
    out = pd.DataFrame()
    out["serialnumber"] = df[col_serial].astype(str)

    # parse timestamps
    if time_format:
        out["time"] = pd.to_datetime(df[col_time], format=time_format, errors="coerce")
    else:
        out["time"] = pd.to_datetime(df[col_time], errors="coerce", utc=True)
        # strip timezone info so comparisons with naive datetimes work
        if out["time"].dt.tz is not None:
            out["time"] = out["time"].dt.tz_localize(None)

    out["latitude"] = pd.to_numeric(df[col_lat], errors="coerce")
    out["longitude"] = pd.to_numeric(df[col_lon], errors="coerce")

    # ── global date filter ──────────────────────────────────────────────────
    if global_start is not None:
        out = out[out["time"] >= global_start].copy()

    # ── per-individual date filters ─────────────────────────────────────────
    if per_individual_starts:
        masks = []
        for serial, start_dt in per_individual_starts.items():
            mask = (out["serialnumber"] == serial) & (out["time"] >= start_dt)
            masks.append(mask)
        # keep rows that either match a per-individual filter or whose serial
        # has no specific filter defined
        filtered_serials = set(per_individual_starts.keys())
        mask_no_filter = ~out["serialnumber"].isin(filtered_serials)
        combined = mask_no_filter
        for m in masks:
            combined = combined | m
        out = out[combined].copy()

    # ── handle duplicate timestamps ─────────────────────────────────────────
    if fix_duplicates:
        out = out.sort_values(["serialnumber", "time", "latitude", "longitude"])
        out["time"] = out.groupby(["serialnumber", "time"])["time"].transform(
            lambda g: g + pd.to_timedelta(range(len(g)), unit="s")
        )

    out = out.sort_values(["serialnumber", "time"]).reset_index(drop=True)
    return out


def export_csv(df: pd.DataFrame, filepath: str) -> None:
    """Write the converted data in the target format (semicolon-separated, quoted)."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        f.write("serialnumber;time;latitude;longitude\n")
        for _, row in df.iterrows():
            serial = str(row["serialnumber"])
            time_str = row["time"].strftime("%Y-%m-%d %H:%M:%S") if pd.notna(row["time"]) else ""
            lat = f"{row['latitude']:.7f}" if pd.notna(row["latitude"]) else ""
            lon = f"{row['longitude']:.7f}" if pd.notna(row["longitude"]) else ""
            f.write(f'"{serial}";"{time_str}";"{lat}";"{lon}"\n')


# ─── GUI ────────────────────────────────────────────────────────────────────────

class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GPS Collar Telemetry Converter")
        self.geometry("960x720")
        self.resizable(True, True)

        self.source_df: pd.DataFrame | None = None
        self.converted_df: pd.DataFrame | None = None
        self.per_individual_starts: dict[str, datetime] = {}

        self._build_ui()

    # ── UI construction ─────────────────────────────────────────────────────

    def _build_ui(self):
        # Use a main frame with padding
        main = ttk.Frame(self, padding=10)
        main.pack(fill="both", expand=True)

        # ── File selection ──────────────────────────────────────────────────
        file_frame = ttk.LabelFrame(main, text="1. Load Source File", padding=8)
        file_frame.pack(fill="x", pady=(0, 6))

        self.file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        ttk.Button(file_frame, text="Browse…", command=self._browse_file).pack(side="left")

        # ── Column mapping ──────────────────────────────────────────────────
        map_frame = ttk.LabelFrame(main, text="2. Map Columns", padding=8)
        map_frame.pack(fill="x", pady=(0, 6))

        labels = ["Serial Number", "Timestamp", "Latitude", "Longitude"]
        self.combo_vars: list[tk.StringVar] = []
        for i, label in enumerate(labels):
            ttk.Label(map_frame, text=f"{label}:").grid(row=i, column=0, sticky="w", padx=(0, 6), pady=2)
            var = tk.StringVar()
            combo = ttk.Combobox(map_frame, textvariable=var, state="readonly", width=40)
            combo.grid(row=i, column=1, sticky="w", pady=2)
            self.combo_vars.append(var)
            if i == 1:
                # Timestamp format entry next to the timestamp combo
                ttk.Label(map_frame, text="Format (optional):").grid(row=i, column=2, sticky="w", padx=(12, 6))
                self.time_fmt_var = tk.StringVar()
                fmt_entry = ttk.Entry(map_frame, textvariable=self.time_fmt_var, width=26)
                fmt_entry.grid(row=i, column=3, sticky="w")
                self.time_fmt_tooltip = ttk.Label(
                    map_frame, text="e.g. %Y-%m-%d %H:%M:%S", foreground="grey"
                )
                self.time_fmt_tooltip.grid(row=i, column=4, sticky="w", padx=(6, 0))

        # ── Filtering ───────────────────────────────────────────────────────
        filter_frame = ttk.LabelFrame(main, text="3. Date Filtering (optional)", padding=8)
        filter_frame.pack(fill="x", pady=(0, 6))

        # Global start date
        gf = ttk.Frame(filter_frame)
        gf.pack(fill="x", pady=(0, 4))
        ttk.Label(gf, text="Global start date (YYYY-MM-DD HH:MM:SS):").pack(side="left")
        self.global_start_var = tk.StringVar()
        ttk.Entry(gf, textvariable=self.global_start_var, width=22).pack(side="left", padx=(6, 0))

        # Per-individual start dates
        pf = ttk.Frame(filter_frame)
        pf.pack(fill="x")
        ttk.Label(pf, text="Per-individual start dates:").pack(anchor="w")

        pf_inner = ttk.Frame(pf)
        pf_inner.pack(fill="x")

        ttk.Label(pf_inner, text="Serial:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ind_serial_var = tk.StringVar()
        self.ind_serial_combo = ttk.Combobox(pf_inner, textvariable=self.ind_serial_var, state="readonly", width=18)
        self.ind_serial_combo.grid(row=0, column=1, sticky="w", padx=(0, 8))

        ttk.Label(pf_inner, text="Start:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.ind_start_var = tk.StringVar()
        ttk.Entry(pf_inner, textvariable=self.ind_start_var, width=22).grid(row=0, column=3, sticky="w", padx=(0, 8))

        ttk.Button(pf_inner, text="Add", command=self._add_individual_filter).grid(row=0, column=4, padx=(0, 4))
        ttk.Button(pf_inner, text="Clear All", command=self._clear_individual_filters).grid(row=0, column=5)

        self.ind_filters_var = tk.StringVar(value="(none)")
        ttk.Label(pf, textvariable=self.ind_filters_var, foreground="grey").pack(anchor="w", pady=(2, 0))

        # ── Options ─────────────────────────────────────────────────────────
        opt_frame = ttk.LabelFrame(main, text="4. Options", padding=8)
        opt_frame.pack(fill="x", pady=(0, 6))

        self.fix_dup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="Fix duplicate timestamps (add 1 s increments)", variable=self.fix_dup_var).pack(
            anchor="w"
        )

        # ── Action buttons ──────────────────────────────────────────────────
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(0, 6))

        ttk.Button(btn_frame, text="Convert & Preview", command=self._convert).pack(side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="Export CSV…", command=self._export).pack(side="left")

        self.status_var = tk.StringVar()
        ttk.Label(btn_frame, textvariable=self.status_var, foreground="green").pack(side="right")

        ttk.Button(btn_frame, text="About", command=self._show_about).pack(side="right", padx=(0, 6))
        ttk.Button(btn_frame, text="Help", command=self._show_help).pack(side="right", padx=(0, 6))

        # ── Preview table ───────────────────────────────────────────────────
        preview_frame = ttk.LabelFrame(main, text="Preview", padding=4)
        preview_frame.pack(fill="both", expand=True)

        cols = ("serialnumber", "time", "latitude", "longitude")
        self.tree = ttk.Treeview(preview_frame, columns=cols, show="headings", height=12)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=200, anchor="w")

        vsb = ttk.Scrollbar(preview_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ── callbacks ───────────────────────────────────────────────────────────

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select source GPS data file",
            filetypes=[("CSV files", "*.csv"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.source_df = load_csv(path)
        except Exception as e:
            messagebox.showerror("Load error", str(e))
            return

        self.file_var.set(path)
        columns = list(self.source_df.columns)
        for var in self.combo_vars:
            var.set("")

        # update all combo boxes with column names
        for widget in self.winfo_children():
            self._update_combos(widget, columns)

        # update individual serial combo (needs column mapping first, so populate later)
        self.ind_serial_combo["values"] = []
        self.per_individual_starts.clear()
        self._update_ind_filters_label()

        self.status_var.set(f"Loaded {len(self.source_df)} rows, {len(columns)} columns")

        # ── auto-guess column mappings ──────────────────────────────────────
        self._auto_map(columns)

    def _update_combos(self, widget, columns):
        """Recursively set combobox values."""
        if isinstance(widget, ttk.Combobox):
            widget["values"] = columns
        for child in widget.winfo_children():
            self._update_combos(child, columns)

    def _auto_map(self, columns: list[str]):
        """Try to guess which columns match the 4 target fields."""
        lower_cols = {c.lower(): c for c in columns}

        serial_hints = ["collar id", "serialnumber", "serial", "device_id", "deviceid", "id", "collar", "tag_id", "tag-id"]
        time_hints = ["acq. time [utc]", "acq. time", "timestamp", "time", "datetime", "date_time", "fix_time", "gps_date", "acquisitiontime"]
        lat_hints = ["latitude [deg]", "latitude", "lat", "y"]
        lon_hints = ["longitude [deg]", "longitude", "lon", "long", "x"]

        mapping = [serial_hints, time_hints, lat_hints, lon_hints]
        for i, hints in enumerate(mapping):
            for hint in hints:
                if hint in lower_cols:
                    self.combo_vars[i].set(lower_cols[hint])
                    break

    def _add_individual_filter(self):
        serial = self.ind_serial_var.get().strip()
        start_str = self.ind_start_var.get().strip()
        if not serial or not start_str:
            messagebox.showwarning("Input needed", "Select a serial number and enter a start date.")
            return
        try:
            dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(start_str, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Date error", "Use format YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
                return
        self.per_individual_starts[serial] = dt
        self._update_ind_filters_label()
        self.ind_start_var.set("")

    def _clear_individual_filters(self):
        self.per_individual_starts.clear()
        self._update_ind_filters_label()

    def _update_ind_filters_label(self):
        if not self.per_individual_starts:
            self.ind_filters_var.set("(none)")
        else:
            parts = [f"{s}: {d.strftime('%Y-%m-%d %H:%M:%S')}" for s, d in self.per_individual_starts.items()]
            self.ind_filters_var.set(" | ".join(parts))

    def _get_mappings(self) -> tuple[str, str, str, str] | None:
        names = ["Serial Number", "Timestamp", "Latitude", "Longitude"]
        vals = [v.get() for v in self.combo_vars]
        for name, val in zip(names, vals):
            if not val:
                messagebox.showwarning("Mapping missing", f"Please map the '{name}' column.")
                return None
        return tuple(vals)  # type: ignore

    def _parse_global_start(self) -> datetime | None:
        s = self.global_start_var.get().strip()
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.strptime(s, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Date error", "Global start date must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
                return None

    def _convert(self):
        if self.source_df is None:
            messagebox.showwarning("No data", "Load a source file first.")
            return

        mappings = self._get_mappings()
        if mappings is None:
            return

        col_serial, col_time, col_lat, col_lon = mappings
        global_start = self._parse_global_start()
        time_fmt = self.time_fmt_var.get().strip() or None

        try:
            self.converted_df = convert_data(
                df=self.source_df,
                col_serial=col_serial,
                col_time=col_time,
                col_lat=col_lat,
                col_lon=col_lon,
                time_format=time_fmt,
                global_start=global_start,
                per_individual_starts=self.per_individual_starts or None,
                fix_duplicates=self.fix_dup_var.get(),
            )
        except Exception as e:
            messagebox.showerror("Conversion error", str(e))
            return

        # populate individual serial combo now that we know serials
        serials = sorted(self.converted_df["serialnumber"].unique())
        self.ind_serial_combo["values"] = serials

        # populate preview tree
        self.tree.delete(*self.tree.get_children())
        for _, row in self.converted_df.head(500).iterrows():
            time_str = row["time"].strftime("%Y-%m-%d %H:%M:%S") if pd.notna(row["time"]) else ""
            lat_str = f"{row['latitude']:.7f}" if pd.notna(row["latitude"]) else ""
            lon_str = f"{row['longitude']:.7f}" if pd.notna(row["longitude"]) else ""
            self.tree.insert("", "end", values=(row["serialnumber"], time_str, lat_str, lon_str))

        n = len(self.converted_df)
        shown = min(n, 500)
        self.status_var.set(f"Converted: {n} rows (showing {shown})")

    def _export(self):
        if self.converted_df is None or self.converted_df.empty:
            messagebox.showwarning("Nothing to export", "Convert data first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save converted data",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            export_csv(self.converted_df, path)
            self.status_var.set(f"Exported {len(self.converted_df)} rows → {os.path.basename(path)}")
            messagebox.showinfo("Done", f"File saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    def _show_about(self):
        win = tk.Toplevel(self)
        win.title("About")
        win.geometry("480x360")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        frame = ttk.Frame(win, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="GPS Collar Telemetry Converter", font=("Segoe UI", 14, "bold")).pack(pady=(0, 4))
        ttk.Label(frame, text="Version 1.0", font=("Segoe UI", 10)).pack()

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        info_top = (
            "Author: Tobias Kürschner 2026 \n\n"
            "Purpose:\n"
            "Convert GPS collar telemetry data from virtually any\n"
            "vendor format into a standardised four-column CSV:\n"
            "    serialnumber ; time ; latitude ; longitude\n\n"
            "The output uses semicolon-separated, quoted values and\n"
            "is ready for direct import into analysis pipelines:"
        )
        ttk.Label(frame, text=info_top, justify="left", wraplength=440).pack(anchor="w")

        # clickable URL
        url = "http://tkuerschner.shinyapps.io/movement-diagnostic"
        link = tk.Label(
            frame, text=url, fg="blue", cursor="hand2",
            font=("Segoe UI", 9, "underline"), anchor="w",
        )
        link.pack(anchor="w", pady=(4, 4))
        link.bind("<Button-1>", lambda e: webbrowser.open(url))

        ttk.Label(frame, text="Built with Python, pandas & Tkinter.", justify="left").pack(anchor="w")

        ttk.Button(frame, text="Close", command=win.destroy).pack(pady=(14, 0))

    def _show_help(self):
        win = tk.Toplevel(self)
        win.title("Help – How to Use")
        win.geometry("620x520")
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        text = tk.Text(frame, wrap="word", font=("Segoe UI", 10), padx=10, pady=10)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vsb.set)
        text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # configure heading tag
        text.tag_configure("heading", font=("Segoe UI", 11, "bold"), spacing3=4)
        text.tag_configure("subheading", font=("Segoe UI", 10, "bold"), spacing1=8, spacing3=2)

        sections = [
            ("heading", "GPS Collar Telemetry Converter – Help\n"),
            ("subheading", "Overview\n"),
            (None,
             "This tool converts GPS collar data exported from any vendor "
             "(Vectronic, Lotek, etc.) into a standardised "
             "four-column format:\n\n"
             "    serialnumber ; time ; latitude ; longitude\n\n"
             "The output is a semicolon-delimited CSV with quoted values, "
             "ready for further analysis.\n\n"),

            ("subheading", "Step 1 – Load Source File\n"),
            (None,
             "Click \"Browse…\" and select your raw GPS data file (CSV or TXT). "
             "The delimiter (comma, semicolon, tab, pipe) is detected automatically. "
             "After loading, the status bar shows the number of rows and columns found.\n\n"),

            ("subheading", "Step 2 – Map Columns\n"),
            (None,
             "Use the four dropdown menus to tell the converter which columns in "
             "your source file correspond to:\n\n"
             "  • Serial Number – the collar / device / animal identifier\n"
             "  • Timestamp – the acquisition date-time of each fix\n"
             "  • Latitude – decimal degrees\n"
             "  • Longitude – decimal degrees\n\n"
             "The converter tries to auto-detect common column names (e.g. "
             "\"Collar ID\", \"Acq. Time [UTC]\", \"Latitude [deg]\"). "
             "Verify and correct the mapping if needed.\n\n"
             "Timestamp format (optional):\n"
             "If automatic date parsing fails, provide a Python strftime format "
             "string, for example:\n"
             "  %Y-%m-%d %H:%M:%S    →  2025-10-15 20:45:52\n"
             "  %d/%m/%Y %H:%M        →  15/10/2025 20:45\n"
             "  %m-%d-%Y %I:%M %p    →  10-15-2025 08:45 PM\n"
             "Leave the field empty to use automatic parsing.\n\n"),

            ("subheading", "Step 3 – Date Filtering (optional)\n"),
            (None,
             "GPS collars often contain junk fixes recorded before deployment "
             "(e.g. test fixes with dates far in the future or past). "
             "Use date filtering to discard them.\n\n"
             "Global start date:\n"
             "Enter a date (YYYY-MM-DD) or date-time (YYYY-MM-DD HH:MM:SS). "
             "All rows with a timestamp before this date are discarded, "
             "regardless of serial number.\n\n"
             "Per-individual start dates:\n"
             "If different collars were deployed on different dates, you can "
             "set a unique start date for each serial number:\n"
             "  1. First run \"Convert & Preview\" so the serial dropdown is "
             "populated.\n"
             "  2. Select a serial number, enter a start date, and click \"Add\".\n"
             "  3. Repeat for each individual as needed.\n"
             "  4. Use \"Clear All\" to remove all individual filters.\n\n"
             "Individual filters override the global filter for that serial "
             "number. Serials without an individual filter still use the global "
             "filter (if set).\n\n"),

            ("subheading", "Step 4 – Options\n"),
            (None,
             "Fix duplicate timestamps:\n"
             "Some data sources produce rows with identical serial + timestamp "
             "combinations (e.g. re-transmitted fixes). When this option is "
             "enabled, duplicate timestamps within the same individual are "
             "offset by 1-second increments so every row has a unique time. "
             "This is required by most movement-analysis packages.\n\n"),

            ("subheading", "Step 5 – Convert & Preview\n"),
            (None,
             "Click \"Convert & Preview\" to apply the column mapping, filters, "
             "and duplicate-fix logic. The first 500 rows are shown in the "
             "preview table. Check that the values look correct before "
             "exporting.\n\n"),

            ("subheading", "Step 6 – Export\n"),
            (None,
             "Click \"Export CSV…\" to save the converted data. The output "
             "file uses:\n"
             "  • Semicolon (;) as the column separator\n"
             "  • Double quotes around every value\n"
             "  • Header: serialnumber;time;latitude;longitude\n"
             "  • Coordinates with 7 decimal places\n"
             "  • Timestamps in YYYY-MM-DD HH:MM:SS format\n\n"),

            ("subheading", "Tips & Troubleshooting\n"),
            (None,
             "• If columns are not detected correctly, make sure the source "
             "file is a well-formed CSV/TXT with a header row.\n"
             "• Rows with unparseable timestamps or coordinates are kept but "
             "will have empty values – review them in the preview.\n"
             "• Very large files (>1 M rows) may take a moment to convert; "
             "the window may appear unresponsive briefly.\n"
             "• The converter reads the file as UTF-8. If your file uses a "
             "different encoding, re-save it as UTF-8 first.\n"),
        ]

        for tag, content in sections:
            if tag:
                text.insert("end", content, tag)
            else:
                text.insert("end", content)

        text.configure(state="disabled")

        btn_frame = ttk.Frame(win, padding=(10, 0, 10, 10))
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right")
        

# ─── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ConverterApp()
    app.mainloop()

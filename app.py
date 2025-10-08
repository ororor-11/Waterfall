
import io
import re
import textwrap
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import rcParams
import streamlit as st

# =========================
# Page setup
# =========================
st.set_page_config(page_title="Cash Waterfall", layout="wide")

# =========================
# Helpers: headers & numbers
# =========================
DASHES = {"-", "–", "—", "−"}  # minus & dash lookalikes

def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Drop BOM, trim spaces, force lowercase for headers."""
    cleaned = []
    for c in df.columns:
        s = str(c)
        try:
            s = s.encode("utf-8").decode("utf-8-sig")  # remove BOM if present
        except Exception:
            pass
        cleaned.append(s.strip().lower())
    df.columns = cleaned
    return df

def coerce_numeric_col(series: pd.Series, dash_zero: bool = True) -> pd.Series:
    """Turn things like '£ 2,296', '(27)', '1.234,56', '—' into real numbers."""
    s = series.astype(str)

    # Trim & remove currency symbols and spaces (including non-breaking)
    s = (s.str.strip()
          .str.replace(r"[£$€]", "", regex=True)
          .str.replace("\u00A0", "", regex=False)  # nbsp
          .str.replace(r"\s+", "", regex=True))

    # Convert (123) to -123
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)

    # Remove apostrophe thousands (e.g., 1'234)
    s = s.str.replace("'", "", regex=False)

    # If both comma and dot appear -> assume comma is thousands (1,234.56)
    both = s.str.contains(",") & s.str.contains(r"\.")
    s = s.where(~both, s.str.replace(",", "", regex=False))

    # If only comma appears -> treat as European decimal (1.234,56 -> 1234.56)
    only_comma = s.str.contains(",") & ~s.str.contains(r"\.")
    s = s.where(~only_comma,
                s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))

    # Treat lone dashes as zero, if desired
    if dash_zero:
        s = s.replace({d: "0" for d in DASHES})

    # Empty strings to NaN -> will be caught as non-numeric
    s = s.replace({"": pd.NA})

    return pd.to_numeric(s, errors="coerce")

# =========================
# Styles & fonts
# =========================
try:
    rcParams['font.family'] = 'Century Gothic'
except Exception:
    rcParams['font.family'] = 'DejaVu Sans'
rcParams['font.size'] = 11

# =========================
# Sidebar controls
# =========================
st.sidebar.header("🎨 Appearance")
color_start = st.sidebar.color_picker("Start/End color", "#4A90E2")
color_pos   = st.sidebar.color_picker("Positive bar color", "#4DB6AC")
color_neg   = st.sidebar.color_picker("Negative bar color", "#D96C6C")
axis_color  = st.sidebar.color_picker("Axis/text color", "#333333")
font_size   = st.sidebar.slider("Base font size", 8, 20, 11)
show_values = st.sidebar.checkbox("Show values on bars", True)

st.sidebar.header("🧾 Text")
title_template = st.sidebar.text_input("Chart title template", value="{entity} – {period} Cash Waterfall")
currency_prefix = st.sidebar.text_input("Value prefix (e.g., £, $, €)", value="£")
value_decimals = st.sidebar.slider("Value decimals", 0, 3, 0)

st.sidebar.header("📐 Units & Filters")
# Unit maps
unit_scale = {
    "Pounds (£)": 1.0,
    "Thousands (£'000)": 1_000.0,
    "Millions (£m)": 1_000_000.0,
}
unit_suffix = {
    "Pounds (£)": "£",
    "Thousands (£'000)": "£'000",
    "Millions (£m)": "£m",
}

csv_unit = st.sidebar.selectbox("My CSV numbers are in", list(unit_scale.keys()), index=1)  # default to thousands
display_unit = st.sidebar.selectbox("Display units", list(unit_scale.keys()), index=1)
conversion_factor = unit_scale[csv_unit] / unit_scale[display_unit]  # multiply raw by this to display

# Y label (auto from display unit) but allow user to override
default_ylabel = f"Cash {unit_suffix[display_unit]}"
y_label = st.sidebar.text_input("Y-axis label", value=default_ylabel)

min_label_threshold = st.sidebar.number_input(
    "Hide labels below this absolute value (after conversion)",
    min_value=0.0, value=0.0, step=1.0
)

st.sidebar.header("✏️ Data editing")
enable_editor = st.sidebar.checkbox("Enable table editor before plotting", False)

# =========================
# Sample CSV download
# =========================
sample_csv = """entity,period,start,label,amount
DevCo,2025-08,2242,Financing,2472
DevCo,2025-08,2242,Intercompany,-2473
DevCo,2025-08,2242,Overheads,-95
DevCo,2025-08,2242,Payroll,-25
DevCo,2025-08,2242,Project Costs,-638
DevCo,2025-08,2242,Corp Tax,136
DevCo,2025-08,2242,FX/Other,10
"""

st.title("Cash Waterfall Generator")
st.download_button(
    label="⬇️ Download sample CSV",
    data=sample_csv,
    file_name="sample_waterfall.csv",
    mime="text/csv",
    help="Click to download a sample CSV you can upload below."
)

with st.expander("CSV format help"):
    st.code(textwrap.dedent("""
entity,period,start,label,amount
DevCo,2025-08,2242,Financing,2472
DevCo,2025-08,2242,Intercompany,-2473
DevCo,2025-08,2242,Overheads,-95
"""))

# =========================
# Waterfall plotting
# =========================
def format_value(v: float, prefix: str = "", decimals: int = 0) -> str:
    """Format numbers with commas, decimals, and optional currency prefix. Avoid '-0'."""
    try:
        rounded = round(float(v), decimals)
        # Avoid "-0" and "-0.0"
        if abs(rounded) < (0.5 * (10 ** -decimals)):
            rounded = 0.0
        return f"{prefix}{rounded:,.{decimals}f}"
    except Exception:
        return str(v)

def plot_waterfall(start, moves, labels, title):
    # Apply global font size
    rcParams['font.size'] = font_size

    labels2 = ["Start"] + list(labels) + ["End"]
    values = list(moves)

    cum = [start]
    for v in values:
        cum.append(cum[-1] + v)
    end_val = cum[-1]

    x = list(range(len(labels2)))
    fig, ax = plt.subplots(figsize=(10, 5))

    # start bar
    ax.bar([0], [start], width=0.6, color=color_start)
    if show_values and abs(start) >= min_label_threshold:
        ax.text(0, start/2 if start != 0 else 0.1, format_value(start, currency_prefix, value_decimals),
                ha="center", va="center", color=axis_color, fontsize=font_size, weight="bold")

    level = start
    for i, (lab, v) in enumerate(zip(labels, values), start=1):
        color = color_pos if v > 0 else color_neg
        ax.bar([i], [v], bottom=[level], width=0.6, color=color)
        if show_values and abs(v) >= min_label_threshold:
            ax.text(i, level + v/2, format_value(v, currency_prefix, value_decimals),
                    ha="center", va="center", color=axis_color, fontsize=font_size, weight="bold")
        level += v

    ax.bar([len(labels2)-1], [end_val], width=0.6, color=color_start)
    if show_values and abs(end_val) >= min_label_threshold:
        ax.text(len(labels2)-1, end_val/2 if end_val != 0 else 0.1, format_value(end_val, currency_prefix, value_decimals),
                ha="center", va="center", color=axis_color, fontsize=font_size, weight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels2, rotation=45, ha="right", color=axis_color)
    ax.set_title(title, color=axis_color, fontsize=font_size+3, weight="bold")
    ax.axhline(0, linewidth=1, color="lightgrey")
    ax.set_ylabel(y_label, color=axis_color)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("lightgrey")
    ax.spines["bottom"].set_color("lightgrey")
    ax.tick_params(axis="y", colors=axis_color)
    ax.tick_params(axis="x", colors=axis_color)
    plt.tight_layout()
    return fig

# =========================
# Validation
# =========================
def validate_df(df: pd.DataFrame):
    errors = []
    required = {"entity","period","start","label","amount"}

    df = normalize_headers(df)
    missing = required - set(df.columns)
    if missing:
        errors.append(f"Missing columns: {', '.join(sorted(missing))}")
        return df, errors, pd.DataFrame()

    # Clean numeric columns
    df["start"] = coerce_numeric_col(df["start"], dash_zero=True)
    df["amount"] = coerce_numeric_col(df["amount"], dash_zero=True)

    # Flag any rows that still failed to parse
    bad = df[df["start"].isna() | df["amount"].isna()]
    if not bad.empty:
        errors.append("Non-numeric values found in 'start' or 'amount'.")

    # Ensure single start per (entity, period)
    starts = df.groupby(["entity","period"])["start"].nunique()
    bad_start = starts[starts > 1]
    if not bad_start.empty:
        errors.append("Multiple different 'start' values found for the same entity/period.")

    return df, errors, bad

# =========================
# File upload & filters
# =========================
file = st.file_uploader("Upload CSV", type=["csv"])
period_filter = st.text_input("Optional: filter by period (e.g., 2025-08)")
entity_filter = st.text_input("Optional: filter by entity (comma-separated)")

if file:
    # Auto-detect delimiter, handle encoding oddities, avoid default NaN so we can custom-parse
    df = pd.read_csv(file, sep=None, engine="python", encoding="utf-8", keep_default_na=False)
    df = normalize_headers(df)

    df, errs, bad = validate_df(df)
    if errs:
        st.error("\n".join(errs))
        with st.expander("Detected headers"):
            st.write(list(df.columns))
        if not bad.empty:
            with st.expander("Show rows with non-numeric values"):
                st.dataframe(bad[["entity","period","label","start","amount"]].head(200))
    else:
        # Filters
        if period_filter:
            df = df[df["period"].astype(str) == period_filter]
        if entity_filter:
            keep = [e.strip() for e in entity_filter.split(",") if e.strip()]
            if keep:
                df = df[df["entity"].isin(keep)]

        if df.empty:
            st.warning("No rows after filtering.")
        else:
            # Optional editor
            if enable_editor:
                st.info("Editing enabled: changes here are used for plotting but not saved anywhere.")
                df = st.data_editor(df, num_rows="dynamic", height=350)
                # Re-coerce numeric in case user typed currency symbols
                if "start" in df.columns:
                    df["start"] = coerce_numeric_col(df["start"], dash_zero=True)
                if "amount" in df.columns:
                    df["amount"] = coerce_numeric_col(df["amount"], dash_zero=True)

            # Build charts per (entity, period)
            for (entity_name, period), g in df.groupby(["entity","period"], sort=True):
                # Convert from CSV units to display units
                start_val = float(g["start"].iloc[0]) * conversion_factor
                labels = g["label"].astype(str).tolist()
                moves  = (g["amount"].astype(float) * conversion_factor).tolist()

                title  = title_template.format(entity=entity_name, period=period)
                fig = plot_waterfall(start_val, moves, labels, title)
                st.pyplot(fig, clear_figure=True)

                # download as PNG
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
                buf.seek(0)
                st.download_button(
                    label=f"Download {entity_name} {period} PNG",
                    data=buf,
                    file_name=f"{entity_name}-{period}-waterfall.png",
                    mime="image/png"
                )

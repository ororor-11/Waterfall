
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

# Defaults (can be overridden by sidebar controls)
COLOR_AXIS_DEFAULT = "#333333"
COLOR_START_END_DEFAULT = "#4A90E2"
COLOR_POSITIVE_DEFAULT  = "#4DB6AC"
COLOR_NEGATIVE_DEFAULT  = "#D96C6C"

# =========================
# Sidebar controls
# =========================
st.sidebar.header("🎨 Appearance")

color_start = st.sidebar.color_picker("Start/End color", COLOR_START_END_DEFAULT)
color_pos   = st.sidebar.color_picker("Positive bar color", COLOR_POSITIVE_DEFAULT)
color_neg   = st.sidebar.color_picker("Negative bar color", COLOR_NEGATIVE_DEFAULT)
axis_color  = st.sidebar.color_picker("Axis/text color", COLOR_AXIS_DEFAULT)

font_size   = st.sidebar.slider("Base font size", 8, 20, 11)
show_values = st.sidebar.checkbox("Show values on bars", True)

st.sidebar.header("🧾 Text")
title_template = st.sidebar.text_input("Chart title template", value="{entity} – {period} Cash Waterfall")
y_label        = st.sidebar.text_input("Y-axis label", value="Cash £'000")
currency_prefix = st.sidebar.text_input("Value prefix (e.g., £, $, €)", value="£")

st.sidebar.header("📐 Scale & Filters")
scale_label = st.sidebar.selectbox("Display units", ["1 (raw)", "Thousands (×1,000)", "Millions (×1,000,000)"], index=1)
scale_map = {"1 (raw)": 1.0, "Thousands (×1,000)": 1_000.0, "Millions (×1,000,000)": 1_000_000.0}
display_scale = scale_map[scale_label]

min_label_threshold = st.sidebar.number_input("Hide labels below this absolute value (after scaling)", min_value=0.0, value=0.0, step=1.0)

st.sidebar.header("✏️ Data editing")
enable_editor = st.sidebar.checkbox("Enable table editor before plotting", False)

# =========================
# Sample CSV download
# =========================
sample_csv = """entity,period,start,label,amount
DevCo,2025-07,2296,Intercompany,1151
DevCo,2025-07,2296,Overheads,-27
DevCo,2025-07,2296,Project Costs,-562
OpCo,2025-07,1386,Financing,15737
OpCo,2025-07,1386,Project Costs,-14380
TopCo,2025-07,2344,Intercompany,-1151
TopCo,2025-07,2344,Financing,-15737
TopCo,2025-07,2344,Overheads,-27
TopCo,2025-07,2344,Equity Injection,21000
Group,2025-07,6026,Project Costs,-16847
Group,2025-07,6026,Overheads,-54
Group,2025-07,6026,Financing,15737
Group,2025-07,6026,Equity Injection,21000
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
DevCo,2025-07,2296,Intercompany,1151
DevCo,2025-07,2296,Overheads,-27
OpCo,2025-07,1386,Financing,15737
Group,2025-07,6026,Project Costs,-16847
"""))

# =========================
# Waterfall plotting
# =========================
def format_value(v: float, prefix: str = "") -> str:
    """Format numbers with commas and optional currency prefix (already scaled)."""
    try:
        return f"{prefix}{v:,.0f}"
    except Exception:
        return str(v)

def plot_waterfall(start, moves, labels, title):
    # Apply global font size
    rcParams['font.size'] = font_size

    # Filter tiny movements for labeling (but still plot bars)
    filtered_for_plot = list(zip(labels, moves))
    labels2 = ["Start"] + [lab for lab, _ in filtered_for_plot] + ["End"]
    values = [val for _, val in filtered_for_plot]

    cum = [start]
    for v in values:
        cum.append(cum[-1] + v)
    end_val = cum[-1]

    x = list(range(len(labels2)))
    fig, ax = plt.subplots(figsize=(9, 5))

    # start bar
    ax.bar([0], [start], width=0.6, color=color_start)
    if show_values and abs(start) >= min_label_threshold:
        ax.text(0, start/2 if start != 0 else 0.1, format_value(start, currency_prefix),
                ha="center", va="center", color=axis_color, fontsize=font_size, weight="bold")

    level = start
    for i, (lab, v) in enumerate(filtered_for_plot, start=1):
        color = color_pos if v > 0 else color_neg
        ax.bar([i], [v], bottom=[level], width=0.6, color=color)
        if show_values and abs(v) >= min_label_threshold:
            ax.text(i, level + v/2, format_value(v, currency_prefix),
                    ha="center", va="center", color=axis_color, fontsize=font_size, weight="bold")
        level += v

    ax.bar([len(labels2)-1], [end_val], width=0.6, color=color_start)
    if show_values and abs(end_val) >= min_label_threshold:
        ax.text(len(labels2)-1, end_val/2 if end_val != 0 else 0.1, format_value(end_val, currency_prefix),
                ha="center", va="center", color=axis_color, fontsize=font_size, weight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels2, rotation=45, ha="right", color=axis_color)
    ax.set_title(title, color=axis_color, fontsize=font_size+2, weight="bold")
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
period_filter = st.text_input("Optional: filter by period (e.g., 2025-07)")
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
                # Scale for display
                start_val = float(g["start"].iloc[0]) / display_scale
                labels = g["label"].astype(str).tolist()
                moves  = (g["amount"].astype(float) / display_scale).tolist()

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

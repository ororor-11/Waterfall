
import io
import textwrap
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import rcParams
import streamlit as st

# ---- Styles & fonts ----
try:
    rcParams['font.family'] = 'Century Gothic'
except Exception:
    rcParams['font.family'] = 'DejaVu Sans'
rcParams['font.size'] = 11

COLOR_START_END = "#4A90E2"
COLOR_POSITIVE  = "#4DB6AC"
COLOR_NEGATIVE  = "#D96C6C"
COLOR_AXIS      = "#333333"

def plot_waterfall(start: float, moves: list[float], labels: list[str], title: str):
    # filter out zeros & normalize labels
    filtered = [(lab.replace("+ ","").replace("- ",""), val) for lab, val in zip(labels, moves) if float(val) != 0]
    labels2 = ["Start"] + [lab for lab, _ in filtered] + ["End"]
    values = [val for _, val in filtered]

    cum = [start]
    for v in values:
        cum.append(cum[-1] + v)
    end_val = cum[-1]

    x = list(range(len(labels2)))
    fig, ax = plt.subplots(figsize=(9,5))

    # start bar
    ax.bar([0], [start], width=0.6, color=COLOR_START_END)
    ax.text(0, start/2 if start != 0 else 0.1, f"{start:,.0f}", ha="center", va="center", color="black", fontsize=11, weight="bold")

    level = start
    for i, (lab, v) in enumerate(filtered, start=1):
        color = COLOR_POSITIVE if v > 0 else COLOR_NEGATIVE
        ax.bar([i], [v], bottom=[level], width=0.6, color=color)
        ax.text(i, level + v/2, f"{v:,.0f}", ha="center", va="center", color="black", fontsize=11, weight="bold")
        level += v

    ax.bar([len(labels2)-1], [end_val], width=0.6, color=COLOR_START_END)
    ax.text(len(labels2)-1, end_val/2 if end_val != 0 else 0.1, f"{end_val:,.0f}", ha="center", va="center", color="black", fontsize=11, weight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels2, rotation=45, ha="right", color=COLOR_AXIS)
    ax.set_title(title, color=COLOR_AXIS, fontsize=13, weight="bold")
    ax.axhline(0, linewidth=1, color="lightgrey")
    ax.set_ylabel("Cash £'000", color=COLOR_AXIS)
    for s in ["top","right"]:
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("lightgrey")
    ax.spines["bottom"].set_color("lightgrey")
    ax.tick_params(axis="y", colors=COLOR_AXIS)
    ax.tick_params(axis="x", colors=COLOR_AXIS)
    plt.tight_layout()
    return fig

def validate_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    errors = []
    required = {"entity","period","start","label","amount"}
    missing = required - set(map(str.lower, df.columns))
    if missing:
        errors.append(f"Missing columns: {', '.join(sorted(missing))}")
        return df, errors

    # normalize col names
    df = df.rename(columns={c: c.lower() for c in df.columns})
    # coerce types
    for col in ["start","amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["start","amount"]].isnull().any().any():
        errors.append("Non-numeric values found in 'start' or 'amount'.")
    # ensure single start per (entity, period)
    starts = df.groupby(["entity","period"])["start"].nunique()
    bad = starts[starts > 1]
    if not bad.empty:
        errors.append("Multiple different 'start' values found for the same entity/period.")
    return df, errors

st.set_page_config(page_title="Cash Waterfall", layout="wide")
st.title("Cash Waterfall Generator")

with st.expander("CSV format help"):
    st.code(textwrap.dedent("""
entity,period,start,label,amount
DevCo,2025-07,2296,Intercompany,1151
DevCo,2025-07,2296,Overheads,-27
OpCo,2025-07,1386,Financing,15737
Group,2025-07,6026,Project Costs,-16847
"""))


file = st.file_uploader("Upload CSV", type=["csv"])
period_filter = st.text_input("Optional: filter by period (e.g., 2025-07)")
entity_filter = st.text_input("Optional: filter by entity (comma-separated)")

if file:
    df = pd.read_csv(file)
    df, errs = validate_df(df)
    if errs:
        st.error("\\n".join(errs))
    else:
        if period_filter:
            df = df[df["period"].astype(str) == period_filter]
        if entity_filter:
            keep = [e.strip() for e in entity_filter.split(",") if e.strip()]
            if keep:
                df = df[df["entity"].isin(keep)]

        if df.empty:
            st.warning("No rows after filtering.")
        else:
            # build charts per (entity, period)
            for (entity, period), g in df.groupby(["entity","period"]):
                start_val = float(g["start"].iloc[0])
                labels = g["label"].tolist()
                moves  = g["amount"].astype(float).tolist()
                title  = f"{entity} – {period} Cash Waterfall"
                fig = plot_waterfall(start_val, moves, labels, title)
                st.pyplot(fig, clear_figure=True)

                # download as PNG
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
                buf.seek(0)
                st.download_button(
                    label=f"Download {entity} {period} PNG",
                    data=buf,
                    file_name=f"{entity}-{period}-waterfall.png",
                    mime="image/png"
                )

"""
Builds the outputs people look at:
  docs/index.html        one-page interactive dashboard (served by GitHub Pages)
  docs/img/*.png         static charts used in the README

Run after build_index.py:  python src/build_dashboard.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT, DOCS = ROOT / "output", ROOT / "docs"
IMG = DOCS / "img"

# Validated categorical slots (colour-blind safe as a set of 3), plus a neutral for "Steady".
SEG_COLORS = {"Double pressure": "#2a78d6", "Volume hotspot": "#eb6834",
              "Saturation hotspot": "#1baf7a", "Steady": "#b5b4ae"}
SEG_ORDER = ["Double pressure", "Volume hotspot", "Saturation hotspot", "Steady"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def png_charts(d: pd.DataFrame, st: pd.DataFrame) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK})

    # 1. Segment map: volume (x, log) vs growth per inhabitant (y)
    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=150)
    style(ax)
    for seg in reversed(SEG_ORDER):
        s = d[d.segment == seg]
        ax.scatter(s.new_units_12m, s.new_per_1000_12m, s=28, c=SEG_COLORS[seg],
                   edgecolors="white", linewidths=0.8, label=f"{seg} ({len(s)})", zorder=3)
    offsets = {"Osnabrück (district)": (6, -12)}
    for _, r in d.head(5).iterrows():
        ax.annotate(r.district, (r.new_units_12m, r.new_per_1000_12m), xytext=offsets.get(r.district, (6, 4)),
                    textcoords="offset points", fontsize=8, color=INK2)
    ax.set_xscale("log")
    ax.set_xticks([300, 1000, 3000, 10000])
    ax.set_xticklabels(["300", "1,000", "3,000", "10,000"])
    ax.minorticks_off()
    ax.axvline(d.new_units_12m.quantile(0.75), color=INK2, lw=0.8, ls=":")
    ax.axhline(d.new_per_1000_12m.quantile(0.75), color=INK2, lw=0.8, ls=":")
    ax.set_xlabel("New solar systems in the last 12 months (log scale)", color=INK2)
    ax.set_ylabel("New systems per 1,000 inhabitants", color=INK2)
    ax.set_title("400 German districts by connection volume and growth rate",
                 loc="left", fontsize=12, color=INK)
    h, l = ax.get_legend_handles_labels()
    ax.legend(h[::-1], l[::-1], frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(IMG / "segments.png")
    plt.close(fig)

    # 2. Top 20 by index
    t = d.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.barh(t.district, t.grid_pressure_index, color=[SEG_COLORS[s] for s in t.segment], height=0.7)
    for y, v in enumerate(t.grid_pressure_index):
        ax.text(v + 0.6, y, f"{v:.1f}", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Grid Pressure Index (0–100)", color=INK2)
    ax.set_title("Top 20 districts by Grid Pressure Index", loc="left", fontsize=12, color=INK)
    handles = [plt.Rectangle((0, 0), 1, 1, color=SEG_COLORS[s]) for s in SEG_ORDER[:3]]
    ax.legend(handles, SEG_ORDER[:3], frameon=False, fontsize=8, loc="lower center",
              bbox_to_anchor=(0.5, 1.0), ncol=3)
    ax.set_title("Top 20 districts by Grid Pressure Index", loc="left", fontsize=12, color=INK, pad=24)
    fig.tight_layout()
    fig.savefig(IMG / "top20.png")
    plt.close(fig)

    # 3. States: growth per inhabitant
    s = st.sort_values("new_per_1000_12m")
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.barh(s.bundesland, s.new_per_1000_12m, color="#2a78d6", height=0.7)
    for y, v in enumerate(s.new_per_1000_12m):
        ax.text(v + 0.15, y, f"{v:.1f}", va="center", fontsize=8, color=INK2)
    ax.set_xlabel("New solar systems per 1,000 inhabitants, last 12 months", color=INK2)
    ax.set_title("Growth by federal state", loc="left", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(IMG / "states.png")
    plt.close(fig)


def html(d: pd.DataFrame, st: pd.DataFrame, summary: dict, playbook: dict) -> str:
    rows = d[["rank", "district", "bundesland", "segment", "grid_pressure_index", "einwohner",
              "new_units_12m", "new_per_1000_12m", "density_per_1000", "storage_share"]].copy()
    rows["storage_share"] = (rows["storage_share"] * 100).round(0)
    data = {
        "rows": rows.round(1).to_dict("records"),
        "states": st[["bundesland", "new_per_1000_12m"]].round(2).to_dict("records"),
        "summary": summary,
        "playbook": playbook,
        "order": SEG_ORDER,
    }
    template = (ROOT / "src" / "dashboard_template.html").read_text(encoding="utf-8")
    return template.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))


def main() -> None:
    import build_index as bi
    d = pd.read_csv(OUT / "district_index.csv")
    st = pd.read_csv(OUT / "state_summary.csv")
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    png_charts(d, st)
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(html(d, st, summary, bi.PLAYBOOK), encoding="utf-8")
    print("dashboard and charts written")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()

"""
Grid Pressure Index: where German distribution grids are under the most pressure
from rooftop solar, batteries and balcony solar.

Input : official Marktstammdatenregister data aggregated per municipality
        (data/raw/photovoltaik-gemeinden-deutschland-2026-10-02.csv)
Output: output/district_index.csv   one row per district (Kreis), ranked
        output/state_summary.csv    one row per federal state
        output/summary.json         headline numbers used in the README

Run:   python src/build_index.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "photovoltaik-gemeinden-deutschland-2026-10-02.csv"
OUT = ROOT / "output"

# Weights of the four index components. They add up to 1.
WEIGHTS = {
    "density": 0.30,       # how saturated the low-voltage grid already is
    "growth_rate": 0.30,   # how fast new systems are being added, per inhabitant
    "volume": 0.30,        # how many new connections the grid operator has to handle
    "storage_share": 0.10, # batteries change load profiles and add complexity
}


def load(path: Path = RAW) -> pd.DataFrame:
    df = pd.read_csv(path)
    expected = {"ags", "bundesland", "kreis", "einheiten_in_betrieb", "einwohner",
                "balkonkraftwerke", "gebaeudesolaranlagen", "freiflaeche",
                "speicher_ja", "speicher_angabe", "neu_okt2025_sep2026", "kwp"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Source file is missing columns: {sorted(missing)}")
    return df


def add_district_code(df: pd.DataFrame) -> pd.DataFrame:
    """The first 5 digits of the official municipality key (AGS) are the district code.
    District names are NOT unique: a city and the rural district around it often share
    a name (e.g. Schweinfurt city 09662 and Landkreis Schweinfurt 09678), so the code
    is the only safe key."""
    df = df.copy()
    df["kreis_code"] = df["ags"].astype(int).astype(str).str.zfill(8).str[:5]
    dup = df.groupby("kreis")["kreis_code"].transform("nunique") > 1
    n_mun = df.groupby("kreis_code")["ags"].transform("size")
    label = df["kreis"].where(~dup, df["kreis"] + n_mun.map(lambda n: " (city)" if n == 1 else " (district)"))
    df["district"] = label
    return df


def quality_report(df: pd.DataFrame) -> dict:
    """Checks run on every build. Problems are reported, not silently dropped."""
    no_pop = df[df["einwohner"].isna() | (df["einwohner"] <= 0)]
    return {
        "rows": int(len(df)),
        "duplicate_ags": int(df["ags"].duplicated().sum()),
        "negative_values": int((df.select_dtypes("number") < 0).sum().sum()),
        "municipalities_without_population": int(len(no_pop)),
        "units_in_those_municipalities": int(no_pop["einheiten_in_betrieb"].sum()),
        "examples_without_population": no_pop.nlargest(3, "einheiten_in_betrieb")["name"].tolist(),
        "storage_field_filled_share": round(df["speicher_angabe"].sum() / df["einheiten_in_betrieb"].sum(), 3),
    }


def to_districts(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate municipalities to districts (Kreise) by official district code."""
    df = add_district_code(df)
    num = ["einwohner", "einheiten_in_betrieb", "kwp", "balkonkraftwerke",
           "gebaeudesolaranlagen", "freiflaeche", "speicher_ja", "speicher_angabe",
           "neu_okt2025_sep2026"]
    keys = ["kreis_code", "bundesland", "district"]
    d = (df.groupby(keys, as_index=False)[num].sum(min_count=1)
           .merge(df.groupby(keys).size().rename("municipalities").reset_index(), on=keys))
    # A district needs a population to compute per-inhabitant figures.
    d = d[d["einwohner"] > 0].copy()

    # Systems that sit in the low-voltage grid: rooftop (building) plus balcony solar.
    d["lv_units"] = d["gebaeudesolaranlagen"] + d["balkonkraftwerke"]
    d["density_per_1000"] = d["lv_units"] / d["einwohner"] * 1000
    d["new_units_12m"] = d["neu_okt2025_sep2026"]
    d["new_per_1000_12m"] = d["new_units_12m"] / d["einwohner"] * 1000
    d["storage_share"] = (d["speicher_ja"] / d["speicher_angabe"]).where(d["speicher_angabe"] > 0)
    d["balcony_share"] = d["balkonkraftwerke"] / d["einheiten_in_betrieb"]
    d["kwp_per_capita"] = d["kwp"] / d["einwohner"]
    return d


def score(d: pd.DataFrame, weights: dict[str, float] = WEIGHTS) -> pd.DataFrame:
    """Each component becomes a percentile score from 0 to 100, then a weighted sum."""
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise ValueError("Weights must add up to 1")
    d = d.copy()
    comp = {
        "density": "density_per_1000",
        "growth_rate": "new_per_1000_12m",
        "volume": "new_units_12m",
        "storage_share": "storage_share",
    }
    for name, col in comp.items():
        d[f"score_{name}"] = d[col].rank(pct=True).fillna(0.5) * 100
    d["grid_pressure_index"] = sum(d[f"score_{k}"] * w for k, w in weights.items())
    d["rank"] = d["grid_pressure_index"].rank(ascending=False, method="min").astype(int)

    # Simple segments that a sales team can act on.
    hi_vol = d["score_volume"] >= 75
    hi_rate = d["score_growth_rate"] >= 75
    d["segment"] = "Steady"
    d.loc[hi_vol & ~hi_rate, "segment"] = "Volume hotspot"      # many requests, large population
    d.loc[~hi_vol & hi_rate, "segment"] = "Saturation hotspot"  # fast growth per head, rural
    d.loc[hi_vol & hi_rate, "segment"] = "Double pressure"      # both
    return d.sort_values("rank")


def sensitivity(d: pd.DataFrame) -> float:
    """How stable is the ranking? Spearman correlation with an equal-weight version."""
    equal = score(d, {k: 0.25 for k in WEIGHTS})
    merged = d[["kreis_code", "rank"]].merge(
        equal[["kreis_code", "rank"]], on="kreis_code", suffixes=("", "_equal"))
    return float(merged["rank"].corr(merged["rank_equal"], method="spearman"))


def states(df: pd.DataFrame) -> pd.DataFrame:
    s = df.groupby("bundesland", as_index=False)[
        ["einwohner", "einheiten_in_betrieb", "kwp", "gebaeudesolaranlagen", "balkonkraftwerke",
         "speicher_ja", "speicher_angabe", "neu_okt2025_sep2026"]].sum()
    s["units_per_1000"] = s["einheiten_in_betrieb"] / s["einwohner"] * 1000
    s["new_per_1000_12m"] = s["neu_okt2025_sep2026"] / s["einwohner"] * 1000
    s["storage_share"] = s["speicher_ja"] / s["speicher_angabe"]
    return s.sort_values("new_per_1000_12m", ascending=False)


PLAYBOOK = {
    "Double pressure": "Call first. Many new connections AND fast growth per inhabitant: the operator needs both faster connection checks and low-voltage grid planning.",
    "Volume hotspot": "Lead with automation. A large number of connection requests to process: pitch time saved per request and shorter waiting times for customers.",
    "Saturation hotspot": "Lead with grid planning. Smaller population but very fast growth per inhabitant: low-voltage feeders fill up, so pitch hosting-capacity analysis and planning transparency.",
    "Steady": "Nurture. Monitor every quarter with this index and reach out when a district moves into a hotspot segment.",
}


def lead_list(d: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """Top-n districts as a sales-ready list with a data-based talking point.
    The grid operator column is left for the sales rep: the full register export
    links every unit to its grid operator (Netzbetreiber), see README 'Next steps'."""
    top = d.head(n).copy()
    growth_rank = d["new_per_1000_12m"].rank(ascending=False, method="min").astype(int)
    top["talking_point"] = [
        f"{int(r.new_units_12m):,} new solar systems in 12 months "
        f"({r.new_per_1000_12m:.1f} per 1,000 inhabitants, #{growth_rank[i]} of {len(d)} for growth); "
        f"{r.density_per_1000:.0f} rooftop/balcony systems per 1,000 inhabitants; "
        f"{r.storage_share:.0%} with a battery."
        for i, r in top.iterrows()
    ]
    top["recommended_approach"] = top["segment"].map(PLAYBOOK)
    top["grid_operator"] = ""
    return top[["rank", "district", "bundesland", "segment", "grid_pressure_index",
                "talking_point", "recommended_approach", "grid_operator"]].round(1)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    raw = load()
    quality = quality_report(raw)
    districts = score(to_districts(raw))
    rho = sensitivity(districts)

    cols = ["rank", "kreis_code", "district", "bundesland", "grid_pressure_index", "segment", "einwohner",
            "municipalities", "einheiten_in_betrieb", "lv_units", "density_per_1000",
            "new_units_12m", "new_per_1000_12m", "storage_share", "balcony_share", "kwp",
            "score_density", "score_growth_rate", "score_volume", "score_storage_share"]
    districts[cols].round(3).to_csv(OUT / "district_index.csv", index=False)
    lead_list(districts).to_csv(OUT / "lead_list_top30.csv", index=False)
    st = states(raw)
    st.round(3).to_csv(OUT / "state_summary.csv", index=False)

    top20 = districts.head(20)
    summary = {
        "data_as_of": str(raw["export_datum"].iloc[0]),
        "municipalities": int(len(raw)),
        "districts_total": int(add_district_code(raw)["kreis_code"].nunique()),
        "districts_ranked": int(len(districts)),
        "data_quality": quality,
        "units_in_operation": int(raw["einheiten_in_betrieb"].sum()),
        "gw_installed": round(raw["kwp"].sum() / 1e6, 1),
        "new_units_12m": int(raw["neu_okt2025_sep2026"].sum()),
        "balcony_units": int(raw["balkonkraftwerke"].sum()),
        "storage_share_national": round(raw["speicher_ja"].sum() / raw["speicher_angabe"].sum(), 3),
        "top20_share_of_new_units": round(top20["new_units_12m"].sum() / districts["new_units_12m"].sum(), 3),
        "top20_share_of_population": round(top20["einwohner"].sum() / districts["einwohner"].sum(), 3),
        "segments": districts["segment"].value_counts().to_dict(),
        "rank_stability_spearman_vs_equal_weights": round(rho, 3),
        "segment_share_of_new_units": (districts.groupby("segment")["new_units_12m"].sum()
                                       / districts["new_units_12m"].sum()).round(3).to_dict(),
        "segment_share_of_population": (districts.groupby("segment")["einwohner"].sum()
                                        / districts["einwohner"].sum()).round(3).to_dict(),
        "top10": top20.head(10)[["rank", "district", "bundesland", "grid_pressure_index", "segment",
                                 "new_units_12m", "density_per_1000"]].round(1).to_dict("records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

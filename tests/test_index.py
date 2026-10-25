import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import build_index as bi  # noqa: E402


def test_weights_add_up_to_one():
    assert abs(sum(bi.WEIGHTS.values()) - 1) < 1e-9


def test_city_and_rural_district_are_not_merged():
    d = bi.to_districts(bi.load())
    names = set(d["district"])
    assert "Schweinfurt (city)" in names and "Schweinfurt (district)" in names
    assert d["kreis_code"].is_unique


def test_no_units_lost_in_aggregation():
    raw = bi.load()
    d = bi.to_districts(raw)
    no_pop = raw.groupby(bi.add_district_code(raw)["kreis_code"])["einwohner"].sum(min_count=1)
    excluded_codes = set(no_pop[~(no_pop > 0)].index)
    raw_c = bi.add_district_code(raw)
    expected = raw_c.loc[~raw_c["kreis_code"].isin(excluded_codes), "einheiten_in_betrieb"].sum()
    assert d["einheiten_in_betrieb"].sum() == expected


def test_index_range_and_ranks():
    d = bi.score(bi.to_districts(bi.load()))
    assert d["grid_pressure_index"].between(0, 100).all()
    assert d["rank"].min() == 1
    assert set(d["segment"]) <= set(bi.PLAYBOOK)


def test_ranking_is_stable():
    d = bi.score(bi.to_districts(bi.load()))
    assert bi.sensitivity(d) > 0.9

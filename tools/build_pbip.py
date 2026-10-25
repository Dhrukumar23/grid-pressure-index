"""Generates the Power BI Project (PBIP) from code: TMDL semantic model + PBIR report.

Open powerbi/GridPressureIndex.pbip in Power BI Desktop. The model reads the CSV
outputs of src/build_index.py straight from this GitHub repository, so it works
without any local setup. To work offline, set the DataFolder parameter to your
local output folder, ending with a backslash (e.g. C:\\repos\\grid-pressure-index\\output\\).

    python tools/build_pbip.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "powerbi"
NAME = "GridPressureIndex"
NS = uuid.UUID("3b7d6a11-58c2-4f0e-9d3a-7c1e2b4f6a90")
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

# Segment colours: same validated, colour-blind-safe set as the web dashboard.
SEGMENTS = [  # name, sort, colour, approach
    ("Double pressure", 1, "#2A78D6", "Call first. Many new connections AND fast growth per inhabitant: the operator needs both faster connection checks and low-voltage grid planning."),
    ("Volume hotspot", 2, "#EB6834", "Lead with automation. A large number of connection requests to process: pitch time saved per request and shorter waiting times for customers."),
    ("Saturation hotspot", 3, "#1BAF7A", "Lead with grid planning. Smaller population but very fast growth per inhabitant: low-voltage feeders fill up, so pitch hosting-capacity analysis and planning transparency."),
    ("Steady", 4, "#B5B4AE", "Nurture. Monitor every quarter with this index and reach out when a district moves into a hotspot segment."),
]
INK, INK2 = "#13202A", "#566571"


def tag(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def indent(text: str, n: int) -> str:
    pad = "\t" * n
    return "\n".join(pad + line if line.strip() else "" for line in dedent(text).strip("\n").splitlines())


# =========================================================================== semantic model

@dataclass
class Col:
    name: str
    source: str
    dtype: str                 # string | int64 | double
    fmt: str | None = None
    hidden: bool = False
    sort_by: str | None = None
    summarize: str = "none"
    desc: str | None = None
    folder: str | None = None


@dataclass
class Measure:
    name: str
    expr: str
    fmt: str | None = None
    folder: str | None = None
    desc: str | None = None


@dataclass
class Table:
    name: str
    csv: str | None            # file in output/, or None for a static table
    cols: list[Col]
    measures: list[Measure] = field(default_factory=list)
    desc: str | None = None
    static_m: str | None = None


INT, DEC1, PCT = "#,0", "#,0.0", "0%"

DISTRICT = Table("District", "district_index.csv", [
    Col("Rank", "rank", "int64", "0", desc="1 = highest Grid Pressure Index"),
    Col("District Code", "kreis_code", "string", desc="Official 5-digit district code (first 5 digits of the AGS)."),
    Col("District", "district", "string", sort_by="Rank"),
    Col("State", "bundesland", "string"),
    Col("Segment", "segment", "string"),
    Col("Index", "grid_pressure_index", "double", DEC1, desc="Grid Pressure Index, 0-100"),
    Col("Inhabitants", "einwohner", "double", INT, hidden=True),
    Col("Municipalities", "municipalities", "int64", INT),
    Col("Units in Operation", "einheiten_in_betrieb", "int64", INT, hidden=True),
    Col("Rooftop and Balcony Units", "lv_units", "int64", INT, hidden=True),
    Col("Density", "density_per_1000", "double", DEC1, folder="Components",
        desc="Rooftop + balcony systems per 1,000 inhabitants"),
    Col("New Units 12M", "new_units_12m", "int64", INT, hidden=True),
    Col("Growth Rate", "new_per_1000_12m", "double", DEC1, folder="Components",
        desc="New systems per 1,000 inhabitants in the last 12 months"),
    Col("Battery Share", "storage_share", "double", PCT, folder="Components"),
    Col("Balcony Share", "balcony_share", "double", PCT, folder="Components"),
    Col("Installed kWp", "kwp", "double", INT, hidden=True),
    Col("Score Density", "score_density", "double", "0", folder="Scores (0-100)"),
    Col("Score Growth Rate", "score_growth_rate", "double", "0", folder="Scores (0-100)"),
    Col("Score Volume", "score_volume", "double", "0", folder="Scores (0-100)"),
    Col("Score Battery", "score_storage_share", "double", "0", folder="Scores (0-100)"),
], measures=[
    Measure("Districts", "COUNTROWS ( 'District' )", INT, "Counts"),
    Measure("Hotspot Districts", "CALCULATE ( [Districts], 'District'[Segment] <> \"Steady\" )", INT, "Counts",
            "Districts in one of the three hotspot segments"),
    Measure("Solar Systems", "SUM ( 'District'[Units in Operation] )", INT, "Volume"),
    Measure("New Systems 12M", "SUM ( 'District'[New Units 12M] )", INT, "Volume",
            "New solar systems put into operation in the last 12 months (Oct 2025 - Sep 2026)"),
    Measure("Population", "SUM ( 'District'[Inhabitants] )", INT, "Volume"),
    Measure("Installed GW", "DIVIDE ( SUM ( 'District'[Installed kWp] ), 1000000 )", "#,0.0", "Volume"),
    Measure("New per 1,000 Inhabitants", "DIVIDE ( [New Systems 12M] * 1000, [Population] )", DEC1, "Rates"),
    Measure("Systems per 1,000 Inhabitants",
            "DIVIDE ( SUM ( 'District'[Rooftop and Balcony Units] ) * 1000, [Population] )", DEC1, "Rates",
            "Rooftop + balcony systems per 1,000 inhabitants (low-voltage grid density)"),
    Measure("Average Index", "AVERAGE ( 'District'[Index] )", DEC1, "Index"),
    Measure("Share of New Systems",
            "DIVIDE ( [New Systems 12M], CALCULATE ( [New Systems 12M], REMOVEFILTERS () ) )", "0.0%", "Shares"),
    Measure("Share of Population",
            "DIVIDE ( [Population], CALCULATE ( [Population], REMOVEFILTERS () ) )", "0.0%", "Shares"),
    Measure("Top 20 Share of New Systems",
            "CALCULATE ( [Share of New Systems], REMOVEFILTERS (), 'District'[Rank] <= 20 )", "0.0%", "Shares",
            "Share of all new systems that went into the 20 highest-ranked districts"),
    Measure("Report Subtitle",
            "\"Official Marktstammdatenregister data as of 2 Oct 2026 · \" & FORMAT ( [Districts], \"#,0\" ) & \" districts in view\"",
            None, "Labels"),
    Measure("Segment Colour Value",
            "SWITCH ( SELECTEDVALUE ( 'District'[Segment] ), \"Double pressure\", \"#2A78D6\", \"Volume hotspot\", \"#EB6834\", \"Saturation hotspot\", \"#1BAF7A\", \"Steady\", \"#B5B4AE\", \"#566571\" )",
            None, "Labels", "Colour per segment, used for conditional formatting so each segment keeps its colour"),
], desc="One row per district (Kreis), ranked by the Grid Pressure Index.")

STATE = Table("State", "state_summary.csv", [
    Col("State", "bundesland", "string"),
    Col("State Inhabitants", "einwohner", "double", INT, hidden=True),
    Col("State New per 1,000", "new_per_1000_12m", "double", DEC1, hidden=True),
], desc="Federal states. Filters the District table.")

SEGMENT = Table("Segment", None, [
    Col("Segment", "Segment", "string", sort_by="Segment Sort"),
    Col("Segment Sort", "Sort", "int64", "0", hidden=True),
    Col("Segment Colour", "Colour", "string", hidden=True),
    Col("Approach", "Approach", "string", desc="Recommended sales approach for this segment"),
], desc="The four action segments and the playbook.",
    static_m="#table(type table [Segment = text, Sort = Int64.Type, Colour = text, Approach = text], {"
             + ", ".join("{" + f'"{n}", {s}, "{c}", "{a}"' + "}" for n, s, c, a in SEGMENTS) + "})")

LEADS = Table("Lead List", "lead_list_top30.csv", [
    Col("Lead Rank", "rank", "int64", "0"),
    Col("Lead District", "district", "string", sort_by="Lead Rank"),
    Col("Lead State", "bundesland", "string"),
    Col("Lead Segment", "segment", "string"),
    Col("Lead Index", "grid_pressure_index", "double", DEC1),
    Col("Talking Point", "talking_point", "string"),
    Col("Recommended Approach", "recommended_approach", "string"),
    Col("Grid Operator", "grid_operator", "string", desc="To be filled by the sales rep (see README next steps)"),
], desc="Top 30 districts as a sales-ready lead list.")

TABLES = [DISTRICT, STATE, SEGMENT, LEADS]
RELATIONSHIPS = [("District", "State", "State", "State"), ("District", "Segment", "Segment", "Segment")]


def col_tmdl(t: Table, c: Col) -> str:
    out = [f"\t/// {c.desc}"] if c.desc else []
    out += [f"\tcolumn {q(c.name)}", f"\t\tdataType: {c.dtype}"]
    if c.hidden:
        out.append("\t\tisHidden")
    if c.fmt:
        out.append(f"\t\tformatString: {c.fmt}")
    if c.folder:
        out.append(f"\t\tdisplayFolder: {c.folder}")
    out += [f"\t\tlineageTag: {tag(t.name, 'col', c.name)}", f"\t\tsummarizeBy: {c.summarize}",
            f"\t\tsourceColumn: {c.source}"]
    if c.sort_by:
        out.append(f"\t\tsortByColumn: {q(c.sort_by)}")
    out += ["", "\t\tannotation SummarizationSetBy = User"]
    return "\n".join(out) + "\n"


def measure_tmdl(t: Table, m: Measure) -> str:
    out = [f"\t/// {m.desc}"] if m.desc else []
    out.append(f"\tmeasure {q(m.name)} = {m.expr}")
    if m.fmt:
        out.append(f"\t\tformatString: {m.fmt}")
    if m.folder:
        out.append(f"\t\tdisplayFolder: {m.folder}")
    out.append(f"\t\tlineageTag: {tag(t.name, 'measure', m.name)}")
    return "\n".join(out) + "\n"


def table_tmdl(t: Table) -> str:
    out = [f"/// {t.desc}"] if t.desc else []
    out += [f"table {q(t.name)}", f"\tlineageTag: {tag(t.name)}", ""]
    out += [measure_tmdl(t, m) for m in t.measures]
    out += [col_tmdl(t, c) for c in t.cols]
    types = {"string": "type text", "int64": "Int64.Type", "double": "type number"}
    out += [f"\tpartition {q(t.name)} = m", "\t\tmode: import", "\t\tsource ="]
    if t.static_m:
        out.append(indent(f"""
            let
                Source = {t.static_m}
            in
                Source""", 4))
    else:
        transforms = ", ".join("{" + f'"{c.source}", {types[c.dtype]}' + "}" for c in t.cols)
        keep = ", ".join(f'"{c.source}"' for c in t.cols)
        out.append(indent(f"""
            let
                Source = fnReadCsv("{t.csv}"),
                Kept = Table.SelectColumns(Source, {{{keep}}}),
                Typed = Table.TransformColumnTypes(Kept, {{{transforms}}}, "en-US")
            in
                Typed""", 4))
    out += ["", "\tannotation PBI_ResultType = Table"]
    return "\n".join(out) + "\n"


def build_model(github_user: str, repo: str, branch: str) -> None:
    sm = OUT / f"{NAME}.SemanticModel"
    d = sm / "definition"
    (d / "tables").mkdir(parents=True)
    (sm / ".platform").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("logical", "model")}}, indent=2))
    (sm / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2))
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1601\n\n")
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: en-US", "\tdataAccessOptions",
             "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
             "annotation __PBI_TimeIntelligenceEnabled = 0", "",
             "annotation PBI_QueryOrder = " + json.dumps(["DataFolder", "fnReadCsv"] + [t.name for t in TABLES]), "",
             'annotation PBI_ProTooling = ["DevMode","TMDLView_Desktop"]', ""]
    model += [f"ref table {q(t.name)}" for t in TABLES] + [""]
    (d / "model.tmdl").write_text("\n".join(model))
    url = f"https://raw.githubusercontent.com/{github_user}/{repo}/{branch}/output/"
    (d / "expressions.tmdl").write_text(dedent(f'''\
        /// Where the CSV outputs live. Default: this GitHub repository.
        /// For local work set it to a folder path ending with a backslash, e.g. C:\\\\repos\\\\grid-pressure-index\\\\output\\\\
        expression DataFolder = "{url}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]
        \tlineageTag: {tag("expr", "DataFolder")}

        \tannotation PBI_ResultType = Text

        /// Reads one CSV output (UTF-8, comma-separated, dot as decimal separator).
        expression fnReadCsv =
        \t\t(fileName as text) as table =>
        \t\tlet
        \t\t    Content = if Text.StartsWith(DataFolder, "http")
        \t\t        then Web.Contents(DataFolder, [RelativePath = fileName])
        \t\t        else File.Contents(DataFolder & fileName),
        \t\t    Csv = Csv.Document(Content, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
        \t\t    Promoted = Table.PromoteHeaders(Csv, [PromoteAllScalars = true])
        \t\tin
        \t\t    Promoted
        \tlineageTag: {tag("expr", "fnReadCsv")}

        \tannotation PBI_ResultType = Function

        '''))
    for t in TABLES:
        (d / "tables" / f"{t.name}.tmdl").write_text(table_tmdl(t))
    rel = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rel += [f"relationship {tag('rel', ft, fc, tt)}", f"\tfromColumn: {q(ft)}.{q(fc)}",
                f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rel))


# =========================================================================== report (PBIR)

def lit(v) -> dict:
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def measure(entity: str, prop: str) -> dict:
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
            "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def column(entity: str, prop: str, active: bool = False) -> dict:
    d = {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
         "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if active:
        d["active"] = True
    return d


def sort_by(field: dict, direction: str) -> dict:
    return {"sort": [{"field": field["field"], "direction": direction}]}


def seg_fill() -> dict:
    """Colour bars by segment via the Segment Colour Value measure."""
    return {"dataPoint": [{"properties": {"fill": {"solid": {"color": {"expr": {"Measure": {
        "Expression": {"SourceRef": {"Entity": "District"}}, "Property": "Segment Colour Value"}}}}}}}]}


class Page:
    def __init__(self, key: str, title: str):
        self.name = tag("page", key).replace("-", "")[:20]
        self.title = title
        self.visuals: list[dict] = []
        self.z = 0

    def _name(self) -> str:
        self.z += 1000
        return tag("visual", self.name, str(self.z)).replace("-", "")[:20]

    def add(self, vtype: str, x, y, w, h, roles: dict | None = None, title: str | None = None,
            objects: dict | None = None, sort: dict | None = None, container: dict | None = None):
        name = self._name()
        visual: dict = {"visualType": vtype}
        if roles:
            visual["query"] = {"queryState": {r: {"projections": p} for r, p in roles.items()}}
            if sort:
                visual["query"]["sortDefinition"] = sort
        if objects:
            visual["objects"] = objects
        vco = dict(container or {})
        if title:
            vco["title"] = [{"properties": {"show": lit(True), "text": lit(title), "fontSize": lit(11), "bold": lit(True)}}]
        vco.setdefault("dropShadow", [{"properties": {"show": lit(False)}}])
        vco.setdefault("background", [{"properties": {"show": lit(True), "color": {"solid": {"color": lit("#FFFFFF")}}, "transparency": lit(0)}}])
        vco.setdefault("border", [{"properties": {"show": lit(True), "color": {"solid": {"color": lit("#DDE4E8")}}, "radius": lit(8)}}])
        visual["visualContainerObjects"] = vco
        visual["drillFilterOtherVisuals"] = True
        self.visuals.append({"$schema": f"{SCHEMA}/visualContainer/2.0.0/schema.json", "name": name,
                             "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
                             "visual": visual})

    def text(self, x, y, w, h, runs: list[tuple[str, dict]]):
        name = self._name()
        self.visuals.append({"$schema": f"{SCHEMA}/visualContainer/2.0.0/schema.json", "name": name,
                             "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
                             "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [
                                 {"textRuns": [{"value": v, "textStyle": s} for v, s in runs]}]}}]},
                                 "drillFilterOtherVisuals": True}})


def card(p: Page, x, y, w, prop, label):
    p.add("card", x, y, w, 92, {"Values": [measure("District", prop)]},
          objects={"labels": [{"properties": {"fontSize": lit(22), "color": {"solid": {"color": lit(INK)}}}}],
                   "categoryLabels": [{"properties": {"show": lit(False)}}]},
          container={"title": [{"properties": {"show": lit(False)}}]})
    # Hide the default label (the measure name) and add a plain-language caption instead.
    p.text(x + 12, y + 64, w - 24, 24, [(label, {"fontSize": "9pt", "color": INK2})])


def header(p: Page, title: str):
    p.text(24, 12, 820, 40, [(title, {"fontFamily": "Segoe UI Semibold", "fontSize": "20pt", "color": INK})])
    p.add("card", 24, 50, 820, 30, {"Values": [measure("District", "Report Subtitle")]},
          objects={"labels": [{"properties": {"fontSize": lit(10), "color": {"solid": {"color": lit(INK2)}}}}],
                   "categoryLabels": [{"properties": {"show": lit(False)}}]},
          container={"title": [{"properties": {"show": lit(False)}}], "border": [{"properties": {"show": lit(False)}}],
                     "background": [{"properties": {"show": lit(False)}}]})


def slicer(p: Page, x, y, w, entity, prop, title):
    p.add("slicer", x, y, w, 56, {"Values": [column(entity, prop, active=True)]}, title=title,
          objects={"data": [{"properties": {"mode": lit("Dropdown")}}]})


def build_pages() -> list[Page]:
    pages = []
    # ------------------------------------------------------------------ 1 overview
    p = Page("overview", "Where the pressure is")
    header(p, "Grid Pressure Index · Germany")
    slicer(p, 880, 12, 180, "State", "State", "State")
    slicer(p, 1076, 12, 180, "Segment", "Segment", "Segment")
    for i, (m, label) in enumerate([("Solar Systems", "solar systems in operation"),
                                    ("New Systems 12M", "new systems in the last 12 months"),
                                    ("New per 1,000 Inhabitants", "new systems per 1,000 inhabitants"),
                                    ("Hotspot Districts", "districts in a hotspot segment"),
                                    ("Top 20 Share of New Systems", "of new systems in the top 20 districts")]):
        card(p, 24 + i * 248, 92, 236, m, label)
    p.add("scatterChart", 24, 196, 760, 508,
          {"Category": [column("District", "District", active=True)],
           "Series": [column("Segment", "Segment", active=True)],
           "X": [measure("District", "New Systems 12M")],
           "Y": [measure("District", "New per 1,000 Inhabitants")]},
          title="Districts by connection volume (x) and growth per inhabitant (y)",
          objects={"categoryAxis": [{"properties": {"axisScale": lit("log"), "title": lit("New systems, last 12 months")}}],
                   "valueAxis": [{"properties": {"title": lit("New per 1,000 inhabitants")}}],
                   "legend": [{"properties": {"show": lit(True), "position": lit("Top")}}]})
    p.add("clusteredBarChart", 796, 196, 460, 508,
          {"Category": [column("State", "State", active=True)], "Y": [measure("District", "New per 1,000 Inhabitants")]},
          title="New systems per 1,000 inhabitants by state",
          sort=sort_by(measure("District", "New per 1,000 Inhabitants"), "Descending"),
          objects={"labels": [{"properties": {"show": lit(True)}}]})
    pages.append(p)

    # ------------------------------------------------------------------ 2 ranking
    p = Page("ranking", "District ranking")
    header(p, "All 400 districts, ranked")
    slicer(p, 880, 12, 180, "State", "State", "State")
    slicer(p, 1076, 12, 180, "Segment", "Segment", "Segment")
    p.add("clusteredBarChart", 24, 92, 460, 612,
          {"Category": [column("District", "District", active=True)], "Y": [measure("District", "Average Index")]},
          title="Grid Pressure Index by district (scroll for all)",
          sort=sort_by(measure("District", "Average Index"), "Descending"),
          objects={**seg_fill(), "labels": [{"properties": {"show": lit(True)}}]})
    p.add("tableEx", 496, 92, 760, 612,
          {"Values": [column("District", "Rank"), column("District", "District"), column("District", "State"),
                      column("District", "Segment"), measure("District", "Average Index"),
                      measure("District", "New Systems 12M"), measure("District", "New per 1,000 Inhabitants"),
                      measure("District", "Systems per 1,000 Inhabitants"), column("District", "Battery Share")]},
          title="District details",
          sort=sort_by(column("District", "Rank"), "Ascending"))
    pages.append(p)

    # ------------------------------------------------------------------ 3 playbook
    p = Page("playbook", "Sales playbook")
    header(p, "From index to action")
    p.add("clusteredColumnChart", 24, 92, 460, 300,
          {"Category": [column("Segment", "Segment", active=True)],
           "Y": [measure("District", "Share of New Systems"), measure("District", "Share of Population")]},
          title="Share of new systems vs share of population, by segment",
          objects={"labels": [{"properties": {"show": lit(True)}}],
                   "legend": [{"properties": {"show": lit(True), "position": lit("Top")}}]})
    p.add("tableEx", 496, 92, 760, 300,
          {"Values": [column("Segment", "Segment"), measure("District", "Districts"),
                      measure("District", "Share of New Systems"), column("Segment", "Approach")]},
          title="Playbook: what to lead with in each segment",
          sort=sort_by(column("Segment", "Segment"), "Ascending"))
    p.add("tableEx", 24, 404, 1232, 300,
          {"Values": [column("Lead List", "Lead Rank"), column("Lead List", "Lead District"),
                      column("Lead List", "Lead State"), column("Lead List", "Lead Segment"),
                      column("Lead List", "Talking Point"), column("Lead List", "Grid Operator")]},
          title="Top 30 lead list with a data-based talking point",
          sort=sort_by(column("Lead List", "Lead Rank"), "Ascending"))
    pages.append(p)
    return pages


def build_report() -> None:
    rp = OUT / f"{NAME}.Report"
    d = rp / "definition"
    (d / "pages").mkdir(parents=True)
    (rp / ".platform").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("logical", "report")}}, indent=2))
    (rp / "definition.pbir").write_text(json.dumps(
        {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    (d / "version.json").write_text(json.dumps({"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}, indent=2))
    base_theme = "CY24SU10"
    res = rp / "StaticResources"
    (res / "SharedResources" / "BaseThemes").mkdir(parents=True)
    (res / "RegisteredResources").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "assets" / f"{base_theme}.json", res / "SharedResources" / "BaseThemes" / f"{base_theme}.json")
    # Legend order in Power BI is alphabetical: Double, Saturation, Steady, Volume.
    theme = {
        "name": "GridPressure",
        "dataColors": ["#2A78D6", "#1BAF7A", "#B5B4AE", "#EB6834", "#6250D6", "#E87BA4", "#EDA100", "#566571"],
        "background": "#FFFFFF", "foreground": INK, "tableAccent": "#2A78D6",
        "textClasses": {"title": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": INK},
                        "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 22, "color": INK},
                        "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": INK2}},
        "visualStyles": {"page": {"*": {"background": [{"color": {"solid": {"color": "#F3F6F7"}}, "transparency": 0}]}}},
    }
    (res / "RegisteredResources" / "GridPressure.json").write_text(json.dumps(theme, indent=2))
    (d / "report.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/report/1.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": base_theme, "reportVersionAtImport": "5.59", "type": "SharedResources"},
            "customTheme": {"name": "GridPressure.json", "reportVersionAtImport": "5.59", "type": "RegisteredResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": base_theme, "path": f"BaseThemes/{base_theme}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "GridPressure.json", "path": "GridPressure.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True, "useEnhancedTooltips": True},
    }, indent=2))
    pages = build_pages()
    (d / "pages" / "pages.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name}, indent=2))
    for p in pages:
        pd = d / "pages" / p.name
        (pd / "visuals").mkdir(parents=True)
        (pd / "page.json").write_text(json.dumps({
            "$schema": f"{SCHEMA}/page/2.0.0/schema.json", "name": p.name, "displayName": p.title,
            "displayOption": "FitToPage", "height": 720, "width": 1280}, indent=2))
        for v in p.visuals:
            (pd / "visuals" / v["name"]).mkdir()
            (pd / "visuals" / v["name"] / "visual.json").write_text(json.dumps(v, indent=2, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-user", default="Dhrukumar23")
    ap.add_argument("--repo", default="grid-pressure-index")
    ap.add_argument("--branch", default="main")
    a = ap.parse_args()
    for p in (OUT / f"{NAME}.SemanticModel", OUT / f"{NAME}.Report"):
        shutil.rmtree(p, ignore_errors=True)
    OUT.mkdir(exist_ok=True)
    build_model(a.github_user, a.repo, a.branch)
    build_report()
    (OUT / f"{NAME}.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    (OUT / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    print(f"PBIP written to {OUT}: {len(TABLES)} tables, {sum(len(t.measures) for t in TABLES)} measures, "
          f"{len(build_pages())} report pages")


if __name__ == "__main__":
    main()

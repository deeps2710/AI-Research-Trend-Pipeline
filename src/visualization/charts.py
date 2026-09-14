"""Reusable DataFrame-to-PNG charts. Return a Path, or None when unsupported."""

import math
from pathlib import Path
import textwrap

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, StrMethodFormatter
import pandas as pd


BLUE = "#28648A"
CAPTION = "Current dataset only • bounded extraction; not global publication totals"


def _data(frame, required):
    if not set(required) <= set(frame.columns):
        return pd.DataFrame(columns=required)
    return frame.dropna(subset=required).copy()


def select_top(frame, metric, key, top_n):
    if type(top_n) is not int or not 1 <= top_n <= 30:
        raise ValueError("top_n must be an integer between 1 and 30")
    return _data(frame, [metric, key]).sort_values(
        [metric, key], ascending=[False, True], kind="stable"
    ).head(top_n)


def _figure(title, xlabel, ylabel, height=5):
    figure = Figure(figsize=(12, height), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    axis.set_title(title, loc="left", fontsize=15, pad=15)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_axisbelow(True)
    figure.supxlabel(CAPTION, fontsize=9, color="#555555")
    return figure, axis


def _save(figure, output_path):
    path = Path(output_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, dpi=220, facecolor="white")
        return path
    finally:
        # Figures are never registered with pyplot, and release artists here.
        figure.clear()


def _years(axis, years):
    axis.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=12))
    axis.xaxis.set_major_formatter(StrMethodFormatter("{x:.0f}"))
    if len(set(years)) == 1:
        year = int(years.iloc[0])
        axis.set_xticks([year])
        axis.set_xlim(year - 0.5, year + 0.5)


def plot_publication_trends(frame, output_path):
    data = _data(frame, ["publication_year", "paper_count"]).sort_values("publication_year")
    if data.empty:
        return None
    figure, axis = _figure("Papers in current dataset by publication year", "Publication year", "Papers")
    # Missing calendar years remain gaps, rather than invented zero counts.
    series = data.set_index("publication_year")["paper_count"]
    series = series.reindex(range(int(series.index.min()), int(series.index.max()) + 1))
    axis.plot(series.index, series, marker="o", color=BLUE, linewidth=2)
    _years(axis, data.publication_year)
    axis.set_ylim(bottom=0)
    axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    axis.grid(axis="y", alpha=0.2)
    if len(data) == 1:
        axis.annotate(f"{int(data.paper_count.iloc[0]):,} papers • one year only",
                      (data.publication_year.iloc[0], data.paper_count.iloc[0]),
                      xytext=(0, -22), textcoords="offset points", ha="center")
    return _save(figure, output_path)


def plot_year_over_year_growth(frame, output_path):
    if "publication_year" not in frame or frame.publication_year.nunique() < 2:
        return None
    data = _data(frame, ["publication_year", "year_over_year_growth_percentage"])
    if data.empty:
        return None
    data = data[data.year_over_year_growth_percentage.map(math.isfinite)].sort_values("publication_year")
    if data.empty:
        return None
    figure, axis = _figure("Year-over-year change in current dataset paper counts", "Publication year", "Change from preceding year (%)")
    axis.bar(data.publication_year, data.year_over_year_growth_percentage, color=BLUE)
    axis.axhline(0, color="#555555", linewidth=0.8)
    _years(axis, data.publication_year)
    return _save(figure, output_path)


def _bars(frame, output_path, metric, key, label, title, xlabel, top_n=10, log_scale=False):
    data = select_top(frame, metric, key, top_n)
    if data.empty:
        return None
    labels = data[label].fillna(data[key]) if label in data else data[key]
    labels = [textwrap.fill(textwrap.shorten(str(value), width=145, placeholder="…"), 44) for value in labels]
    figure, axis = _figure(title, xlabel, "", height=max(5, len(data) * 0.72 + 1.6))
    bars = axis.barh(range(len(data)), data[metric], color=BLUE, height=0.65)
    axis.set_yticks(range(len(data)), labels, fontsize=10)
    axis.invert_yaxis()
    axis.set_xlim(left=0)
    if log_scale:
        axis.set_xscale("symlog", linthresh=1)
        axis.set_xlabel(xlabel + " (symmetric log scale; linear from 0 to 1)")
    else:
        axis.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
    axis.set_xlim(right=max(1, float(data[metric].max()) * 1.16))
    axis.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    axis.grid(axis="x", alpha=0.2)
    axis.margins(x=0.18)
    axis.bar_label(bars, labels=[f"{value:,.0f}" for value in data[metric]], padding=4, fontsize=9)
    return _save(figure, output_path)


def plot_top_topics(frame, output_path, top_n=10):
    return _bars(frame, output_path, "paper_count", "topic_id", "topic_name",
                 "Top topics by papers in current dataset", "Distinct papers", top_n)


def plot_top_cited_papers(frame, output_path, top_n=10, log_scale=False):
    return _bars(frame, output_path, "cited_by_count", "paper_id", "title",
                 "Most cited papers in current dataset", "Citations", top_n, log_scale)


def plot_top_authors(frame, output_path, top_n=10):
    return _bars(frame, output_path, "paper_count", "author_id", "author_name",
                 "Top authors by papers in current dataset", "Distinct authored papers (full counting)", top_n)


def plot_top_institutions(frame, output_path, top_n=10):
    return _bars(frame, output_path, "paper_count", "institution_id", "institution_name",
                 "Top institutions by papers in current dataset", "Distinct affiliated papers (full counting)", top_n)


def plot_topic_trends(frame, output_path, top_n=5, topic_ids=None):
    if not 1 <= top_n <= 5:
        raise ValueError("Topic trend top_n must be between 1 and 5")
    data = _data(frame, ["publication_year", "topic_id", "paper_count"])
    if topic_ids is not None:
        if len(set(topic_ids)) > 5:
            raise ValueError("Select at most five topic IDs")
        data = data[data.topic_id.isin(topic_ids)]
    else:
        selected = data.groupby("topic_id")["paper_count"].sum().sort_values(ascending=False, kind="stable").head(top_n).index
        data = data[data.topic_id.isin(selected)]
    if data.publication_year.nunique() < 2:
        return None
    # Do not present a group of single-year points as a temporal trend.
    valid = data.groupby("topic_id").publication_year.nunique()
    data = data[data.topic_id.isin(valid[valid >= 2].index)]
    if data.empty:
        return None
    figure, axis = _figure("Selected topic counts over time in current dataset", "Publication year", "Distinct papers", height=6)
    colors = [BLUE, "#B55D15", "#36856B", "#795D92", "#555555"]
    years = range(int(data.publication_year.min()), int(data.publication_year.max()) + 1)
    for index, (topic, rows) in enumerate(data.groupby("topic_id", sort=True)):
        series = rows.set_index("publication_year")["paper_count"].reindex(years)
        label = rows.topic_name.dropna().iloc[0] if "topic_name" in rows and rows.topic_name.notna().any() else topic
        axis.plot(series.index, series, marker=["o", "s", "^", "D", "v"][index],
                  color=colors[index], label=textwrap.fill(str(label), 42))
    _years(axis, data.publication_year)
    axis.set_ylim(bottom=0)
    axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    axis.grid(axis="y", alpha=0.2)
    axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9, frameon=False)
    return _save(figure, output_path)


def plot_citation_distribution(frame, output_path, log_spacing=True):
    data = _data(frame, ["cited_by_count"])
    values = data.cited_by_count
    values = values[values.map(math.isfinite) & (values >= 0)].astype(float)
    if values.empty:
        return None
    transform = math.log1p if log_spacing else float
    plotted = values.map(transform)
    maximum = max(float(plotted.max()), 1.0)
    bins = min(35, max(5, int(math.sqrt(len(values)))))
    edges = [maximum * index / bins for index in range(bins + 1)]
    xlabel = "Citations (log1p spacing; tick labels show raw counts)" if log_spacing else "Citations"
    figure, axis = _figure("Citation distribution in current dataset", xlabel, "Papers per bin")
    axis.hist(plotted, bins=edges, color=BLUE, edgecolor="white")
    for name, value, color, style in (("Mean", values.mean(), "#B55D15", "--"),
                                       ("Median", values.median(), "#333333", ":")):
        axis.axvline(transform(value), color=color, linestyle=style, linewidth=2,
                     label=f"{name}: {value:,.1f}")
    if log_spacing:
        ticks = [0, 1] + [10 ** power for power in range(1, 12) if 10 ** power <= values.max()]
        axis.set_xticks([math.log1p(value) for value in ticks], [f"{value:,}" for value in ticks])
    axis.set_xlim(left=0)
    axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    axis.legend(frameon=False)
    return _save(figure, output_path)


def plot_open_access(frame, output_path):
    data = _data(frame, ["paper_count"])
    if data.empty or "oa_status" not in data:
        return None
    data["oa_status"] = data.oa_status.fillna("unknown").replace("", "unknown")
    return _bars(data, output_path, "paper_count", "oa_status", "oa_status",
                 "Open-access status in current dataset", "Papers", min(len(data), 30))

import streamlit as st
from dashboard import data_access as data
from dashboard.components import chart, metrics
from src.visualization import charts


def render(path, kpis):
    st.title("Research overview")
    st.caption("Explore the papers and research entities currently loaded in the warehouse.")
    metrics(kpis, [("total_papers", "Papers", 0, False), ("total_citations", "Citations", 0, False),
                   ("average_citations_per_paper", "Mean citations", 1, False),
                   ("median_citations_per_paper", "Median citations", 1, False),
                   ("open_access_percentage", "Confirmed open access", 1, True),
                   ("unique_authors", "Authors", 0, False), ("unique_topics", "Topics", 0, False),
                   ("unique_institutions", "Institutions", 0, False)])
    chart(charts.plot_publication_trends, data.get_view(path, "publication_trends"))
    left, right = st.columns(2)
    with left:
        chart(charts.plot_top_topics, data.get_view(path, "topic_summary", 10))
    with right:
        chart(charts.plot_open_access, data.get_view(path, "open_access_summary", 30))

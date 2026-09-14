import streamlit as st
from dashboard import data_access as data
from dashboard.components import chart, table
from src.visualization import charts


def render(path, kpis):
    st.title("Authors & institutions")
    st.caption("Full counting: each listed author/institution receives the paper's full citation association, not a fractional contribution. Entity totals are not additive corpus totals.")
    top_n = st.slider("Top entities", 5, 30, 10, step=5)
    authors, institutions = st.tabs(["Authors", "Institutions"])
    with authors:
        frame = data.get_view(path, "author_summary", top_n)
        chart(charts.plot_top_authors, frame, top_n=top_n)
        table(frame)
    with institutions:
        frame = data.get_view(path, "institution_summary", top_n)
        chart(charts.plot_top_institutions, frame, top_n=top_n)
        table(frame)

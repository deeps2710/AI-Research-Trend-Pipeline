"""Launch from the repository root: streamlit run dashboard/app.py."""
from pathlib import Path
import sys

# Streamlit executes this file as a script; make root packages importable.
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
import streamlit as st

from dashboard.config import COVERAGE, database_path
from dashboard import data_access as data
from dashboard.views import overview, research_trends, topics, papers, authors_institutions

PAGES = {"Overview": overview, "Research Trends": research_trends,
         "Topic Intelligence": topics, "Paper Explorer": papers,
         "Authors & Institutions": authors_institutions}


def main():
    st.set_page_config(page_title="Research intelligence", layout="wide")
    st.sidebar.title("Research intelligence")
    selected = st.sidebar.radio("Explore", list(PAGES))
    st.sidebar.caption("Source: OpenAlex")
    st.warning(COVERAGE)
    path = database_path()
    try:
        data.validate_database(path)
        kpis = data.get_overview_kpis(path)
        count = kpis.get("total_papers")
        st.sidebar.metric("Loaded papers", "Unavailable" if pd.isna(count) else f"{count:,.0f}")
        first, last = kpis.get("earliest_publication_year"), kpis.get("latest_publication_year")
        if first is not None and last is not None and not pd.isna(first) and not pd.isna(last):
            st.sidebar.caption(f"Publication year range: {int(first)}–{int(last)}")
        st.sidebar.caption("Page-local filters. Refresh the pipeline through the CLI; the dashboard only reads data.")
        PAGES[selected].render(path, kpis)
    except data.DashboardError as error:
        st.error(str(error))


if __name__ == "__main__":
    main()

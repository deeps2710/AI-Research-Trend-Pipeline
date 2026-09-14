import streamlit as st
from dashboard import data_access as data
from dashboard.components import table, topic_choices


def render(path, kpis):
    st.title("Paper explorer")
    st.caption("Filters apply only to this table. Topic filtering includes all associated topics, not just the primary topic.")
    available = data.fields(path, "top_papers")
    year, topic, minimum, status = None, None, None, None
    left, middle, right = st.columns(3)
    with left:
        years = data.get_view(path, "publication_trends")
        if "publication_year" in available and "publication_year" in years:
            year = st.selectbox("Publication year", [None] + sorted(years.publication_year.dropna().astype(int).tolist()),
                                format_func=lambda item: "All years" if item is None else str(item))
        if "cited_by_count" in available:
            threshold = st.number_input("Minimum citations", min_value=0, value=0, step=1)
            minimum = int(threshold) if threshold > 0 else None
    with middle:
        if data.topic_filter_available(path):
            topic = topic_choices(data.get_view(path, "topic_summary", 500), allow_all=True)
        oa = data.get_view(path, "open_access_summary", 50)
        if "oa_status" in available and "oa_status" in oa:
            status = st.selectbox("Open-access status", [None] + oa.oa_status.tolist(),
                                  format_func=lambda item: "All statuses" if item is None else str(item))
    with right:
        sorting = st.selectbox("Sort by", [name for name, field in
                              (("citations", "cited_by_count"), ("year", "publication_year"), ("title", "title"))
                              if field in available] or ["citations"])
        limit = st.slider("Result limit", 10, 200, 50, step=10)
    result = data.get_papers(path, year, topic, minimum, status, sorting, limit)
    st.caption(f"Showing {len(result):,} rows; maximum {limit}. Minimum 0 keeps papers with unknown citations.")
    table(result)

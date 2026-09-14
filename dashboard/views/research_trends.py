import streamlit as st
from dashboard import data_access as data
from dashboard.components import chart, table
from src.visualization import charts


def render(path, kpis):
    st.title("Research trends")
    years = data.get_view(path, "publication_trends")
    chart(charts.plot_publication_trends, years)
    if years.empty or "publication_year" not in years or years.publication_year.nunique() < 2:
        st.info("Only one or no publication years are available. Temporal analysis needs multiple years; null growth is not zero growth.")
        return
    chart(charts.plot_year_over_year_growth, years)
    topics = data.get_view(path, "topic_summary", 500)
    if not topics.empty:
        labels = dict(zip(topics.topic_id, topics.topic_name.fillna(topics.topic_id) if "topic_name" in topics else topics.topic_id))
        selected = st.multiselect("Topics to compare (up to five)", topics.topic_id.tolist(),
                                 default=topics.topic_id.head(5).tolist(), max_selections=5,
                                 format_func=lambda item: labels[item])
        import pandas as pd
        frames = [data.get_view(path, "topic_yearly_trends", topic_id=topic) for topic in selected]
        if frames:
            chart(charts.plot_topic_trends, pd.concat(frames), topic_ids=selected)
    table(years)

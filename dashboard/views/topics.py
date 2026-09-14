import streamlit as st
from dashboard import data_access as data
from dashboard.components import chart, metrics, table, topic_choices
from src.visualization import charts


def render(path, kpis):
    st.title("Topic intelligence")
    st.caption("Select from up to 500 topics, ordered by paper count in the current dataset.")
    topics = data.get_view(path, "topic_summary", 500)
    selected = topic_choices(topics)
    if selected is None:
        return
    row = topics[topics.topic_id == selected].iloc[0].to_dict()
    metrics(row, [("paper_count", "Papers", 0, False), ("total_citations", "Citations", 0, False),
                  ("average_citations", "Mean citations", 1, False), ("median_citations", "Median citations", 1, False),
                  ("open_access_percentage", "Confirmed open access", 1, True)])
    chart(charts.plot_topic_trends, data.get_view(path, "topic_yearly_trends", topic_id=selected), topic_ids=[selected])
    st.subheader("Most cited associated papers")
    if data.topic_filter_available(path):
        table(data.get_papers(path, topic_id=selected, limit=20))
    else:
        st.info("Paper-topic relationships are unavailable.")

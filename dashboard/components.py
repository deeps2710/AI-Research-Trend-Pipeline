"""Small native Streamlit UI components shared by the pages."""
import threading

import pandas as pd
import streamlit as st

# Matplotlib is not thread-safe across concurrent Streamlit sessions.
_PLOT_LOCK = threading.RLock()


def metrics(values, definitions):
    present = [(key, label, decimals, percent) for key, label, decimals, percent in definitions if key in values]
    for start in range(0, len(present), 4):
        for column, (key, label, decimals, percent) in zip(st.columns(4), present[start:start + 4]):
            value = values[key]
            text = "Unavailable" if pd.isna(value) else f"{value:,.{decimals}f}" + ("%" if percent else "")
            column.metric(label, text)


def chart(plot, frame, **kwargs):
    with _PLOT_LOCK:
        figure = plot(frame, None, **kwargs)
        if figure is None:
            st.info("No usable chart data. Time-series charts require multiple publication years.")
            return
        try:
            st.pyplot(figure, width="stretch")
        finally:
            figure.clear()


def table(frame):
    if frame.empty:
        st.info("No records match this selection.")
        return
    shown = frame.copy()
    config = {}
    for name in shown.columns:
        if "percentage" in name:
            config[name] = st.column_config.NumberColumn(format="%.1f%%")
        elif "citation" in name or name == "paper_count":
            config[name] = st.column_config.NumberColumn(format="localized")
    if "doi" in shown:
        # Only recognized DOI URLs become clickable links.
        shown["doi"] = shown.doi.where(shown.doi.fillna("").str.startswith(("https://doi.org/", "http://doi.org/")))
        config["doi"] = st.column_config.LinkColumn("DOI")
    st.dataframe(shown, hide_index=True, width="stretch", column_config=config)


def topic_choices(frame, label="Topic", allow_all=False, key=None):
    if frame.empty or "topic_id" not in frame:
        st.info("No identified topics are available.")
        return None
    names = dict(zip(frame.topic_id, frame.topic_name.fillna(frame.topic_id) if "topic_name" in frame else frame.topic_id))
    options = ([None] if allow_all else []) + frame.topic_id.tolist()
    return st.selectbox(label, options, format_func=lambda value: "All topics" if value is None else names[value], key=key)

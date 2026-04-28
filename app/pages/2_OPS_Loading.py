"""
pages/2_OPS_Loading.py — dummy
"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="OPS Loading", page_icon="🚛", layout="wide")
st.title("🚛 OPS Loading")
st.divider()

col1, col2 = st.columns(2)
with col1:
    st.date_input("Date From")
with col2:
    st.date_input("Date To")

st.button("🔄 Refresh", use_container_width=False)
st.divider()

dummy = {
    "Date":        ["2026-04-28", "2026-04-29"],
    "Container":   ["MSKU1234567", "TCKU8765432"],
    "DO Number":   ["DO-2026001", "DO-2026002"],
    "Loading Time": ["08:00", "10:30"],
    "Status":      ["Done", "Pending"],
}
st.data_editor(pd.DataFrame(dummy), use_container_width=True, hide_index=True)

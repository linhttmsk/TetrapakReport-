import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import nav  # type: ignore

st.set_page_config(page_title="Container Inventory", page_icon="🗄️", layout="wide")
nav.sidebar()
st.title("🗄️ Container Inventory")
st.info("Coming soon")

"""
pages/1_Daily_Shipment.py — dummy
"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Daily Shipment", page_icon="🚢", layout="wide")
st.title("🚢 Daily Shipment")
st.divider()

# ── Filters ──
col1, col2, col3, col4 = st.columns(4)
with col1:
    client = st.selectbox("Client", ["Tetra Pak", "All"])
with col2:
    do_number = st.text_input("DO Number")
with col3:
    date_from = st.date_input("Date From")
with col4:
    status = st.selectbox("Status", ["All", "1-New", "2-In Progress", "3-Loading Passed", "4-Booking Done"])

col_btn1, col_btn2, col_btn3, _ = st.columns([1, 1, 1, 5])
with col_btn1:
    btn_refresh = st.button("🔄 Refresh", use_container_width=True)
with col_btn2:
    btn_update = st.button("⬆ Update", use_container_width=True, type="primary")
with col_btn3:
    btn_pass = st.button("✅ Pass Loading", use_container_width=True)

st.divider()

# ── Dummy data ──
if btn_refresh or True:
    dummy_data = {
        "DO Number":   ["DO-2026001", "DO-2026002", "DO-2026003", "DO-2026004"],
        "Client":      ["Tetra Pak", "Tetra Pak", "Tetra Pak", "Tetra Pak"],
        "Shipper":     ["Tetra Pak VN", "Tetra Pak TH", "Tetra Pak SG", "Tetra Pak MY"],
        "ETD":         ["2026-04-28", "2026-04-30", "2026-05-02", "2026-05-05"],
        "Container":   ["MSKU1234567", "TCKU8765432", "CMAU3456789", "MSCU9876543"],
        "Status":      ["3-Loading Passed", "2-In Progress", "1-New", "0-Withdraw Request"],
        "Remark":      ["", "Pending docs", "", "Customer request"],
        "Updated By":  ["TLT023", "TLT023", "", ""],
        "Updated On":  ["2026-04-27", "2026-04-27", "", ""],
    }
    df = pd.DataFrame(dummy_data)

    # Interactive editable table
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=["1-New", "2-In Progress", "3-Loading Passed", "4-Booking Done", "0-Withdraw Request"]
            ),
            "ETD": st.column_config.DateColumn("ETD"),
        },
        hide_index=True,
        key="daily_shipment_table"
    )

    if btn_update:
        st.success(f"Updated {len(edited_df)} rows to SQL", icon="✅")

    if btn_pass:
        st.success("Pass Loading done!", icon="✅")

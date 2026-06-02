import streamlit as st
import sys, os

current_file = os.path.abspath(__file__)
src_folder = os.path.join(os.path.dirname(os.path.dirname(current_file)), "src")
sys.path.insert(0, src_folder)

import db
import nav  # type: ignore

st.set_page_config(page_title="Dev - Daily Table Admin", page_icon="⚙️", layout="wide")
nav.sidebar()
st.title("⚙️ Dev - Daily Table Admin")

# ── Status ──
exists = db.daily_table_exists()
if exists:
    cnt = db.daily_count()
    st.success(f"✅ Table [fact].[DailyShipment] exists — {cnt} records")
else:
    st.warning("⚠️ Table [fact].[DailyShipment] does NOT exist")

st.divider()

# ── Table Management ──
st.subheader("Table Management")
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📝 Create Table", use_container_width=True, type="primary"):
        if db.daily_create_table():
            st.success("Created [fact].[DailyShipment]")
            st.rerun()
        else:
            st.error("Failed — table may already exist")

with col2:
    if st.button("🗑️ Truncate (clear data)", use_container_width=True):
        if st.session_state.get("confirm_truncate"):
            if db.daily_truncate_table():
                st.success("Truncated — all rows deleted, table kept")
                st.session_state.confirm_truncate = False
                st.rerun()
            else:
                st.error("Failed to truncate")
        else:
            st.session_state.confirm_truncate = True
            st.warning("Click again to confirm truncate")

with col3:
    if st.button("💥 Drop Table", use_container_width=True):
        if st.session_state.get("confirm_drop"):
            if db.daily_drop_table():
                st.success("Dropped [fact].[DailyShipment]")
                st.session_state.confirm_drop = False
                st.rerun()
            else:
                st.error("Failed to drop")
        else:
            st.session_state.confirm_drop = True
            st.warning("Click again to confirm drop")

st.divider()

# ── History Table ──
st.subheader("Version History Table")
hist_exists = db.history_table_exists()
col_h1, col_h2 = st.columns(2)
with col_h1:
    if st.button("📝 Create DailyShipmentHistory Table", use_container_width=True, type="primary"):
        if db.history_create_table():
            st.success("Created [fact].[DailyShipmentHistory]")
            st.rerun()
        else:
            st.error("Failed — table may already exist")
with col_h2:
    if hist_exists:
        cnt = db.fetch("SELECT COUNT(*) AS cnt FROM [fact].[DailyShipmentHistory]")
        st.info(f"✅ Table exists — {int(cnt.iloc[0]['cnt'])} history records")
    else:
        st.warning("⚠️ Table does not exist — create it to enable version history")

st.divider()

# ── Templates Table ──
st.subheader("Column Templates Table")
tmpl_exists = not db.template_get_all().empty

col_t1, col_t2 = st.columns(2)
with col_t1:
    if st.button("📝 Create ColumnTemplates Table", use_container_width=True, type="primary"):
        if db.template_create_table():
            st.success("Created [fact].[ColumnTemplates]")
            st.rerun()
        else:
            st.error("Failed — check if schema 'fact' exists and you have CREATE permission")

with col_t2:
    if tmpl_exists:
        df_tmpl = db.template_get_all()
        st.dataframe(df_tmpl[["TemplateName", "TeamName", "IsDefault", "UpdatedBy", "UpdatedAt"]], use_container_width=True)
    else:
        st.info("No templates yet")

st.divider()

# ── FormulaConfig Tables ──
st.subheader("Formula Config Tables")
fc_exists  = db.formula_config_table_exists()
fm_exists  = db.formula_mapping_table_exists()

col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    if st.button("📝 Create FormulaConfig Tables", use_container_width=True, type="primary"):
        if db.formula_config_create_tables():
            st.success("Created [fact].[FormulaConfig] + [fact].[FormulaMapping]")
            st.rerun()
        else:
            st.error("Failed — tables may already exist or missing permissions")

with col_f2:
    if st.button("🌱 Seed Default Formulas", use_container_width=True):
        if not fc_exists:
            st.error("Create tables first")
        else:
            if db.formula_config_seed():
                st.success("Seeded 11 default formula rules")
                st.rerun()
            else:
                st.error("Seed failed")

with col_f3:
    if fc_exists:
        cnt_fc = db.fetch("SELECT COUNT(*) AS cnt FROM [fact].[FormulaConfig]")
        cnt_fm = db.fetch("SELECT COUNT(*) AS cnt FROM [fact].[FormulaMapping]")
        n_fc = int(cnt_fc.iloc[0]["cnt"]) if not cnt_fc.empty else 0
        n_fm = int(cnt_fm.iloc[0]["cnt"]) if not cnt_fm.empty else 0
        st.info(f"✅ FormulaConfig: {n_fc} rules | FormulaMapping: {n_fm} entries")
    else:
        st.warning("⚠️ FormulaConfig tables do not exist")

st.divider()

# ── Raw Query Tester ──
st.subheader("Raw SQL Query")
query_input = st.text_area("SQL Query", height=120, placeholder="SELECT TOP 10 * FROM [fact].[DailyShipment] ORDER BY ID DESC")

if st.button("▶️ Execute", type="primary"):
    if query_input.strip():
        df = db.fetch(query_input)
        if not df.empty:
            st.success(f"{len(df)} rows")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No rows returned")
    else:
        st.warning("Enter a query")

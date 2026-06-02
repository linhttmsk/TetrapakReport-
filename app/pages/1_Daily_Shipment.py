import streamlit as st
import pandas as pd
import sys, os, json
from datetime import datetime

current_file = os.path.abspath(__file__)
src_folder = os.path.join(os.path.dirname(os.path.dirname(current_file)), "src")
sys.path.insert(0, src_folder)

import db
import nav  # type: ignore

st.set_page_config(page_title="Daily Shipment", page_icon="🚢", layout="wide")
nav.sidebar()


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR — Column Template Management
# ═══════════════════════════════════════════════════════════════════════════


# ── Active columns: set from applied template, never from the column picker ──
if "active_columns" not in st.session_state:
    st.session_state.active_columns = db.template_get_default_columns()

with st.sidebar:
    st.divider()
    st.header("Column Templates")

    all_templates = db.template_get_all()
    tmpl_names = all_templates["TemplateName"].tolist() if not all_templates.empty else []

    # ── Select & apply template → updates active_columns ──
    _tmpl_options = ["(Custom)"] + tmpl_names
    _default_idx  = 0
    if not all_templates.empty:
        _def = all_templates[all_templates["IsDefault"] == 1]
        if not _def.empty:
            _def_name = _def.iloc[0]["TemplateName"]
            if _def_name in tmpl_names:
                _default_idx = tmpl_names.index(_def_name) + 1  # +1 for "(Custom)"
    selected_tmpl = st.selectbox("Active template", _tmpl_options, index=_default_idx, key="sel_tmpl")

    if selected_tmpl != "(Custom)" and st.button("Apply template", use_container_width=True):
        st.session_state.active_columns = db.template_get_columns(selected_tmpl)
        st.rerun()

    st.divider()

    # ── Create template — column picker here is ONLY for building a new template ──
    with st.expander("💾 Create Template"):
        st.caption("Select columns to include in this template:")

        if "tmpl_draft_cols" not in st.session_state:
            st.session_state.tmpl_draft_cols = db.template_get_default_columns()

        chosen = st.multiselect(
            "Columns",
            options=db.DAILY_COLUMNS,
            default=[c for c in st.session_state.tmpl_draft_cols if c in db.DAILY_COLUMNS],
            key="col_picker",
            label_visibility="collapsed",
        )
        st.session_state.tmpl_draft_cols = chosen

        st.divider()

        t_name = st.text_input("Template name", key="new_tmpl_name")
        t_team = st.text_input("Team (optional)", key="new_tmpl_team")
        t_default = st.checkbox("Set as default", key="new_tmpl_default")
        if st.button("Save", use_container_width=True, key="btn_save_tmpl"):
            if t_name.strip() and chosen:
                if db.template_save(t_name.strip(), chosen, t_team.strip(), t_default):
                    st.success(f"Saved '{t_name}'")
                    st.rerun()
                else:
                    st.error("Save failed")
            else:
                st.warning("Enter a name and select at least one column")

    # ── Delete template ──
    if tmpl_names:
        with st.expander("🗑️ Delete Template"):
            del_name = st.selectbox("Select to delete", tmpl_names, key="del_tmpl_sel")
            if st.button("Delete", use_container_width=True, key="btn_del_tmpl"):
                if db.template_delete(del_name):
                    st.success(f"Deleted '{del_name}'")
                    st.rerun()

active_cols = st.session_state.active_columns  # shorthand

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

st.title("🚢 Daily Shipment Management")
st.caption(f"Showing {len(active_cols)} columns · Template: {selected_tmpl}")

if "df_data" not in st.session_state:
    st.session_state.df_data = pd.DataFrame()
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "show_delete" not in st.session_state:
    st.session_state.show_delete = False

STATUS_OPTIONS = [
    "14-Vessel arrived at destination", "1-New", "2-In Progress",
    "3-Loading Passed", "4-Booking Done", "0-Withdraw Request",
]
_MODES = ["Insert New", "Update Existing (by DO No.)", "Upsert (Insert or Update)"]


def _run_import(df_in: pd.DataFrame, mode: str):
    if not db.daily_table_exists():
        st.error("Table [fact].[DailyShipment] does not exist — go to Dev page to create it first")
        return
    df_in = df_in.dropna(how="all")
    if "DO_No" in df_in.columns:
        df_in = df_in[df_in["DO_No"].notna() & (df_in["DO_No"].astype(str).str.strip() != "")]
    if df_in.empty:
        st.warning("No valid rows — DO No. is required and must not be empty")
        return
    all_warnings = []
    for rec in db._map_df_to_records(df_in):
        w = db.daily_validate_record(rec)
        if w:
            all_warnings += [f"[{rec.get('DO_No','?')}] {x}" for x in w]
    if all_warnings:
        with st.expander(f"⚠️ Type warnings — {len(all_warnings)} column(s) will be NULL"):
            for w in all_warnings:
                st.text(w)
    CHUNK = 500
    total = len(df_in)
    prog  = st.progress(0, text=f"0 / {total} rows...")
    stat  = st.empty()
    tot_ok = tot_fail = tot_ins = tot_upd = 0
    all_errors: list = []
    for i in range(0, total, CHUNK):
        chunk = df_in.iloc[i : i + CHUNK]
        prog.progress(i / total, text=f"{i} / {total} rows...")
        stat.caption(f"Processing rows {i + 1}–{min(i + CHUNK, total)}...")
        if mode == "Insert New":
            ok, fail, errs = db.daily_bulk_insert(chunk)
            tot_ok += ok;  tot_fail += fail
        elif mode == "Update Existing (by DO No.)":
            ok, fail, errs = db.daily_bulk_update(chunk)
            tot_ok += ok;  tot_fail += fail
        else:
            ins, upd, fail, errs = db.daily_bulk_upsert(chunk)
            tot_ins += ins;  tot_upd += upd;  tot_fail += fail
        all_errors.extend(errs)
    prog.progress(1.0, text=f"Done — {total} rows processed")
    stat.empty()
    if mode == "Insert New":
        (st.success if tot_ok else st.error)(f"Inserted **{tot_ok}** rows — {tot_fail} failed")
    elif mode == "Update Existing (by DO No.)":
        (st.success if tot_ok else st.error)(f"Updated **{tot_ok}** rows — {tot_fail} failed")
    else:
        if tot_ins or tot_upd:
            st.success(f"Inserted **{tot_ins}** + Updated **{tot_upd}** — {tot_fail} failed")
        else:
            st.error(f"All {tot_fail} rows failed")
    if all_errors:
        with st.expander(f"⚠️ Error details ({len(all_errors)} issues)"):
            for e in all_errors[:20]:
                st.text(e)
    st.session_state.df_data = pd.DataFrame()


# ── Tab selector ──
st.divider()
_TABS = ["🔍 Filter & View", "📋 Paste / Type", "📁 Upload Excel", "📜 Version History"]
active_tab = st.radio("", _TABS, horizontal=True, key="main_tab", label_visibility="collapsed")
st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — FILTER & VIEW  (fragment → buttons only rerun this block)
# ═══════════════════════════════════════════════════════════════════════════
@st.fragment
def _tab_filter_view():
    active_cols = st.session_state.active_columns

    st.caption("💡 Use filters to find shipments that need to be updated before saving changes")
    def _parse(raw: str) -> list:
        return [x.strip() for x in raw.replace(",", "\n").split("\n") if x.strip()]

    col1, col2 = st.columns([4, 1.5])
    with col1:
        filter_status = st.selectbox("Filter by Status", [
            "All", "14-Vessel arrived at destination", "1-New", "2-In Progress",
            "3-Loading Passed", "4-Booking Done", "0-Withdraw Request",
        ])
    with col2:
        st.write("")
        btn_refresh = st.button("🔄 Refresh Data", use_container_width=True, type="primary")

    col3, col4, col5, col6 = st.columns(4)
    with col3:
        filter_do_nos_raw = st.text_area(
            "DO No.", height=80, placeholder="one per line or comma-separated", key="filter_do_nos",
        )
    with col4:
        filter_shipment_raw = st.text_area(
            "Shipment No.", height=80, placeholder="one per line or comma-separated", key="filter_shipment_nos",
        )
    with col5:
        filter_bl_raw = st.text_area(
            "BL No.", height=80, placeholder="one per line or comma-separated", key="filter_bl_nos",
        )
    with col6:
        filter_container_raw = st.text_area(
            "Container No.", height=80, placeholder="one per line or comma-separated", key="filter_container_nos",
        )

    col7, col8 = st.columns([1.5, 1.5])
    with col7:
        filter_etd_from = st.date_input("ETD From", value=None, key="etd_from")
    with col8:
        filter_etd_to = st.date_input("ETD To", value=None, key="etd_to")

    filter_do_nos      = _parse(filter_do_nos_raw)
    filter_shipment_nos = _parse(filter_shipment_raw)
    filter_bl_nos      = _parse(filter_bl_raw)
    filter_container_nos = _parse(filter_container_raw)

    if btn_refresh:
        st.session_state.df_data = pd.DataFrame()

    if st.session_state.df_data.empty:
        with st.spinner("Loading from SQL..."):
            st.session_state.df_data = db.daily_fetch_all(
                status=None if filter_status == "All" else filter_status,
                do_nos=filter_do_nos or None,
                bl_nos=filter_bl_nos or None,
                shipment_nos=filter_shipment_nos or None,
                container_nos=filter_container_nos or None,
                etd_from=filter_etd_from,
                etd_to=filter_etd_to,
                limit=5000,
            )
            st.session_state.last_refresh = datetime.now().strftime("%H:%M:%S")

    df_display = st.session_state.df_data.copy()
    st.divider()

    if df_display.empty:
        st.warning("No records found. Click Refresh or adjust filters.")
        return

    st.info(f"📦 **{len(df_display)}** records · Last refresh: {st.session_state.last_refresh}")

    view_cols = ["ID"] + [c for c in active_cols if c != "ID"]
    available = [c for c in view_cols if c in df_display.columns]
    df_view   = df_display[available].copy()

    edited_df = st.data_editor(
        df_view, use_container_width=True, num_rows="fixed",
        column_config={
            "ID":            st.column_config.NumberColumn("ID", disabled=True),
            "DO_No":            st.column_config.TextColumn("DO_No", disabled=True),
            "Status":        st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
            "DO_ETD":        st.column_config.DatetimeColumn("DO ETD"),
            "Requested_ETA": st.column_config.DatetimeColumn("Requested ETA"),
            "UpdatedAt":     st.column_config.DatetimeColumn("Updated At", disabled=True),
            "UpdatedBy":     st.column_config.TextColumn("Updated By", disabled=True),
            "CreatedAt":     st.column_config.DatetimeColumn("Created At", disabled=True),
            "CreatedBy":     st.column_config.TextColumn("Created By", disabled=True),
        },
        hide_index=True, key="view_editor",
    )

    col_a1, col_a2, col_a3, col_a4 = st.columns([1.5, 1.5, 1.5, 1.5])
    with col_a1:
        btn_sync  = st.button("💾 Save Changes",     use_container_width=True, type="primary")
    with col_a2:
        if st.button("🗑️ Delete by DO No.", use_container_width=True):
            st.session_state.show_delete = not st.session_state.show_delete
    with col_a3:
        btn_reset = st.button("🔙 Discard & Reload", use_container_width=True)
    with col_a4:
        if st.session_state.show_delete:
            if st.button("✖ Cancel Delete", use_container_width=True):
                st.session_state.show_delete = False

    if btn_sync:
        changes = 0
        for idx in range(len(edited_df)):
            if idx >= len(df_view):
                continue
            changed = any(
                not (pd.isna(df_view.iloc[idx].get(c)) and pd.isna(edited_df.iloc[idx].get(c)))
                and df_view.iloc[idx].get(c) != edited_df.iloc[idx].get(c)
                for c in available if c not in ("ID", "CreatedAt", "CreatedBy")
            )
            if changed:
                do_no = edited_df.iloc[idx].get("DO_No")
                if do_no:
                    record = {k: v for k, v in edited_df.iloc[idx].to_dict().items()
                              if k != "ID" and not (isinstance(v, float) and pd.isna(v))}
                    if db.daily_update(do_no, record):
                        changes += 1
        if changes:
            st.success(f"✅ Saved {changes} record(s)")
            st.session_state.df_data = pd.DataFrame()
        else:
            st.info("No changes detected")

    if st.session_state.show_delete:
        st.divider()
        del_raw = st.text_area(
            "🗑️ DO No. to delete — one per line or comma-separated",
            height=100, placeholder="DO-001\nDO-002, DO-003", key="del_do_input",
        )
        del_list = [x.strip() for x in del_raw.replace(",", "\n").split("\n") if x.strip()]
        if del_list:
            st.warning(f"Will delete **{len(del_list)}** record(s): {', '.join(del_list[:10])}{'...' if len(del_list) > 10 else ''}")
            if st.button("✅ Confirm Delete", key="confirm_del", type="primary"):
                ok, fail, errs = db.daily_bulk_delete(del_list)
                (st.success if ok else st.error)(
                    f"Deleted **{ok}** record(s)" + (f" — {fail} failed" if fail else "")
                )
                if errs:
                    with st.expander(f"Error details ({len(errs)})"):
                        for e in errs: st.text(e)
                st.session_state.show_delete = False
                st.session_state.df_data = pd.DataFrame()

    if btn_reset:
        st.session_state.show_delete = False
        st.session_state.df_data = pd.DataFrame()



# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — PASTE / TYPE  (fragment)
# ═══════════════════════════════════════════════════════════════════════════
@st.fragment
def _tab_paste():
    active_cols  = st.session_state.active_columns
    import_mode_t = st.radio("Mode", _MODES, horizontal=True, key="imode_table")

    _AUDIT = {"CreatedBy", "CreatedAt", "UpdatedBy", "UpdatedAt"}
    import_cols = [c for c in active_cols if c in db.DAILY_COLUMNS and c not in _AUDIT]
    if "DO_No" not in import_cols:
        import_cols = ["DO_No"] + import_cols

    st.caption(f"⚠️ **Khi paste từ Excel, cột phải đúng thứ tự:** `{'  |  '.join(import_cols)}`")
    st.caption("Click vào ô đầu tiên → Ctrl+V · DO No. là bắt buộc")

    empty_df = pd.DataFrame({c: pd.Series(dtype="object") for c in import_cols})
    empty_df = pd.concat([empty_df, pd.DataFrame([{c: None for c in import_cols}] * 5)], ignore_index=True)

    import_edited = st.data_editor(
        empty_df, use_container_width=True, num_rows="dynamic",
        column_config={
            "Status":        st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
            "DO_ETD":        st.column_config.DatetimeColumn("DO ETD"),
            "Requested_ETA": st.column_config.DatetimeColumn("Requested ETA"),
        },
        hide_index=True, key="import_table_editor",
    )
    if st.button("💾 Save to SQL", type="primary", key="btn_save_table"):
        _run_import(import_edited.copy(), import_mode_t)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — UPLOAD EXCEL  (fragment)
# ═══════════════════════════════════════════════════════════════════════════
@st.fragment
def _tab_excel():
    import_mode_e = st.radio("Mode", _MODES, horizontal=True, key="imode_excel")
    uploaded = st.file_uploader("Choose Excel file (.xlsx / .xls)", type=["xlsx", "xls"], key="excel_uploader")

    if uploaded:
        try:
            xl    = pd.ExcelFile(uploaded)
            sheet = (
                st.selectbox("Sheet", xl.sheet_names, key="sheet_sel")
                if len(xl.sheet_names) > 1 else xl.sheet_names[0]
            )
            df_xl = pd.read_excel(uploaded, sheet_name=sheet)
            df_xl.columns = df_xl.columns.str.strip()
            st.info(f"**{len(df_xl)}** rows from sheet **{sheet}** — preview first 50 rows (import uses all rows):")
            st.dataframe(df_xl.head(50), use_container_width=True, hide_index=True)
            if st.button("💾 Import to SQL", type="primary", key="btn_import_excel"):
                _run_import(df_xl.copy(), import_mode_e)
        except Exception as e:
            st.error(f"Read error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4 — VERSION HISTORY  (fragment)
# ═══════════════════════════════════════════════════════════════════════════
@st.fragment
def _tab_history():
    if not db.history_table_exists():
        st.warning("History table not created yet — go to Dev page and click **Create DailyShipmentHistory Table**")
        return

    h_raw = st.text_area(
        "DO No. — one per line or comma-separated",
        height=80, placeholder="e.g.\nDO-001\nDO-002, DO-003", key="hist_do_input",
    )
    if not h_raw.strip():
        st.info("Enter DO No. above to load history")
        return

    do_list = [x.strip() for x in h_raw.replace(",", "\n").split("\n") if x.strip()]

    rows = []
    for do_no in do_list:
        hist_df = db.history_fetch_by_do(do_no, limit=100)
        for _, row in hist_df.iterrows():
            try:
                snap = json.loads(row["SnapshotJSON"])
            except Exception:
                snap = {}
            snap["DO_No"]      = do_no
            snap["Action"]     = row["HistoryAction"]
            snap["Changed At"] = row["HistoryAt"]
            snap["Changed By"] = row["HistoryBy"]
            rows.append(snap)

    if not rows:
        st.info(f"No history found for: {', '.join(do_list)}")
        return

    flat = pd.DataFrame(rows)
    meta = ["DO_No", "Action", "Changed At", "Changed By"]
    rest = [c for c in flat.columns if c not in meta]
    flat = flat[meta + rest]

    st.caption(f"**{len(flat)}** version(s) for **{len(do_list)}** DO No(s) — use the download button to export CSV")
    st.dataframe(flat, use_container_width=True, hide_index=True)


# ── Render active tab ──
if active_tab == _TABS[0]:
    _tab_filter_view()
elif active_tab == _TABS[1]:
    _tab_paste()
elif active_tab == _TABS[2]:
    _tab_excel()
else:
    _tab_history()


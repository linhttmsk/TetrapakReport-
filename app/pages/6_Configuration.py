import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import db  # type: ignore
import nav  # type: ignore

st.set_page_config(page_title="Configuration", page_icon="🔧", layout="wide")
nav.sidebar()
st.title("🔧 Configuration")

# ── Guard: tables must exist ──
if not db.formula_config_table_exists():
    st.warning("FormulaConfig tables not created yet. Go to **Dev** page and click **Create FormulaConfig Tables**.")
    st.stop()

# ══════════════════════════════════════════════════════════════
# FORMULA RULES
# ══════════════════════════════════════════════════════════════

st.subheader("Formula Rules")
st.caption(
    "Each rule auto-fills a column when data is saved. Rules with **DONE** in the target column are skipped. "
    "Changes take effect on the next save; existing rows are not back-filled."
)

df_cfg = db.formula_config_get_all()

FORMULA_TYPES = db.FORMULA_TYPES
ALL_COLS = db.DAILY_COLUMNS

# helper: blank string → None, None → blank
def _s(v): return "" if v is None else str(v)
def _n(s): return None if (s is None or str(s).strip() == "") else str(s).strip()
def _ni(s):
    try: return int(s)
    except Exception: return 0


@st.fragment
def _formula_rules_section():
    df = db.formula_config_get_all()

    # ── Existing rules table ──
    if df.empty:
        st.info("No formula rules yet. Add one below.")
    else:
        # Show as read-only table + per-row actions
        col_headers = ["Target Column", "Formula Type", "Source 1", "Source 2",
                       "Offset", "Cond Col", "Thresh", "Off True", "Off False",
                       "Order", "Description", ""]
        hdr = st.columns([2, 2, 1.5, 1.5, 0.8, 1.5, 0.8, 0.8, 0.8, 0.8, 3, 1])
        for h, col in zip(col_headers, hdr):
            col.markdown(f"**{h}**")
        st.divider()

        for _, row in df.iterrows():
            rid = int(row["ID"])
            cols = st.columns([2, 2, 1.5, 1.5, 0.8, 1.5, 0.8, 0.8, 0.8, 0.8, 3, 1])
            cols[0].write(row["TargetCol"])
            cols[1].write(row["FormulaType"])
            cols[2].write(_s(row.get("SourceCol1")))
            cols[3].write(_s(row.get("SourceCol2")))
            cols[4].write(_s(row.get("OffsetDays")))
            cols[5].write(_s(row.get("ConditionCol")))
            cols[6].write(_s(row.get("Threshold")))
            cols[7].write(_s(row.get("OffsetTrue")))
            cols[8].write(_s(row.get("OffsetFalse")))
            cols[9].write(_s(row.get("SortOrder")))
            cols[10].write(_s(row.get("Description")))
            if cols[11].button("✏️", key=f"edit_{rid}", help="Edit this rule"):
                st.session_state["_fc_edit_id"] = rid
                st.rerun()

    # ── Edit / Add form ──
    edit_id = st.session_state.get("_fc_edit_id")
    edit_row = None
    if edit_id and not df.empty:
        matches = df[df["ID"] == edit_id]
        if not matches.empty:
            edit_row = matches.iloc[0].to_dict()

    with st.expander("➕ Add rule" if not edit_row else f"✏️ Edit rule — {edit_row['TargetCol']}", expanded=(edit_row is not None)):
        with st.form("fc_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            target_default = edit_row["TargetCol"] if edit_row else ALL_COLS[0]
            target = c1.selectbox("Target Column *", ALL_COLS,
                                   index=ALL_COLS.index(target_default) if target_default in ALL_COLS else 0)
            ftype_default = edit_row["FormulaType"] if edit_row else FORMULA_TYPES[0]
            ftype = c2.selectbox("Formula Type *", FORMULA_TYPES,
                                  index=FORMULA_TYPES.index(ftype_default) if ftype_default in FORMULA_TYPES else 0)

            src_cols = [""] + ALL_COLS
            c3, c4 = st.columns(2)
            src1_default = _s(edit_row.get("SourceCol1")) if edit_row else ""
            src1 = c3.selectbox("Source Col 1", src_cols,
                                 index=src_cols.index(src1_default) if src1_default in src_cols else 0)
            src2_default = _s(edit_row.get("SourceCol2")) if edit_row else ""
            src2 = c4.selectbox("Source Col 2", src_cols,
                                 index=src_cols.index(src2_default) if src2_default in src_cols else 0)

            c5, c6, c7, c8, c9, c10 = st.columns(6)
            offset    = c5.number_input("Offset Days",  value=_ni(edit_row.get("OffsetDays"))  if edit_row else 0, step=1)
            cond_col_default = _s(edit_row.get("ConditionCol")) if edit_row else ""
            cond_col  = c6.selectbox("Condition Col", src_cols,
                                     index=src_cols.index(cond_col_default) if cond_col_default in src_cols else 0)
            threshold = c7.number_input("Threshold",   value=_ni(edit_row.get("Threshold"))   if edit_row else 0, step=1)
            off_true  = c8.number_input("Offset True", value=_ni(edit_row.get("OffsetTrue"))  if edit_row else 0, step=1)
            off_false = c9.number_input("Offset False",value=_ni(edit_row.get("OffsetFalse")) if edit_row else 0, step=1)
            sort_order= c10.number_input("Sort Order", value=_ni(edit_row.get("SortOrder"))   if edit_row else 0, step=10)

            desc = st.text_input("Description", value=_s(edit_row.get("Description")) if edit_row else "")

            bc1, bc2, bc3 = st.columns([1, 1, 4])
            submitted = bc1.form_submit_button("💾 Save", type="primary")
            cancelled = bc2.form_submit_button("Cancel")

            if cancelled:
                st.session_state.pop("_fc_edit_id", None)
                st.rerun()

            if submitted:
                record = {
                    "TargetCol":    target,
                    "FormulaType":  ftype,
                    "SourceCol1":   _n(src1),
                    "SourceCol2":   _n(src2),
                    "OffsetDays":   int(offset),
                    "ConditionCol": _n(cond_col),
                    "Threshold":    int(threshold),
                    "OffsetTrue":   int(off_true),
                    "OffsetFalse":  int(off_false),
                    "SortOrder":    int(sort_order),
                    "Description":  _n(desc),
                }
                if edit_row:
                    record["ID"] = edit_id
                if db.formula_config_save(record):
                    st.success("Saved.")
                    st.session_state.pop("_fc_edit_id", None)
                    st.rerun()
                else:
                    st.error(f"Save failed: {db._last_error}")

    # ── Delete ──
    if not df.empty:
        with st.expander("🗑️ Delete a rule"):
            options = {f"[{int(r['ID'])}] {r['TargetCol']} — {r['FormulaType']}": int(r["ID"])
                       for _, r in df.iterrows()}
            chosen = st.selectbox("Select rule to delete", list(options.keys()))
            if st.button("Delete", type="primary", key="fc_del"):
                db.formula_config_delete(options[chosen])
                st.rerun()


_formula_rules_section()

# ══════════════════════════════════════════════════════════════
# CODE MAPPINGS (for CODE_MAP formula type)
# ══════════════════════════════════════════════════════════════

st.divider()
st.subheader("Code Mappings")
st.caption("Input → Output value pairs for rules that use **CODE_MAP** formula type.")

df_all = db.formula_config_get_all()
code_map_rows = df_all[df_all["FormulaType"] == "CODE_MAP"] if not df_all.empty else df_all

if code_map_rows.empty:
    st.info("No CODE_MAP formula rules found. Add one above first.")
else:
    @st.fragment
    def _code_mapping_section():
        df_cfg2 = db.formula_config_get_all()
        cm_rows = df_cfg2[df_cfg2["FormulaType"] == "CODE_MAP"]

        options = {f"[{int(r['ID'])}] {r['TargetCol']} (src: {r['SourceCol1']})": int(r["ID"])
                   for _, r in cm_rows.iterrows()}
        chosen_label = st.selectbox("Select CODE_MAP rule", list(options.keys()), key="cm_select")
        cfg_id = options[chosen_label]

        df_map = db.formula_mapping_get(cfg_id)

        st.markdown("**Edit mappings** — Input values are matched case-insensitively")
        if df_map.empty:
            rows_edit = [{"InputValue": "", "OutputValue": ""}]
        else:
            rows_edit = df_map[["InputValue", "OutputValue"]].to_dict("records")
            rows_edit.append({"InputValue": "", "OutputValue": ""})

        edited = st.data_editor(
            rows_edit,
            column_config={
                "InputValue":  st.column_config.TextColumn("Input Value (e.g. MAEU)", width="medium"),
                "OutputValue": st.column_config.TextColumn("Output Value (e.g. IC26TML)", width="medium"),
            },
            num_rows="dynamic",
            use_container_width=True,
            key=f"cm_editor_{cfg_id}",
        )

        if st.button("💾 Save Mappings", type="primary", key=f"cm_save_{cfg_id}"):
            clean = [r for r in edited if r.get("InputValue", "").strip()]
            if db.formula_mapping_save_all(cfg_id, clean):
                st.success(f"Saved {len(clean)} mapping(s).")
                st.rerun()
            else:
                st.error(f"Save failed: {db._last_error}")

    _code_mapping_section()

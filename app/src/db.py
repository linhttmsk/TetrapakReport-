"""
app/src/db.py — SQL Server connection & core CRUD
Credentials fetched from Azure Key Vault, cached in-process with configurable TTL.
"""
import pyodbc
import pandas as pd
import time
import base64
from datetime import datetime, timedelta
from configparser import ConfigParser
import os, getpass, json

# ── Config ──
current_file = os.path.abspath(__file__)
app_folder   = os.path.dirname(os.path.dirname(current_file))
inifile      = os.path.join(app_folder, ".streamlit", "config.ini")
parser       = ConfigParser()
parser.read(inifile)

DRIVER    = parser.get("SQL",   "driver",        fallback="ODBC Driver 17 for SQL Server")
VAULT_URL = parser.get("AZURE", "vault_url",     fallback="https://tlt023keyvault.vault.azure.net/")
TENANT_ID = parser.get("AZURE", "tenant_id",     fallback="05d75c05-fa1a-42e7-9cf1-eb416c396f2d")
CACHE_TTL = int(parser.get("AZURE", "cache_ttl_sec", fallback="28800"))

USER = getpass.getuser().upper()

# ── Key Vault credential cache ──
_kv_cache:      dict  = {}
_kv_fetched_at: float = 0.0

# ── Persistent connection ──
_conn: pyodbc.Connection | None = None


_KR_SERVICE = "TetrapakReport"
_KR_USER    = "db_secrets"


def _kr_load() -> tuple[dict, float]:
    """Load secrets + timestamp from Windows Credential Manager."""
    import keyring
    raw = keyring.get_password(_KR_SERVICE, _KR_USER)
    if not raw:
        return {}, 0.0
    d = json.loads(raw)
    return d.get("s", {}), d.get("t", 0.0)


def _kr_save(secrets: dict, fetched_at: float):
    """Persist secrets + timestamp to Windows Credential Manager."""
    import keyring
    keyring.set_password(_KR_SERVICE, _KR_USER, json.dumps({"s": secrets, "t": fetched_at}))


def _get_secrets() -> dict:
    
    """Return SQL credentials, using a 3-layer cache:
       1. In-memory  → fastest, lives for the process lifetime
       2. Credential Manager → survives restarts, encrypted by Windows
       3. Azure Key Vault  → ground truth, opens browser on first use
    """
    global _kv_cache, _kv_fetched_at

    # 1 — in-memory
    if _kv_cache and (time.time() - _kv_fetched_at) < CACHE_TTL:
        return _kv_cache

    # 2 — Windows Credential Manager
    cached, fetched_at = _kr_load()
    if cached and (time.time() - fetched_at) < CACHE_TTL:
        _kv_cache, _kv_fetched_at = cached, fetched_at
        print("[DB] Secrets loaded from Credential Manager (cache hit)")
        return _kv_cache

    
    # 3 — Azure Key Vault (opens browser on first login)
    from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
    from azure.keyvault.secrets import SecretClient
    
    cred = InteractiveBrowserCredential(
        tenant_id=TENANT_ID,
        additionally_allowed_tenants=["*"],
        cache_persistence_options=TokenCachePersistenceOptions(name="TetrapakReport"),
    )
    client = SecretClient(vault_url=VAULT_URL, credential=cred)

    def _b64(name: str) -> str:
        return base64.b64decode(client.get_secret(name).value.encode("ascii")).decode("ascii")

    _kv_cache = {
        "SQLserver":   _b64("SQLserver"),
        "SQLdatabase": _b64("SQLdatabase"),
        "SQLuser":     _b64("SQLuser"),
        "SQLpassword": _b64("SQLpassword"),
    }
    _kv_fetched_at = time.time()
    _kr_save(_kv_cache, _kv_fetched_at)
    print(f"[DB] Key Vault secrets refreshed, saved to Credential Manager (TTL {CACHE_TTL//3600}h)")
    return _kv_cache


def _build_conn() -> pyodbc.Connection:
    s = _get_secrets()
    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={s['SQLserver']};"
        f"DATABASE={s['SQLdatabase']};"
        f"UID={s['SQLuser']};PWD={s['SQLpassword']};"
        "Encrypt=yes;TrustServerCertificate=yes;Trusted_Connection=no;"
        "MultipleActiveResultSets=yes;Connection Timeout=50;ConnectRetryInterval=10;"
    )
    return pyodbc.connect(conn_str)


def get_conn() -> pyodbc.Connection:
    """Return the shared persistent connection, reconnecting if dropped."""
    global _conn
    try:
        if _conn is not None:
            _conn.execute("SELECT 1")   # ping — fails if connection dropped
            return _conn
    except Exception:
        pass
    _conn = _build_conn()
    print("[DB] (Re)connected to SQL Server")
    return _conn


def test_conn() -> bool:
    try:
        get_conn()
        return True
    except:
        return False


# ── READ ──
def fetch(query: str, params: list = []) -> pd.DataFrame:
    try:
        df = pd.read_sql(query, get_conn(), params=params)
        return df
    except Exception as e:
        print(f"[DB] fetch error: {e}")
        return pd.DataFrame()


# ── INSERT ──
def insert(table: str, data: dict) -> bool:
    data["CreatedBy"] = USER
    data["CreatedOn"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["UpdatedBy"] = USER
    data["UpdatedOn"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols         = ", ".join(data.keys())
    placeholders = ", ".join(["?" for _ in data])
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    return _execute(sql, list(data.values()))


# ── UPDATE ──
def update(table: str, data: dict, key_col: str, key_val) -> bool:
    data["UpdatedBy"] = USER
    data["UpdatedOn"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
    sql = f"UPDATE {table} SET {set_clause} WHERE {key_col} = ?"
    return _execute(sql, list(data.values()) + [key_val])


# ── BATCH UPSERT (Insert or Update) ──
def batch_upsert(table: str, records: list, key_col: str) -> tuple:
    ok = fail = 0
    for rec in records:
        key_val = rec.get(key_col)
        if key_val is None:
            fail += 1
            continue
        df = fetch(f"SELECT 1 FROM {table} WHERE {key_col} = ?", [key_val])
        if df.empty:
            success = insert(table, dict(rec))
        else:
            r = dict(rec)
            r.pop(key_col, None)
            success = update(table, r, key_col, key_val)
        if success:
            ok += 1
        else:
            fail += 1
    return ok, fail


# ── DELETE ──
def delete(table: str, key_col: str, key_val) -> bool:
    sql = f"DELETE FROM {table} WHERE {key_col} = ?"
    return _execute(sql, [key_val])


# ── BATCH DELETE ──
def batch_delete(table: str, key_col: str, key_values: list) -> bool:
    placeholders = ", ".join(["?" for _ in key_values])
    sql = f"DELETE FROM {table} WHERE {key_col} IN ({placeholders})"
    return _execute(sql, key_values)


# ── EXECUTE helper ──
_last_error: str = ""

def _execute(sql: str, params: list = []) -> bool:
    global _last_error
    try:
        conn = get_conn()
        conn.execute(sql, params)
        conn.commit()
        _last_error = ""
        return True
    except Exception as e:
        _last_error = str(e)
        print(f"[DB] execute error: {e}")
        return False


# ── SEND EMAIL via Outlook ──
def send_email(to: str, subject: str, body: str, cc: str = "") -> bool:
    try:
        import win32com.client
        outlook      = win32com.client.Dispatch("Outlook.Application")
        mail         = outlook.CreateItem(0)
        mail.To      = to
        mail.CC      = cc
        mail.Subject = subject
        mail.Body    = body
        mail.Send()
        return True
    except Exception as e:
        print(f"[Email] error: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
# DAILY TABLE CRUD OPERATIONS (Key: DO_No)
# ═════════════════════════════════════════════════════════════════════════════

_TABLE         = "[fact].[DailyShipment]"
_TABLE_HISTORY = "[fact].[DailyShipmentHistory]"


# ═════════════════════════════════════════════════════════════════════════════
# HISTORY — snapshot rows to audit table before UPDATE / DELETE
# ═════════════════════════════════════════════════════════════════════════════

def history_table_exists() -> bool:
    df = fetch(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='DailyShipmentHistory' AND TABLE_SCHEMA='fact'"
    )
    return not df.empty


def history_create_table() -> bool:
    daily_create_schema()
    sql = """
        CREATE TABLE [fact].[DailyShipmentHistory] (
            [HistoryID]     INT IDENTITY(1,1) NOT NULL,
            [DO_No]         VARCHAR(255) NOT NULL,
            [HistoryAction] VARCHAR(20)  NOT NULL,
            [HistoryAt]     DATETIME     NOT NULL,
            [HistoryBy]     VARCHAR(255) NOT NULL,
            [SnapshotJSON]  VARCHAR(MAX)
        )
    """
    return _execute(sql)


def _history_snapshot(do_nos: list, action: str) -> None:
    """Copy current rows to history before modifying. Fails silently."""
    if not do_nos or not history_table_exists():
        return
    try:
        ph  = ", ".join("?" for _ in do_nos)
        cur = fetch(f"SELECT * FROM {_TABLE} WHERE [DO_No] IN ({ph})", do_nos)
        if cur.empty:
            return
        now  = datetime.now()
        rows = []
        for _, row in cur.iterrows():
            snap = {}
            for k, v in row.items():
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    snap[k] = None
                elif hasattr(v, "isoformat"):
                    snap[k] = v.isoformat()
                else:
                    snap[k] = v
            rows.append((str(row["DO_No"]), action, now, USER, json.dumps(snap, default=str)))
        sql = f"""INSERT INTO {_TABLE_HISTORY}
                  ([DO_No],[HistoryAction],[HistoryAt],[HistoryBy],[SnapshotJSON])
                  VALUES (?,?,?,?,?)"""
        _executemany(sql, rows)
    except Exception as e:
        print(f"[History] snapshot failed (non-fatal): {e}")


def history_fetch_by_do(do_no: str, limit: int = 50) -> pd.DataFrame:
    """Return history rows for a DO_No, newest first."""
    try:
        return fetch(
            f"SELECT TOP (?) [HistoryID],[HistoryAction],[HistoryAt],[HistoryBy],[SnapshotJSON]"
            f" FROM {_TABLE_HISTORY} WHERE [DO_No]=? ORDER BY [HistoryAt] DESC",
            [limit, do_no],
        )
    except Exception:
        return pd.DataFrame()

def daily_fetch_all(
    status: str = None,
    do_nos: list = None,
    bl_nos: list = None,
    shipment_nos: list = None,
    container_nos: list = None,
    etd_from=None,
    etd_to=None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Fetch Daily records with optional filters."""
    query = f"SELECT TOP (?) * FROM {_TABLE} WHERE 1=1"
    params = [limit]

    def _in(col, vals):
        ph = ", ".join("?" for _ in vals)
        return f" AND [{col}] IN ({ph})", list(vals)

    if status:
        query += " AND [Status] = ?"
        params.append(status)
    if do_nos:
        q, p = _in("DO_No", do_nos);         query += q; params.extend(p)
    if bl_nos:
        q, p = _in("BL_No", bl_nos);         query += q; params.extend(p)
    if shipment_nos:
        q, p = _in("Shipment_No", shipment_nos); query += q; params.extend(p)
    if container_nos:
        q, p = _in("Container_No", container_nos); query += q; params.extend(p)
    if etd_from:
        query += " AND [DO_ETD] >= ?"; params.append(str(etd_from))
    if etd_to:
        query += " AND [DO_ETD] <= ?"; params.append(str(etd_to))

    query += " ORDER BY [CreatedAt] DESC"
    return fetch(query, params)


def daily_fetch_by_do(do_no: str) -> pd.DataFrame:
    """Fetch single Daily record by DO_No."""
    query = f"SELECT * FROM {_TABLE} WHERE [DO_No] = ?"
    return fetch(query, [do_no])


def daily_validate_record(record: dict) -> list[str]:
    """Return list of column warnings for a record (wrong types that will be set to NULL)."""
    warnings = []
    for col, val in record.items():
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if col in _INT_COLS:
            try:
                int(float(str(val).replace(",", ".")))
            except Exception:
                warnings.append(f"{col} = '{val}' → not a valid integer, will be NULL")
        elif col in _DECIMAL_COLS:
            try:
                float(str(val).replace(",", "."))
            except Exception:
                warnings.append(f"{col} = '{val}' → not a valid number, will be NULL")
        elif col in _DATETIME_COLS:
            parsed = pd.to_datetime(val, dayfirst=False, errors="coerce")
            if pd.isna(parsed):
                warnings.append(f"{col} = '{val}' → not a valid date, will be NULL")
    return warnings


def daily_insert(record: dict) -> bool:
    """Insert single Daily record. Keys: DO_No (required), Status, Shipment_No, ..."""
    for k in list(record.keys()):
        record[k] = _coerce(k, record[k])
    record = _compute_formulas(record)

    record["CreatedBy"] = USER
    record["UpdatedBy"] = USER
    record["CreatedAt"] = datetime.now()
    record["UpdatedAt"] = datetime.now()

    cols = ", ".join([f"[{k}]" for k in record.keys()])
    placeholders = ", ".join(["?" for _ in record])
    sql = f"INSERT INTO {_TABLE} ({cols}) VALUES ({placeholders})"
    return _execute(sql, list(record.values()))


def daily_update(do_no: str, record: dict) -> bool:
    """Update Daily record by DO_No."""
    _history_snapshot([do_no], "UPDATE")
    for k in list(record.keys()):
        record[k] = _coerce(k, record[k])
    record = _compute_formulas(record)
    record["UpdatedBy"] = USER
    record["UpdatedAt"] = datetime.now()
    set_clause = ", ".join([f"[{k}] = ?" for k in record.keys()])
    sql = f"UPDATE {_TABLE} SET {set_clause} WHERE [DO_No] = ?"
    return _execute(sql, list(record.values()) + [do_no])


def daily_delete(do_no: str) -> bool:
    """Delete Daily record by DO_No."""
    _history_snapshot([do_no], "DELETE")
    sql = f"DELETE FROM {_TABLE} WHERE [DO_No] = ?"
    return _execute(sql, [do_no])


def daily_bulk_delete(do_nos: list) -> tuple:
    """Delete multiple records by DO_No. Returns (ok, fail, errors)."""
    clean = [str(d).strip() for d in do_nos if str(d).strip()]
    _history_snapshot(clean, "DELETE")
    ok = fail = 0
    errors: list[str] = []
    for do_no in clean:
        sql = f"DELETE FROM {_TABLE} WHERE [DO_No] = ?"
        if _execute(sql, [do_no]):
            ok += 1
        else:
            fail += 1
            errors.append(f"{do_no}: {_last_error}")
    return ok, fail, errors


# Excel header → DB column name. Also accepts DB column names directly (pass-through).
_COLUMN_MAPPING = {
    "Status": "Status",
    "Shipment no.": "Shipment_No",       "Shipment_No": "Shipment_No",
    "DO No.": "DO_No",                   "DO_No": "DO_No",
    "Group No.": "Group_No",             "Group_No": "Group_No",
    "DO ETD": "DO_ETD",                  "DO_ETD": "DO_ETD",
    "Ship-to": "Ship_To",                "Ship_To": "Ship_To",
    "Country": "Country",
    "IncoB": "IncoB",
    "Port of Discharge": "Port_of_Discharge",   "Port_of_Discharge": "Port_of_Discharge",
    "Transport Mode": "Transport_Mode",          "Transport_Mode": "Transport_Mode",
    "Requested ETA": "Requested_ETA",           "Requested_ETA": "Requested_ETA",
    "Cont Size": "Cont_Size",                   "Cont_Size": "Cont_Size",
    "Shipment ID (PRE carriage)": "Shipment_ID_PRE_Carriage",   "Shipment_ID_PRE_Carriage": "Shipment_ID_PRE_Carriage",
    "Shipment ID (MAIN carriage)": "Shipment_ID_MAIN_Carriage", "Shipment_ID_MAIN_Carriage": "Shipment_ID_MAIN_Carriage",
    "Exp. Invoice No.": "Exp_Invoice_No",       "Exp_Invoice_No": "Exp_Invoice_No",
    "Exp. Invoice date": "Exp_Invoice_Date",    "Exp_Invoice_Date": "Exp_Invoice_Date",
    "TPI Invoice no.": "TPI_Invoice_No",        "TPI_Invoice_No": "TPI_Invoice_No",
    "Packing list No.": "Packing_List_No",      "Packing_List_No": "Packing_List_No",
    "Actual full and correct docs received date": "Actual_Full_and_Correct_Docs_Received_Date",
    "Actual_Full_and_Correct_Docs_Received_Date": "Actual_Full_and_Correct_Docs_Received_Date",
    "G.W": "G_W",   "G_W": "G_W",
    "N. W": "N_W",  "N_W": "N_W",
    "Pallet": "Pallet",
    "Box": "Box",
    "Booking No": "Booking_No",         "Booking_No": "Booking_No",
    "Shipping line": "Shipping_Line",   "Shipping_Line": "Shipping_Line",
    "Vessel": "Vessel",
    "Voyage": "Voyage",
    "BL No": "BL_No",       "BL_No": "BL_No",
    "BL type": "BL_Type",   "BL_Type": "BL_Type",
    "BL Released on": "BL_Released_On", "BL_Released_On": "BL_Released_On",
    "Port Cutoff": "Port_Cutoff",       "Port_Cutoff": "Port_Cutoff",
    "SI Cutoff": "SI_Cutoff",           "SI_Cutoff": "SI_Cutoff",
    "VGM Cutoff": "VGM_Cutoff",         "VGM_Cutoff": "VGM_Cutoff",
    "Original ETD Port": "Original_ETD_Port",   "Original_ETD_Port": "Original_ETD_Port",
    "Delay ETD Port": "Delay_ETD_Port",         "Delay_ETD_Port": "Delay_ETD_Port",
    "ATD port": "ATD_Port",     "ATD_Port": "ATD_Port",
    "ETA dest": "ETA_Dest",     "ETA_Dest": "ETA_Dest",
    "Delay ETA Port": "Delay_ETA_Port", "Delay_ETA_Port": "Delay_ETA_Port",
    "ATA dest": "ATA_Dest",     "ATA_Dest": "ATA_Dest",
    "SI/VGM submission": "SI_VGM_Submission",   "SI_VGM_Submission": "SI_VGM_Submission",
    "Check draft": "Check_Draft",       "Check_Draft": "Check_Draft",
    "Send pre-alert": "Send_Pre_Alert", "Send_Pre_Alert": "Send_Pre_Alert",
    "Send SWB": "Send_SWB",             "Send_SWB": "Send_SWB",
    "Send final CO": "Send_Final_CO",   "Send_Final_CO": "Send_Final_CO",
    "Check debit note": "Check_Debit_Note", "Check_Debit_Note": "Check_Debit_Note",
    "Main carriage far week": "Main_Carriage_Far_Week", "Main_Carriage_Far_Week": "Main_Carriage_Far_Week",
    "Loading date": "Loading_Date",     "Loading_Date": "Loading_Date",
    "Container No.": "Container_No",    "Container_No": "Container_No",
    "Seal No": "Seal_No",               "Seal_No": "Seal_No",
    "Export Declaration No.": "Export_Declaration_No",  "Export_Declaration_No": "Export_Declaration_No",
    "Lane": "Lane",
    "Export Declaration Date": "Export_Declaration_Date", "Export_Declaration_Date": "Export_Declaration_Date",
    "Master Invoice No": "Master_Invoice_No",   "Master_Invoice_No": "Master_Invoice_No",
    "C/O No.": "C_O_No",    "C_O_No": "C_O_No",
    "CO Date": "CO_Date",   "CO_Date": "CO_Date",
    "Main carriage INV": "Main_Carriage_INV",           "Main_Carriage_INV": "Main_Carriage_INV",
    "Main carriage INV date": "Main_Carriage_INV_Date", "Main_Carriage_INV_Date": "Main_Carriage_INV_Date",
    "Ocean Freight (BAS)": "Main_Carriage_INV",  # legacy Excel header alias
    "Invoice date": "Main_Carriage_INV_Date",    # legacy Excel header alias
    "PIC": "PIC",
    "DO ETD Week": "DO_ETD_Week",       "DO_ETD_Week": "DO_ETD_Week",
    "Far billing week": "Far_Billing_Week", "Far_Billing_Week": "Far_Billing_Week",
    "Week allocation": "Week_Allocation",   "Week_Allocation": "Week_Allocation",
    "OF": "OF",
    "BAF": "BAF",
    "T.A": "T_A",   "T_A": "T_A",
    "ROE": "ROE",
    "Loading month": "Loading_Month",   "Loading_Month": "Loading_Month",
    "Loading Week": "Loading_Week",     "Loading_Week": "Loading_Week",
    "FAR approval status": "FAR_Approval_Status", "FAR_Approval_Status": "FAR_Approval_Status",
    "Serial no.": "Serial_No",          "Serial_No": "Serial_No",
    "Pending pallet": "Pending_Pallet", "Pending_Pallet": "Pending_Pallet",
}


# Columns that must be numeric — text values will be coerced to None
_INT_COLS = {
    "Delay_ETD_Port", "Delay_ETA_Port", "Pallet", "Box",
    "Main_Carriage_Far_Week", "DO_ETD_Week", "Far_Billing_Week",
    "Week_Allocation", "Loading_Month", "Loading_Week", "Pending_Pallet",
}
_DECIMAL_COLS = {
    "G_W", "N_W", "Main_Carriage_INV", "OF", "BAF", "T_A", "ROE",
}
_DATETIME_COLS = {
    "DO_ETD", "Requested_ETA", "Exp_Invoice_Date", "Actual_Full_and_Correct_Docs_Received_Date",
    "BL_Released_On", "Port_Cutoff", "SI_Cutoff", "VGM_Cutoff",
    "Original_ETD_Port", "ATD_Port", "ETA_Dest", "ATA_Dest",
    "Loading_Date", "Export_Declaration_Date", "CO_Date", "Customs_Finished",
    "Drop_Off_Container", "CDS_Cancellation", "Original_Documents_Couriered_On",
    "Main_Carriage_INV_Date",
}
# Formula columns stored as VARCHAR(50) — value is "YYYY-MM-DD" string or "DONE"
_FORMULA_DATE_COLS = {
    "SI_VGM_Submission", "Check_Draft", "Send_Pre_Alert",
    "Send_SWB", "Send_Final_CO", "Check_Debit_Note",
}
# FAR document code per shipping line carrier (used as seed data)
_FAR_CODES: dict[str, str] = {
    "COSU": "IC26TAB",
    "EGLV": "IC26TAA",
    "MAEU": "IC26TML",
    "REGU": "IC26TAA",
    "HLCU": "IC26TnC",
    "OOLU": "IC26TAR",
    "ONEY": "***",
}

# ── Formula Config tables ──
_TABLE_FORMULA_CONFIG  = "[fact].[FormulaConfig]"
_TABLE_FORMULA_MAPPING = "[fact].[FormulaMapping]"

FORMULA_TYPES = [
    "DATE_MIN_OFFSET",      # min(src1, src2) + offset_days
    "DATE_MAX_OFFSET",      # max(src1, src2) + offset_days
    "DATE_DELAY_OFFSET",    # cond_col>thresh → src1+cond+off_true, else src1+off_false
    "DATE_DELAY_FALLBACK",  # cond_col>thresh → src1+cond+off_true, else src2+off_false
    "EXTRACT_ISOWEEK",      # isoweeknum(src1)
    "EXTRACT_MONTH",        # month(src1)
    "EXTRACT_WEEK",         # weeknum(src1)
    "CODE_MAP",             # FormulaMapping[src1_val] → output
]

_formula_cache_data: list  = []
_formula_cache_ts:   float = 0.0
_FORMULA_CACHE_TTL = 300  # 5 min


def _coerce(db_col: str, val):
    """Cast val to the right Python type for this DB column. Returns None on bad value."""
    if val is None:
        return None
    try:
        if db_col in _INT_COLS:
            return int(float(str(val).replace(",", ".")))
        if db_col in _DECIMAL_COLS:
            return float(str(val).replace(",", "."))
        if db_col in _DATETIME_COLS:
            if isinstance(val, datetime):
                return val
            parsed = pd.to_datetime(val, dayfirst=False, errors="coerce")
            return None if pd.isna(parsed) else parsed.to_pydatetime()
        if db_col in _FORMULA_DATE_COLS:
            if isinstance(val, str) and val.strip().upper() == "DONE":
                return "DONE"
            if isinstance(val, datetime):
                return val.strftime("%Y-%m-%d")
            parsed = pd.to_datetime(val, dayfirst=False, errors="coerce")
            return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    # VARCHAR columns: Excel reads numeric IDs as int64 or float64 (e.g. 145763091 / 145763091.0)
    # Always return clean string so type mismatch doesn't break IN-set lookup or SQL compare
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        try:
            int_val = int(val)
            return str(int_val) if float(val) == int_val else str(val)
        except (ValueError, OverflowError):
            return str(val)
    return val


def _parse_date(val) -> "datetime | None":
    """Parse any value to Python datetime. Returns None on failure."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if hasattr(val, "to_pydatetime"):
        return val.to_pydatetime()
    if isinstance(val, str):
        p = pd.to_datetime(val, dayfirst=False, errors="coerce")
        return None if pd.isna(p) else p.to_pydatetime()
    return None


def _fmt_date(d) -> "str | None":
    return d.strftime("%Y-%m-%d") if d else None


def _apply_formula_config(rec: dict, cfg_list: list, mapping_dict: dict) -> dict:
    """Generic formula engine driven by FormulaConfig DB rows.
    Only writes a key when a result can be computed (never overwrites with None).
    """
    for cfg in cfg_list:
        target   = cfg["TargetCol"]
        ftype    = cfg["FormulaType"]
        src1     = cfg.get("SourceCol1")
        src2     = cfg.get("SourceCol2")
        offset   = int(cfg.get("OffsetDays")  or 0)
        cond_col = cfg.get("ConditionCol")
        thresh   = int(cfg.get("Threshold")   or 0)
        off_t    = int(cfg.get("OffsetTrue")  or 0)
        off_f    = int(cfg.get("OffsetFalse") or 0)
        cfg_id   = int(cfg.get("ID") or 0)

        if str(rec.get(target, "")).strip().upper() == "DONE":
            continue

        result = None

        if ftype == "DATE_MIN_OFFSET":
            cands = [v for v in [_parse_date(rec.get(src1)), _parse_date(rec.get(src2))] if v]
            if cands:
                result = _fmt_date(min(cands) + timedelta(days=offset))

        elif ftype == "DATE_MAX_OFFSET":
            cands = [v for v in [_parse_date(rec.get(src1)), _parse_date(rec.get(src2))] if v]
            if cands:
                result = _fmt_date(max(cands) + timedelta(days=offset))

        elif ftype == "DATE_DELAY_OFFSET":
            # cond_col > thresh → src1 + cond_val + off_t, else src1 + off_f
            base = _parse_date(rec.get(src1))
            if base:
                delay = int(rec.get(cond_col) or 0) if cond_col else 0
                result = _fmt_date(base + timedelta(days=delay + off_t if delay > thresh else off_f))

        elif ftype == "DATE_DELAY_FALLBACK":
            # cond_col > thresh → src1 + cond_val + off_t, else src2 + off_f
            base = _parse_date(rec.get(src1))
            if base:
                delay = int(rec.get(cond_col) or 0) if cond_col else 0
                if delay > thresh:
                    result = _fmt_date(base + timedelta(days=delay + off_t))
                else:
                    fb = _parse_date(rec.get(src2))
                    if fb:
                        result = _fmt_date(fb + timedelta(days=off_f))

        elif ftype == "EXTRACT_ISOWEEK":
            d = _parse_date(rec.get(src1))
            if d:
                result = d.isocalendar()[1]

        elif ftype == "EXTRACT_MONTH":
            d = _parse_date(rec.get(src1))
            if d:
                result = d.month

        elif ftype == "EXTRACT_WEEK":
            d = _parse_date(rec.get(src1))
            if d:
                result = d.isocalendar()[1]

        elif ftype == "CODE_MAP":
            val = str(rec.get(src1) or "").strip().upper()
            if val and cfg_id in mapping_dict:
                result = mapping_dict[cfg_id].get(val)

        if result is not None:
            rec[target] = result

    return rec


# ── FormulaConfig DB helpers ──

def formula_config_table_exists() -> bool:
    df = fetch(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FormulaConfig' AND TABLE_SCHEMA='fact'"
    )
    return not df.empty


def formula_mapping_table_exists() -> bool:
    df = fetch(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FormulaMapping' AND TABLE_SCHEMA='fact'"
    )
    return not df.empty


def formula_config_create_tables() -> bool:
    daily_create_schema()
    ok1 = _execute("""
        CREATE TABLE [fact].[FormulaConfig] (
            [ID]           INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
            [TargetCol]    VARCHAR(255) NOT NULL,
            [FormulaType]  VARCHAR(50)  NOT NULL,
            [SourceCol1]   VARCHAR(255),
            [SourceCol2]   VARCHAR(255),
            [OffsetDays]   INT DEFAULT 0,
            [ConditionCol] VARCHAR(255),
            [Threshold]    INT DEFAULT 0,
            [OffsetTrue]   INT DEFAULT 0,
            [OffsetFalse]  INT DEFAULT 0,
            [SortOrder]    INT DEFAULT 0,
            [Description]  VARCHAR(500),
            [CreatedBy]    VARCHAR(255),
            [CreatedAt]    DATETIME DEFAULT GETDATE(),
            [UpdatedBy]    VARCHAR(255),
            [UpdatedAt]    DATETIME DEFAULT GETDATE()
        )
    """)
    ok2 = _execute("""
        CREATE TABLE [fact].[FormulaMapping] (
            [ID]          INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
            [ConfigID]    INT NOT NULL,
            [InputValue]  VARCHAR(255) NOT NULL,
            [OutputValue] VARCHAR(255) NOT NULL,
            CONSTRAINT FK_FormulaMapping_Config FOREIGN KEY ([ConfigID])
                REFERENCES [fact].[FormulaConfig]([ID]) ON DELETE CASCADE
        )
    """)
    return ok1 and ok2


def formula_config_invalidate_cache():
    global _formula_cache_data, _formula_cache_ts
    _formula_cache_data = []
    _formula_cache_ts   = 0.0


def formula_config_seed() -> bool:
    """Insert the 11 hardcoded formula rules as initial FormulaConfig + FormulaMapping rows."""
    if not formula_config_table_exists():
        return False
    _execute(f"DELETE FROM {_TABLE_FORMULA_MAPPING}")
    _execute(f"DELETE FROM {_TABLE_FORMULA_CONFIG}")
    now = datetime.now()
    rows = [
        # (TargetCol, FormulaType, SourceCol1, SourceCol2, OffsetDays, ConditionCol, Threshold, OffsetTrue, OffsetFalse, SortOrder, Description)
        ("SI_VGM_Submission",  "DATE_MIN_OFFSET",     "VGM_Cutoff",        "SI_Cutoff",      -1, None,             0, 0, 0,  10, "min(VGM, SI) - 1 day"),
        ("Check_Draft",        "DATE_MAX_OFFSET",     "VGM_Cutoff",        "SI_Cutoff",       0, None,             0, 0, 0,  20, "max(VGM, SI)"),
        ("Send_Pre_Alert",     "DATE_MAX_OFFSET",     "VGM_Cutoff",        "SI_Cutoff",       0, None,             0, 0, 0,  30, "max(VGM, SI)"),
        ("Send_SWB",           "DATE_DELAY_OFFSET",   "Original_ETD_Port", None,              0, "Delay_ETD_Port", 0, -1, 1, 40, "Delay>0: ETD+Delay-1, else ETD+1"),
        ("Send_Final_CO",      "DATE_DELAY_FALLBACK", "Original_ETD_Port", "BL_Released_On",  0, "Delay_ETD_Port", 2,  2, 2, 50, "Delay>2: ETD+Delay+2, else BL+2"),
        ("Check_Debit_Note",   "DATE_DELAY_OFFSET",   "Original_ETD_Port", None,              0, "Delay_ETD_Port", 0, -1, 1, 60, "Delay>0: ETD+Delay-1, else ETD+1"),
        ("DO_ETD_Week",        "EXTRACT_ISOWEEK",     "DO_ETD",            None,              0, None,             0, 0, 0,  70, "ISO week of DO_ETD"),
        ("Far_Billing_Week",   "EXTRACT_ISOWEEK",     "ATD_Port",          None,              0, None,             0, 0, 0,  80, "ISO week of ATD_Port"),
        ("Loading_Month",      "EXTRACT_MONTH",       "Loading_Date",      None,              0, None,             0, 0, 0,  90, "Month of Loading_Date"),
        ("Loading_Week",       "EXTRACT_WEEK",        "Loading_Date",      None,              0, None,             0, 0, 0, 100, "ISO week of Loading_Date"),
        ("FAR_Approval_Status","CODE_MAP",            "Shipping_Line",     None,              0, None,             0, 0, 0, 110, "FAR code by shipping line"),
    ]
    sql = f"""INSERT INTO {_TABLE_FORMULA_CONFIG}
              ([TargetCol],[FormulaType],[SourceCol1],[SourceCol2],[OffsetDays],
               [ConditionCol],[Threshold],[OffsetTrue],[OffsetFalse],[SortOrder],[Description],
               [CreatedBy],[CreatedAt],[UpdatedBy],[UpdatedAt])
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    for r in rows:
        _execute(sql, list(r) + [USER, now, USER, now])

    df_id = fetch(f"SELECT TOP 1 [ID] FROM {_TABLE_FORMULA_CONFIG} WHERE [TargetCol]='FAR_Approval_Status'")
    if not df_id.empty:
        cfg_id = int(df_id.iloc[0]["ID"])
        map_sql = f"INSERT INTO {_TABLE_FORMULA_MAPPING} ([ConfigID],[InputValue],[OutputValue]) VALUES (?,?,?)"
        for code, far_val in _FAR_CODES.items():
            _execute(map_sql, [cfg_id, code.upper(), far_val])

    formula_config_invalidate_cache()
    return True


def _get_formula_config() -> list:
    """Return FormulaConfig rows as list of dicts. Cached 5 min. Returns [] if table absent."""
    global _formula_cache_data, _formula_cache_ts
    if _formula_cache_data and (time.time() - _formula_cache_ts) < _FORMULA_CACHE_TTL:
        return _formula_cache_data
    if not formula_config_table_exists():
        return []
    df = fetch(f"SELECT * FROM {_TABLE_FORMULA_CONFIG} ORDER BY [SortOrder],[ID]")
    if df.empty:
        return []
    _formula_cache_data = df.to_dict("records")
    _formula_cache_ts   = time.time()
    return _formula_cache_data


def _get_formula_mapping_dict() -> dict:
    """Return {config_id: {INPUT_UPPER: output}} from FormulaMapping."""
    if not formula_mapping_table_exists():
        return {}
    df = fetch(f"SELECT [ConfigID],[InputValue],[OutputValue] FROM {_TABLE_FORMULA_MAPPING}")
    if df.empty:
        return {}
    result: dict = {}
    for _, row in df.iterrows():
        cid = int(row["ConfigID"])
        if cid not in result:
            result[cid] = {}
        result[cid][str(row["InputValue"]).strip().upper()] = row["OutputValue"]
    return result


def formula_config_get_all() -> pd.DataFrame:
    try:
        return fetch(f"SELECT * FROM {_TABLE_FORMULA_CONFIG} ORDER BY [SortOrder],[ID]")
    except Exception:
        return pd.DataFrame()


def formula_config_save(row: dict) -> bool:
    """Insert or update a FormulaConfig row. ID present → update, absent → insert."""
    formula_config_invalidate_cache()
    cfg_id = row.get("ID")
    data = {k: v for k, v in row.items() if k not in ("ID", "CreatedBy", "CreatedAt")}
    data["UpdatedBy"] = USER
    data["UpdatedAt"] = datetime.now()
    if cfg_id:
        set_clause = ", ".join(f"[{k}] = ?" for k in data.keys())
        return _execute(f"UPDATE {_TABLE_FORMULA_CONFIG} SET {set_clause} WHERE [ID] = ?",
                        list(data.values()) + [int(cfg_id)])
    data["CreatedBy"] = USER
    data["CreatedAt"] = datetime.now()
    cols = ", ".join(f"[{k}]" for k in data.keys())
    ph   = ", ".join("?" for _ in data)
    return _execute(f"INSERT INTO {_TABLE_FORMULA_CONFIG} ({cols}) VALUES ({ph})", list(data.values()))


def formula_config_delete(cfg_id: int) -> bool:
    formula_config_invalidate_cache()
    return _execute(f"DELETE FROM {_TABLE_FORMULA_CONFIG} WHERE [ID] = ?", [int(cfg_id)])


def formula_mapping_get(config_id: int) -> pd.DataFrame:
    try:
        return fetch(
            f"SELECT * FROM {_TABLE_FORMULA_MAPPING} WHERE [ConfigID] = ? ORDER BY [InputValue]",
            [config_id],
        )
    except Exception:
        return pd.DataFrame()


def formula_mapping_save_all(config_id: int, rows: list) -> bool:
    """Replace all mapping rows for a config_id. rows = [{'InputValue': ..., 'OutputValue': ...}]"""
    formula_config_invalidate_cache()
    _execute(f"DELETE FROM {_TABLE_FORMULA_MAPPING} WHERE [ConfigID] = ?", [config_id])
    if not rows:
        return True
    sql = f"INSERT INTO {_TABLE_FORMULA_MAPPING} ([ConfigID],[InputValue],[OutputValue]) VALUES (?,?,?)"
    for r in rows:
        if not _execute(sql, [config_id, str(r["InputValue"]).strip(), str(r["OutputValue"]).strip()]):
            return False
    return True


def _compute_formulas(record: dict) -> dict:
    """Compute formula columns. Uses DB FormulaConfig if available, else hardcoded fallback.
    Only writes a key when a result is computed — never overwrites with None, so:
      INSERT → col absent = DB stores NULL
      UPDATE → col absent = existing DB value preserved
    """
    rec = dict(record)

    # ── DB-driven path ──
    cfg_list = _get_formula_config()
    if cfg_list:
        return _apply_formula_config(rec, cfg_list, _get_formula_mapping_dict())

    # ── Hardcoded fallback (FormulaConfig table not created yet) ──
    def _d(col):   return _parse_date(rec.get(col))
    def _done(col): return str(rec.get(col, "")).strip().upper() == "DONE"
    def _fmt(d):   return _fmt_date(d)

    if not _done("SI_VGM_Submission"):
        cands = [v for v in [_d("VGM_Cutoff"), _d("SI_Cutoff")] if v]
        if cands: rec["SI_VGM_Submission"] = _fmt(min(cands) - timedelta(days=1))

    if not _done("Check_Draft"):
        cands = [v for v in [_d("VGM_Cutoff"), _d("SI_Cutoff")] if v]
        if cands: rec["Check_Draft"] = _fmt(max(cands))

    if not _done("Send_Pre_Alert"):
        cands = [v for v in [_d("VGM_Cutoff"), _d("SI_Cutoff")] if v]
        if cands: rec["Send_Pre_Alert"] = _fmt(max(cands))

    if not _done("Send_SWB"):
        orig = _d("Original_ETD_Port")
        if orig:
            delay = int(rec.get("Delay_ETD_Port") or 0)
            rec["Send_SWB"] = _fmt(orig + timedelta(days=delay - 1 if delay > 0 else 1))

    if not _done("Send_Final_CO"):
        orig = _d("Original_ETD_Port")
        if orig:
            delay = int(rec.get("Delay_ETD_Port") or 0)
            bl = _d("BL_Released_On")
            if delay > 2:
                rec["Send_Final_CO"] = _fmt(orig + timedelta(days=delay + 2))
            elif bl:
                rec["Send_Final_CO"] = _fmt(bl + timedelta(days=2))

    if not _done("Check_Debit_Note"):
        orig = _d("Original_ETD_Port")
        if orig:
            delay = int(rec.get("Delay_ETD_Port") or 0)
            rec["Check_Debit_Note"] = _fmt(orig + timedelta(days=delay - 1 if delay > 0 else 1))

    do_etd = _d("DO_ETD")
    if do_etd: rec["DO_ETD_Week"] = do_etd.isocalendar()[1]

    atd = _d("ATD_Port")
    if atd: rec["Far_Billing_Week"] = atd.isocalendar()[1]

    ld = _d("Loading_Date")
    if ld:
        rec["Loading_Month"] = ld.month
        rec["Loading_Week"]  = ld.isocalendar()[1]

    if not rec.get("FAR_Approval_Status"):
        sl = str(rec.get("Shipping_Line") or "").strip().upper()
        if sl:
            code = _FAR_CODES.get(sl)
            if code: rec["FAR_Approval_Status"] = code

    return rec


def _map_df_to_records(df: pd.DataFrame) -> list:
    """Convert a DataFrame (Excel or DB columns) to a list of DB-column dicts."""
    df_clean = df.copy()
    df_clean.columns = df_clean.columns.str.strip()
    records = []
    for _, row in df_clean.iterrows():
        rec = {}
        for col in df_clean.columns:
            if col in _COLUMN_MAPPING:
                db_col = _COLUMN_MAPPING[col]
                val = row[col]
                val = None if pd.isna(val) else val
                rec[db_col] = _coerce(db_col, val)
        records.append(rec)
    return records


def _executemany(sql: str, params_list: list) -> tuple[bool, str]:
    """Run executemany with fast_executemany. Returns (success, error_msg)."""
    global _last_error
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.fast_executemany = True
        cur.executemany(sql, params_list)
        conn.commit()
        _last_error = ""
        return True, ""
    except Exception as e:
        _last_error = str(e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, str(e)


def _row_insert(rec: dict) -> bool:
    cols = ", ".join(f"[{c}]" for c in rec.keys())
    ph   = ", ".join("?" for _ in rec)
    return _execute(f"INSERT INTO {_TABLE} ({cols}) VALUES ({ph})", list(rec.values()))


def _row_update(do_no: str, rec: dict) -> bool:
    set_clause = ", ".join(f"[{k}] = ?" for k in rec.keys())
    return _execute(f"UPDATE {_TABLE} SET {set_clause} WHERE [DO_No] = ?", list(rec.values()) + [do_no])


def daily_bulk_insert(df: pd.DataFrame) -> tuple:
    """Batch insert via executemany. Falls back row-by-row on failure. Returns (ok, fail, errors)."""
    now = datetime.now()
    fail = 0
    errors: list[str] = []
    valid: list[dict] = []

    for rec in _map_df_to_records(df):
        if not rec.get("DO_No"):
            fail += 1
            errors.append("Row skipped — DO_No is empty")
            continue
        rec = _compute_formulas(rec)
        rec.update({"CreatedBy": USER, "UpdatedBy": USER, "CreatedAt": now, "UpdatedAt": now})
        valid.append(rec)

    if not valid:
        return 0, fail, errors

    cols = list(valid[0].keys())
    sql  = f"INSERT INTO {_TABLE} ({', '.join(f'[{c}]' for c in cols)}) VALUES ({', '.join('?' for _ in cols)})"
    params_list = [[rec.get(c) for c in cols] for rec in valid]

    ok_batch, err_msg = _executemany(sql, params_list)
    if ok_batch:
        return len(valid), fail, errors

    # Batch failed — retry row-by-row to surface bad rows
    errors.append(f"Batch failed, retrying row-by-row: {err_msg}")
    ok = 0
    for rec in valid:
        if _row_insert(rec):
            ok += 1
        else:
            fail += 1
            errors.append(f"{rec.get('DO_No', '?')}: {_last_error}")
    return ok, fail, errors


def daily_bulk_update(df: pd.DataFrame) -> tuple:
    """Batch update via executemany. Falls back row-by-row on failure. Returns (ok, fail, errors)."""
    now = datetime.now()
    fail = 0
    errors: list[str] = []
    valid: list[tuple] = []  # (do_no, rec)

    for rec in _map_df_to_records(df):
        do_no = rec.pop("DO_No", None)
        if not do_no:
            fail += 1
            errors.append("Row skipped — DO_No is empty")
            continue
        rec = _compute_formulas(rec)
        rec.update({"UpdatedBy": USER, "UpdatedAt": now})
        valid.append((do_no, rec))

    if not valid:
        return 0, fail, errors

    _history_snapshot([dn for dn, _ in valid], "UPDATE")

    cols = list(valid[0][1].keys())
    set_clause = ", ".join(f"[{c}] = ?" for c in cols)
    sql = f"UPDATE {_TABLE} SET {set_clause} WHERE [DO_No] = ?"
    params_list = [[rec.get(c) for c in cols] + [do_no] for do_no, rec in valid]

    ok_batch, err_msg = _executemany(sql, params_list)
    if ok_batch:
        return len(valid), fail, errors

    errors.append(f"Batch failed, retrying row-by-row: {err_msg}")
    ok = 0
    for do_no, rec in valid:
        if _row_update(do_no, rec):
            ok += 1
        else:
            fail += 1
            errors.append(f"{do_no}: {_last_error}")
    return ok, fail, errors


def daily_bulk_upsert(df: pd.DataFrame) -> tuple:
    """Batch upsert — one EXISTS query, then batch INSERT + batch UPDATE. Returns (inserted, updated, fail, errors)."""
    now = datetime.now()
    inserted = updated = fail = 0
    errors: list[str] = []

    all_recs = _map_df_to_records(df)
    all_do_nos = [r["DO_No"] for r in all_recs if r.get("DO_No")]

    if not all_do_nos:
        return 0, 0, len(all_recs), ["All rows skipped — DO_No is empty"]

    # One query to get all existing DO_Nos
    ph = ", ".join("?" for _ in all_do_nos)
    ex_df = fetch(f"SELECT [DO_No] FROM {_TABLE} WHERE [DO_No] IN ({ph})", all_do_nos)
    existing = set(ex_df["DO_No"].tolist()) if not ex_df.empty else set()

    insert_recs: list[dict] = []
    update_recs: list[tuple] = []
    queued_inserts: set = set()  # track DO_Nos already in insert_recs

    for rec in all_recs:
        do_no = rec.get("DO_No")
        if not do_no:
            fail += 1
            errors.append("Row skipped — DO_No is empty")
            continue
        if do_no in existing or do_no in queued_inserts:
            # Already in DB OR duplicate within this batch → UPDATE
            upd = {k: v for k, v in rec.items() if k != "DO_No"}
            upd = _compute_formulas(upd)
            upd.update({"UpdatedBy": USER, "UpdatedAt": now})
            update_recs.append((do_no, upd))
        else:
            rec = _compute_formulas(rec)
            rec.update({"CreatedBy": USER, "UpdatedBy": USER, "CreatedAt": now, "UpdatedAt": now})
            insert_recs.append(rec)
            queued_inserts.add(do_no)

    # Batch INSERT
    if insert_recs:
        cols = list(insert_recs[0].keys())
        sql  = f"INSERT INTO {_TABLE} ({', '.join(f'[{c}]' for c in cols)}) VALUES ({', '.join('?' for _ in cols)})"
        ok_b, err_msg = _executemany(sql, [[r.get(c) for c in cols] for r in insert_recs])
        if ok_b:
            inserted = len(insert_recs)
        else:
            errors.append(f"Batch insert failed, retrying row-by-row: {err_msg}")
            for rec in insert_recs:
                if _row_insert(rec):
                    inserted += 1
                else:
                    fail += 1
                    errors.append(f"{rec.get('DO_No', '?')}: {_last_error}")

    # Batch UPDATE
    if update_recs:
        _history_snapshot([dn for dn, _ in update_recs], "UPDATE")
        cols = list(update_recs[0][1].keys())
        set_clause = ", ".join(f"[{c}] = ?" for c in cols)
        sql = f"UPDATE {_TABLE} SET {set_clause} WHERE [DO_No] = ?"
        ok_b, err_msg = _executemany(sql, [[rec.get(c) for c in cols] + [dn] for dn, rec in update_recs])
        if ok_b:
            updated = len(update_recs)
        else:
            errors.append(f"Batch update failed, retrying row-by-row: {err_msg}")
            for do_no, rec in update_recs:
                if _row_update(do_no, rec):
                    updated += 1
                else:
                    fail += 1
                    errors.append(f"{do_no}: {_last_error}")

    return inserted, updated, fail, errors


# ═════════════════════════════════════════════════════════════════════════════
# DAILY TABLE MANAGEMENT (Create / Drop / Truncate)
# ═════════════════════════════════════════════════════════════════════════════

def daily_create_schema() -> bool:
    return _execute("IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'fact') EXEC('CREATE SCHEMA fact')")


def daily_table_exists() -> bool:
    df = fetch(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'DailyShipment' AND TABLE_SCHEMA = 'fact'"
    )
    return not df.empty


def daily_count() -> int:
    df = fetch(f"SELECT COUNT(*) AS cnt FROM {_TABLE}")
    return int(df.iloc[0]["cnt"]) if not df.empty else 0


def daily_create_table() -> bool:
    daily_create_schema()
    sql = """
        CREATE TABLE [fact].[DailyShipment] (
            [ID]                                         INT IDENTITY(1,1) NOT NULL,
            [Status]                                     VARCHAR(255),
            [Shipment_No]                                VARCHAR(255),
            [DO_No]                                      VARCHAR(255) PRIMARY KEY NOT NULL,
            [Group_No]                                   VARCHAR(255),
            [DO_ETD]                                     DATETIME,
            [Ship_To]                                    VARCHAR(255),
            [Country]                                    VARCHAR(255),
            [IncoB]                                      VARCHAR(255),
            [Port_of_Discharge]                          VARCHAR(255),
            [Transport_Mode]                             VARCHAR(255),
            [Requested_ETA]                              DATETIME,
            [Cont_Size]                                  VARCHAR(255),
            [Shipment_ID_PRE_Carriage]                   VARCHAR(255),
            [Shipment_ID_MAIN_Carriage]                  VARCHAR(255),
            [Exp_Invoice_No]                             VARCHAR(255),
            [Exp_Invoice_Date]                           DATETIME,
            [TPI_Invoice_No]                             VARCHAR(255),
            [Packing_List_No]                            VARCHAR(255),
            [Actual_Full_and_Correct_Docs_Received_Date] DATETIME,
            [G_W]                                        DECIMAL(18,3),
            [N_W]                                        DECIMAL(18,3),
            [Pallet]                                     INT,
            [Box]                                        INT,
            [Booking_No]                                 VARCHAR(255),
            [Shipping_Line]                              VARCHAR(255),
            [Vessel]                                     VARCHAR(255),
            [Voyage]                                     VARCHAR(255),
            [BL_No]                                      VARCHAR(255),
            [BL_Type]                                    VARCHAR(255),
            [BL_Released_On]                             DATETIME,
            [Port_Cutoff]                                DATETIME,
            [SI_Cutoff]                                  DATETIME,
            [VGM_Cutoff]                                 DATETIME,
            [Original_ETD_Port]                          DATETIME,
            [Delay_ETD_Port]                             INT,
            [ATD_Port]                                   DATETIME,
            [ETA_Dest]                                   DATETIME,
            [Delay_ETA_Port]                             INT,
            [ATA_Dest]                                   DATETIME,
            [SI_VGM_Submission]                          VARCHAR(50),
            [Check_Draft]                                VARCHAR(50),
            [Send_Pre_Alert]                             VARCHAR(50),
            [Send_SWB]                                   VARCHAR(50),
            [Send_Final_CO]                              VARCHAR(50),
            [Check_Debit_Note]                           VARCHAR(50),
            [Main_Carriage_Far_Week]                     INT,
            [Loading_Date]                               DATETIME,
            [Container_No]                               VARCHAR(255),
            [Seal_No]                                    VARCHAR(255),
            [Export_Declaration_No]                      VARCHAR(255),
            [Lane]                                       VARCHAR(255),
            [Export_Declaration_Date]                    DATETIME,
            [Master_Invoice_No]                          VARCHAR(255),
            [C_O_No]                                     VARCHAR(255),
            [CO_Date]                                    DATETIME,
            [Main_Carriage_INV]                          DECIMAL(18,2),
            [Main_Carriage_INV_Date]                     DATETIME,
            [PIC]                                        VARCHAR(255),
            [DO_ETD_Week]                                INT,
            [Far_Billing_Week]                           INT,
            [Week_Allocation]                            INT,
            [OF]                                         DECIMAL(18,2),
            [BAF]                                        DECIMAL(18,2),
            [T_A]                                        DECIMAL(18,2),
            [ROE]                                        DECIMAL(18,2),
            [Loading_Month]                              INT,
            [Loading_Week]                               INT,
            [FAR_Approval_Status]                        VARCHAR(255),
            [Serial_No]                                  VARCHAR(255),
            [Pending_Pallet]                             INT,
            [CreatedBy]                                  VARCHAR(255) NOT NULL,
            [CreatedAt]                                  DATETIME     NOT NULL,
            [UpdatedBy]                                  VARCHAR(255) NOT NULL,
            [UpdatedAt]                                  DATETIME     NOT NULL
        )
    """
    return _execute(sql)


def daily_drop_table() -> bool:
    return _execute(f"DROP TABLE IF EXISTS {_TABLE}")


def daily_truncate_table() -> bool:
    return _execute(f"TRUNCATE TABLE {_TABLE}")


# ═════════════════════════════════════════════════════════════════════════════
# COLUMN CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

# All user-facing columns in spec order (excludes ID)
DAILY_COLUMNS: list[str] = [
    "DO_No", "Status", "Shipment_No", "Group_No", "DO_ETD", "Ship_To", "Country",
    "IncoB", "Port_of_Discharge", "Transport_Mode", "Requested_ETA", "Cont_Size",
    "Shipment_ID_PRE_Carriage", "Shipment_ID_MAIN_Carriage",
    "Exp_Invoice_No", "Exp_Invoice_Date", "TPI_Invoice_No", "Packing_List_No",
    "Actual_Full_and_Correct_Docs_Received_Date",
    "G_W", "N_W", "Pallet", "Box",
    "Booking_No", "Shipping_Line", "Vessel", "Voyage",
    "BL_No", "BL_Type", "BL_Released_On",
    "Port_Cutoff", "SI_Cutoff", "VGM_Cutoff",
    "Original_ETD_Port", "Delay_ETD_Port", "ATD_Port",
    "ETA_Dest", "Delay_ETA_Port", "ATA_Dest",
    "SI_VGM_Submission", "Check_Draft", "Send_Pre_Alert", "Send_SWB",
    "Send_Final_CO", "Check_Debit_Note", "Main_Carriage_Far_Week",
    "Loading_Date", "Container_No", "Seal_No",
    "Export_Declaration_No", "Lane", "Export_Declaration_Date",
    "Master_Invoice_No", "C_O_No", "CO_Date",
    "Main_Carriage_INV", "Main_Carriage_INV_Date", "PIC",
    "DO_ETD_Week", "Far_Billing_Week", "Week_Allocation",
    "OF", "BAF", "T_A", "ROE",
    "Loading_Month", "Loading_Week", "FAR_Approval_Status",
    "Serial_No", "Pending_Pallet",
    "CreatedBy", "CreatedAt", "UpdatedBy", "UpdatedAt",
]

DAILY_DEFAULT_COLUMNS: list[str] = [
    "DO_No", "Status", "Shipment_No", "Ship_To", "Country",
    "Port_of_Discharge", "DO_ETD", "Requested_ETA",
    "Booking_No", "Vessel", "Container_No",
]


# ═════════════════════════════════════════════════════════════════════════════
# COLUMN TEMPLATES — stored in [fact].[ColumnTemplates]
# ═════════════════════════════════════════════════════════════════════════════

_TABLE_TEMPLATES = "[fact].[ColumnTemplates]"


def template_create_table() -> bool:
    # Create fact schema if not exists (same as daily table)
    _execute("IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'fact') EXEC('CREATE SCHEMA fact')")
    sql = """
        CREATE TABLE [fact].[ColumnTemplates] (
            [ID]           INT IDENTITY(1,1) NOT NULL,
            [TemplateName] VARCHAR(255) NOT NULL,
            [TeamName]     VARCHAR(255) DEFAULT '',
            [Columns]      VARCHAR(MAX) NOT NULL,
            [IsDefault]    BIT DEFAULT 0,
            [CreatedBy]    VARCHAR(255),
            [CreatedAt]    DATETIME,
            [UpdatedBy]    VARCHAR(255),
            [UpdatedAt]    DATETIME,
            CONSTRAINT UQ_TemplateName UNIQUE ([TemplateName])
        )
    """
    return _execute(sql)


def template_get_all() -> pd.DataFrame:
    try:
        return fetch(f"SELECT * FROM {_TABLE_TEMPLATES} ORDER BY [TemplateName]")
    except Exception:
        return pd.DataFrame()


def template_get_columns(name: str) -> list[str]:
    try:
        df = fetch(f"SELECT [Columns] FROM {_TABLE_TEMPLATES} WHERE [TemplateName] = ?", [name])
        if not df.empty:
            return json.loads(df.iloc[0]["Columns"])
    except Exception:
        pass
    return DAILY_DEFAULT_COLUMNS


def template_get_default_columns() -> list[str]:
    try:
        df = fetch(f"SELECT TOP 1 [Columns] FROM {_TABLE_TEMPLATES} WHERE [IsDefault] = 1 ORDER BY [ID]")
        if not df.empty:
            return json.loads(df.iloc[0]["Columns"])
    except Exception:
        pass
    return DAILY_DEFAULT_COLUMNS


def template_save(name: str, columns: list[str], team: str = "", is_default: bool = False) -> bool:
    if is_default:
        _execute(f"UPDATE {_TABLE_TEMPLATES} SET [IsDefault] = 0")
    cols_json = json.dumps(columns)
    existing = fetch(f"SELECT 1 FROM {_TABLE_TEMPLATES} WHERE [TemplateName] = ?", [name])
    if not existing.empty:
        sql = f"""UPDATE {_TABLE_TEMPLATES}
                  SET [Columns]=?, [TeamName]=?, [IsDefault]=?, [UpdatedBy]=?, [UpdatedAt]=GETDATE()
                  WHERE [TemplateName]=?"""
        return _execute(sql, [cols_json, team, 1 if is_default else 0, USER, name])
    else:
        sql = f"""INSERT INTO {_TABLE_TEMPLATES}
                  ([TemplateName],[TeamName],[Columns],[IsDefault],[CreatedBy],[CreatedAt],[UpdatedBy],[UpdatedAt])
                  VALUES (?,?,?,?,?,GETDATE(),?,GETDATE())"""
        return _execute(sql, [name, team, cols_json, 1 if is_default else 0, USER, USER])


def template_delete(name: str) -> bool:
    return _execute(f"DELETE FROM {_TABLE_TEMPLATES} WHERE [TemplateName] = ?", [name])

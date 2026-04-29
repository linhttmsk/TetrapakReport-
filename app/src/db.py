"""
app/src/db.py — SQL Server connection & core CRUD
Insert, Update, Batch Upsert, Delete, Send Email
"""
import pyodbc
import pandas as pd
from datetime import datetime
from configparser import ConfigParser
import os, sys, getpass

# ── Config ──
# Use __file__ to get correct path regardless of how Streamlit was launched
current_file = os.path.abspath(__file__)  # ...app/src/db.py
app_folder = os.path.dirname(os.path.dirname(current_file))  # ...app/
inifile = os.path.join(app_folder, ".streamlit", "config.ini")
parser = ConfigParser()
parser.read(inifile)

DRIVER   = parser.get("SQL", "driver",   fallback="ODBC Driver 17 for SQL Server")
SERVER   = parser.get("SQL", "server",   fallback="")
DATABASE = parser.get("SQL", "database", fallback="")
TRUSTED  = parser.get("SQL", "trusted",  fallback="yes")
UID_SQL  = parser.get("SQL", "uid",      fallback="")
PW       = parser.get("SQL", "pw",       fallback="")
USER     = getpass.getuser().upper()

# ── Connection ──
def get_conn() -> pyodbc.Connection:
    if TRUSTED.lower() == "yes":
        conn_str = (f"DRIVER={{{DRIVER}}};SERVER={SERVER};"
                    f"DATABASE={DATABASE};Trusted_Connection=yes;")
    else:
        conn_str = (f"DRIVER={{{DRIVER}}};SERVER={SERVER};"
                    f"DATABASE={DATABASE};UID={UID_SQL};PWD={PW};")
    return pyodbc.connect(conn_str, timeout=10)

def test_conn() -> bool:
    try:
        get_conn().close()
        return True
    except:
        return False

# ── READ ──
def fetch(query: str, params: list = []) -> pd.DataFrame:
    try:
        conn = get_conn()
        df = pd.read_sql(query, conn, params=params)
        conn.close()
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
def _execute(sql: str, params: list = []) -> bool:
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] execute error: {e}")
        return False

# ── SEND EMAIL via Outlook ──
def send_email(to: str, subject: str, body: str, cc: str = "") -> bool:
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
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

import sqlite3, json, sys

db = r"F:\PythonProject\emotion_dashboard\data\.migration_shadow\market_store_5535.next.sqlite3"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()

def q(sql, *a):
    try:
        return cur.execute(sql, a).fetchall()
    except Exception as e:
        return [("ERR", str(e))]

print("=== meta.schema ===")
if q("SELECT name FROM sqlite_master WHERE name='meta'"):
    print(q("SELECT key, value FROM meta")[:10])
else:
    print("(no meta table)")

print("\n=== tables/views ===")
rows = q("SELECT type, name FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name")
tables = [r[1] for r in rows if r[0]=='table']
views  = [r[1] for r in rows if r[0]=='view']
print(f"tables={len(tables)} views={len(views)}")
print("views:", views)

print("\n=== counts ===")
for t in ["batches","batches_fact","batch_dim","published_days","source_rows","source_rows_fact",
          "research_rows","research_rows_fact","quote_observations","quote_fact","metrics_fact",
          "history_records","history_fact","s02b_revisions","s02b_revisions_fact","s02lp_inputs",
          "s02lp_inputs_fact","master_versions","master_member","candidates","factors","revisions"]:
    if t in tables or t in views:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
            print(f"{t}: {n}")
        except Exception as e:
            print(f"{t}: ERR {e}")

print("\n=== published_days pointers ===")
if "published_days" in tables:
    rows = q("SELECT trade_date, first_batch_id, batch_id FROM published_days ORDER BY trade_date")
    bset = set()
    for bt in ("batches","batches_fact"):
        if bt in tables:
            bset = set(r[0] for r in q(f"SELECT id FROM {bt}"))
            break
    for r in rows:
        f_ok = r[1] in bset if r[1] else None
        c_ok = r[2] in bset if r[2] else None
        flag = ""
        if f_ok is False or c_ok is False: flag = " <-- DANGLING"
        print(r[0], "first_ok=",f_ok,"current_ok=",c_ok, flag)

print("\n=== batch_dim ===")
if "batch_dim" in tables:
    cols = [c[1] for c in q(f"PRAGMA table_info(batch_dim)")]
    print("cols:", cols)
    print("dup batch_id:", q("SELECT batch_id, COUNT(*) FROM batch_dim GROUP BY batch_id HAVING COUNT(*)>1"))
    total = q("SELECT COUNT(*) FROM batch_dim")[0][0]
    print("total:", total)

print("\n=== indexes on key tables ===")
for t in ["batches_fact","research_rows_fact","source_rows_fact","quote_fact","metrics_fact","history_fact","batch_dim","published_days"]:
    if t in tables:
        idx = q(f"PRAGMA index_list(\"{t}\")")
        print(t, "->", [i[1] for i in idx])

print("\n=== research_rows_fact dup keys ===")
if "research_rows_fact" in tables:
    cols = [c[1] for c in q(f"PRAGMA table_info(research_rows_fact)")]
    print("cols:", cols)
    dups = q("SELECT batch_id, code, factor_id, COUNT(*) c FROM research_rows_fact GROUP BY batch_id, code, factor_id HAVING c>1 LIMIT 5")
    print("sample dups:", dups)
    nd = q("SELECT COUNT(*) FROM (SELECT 1 FROM research_rows_fact GROUP BY batch_id, code, factor_id HAVING COUNT(*)>1)")[0][0]
    print("dup key groups:", nd)

con.close()

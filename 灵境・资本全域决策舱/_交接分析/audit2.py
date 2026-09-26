import sqlite3

ev = r"F:\PythonProject\emotion_dashboard\data\.migration_shadow\evidence_5535.next.sqlite3"
db = r"F:\PythonProject\emotion_dashboard\data\.migration_shadow\market_store_5535.next.sqlite3"

evc = sqlite3.connect(f"file:{ev}?mode=ro", uri=True)
ev_ids = set(r[0] for r in evc.execute("SELECT blob_id FROM ev_blob"))
print("ev_blob ids:", len(ev_ids))

hot = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
for t in ["research_rows_fact","source_rows_fact","quote_fact","metrics_fact","history_fact","s02b_revisions_fact","s02lp_inputs_fact","master_member"]:
    try:
        rows = hot.execute(f"SELECT blob_id, COUNT(*) FROM {t} WHERE blob_id IS NOT NULL GROUP BY blob_id").fetchall()
        refs = sum(c for _, c in rows)
        dangling = [(b, c) for b, c in rows if b not in ev_ids]
        drows = sum(c for _, c in dangling)
        sample = dangling[:3]
        print(f"{t}: refs={refs} distinct={len(rows)} dangling_rows={drows} sample={sample}")
    except Exception as e:
        print(t, "ERR", e)
evc.close(); hot.close()

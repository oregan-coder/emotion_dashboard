import sqlite3
db_path = 'data/.migration_shadow/market_store_5535.next.sqlite3'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
# 今天s02a_jobs
cur.execute("SELECT id, state, requested_at FROM s02a_jobs WHERE date(requested_at) = '2026-09-26' ORDER BY requested_at DESC")
rows = cur.fetchall()
print(f'今天s02a_jobs任务数: {len(rows)}')
for r in rows:
    print(f'  任务ID:{r[0]} 状态:{r[1]} 请求时间:{r[2]}')
print('\n')
# 今天jobs
cur.execute("SELECT id, status, requested_date, mode, started_at FROM jobs WHERE date(started_at) = '2026-09-26' ORDER BY started_at DESC")
rows2 = cur.fetchall()
print(f'今天jobs表任务数: {len(rows2)}')
for r in rows2:
    print(f'  任务ID:{r[0]} 状态:{r[1]} 日期:{r[2]} 模式:{r[3]} 开始时间:{r[4]}')
conn.close()

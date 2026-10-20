import os
import sqlite3

DB = os.environ.get('DB_PATH', '/data/boatrace_ev.sqlite3')

with sqlite3.connect(DB) as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS storage_test (id INTEGER PRIMARY KEY, message TEXT)')
    conn.execute('INSERT INTO storage_test (message) VALUES (?)', ('sqlite_write_test',))
    count = conn.execute('SELECT COUNT(*) FROM storage_test').fetchone()[0]

print('STORAGE_TEST_OK', count)

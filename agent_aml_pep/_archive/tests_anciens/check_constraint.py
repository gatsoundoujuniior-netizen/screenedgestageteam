import sys; sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import query_all
rows = query_all("""
    SELECT conname, pg_get_constraintdef(oid) as def
    FROM pg_constraint
    WHERE conrelid = 'pep'::regclass AND contype = 'u'
""")
for r in rows:
    print(r['conname'], '->', r['def'])

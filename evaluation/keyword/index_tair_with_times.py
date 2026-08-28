"""
Index TAIR query log with timestamps.
CSV format: user_id,"start_time","end_time",result_count,"query"
"""
import csv
import logging
import sys
import os

_here = os.path.dirname(os.path.abspath(__file__))
os.chdir(_here)
sys.path.insert(0, os.path.join(_here, '..', '..'))

from leaker.api import QueryInputDocument
from leaker.whoosh_interface import WhooshQueryLogWriter

logging.basicConfig(level=logging.INFO,
                    format='{asctime} {levelname:8.8} {name}: {message}', style='{',
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

TAIR_LOG = os.path.join(_here, '..', '..', 'data_sources', 'TAIR', 'query_log', 'TAIR_query_log.txt')

if __name__ == '__main__':
    writer = WhooshQueryLogWriter("tair_ql")

    count = 0
    skipped = 0
    with open(TAIR_LOG, encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if len(row) < 5:
                skipped += 1
                continue
            user_id = row[0].rstrip('"').strip()
            start_time = row[1].strip()
            query = row[4].strip()
            if not query or not user_id or not start_time:
                skipped += 1
                continue
            doc = QueryInputDocument(f"tair_{i}", query, user_id, query_time=start_time)
            writer.write(doc)
            count += 1
            if count % 50000 == 0:
                log.info(f"Indexed {count} records...")

    writer.flush()
    log.info(f"Done. Indexed {count} records, skipped {skipped}.")

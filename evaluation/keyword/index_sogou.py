"""
Index Sogou query log with timestamps.

Sogou SogouQ format (tab-separated, UTF-8 or GBK):
  访问时间\t用户ID\t[查询词]\t排名\t点击序号\t点击URL

Time is HH:MM:SS only (no date). We detect day rollovers (time going backward)
and increment a day counter starting from BASE_DATE so TimeGapSegmenter works
correctly across day boundaries.

Download:
  http://www.sogou.com/labs/dl/q.html  (requires registration)
  Place the .txt/.gz file at:  data_sources/Sogou/SogouQ.txt

Usage:
  D:\conda\envs\maple\python.exe index_sogou.py
"""
import csv
import logging
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from leaker.api import QueryInputDocument
from leaker.whoosh_interface import WhooshQueryLogWriter

logging.basicConfig(
    level=logging.INFO,
    format='{asctime} {levelname:8.8} {name}: {message}',
    style='{',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# Starting date for day-rollover reconstruction (SogouQ full = June 2008)
BASE_DATE = datetime(2008, 6, 1)

SOGOU_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'data_sources', 'Sogou', 'SogouQ.txt'
)


def strip_brackets(query: str) -> str:
    """Remove surrounding [] from Sogou query terms."""
    query = query.strip()
    if query.startswith('[') and query.endswith(']'):
        query = query[1:-1]
    return query.strip()


if __name__ == '__main__':
    writer = WhooshQueryLogWriter("sogou_ql")

    count = 0
    skipped = 0
    prev_time_str = "00:00:00"
    current_date = BASE_DATE

    try:
        f = open(SOGOU_FILE, encoding='gbk', errors='replace')
    except FileNotFoundError:
        log.error(f"File not found: {SOGOU_FILE}")
        log.error("Download SogouQ from http://www.sogou.com/labs/dl/q.html")
        log.error("and place it at data_sources/Sogou/SogouQ.txt")
        sys.exit(1)

    with f:
        reader = csv.reader(f, delimiter='\t')
        for i, row in enumerate(reader):
            if len(row) < 3:
                skipped += 1
                continue

            time_str = row[0].strip()   # HH:MM:SS
            user_id  = row[1].strip()   # anonymized user ID
            raw_query = row[2].strip()  # [查询词]

            if not time_str or not user_id or not raw_query:
                skipped += 1
                continue

            query = strip_brackets(raw_query)
            if not query:
                skipped += 1
                continue

            # Detect day rollover: if time goes backward, increment date
            try:
                cur_t = datetime.strptime(time_str, "%H:%M:%S")
                prv_t = datetime.strptime(prev_time_str, "%H:%M:%S")
                if cur_t < prv_t:
                    current_date += timedelta(days=1)
            except ValueError:
                pass
            prev_time_str = time_str

            full_dt = datetime.combine(current_date.date(),
                                       datetime.strptime(time_str, "%H:%M:%S").time())
            full_dt_str = full_dt.strftime("%Y-%m-%d %H:%M:%S")

            doc = QueryInputDocument(
                f"sogou_{i}", query, user_id, query_time=full_dt_str
            )
            writer.write(doc)
            count += 1

            if count % 100_000 == 0:
                log.info(f"Indexed {count:,} records (skipped {skipped:,})...")

    writer.flush()
    log.info(f"Done. Indexed {count:,} records, skipped {skipped:,}.")

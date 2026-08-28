"""
Index Yandex Personalized Web Search Challenge query log.

Dataset: https://www.kaggle.com/c/yandex-personalized-web-search-challenge/data
Place train.tsv at:  data_sources/Yandex/train.tsv  (16 GB uncompressed)

Line format (tab-separated):
  Session metadata:  SessionID  0        M  UserID  Day
  Query event:       SessionID  TimePassed  Q  SERPID  QueryID  Term1,Term2,...  URL1:Dom1 ...
  Click event:       SessionID  TimePassed  C  SERPID  UrlID  DomainID

  TimePassed = seconds since session start (relative, not absolute)
  We reconstruct absolute datetime as:
      base_date + (Day-1)*24h + session_start_estimate + TimePassed

  session_start_estimate is unknown, so we set it to 0 each day
  (sessions within the same day are ordered chronologically in the file,
   so relative ordering is preserved even if absolute time is approximate).

Keywords = TermIDs (e.g. "48291"). Matching works identically to plaintext:
  recovered[token] == ground_truth_termid  → correct

Usage:
  D:\conda\envs\maple\python.exe index_yandex.py
"""
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

YANDEX_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'data_sources', 'Yandex', 'train.tsv'
)

# Base date for reconstructing absolute timestamps
BASE_DATE = datetime(2013, 1, 1)


def make_timestamp(day: int, time_passed_sec: int) -> str:
    dt = BASE_DATE + timedelta(days=day - 1, seconds=time_passed_sec)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == '__main__':
    if not os.path.exists(YANDEX_FILE):
        log.error(f"File not found: {YANDEX_FILE}")
        log.error("Download from: https://www.kaggle.com/c/yandex-personalized-web-search-challenge/data")
        log.error("Place train.tsv at: data_sources/Yandex/train.tsv")
        sys.exit(1)

    writer = WhooshQueryLogWriter("yandex_ql")

    count = 0
    skipped = 0
    fmt_errors = 0

    # State for current session
    cur_user_id = None
    cur_day = 1
    cur_session_id = None

    with open(YANDEX_FILE, encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f):
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 3:
                skipped += 1
                continue

            session_id  = parts[0]
            time_passed = parts[1]
            event_type  = parts[2]

            # ── Session metadata ─────────────────────────────────────────────
            if event_type == 'M':
                # Format: SessionID  0  M  UserID  Day
                if len(parts) < 5:
                    fmt_errors += 1
                    continue
                cur_session_id = session_id
                cur_user_id    = parts[3]
                try:
                    cur_day = int(parts[4])
                except ValueError:
                    cur_day = 1

            # ── Query event ──────────────────────────────────────────────────
            elif event_type == 'Q':
                # Format: SessionID  TimePassed  Q  SERPID  QueryID  Term1,Term2,...  URL:Dom ...
                if len(parts) < 6 or cur_user_id is None:
                    skipped += 1
                    continue

                term_str = parts[5]          # "TermID1,TermID2,..."
                terms = [t.strip() for t in term_str.split(',') if t.strip()]
                if not terms:
                    skipped += 1
                    continue

                try:
                    tp = int(time_passed)
                except ValueError:
                    tp = 0

                ts = make_timestamp(cur_day, tp)

                # Each term in the query → one document entry
                # (treats each TermID as an independent keyword query)
                for term_id in terms:
                    doc = QueryInputDocument(
                        f"yandex_{line_num}_{term_id}",
                        term_id,
                        cur_user_id,
                        query_time=ts,
                    )
                    writer.write(doc)
                    count += 1

            # click events (C) are ignored — we don't need them

            if line_num % 500_000 == 0 and line_num > 0:
                log.info(f"Processed {line_num:,} lines | indexed {count:,} terms | skipped {skipped:,}")

    writer.flush()
    log.info(f"Done. Indexed {count:,} query-term records, skipped {skipped:,}, fmt_errors {fmt_errors}.")
    log.info("Dataset name for experiments: 'yandex_ql'")

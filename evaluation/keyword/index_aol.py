"""
For License information see the LICENSE file.

Authors: Amos Treiber

"""
import csv
import logging
import os
import re
import sys
from datetime import datetime
from typing import Iterator

_here = os.path.dirname(os.path.abspath(__file__))
os.chdir(_here)
sys.path.insert(0, os.path.join(_here, '..', '..'))

from leaker.api import QueryInputDocument
from leaker.preprocessing import Sink, Preprocessor
from leaker.preprocessing.data import DirectoryEnumerator
from leaker.preprocessing.data.keyword_file import RelativeFile, filter_url
from leaker.preprocessing.pipeline import Filter
from leaker.whoosh_interface import WhooshQueryLogWriter

f = logging.Formatter(fmt='{asctime} {levelname:8.8} {process} --- [{threadName:12.12}] {name:32.32}: {message}',
                      style='{')

console = logging.StreamHandler(sys.stdout)
console.setFormatter(f)

file = logging.FileHandler('aol_indexing.log', 'w', 'utf-8')
file.setFormatter(f)

logging.basicConfig(handlers=[console, file], level=logging.INFO)


class AOLQueryDocumentLoader(Filter):
    """Reads AOL query log .txt files and yields QueryInputDocument with query_time."""

    def filter(self, source: Iterator[RelativeFile]) -> Iterator[QueryInputDocument]:
        for base, relative in source:
            if not re.match(r".*\.(txt)$", relative):
                continue
            filepath = os.path.join(base, relative)
            with open(filepath, encoding='latin-1', errors='ignore') as fp:
                reader = csv.reader(fp, delimiter='\t')
                next(reader, None)  # skip header: AnonID, Query, QueryTime, ItemRank, ClickURL

                prev_content = ""
                prev_time = datetime.strptime("2000-01-01 00:00:00", "%Y-%m-%d %X")

                for i, line in enumerate(reader):
                    if len(line) < 2:
                        continue
                    content = line[1]
                    if not content:
                        continue

                    try:
                        time = datetime.strptime(line[2], "%Y-%m-%d %X")
                    except (ValueError, IndexError):
                        time = prev_time

                    # Skip click rows (same query + has click URL + within same day)
                    if (content == prev_content and len(line) > 3 and line[3] != ""
                            and not (time - prev_time).days >= 1):
                        continue

                    user_id = line[0].strip()
                    doc_id = f"{relative}_{i}"
                    time_str = line[2].strip() if len(line) > 2 else ""

                    prev_content = content
                    prev_time = time

                    yield QueryInputDocument(doc_id, filter_url(content), user_id, query_time=time_str)


aol = DirectoryEnumerator("../../data_sources/AOL/AOL-user-ct-collection-small")
aol_loader = AOLQueryDocumentLoader()
aol_sink: Sink[QueryInputDocument] = WhooshQueryLogWriter("aol_new")

preprocessor = Preprocessor(aol, [aol_loader > aol_sink])
preprocessor.run()

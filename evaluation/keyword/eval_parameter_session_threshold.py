"""
Session Threshold Sensitivity

Wikidata SPARQL, |W|=500, N_SEEDS=5
Vary THRESHOLD delta (time-gap) in {10, 20, 30, 60} minutes
Report avg accuracy and session count across seeds
"""
import sys, os, time, random
import logging
from collections import Counter
from urllib.parse import unquote_plus

_here = os.path.dirname(os.path.abspath(__file__))
os.chdir(_here)
sys.path.insert(0, os.path.join(_here, '..', '..'))

logging.basicConfig(level=logging.WARNING,
                    format='{asctime} {levelname:8.8} {name}: {message}', style='{',
                    handlers=[logging.StreamHandler(sys.stdout)])

from leaker.attack.session_recovery import (
    SessionBasedRecovery, TimeGapSegmenter,
)

TSV_FILE  = os.path.join(_here, '..', '..', 'data_sources', 'Wikidata SPARQL Logs', 'I1_status2xx_userData_Joined.tsv')
N_KW      = 500
N_SEEDS   = 5
TOP_K     = 5
BATCH     = 5
BETA      = 0.5
DELTAS    = [10, 20, 30, 60]  # minutes


def load_wikidata(tsv_file, n_kw):
    all_pairs = []
    with open(tsv_file, encoding='utf-8') as f:
        next(f)
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 2:
                continue
            query = unquote_plus(parts[0]).strip()
            ts    = parts[1].strip()
            if query and ts:
                all_pairs.append((query, ts))
    top_kws  = {kw for kw, _ in Counter(kw for kw, _ in all_pairs).most_common(n_kw)}
    filtered = [(kw, ts) for kw, ts in all_pairs if kw in top_kws]
    vocab    = sorted(top_kws)
    kw_to_tok = {kw: str(i) for i, kw in enumerate(vocab)}
    return filtered, top_kws, kw_to_tok


def run_seed(seed, filtered, kw_to_tok, delta):
    random.seed(seed)
    shuffled = filtered[:]
    random.shuffle(shuffled)
    half        = len(shuffled) // 2
    train_pairs = shuffled[:half]
    test_sorted = sorted(shuffled[half:], key=lambda x: x[1])

    tok_seq = [(kw_to_tok[kw], ts) for kw, ts in test_sorted]
    n_test  = len(test_sorted)

    sbr = SessionBasedRecovery(
        segmenter=TimeGapSegmenter(delta_minutes=delta), cooc_version=2,
        top_k=TOP_K, beta=BETA, batch_size=BATCH, dedup=False,
    )
    pred = sbr.recover(tok_seq, {'global': train_pairs})
    acc  = sum(1 for kw, _ in test_sorted if pred.get(kw_to_tok[kw]) == kw) / n_test

    # count sessions in train set (parse timestamps first)
    from leaker.attack.session_recovery import _parse_time
    train_parsed = [(kw, _parse_time(ts)) for kw, ts in train_pairs]
    seg = TimeGapSegmenter(delta_minutes=delta)
    n_sessions = len(seg.segment(train_parsed))

    return acc, n_sessions


if __name__ == '__main__':
    print(f"Loading Wikidata SPARQL log...", flush=True)
    filtered, top_kws, kw_to_tok = load_wikidata(TSV_FILE, N_KW)
    print(f"  |W|={N_KW}  filtered pairs: {len(filtered):,}", flush=True)

    print(f"\n{'='*55}")
    print(f"   Session Threshold (THRESHOLD, |W|={N_KW})")
    print(f"{'='*55}")
    print(f"  {'delta(min)':>10}  {'avg accuracy':>14}  {'avg sessions':>12}")
    print(f"  {'-'*44}")

    for delta in DELTAS:
        accs, n_sess = [], []
        for seed in range(N_SEEDS):
            acc, ns = run_seed(seed, filtered, kw_to_tok, delta)
            accs.append(acc)
            n_sess.append(ns)
        avg_acc  = sum(accs) / len(accs)
        avg_sess = sum(n_sess) / len(n_sess)
        print(f"  {delta:>10}  {avg_acc*100:>13.2f}%  {avg_sess:>12.0f}")
        sys.stdout.flush()

    print(f"{'='*55}")

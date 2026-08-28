"""
Wikidata SPARQL — Large Keyword Universe (Section 5.3.3)

Dataset  : Wikidata SPARQL query logs (global, no user separation)
Split    : random 50/50 train/test, repeated over N_SEEDS seeds
|W|      : configurable via --n_kw (500, 1000, 2000)

Methods  :
  THRESHOLD  TimeGapSegmenter(delta=20min)
  DENSITY    DBSCANSegmenter(eps=20min, min_samples=3)
  MAPLE      MarkovDecoding  [skipped if timeout or |W|>=1000 is slow]
  IHOP       MarkovIHOP(pfree=0.25, niters=3)

Params   : top_k=5, RefSpeed=5, beta=0.5, dedup=False
Seeds    : 5 independent runs (seeds 0..4)

Usage    : python eval_large_keyword.py [--n_kw 500]
"""
import sys, os, time, random, argparse, threading
import logging
from collections import Counter
from urllib.parse import unquote_plus

import numpy as np

_here = os.path.dirname(os.path.abspath(__file__))
os.chdir(_here)
sys.path.insert(0, os.path.join(_here, '..', '..'))

logging.basicConfig(level=logging.WARNING,
                    format='{asctime} {levelname:8.8} {name}: {message}', style='{',
                    handlers=[logging.StreamHandler(sys.stdout)])

from leaker.api import QuerySequence
from leaker.attack.markov.decoding import MarkovDecoding
from leaker.attack.markov.ihop import MarkovIHOP
from leaker.attack.session_recovery import (
    SessionBasedRecovery, TimeGapSegmenter, DBSCANSegmenter,
)


def make_query_sequence(keyword_list, vocab):
    """Build QuerySequence for MarkovDecoding (MAPLE only).
    Uses full vocab size so the HMM isn't skipped due to coverage gaps.
    Zero rows (unseen keywords) get uniform distribution.
    """
    n = len(vocab)
    kw2st = {kw: i for i, kw in enumerate(vocab)}
    t_mat = np.zeros((n, n))
    for i in range(len(keyword_list) - 1):
        a, b = keyword_list[i], keyword_list[i + 1]
        if a in kw2st and b in kw2st:
            t_mat[kw2st[a]][kw2st[b]] += 1
    for i in range(n):
        s = t_mat[i].sum()
        if s == 0:
            t_mat[i] = 1.0 / n
        else:
            t_mat[i] /= s
    return QuerySequence(transition_matrix=t_mat, num_states=n, query_list=keyword_list,
                         keyword_to_state=kw2st, alt_state_map=None, original_transition_matrix=t_mat)

parser = argparse.ArgumentParser()
parser.add_argument('--n_kw', type=int, default=500, choices=[500, 1000, 2000],
                    help='Keyword universe size')
args = parser.parse_args()

TSV_FILE   = os.path.join(_here, '..', '..', 'data_sources', 'Wikidata SPARQL Logs', 'I1_status2xx_userData_Joined.tsv')
N_KW       = args.n_kw
N_SEEDS    = 5
TOP_K      = 5
BATCH_SIZE = 5    # RefSpeed=5
BETA       = 0.5
IHOP_NITERS = 3
TIMEOUT_S   = 500  # skip MAPLE/IHOP if they exceed this

SEG_CONFIGS = [
    ('THRESHOLD', TimeGapSegmenter(delta_minutes=20)),
    ('DENSITY',   DBSCANSegmenter(eps_minutes=20, min_samples=3)),
]
METHODS = ['THRESHOLD', 'DENSITY', 'MAPLE', 'IHOP']


def run_with_timeout(fn, timeout):
    """Run fn() in a daemon thread; return result or None on timeout."""
    result = [None]
    def worker():
        result[0] = fn()
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def run_seed(seed, all_pairs, top_kws, vocab, kw_to_tok):
    random.seed(seed)
    np.random.seed(seed)
    shuffled = all_pairs[:]
    random.shuffle(shuffled)
    half        = len(shuffled) // 2
    train_pairs = shuffled[:half]
    test_pairs  = shuffled[half:]
    test_sorted = sorted(test_pairs, key=lambda x: x[1])

    train_kws = [kw for kw, _ in train_pairs]
    tok_seq   = [(kw_to_tok[kw], ts) for kw, ts in test_sorted]
    test_int  = [int(kw_to_tok[kw]) for kw, _ in test_sorted]
    n_test    = len(test_sorted)
    res       = {}

    aux_similar = {'global': train_pairs}
    for label, seg in SEG_CONFIGS:
        t0 = time.time()
        try:
            sbr = SessionBasedRecovery(
                segmenter=seg, cooc_version=2,
                top_k=TOP_K, beta=BETA, batch_size=BATCH_SIZE, dedup=False,
            )
            pred = sbr.recover(tok_seq, aux_similar)
            acc  = sum(1 for kw, _ in test_sorted
                       if pred.get(kw_to_tok[kw]) == kw) / n_test
        except Exception:
            acc = 0.0
        res[label] = (acc, time.time() - t0)

    q_seq = make_query_sequence(train_kws, vocab)
    for label, mk_fn in [
        ('MAPLE', lambda: MarkovDecoding(q_seq)),
        # IHOP: raw list — skips when train coverage < test distinct tokens (matches paper behavior)
        ('IHOP',  lambda: MarkovIHOP([train_kws], pfree=0.25, niters=IHOP_NITERS, ep=1e-20)),
    ]:
        t0 = time.time()
        def _run(mk_fn=mk_fn, test_int=test_int, test_sorted=test_sorted, n_test=n_test):
            try:
                rec = mk_fn().recover(test_int)
                return sum(1 for (kw, _), r in zip(test_sorted, rec) if kw == r) / n_test
            except Exception:
                return 0.0
        r = run_with_timeout(_run, TIMEOUT_S)
        elapsed = time.time() - t0
        if r is None:
            res[label] = (None, elapsed)  # timeout
        else:
            res[label] = (r, elapsed)

    return res


if __name__ == '__main__':
    print(f"Loading Wikidata SPARQL log from:\n  {TSV_FILE}", flush=True)
    all_pairs = []
    with open(TSV_FILE, encoding='utf-8') as f:
        next(f)
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 2:
                continue
            query = unquote_plus(parts[0]).strip()
            ts    = parts[1].strip()
            if query and ts:
                all_pairs.append((query, ts))

    kw_counter = Counter(kw for kw, _ in all_pairs)
    top_kws    = {kw for kw, _ in kw_counter.most_common(N_KW)}
    filtered   = [(kw, ts) for kw, ts in all_pairs if kw in top_kws]
    vocab      = sorted(top_kws)
    kw_to_tok  = {kw: str(i) for i, kw in enumerate(vocab)}

    print(f"  Total pairs: {len(all_pairs):,}  |  top-{N_KW} filtered: {len(filtered):,}", flush=True)

    seed_results = []
    print(f"\n{'='*68}")
    print(f"  Wikidata |W|={N_KW}   {N_SEEDS} seeds")
    print(f"  THRESHOLD(20min)  DENSITY(20min,m=3)  MAPLE  IHOP(n=3)")
    print(f"{'='*68}")
    print(f"  {'Seed':>4}  " + '  '.join(f"{m:>18}" for m in METHODS))
    print(f"  {'-'*60}")

    for seed in range(N_SEEDS):
        res = run_seed(seed, filtered, top_kws, vocab, kw_to_tok)
        seed_results.append(res)

        row = f"  {seed:>4}  "
        for m in METHODS:
            acc, t = res[m]
            if acc is None:
                row += f"  {'TIMEOUT':>16s}  "
            else:
                row += f"  {acc*100:>8.2f}% ({t:>4.0f}s)  "
        print(row)
        sys.stdout.flush()

    print(f"  {'-'*60}")
    avg_row = f"  {'Avg':>4}  "
    for m in METHODS:
        valid = [(r[m][0], r[m][1]) for r in seed_results if r[m][0] is not None]
        if not valid:
            avg_row += f"  {'N/A (all timeout)':>16s}  "
        else:
            avg_acc = sum(a for a, _ in valid) / len(valid)
            avg_t   = sum(t for _, t in valid) / len(valid)
            avg_row += f"  {avg_acc*100:>8.2f}% ({avg_t:>4.0f}s)  "
    print(avg_row)
    print(f"{'='*68}")

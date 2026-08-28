"""
RefSpeed (batch_size) Sensitivity

Wikidata SPARQL, |W|=500, N_SEEDS=5
Vary RefSpeed (batch_size) in {5, 10, 20, 50, 100}
Test both THRESHOLD(20min) and DENSITY(20min, m=3)

RefSpeed controls how many tokens are recovered per iteration (Phase 4).
Higher RefSpeed = faster but potentially less accurate.
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
    SessionBasedRecovery, TimeGapSegmenter, DBSCANSegmenter,
)

TSV_FILE   = os.path.join(_here, '..', '..', 'data_sources', 'Wikidata SPARQL Logs', 'I1_status2xx_userData_Joined.tsv')
N_KW       = 500
N_SEEDS    = 5
TOP_K      = 5
BETA       = 0.5
REFSPEEDS  = [5, 10, 20, 50, 100]

SEG_CONFIGS = [
    ('THRESHOLD', TimeGapSegmenter(delta_minutes=20)),
    ('DENSITY',   DBSCANSegmenter(eps_minutes=20, min_samples=3)),
]


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
    top_kws   = {kw for kw, _ in Counter(kw for kw, _ in all_pairs).most_common(n_kw)}
    filtered  = [(kw, ts) for kw, ts in all_pairs if kw in top_kws]
    kw_to_tok = {kw: str(i) for i, kw in enumerate(sorted(top_kws))}
    return filtered, top_kws, kw_to_tok


def run_seed(seed, filtered, kw_to_tok, batch_size, seg):
    random.seed(seed)
    shuffled = filtered[:]
    random.shuffle(shuffled)
    half        = len(shuffled) // 2
    train_pairs = shuffled[:half]
    test_sorted = sorted(shuffled[half:], key=lambda x: x[1])

    tok_seq = [(kw_to_tok[kw], ts) for kw, ts in test_sorted]
    n_test  = len(test_sorted)

    t0 = time.time()
    sbr = SessionBasedRecovery(
        segmenter=seg, cooc_version=2,
        top_k=TOP_K, beta=BETA, batch_size=batch_size, dedup=False,
    )
    pred = sbr.recover(tok_seq, {'global': train_pairs})
    acc  = sum(1 for kw, _ in test_sorted if pred.get(kw_to_tok[kw]) == kw) / n_test
    return acc, time.time() - t0


if __name__ == '__main__':
    print(f"Loading Wikidata SPARQL log...", flush=True)
    filtered, top_kws, kw_to_tok = load_wikidata(TSV_FILE, N_KW)
    print(f"  |W|={N_KW}  filtered pairs: {len(filtered):,}", flush=True)

    print(f"\n{'='*65}")
    print(f" RefSpeed/batch_size (|W|={N_KW}, {N_SEEDS} seeds)")
    print(f"{'='*65}")
    header = f"  {'RefSpeed':>9}  " + '  '.join(f"{label:>18}" for label, _ in SEG_CONFIGS)
    print(header)
    print(f"  {'-'*58}")

    for bs in REFSPEEDS:
        row = f"  {bs:>9}  "
        for label, seg in SEG_CONFIGS:
            accs, times = [], []
            for s in range(N_SEEDS):
                acc, t = run_seed(s, filtered, kw_to_tok, bs, seg)
                accs.append(acc)
                times.append(t)
            avg_acc = sum(accs) / len(accs)
            avg_t   = sum(times) / len(times)
            row += f"  {avg_acc*100:>8.2f}% ({avg_t:>4.0f}s)  "
        print(row)
        sys.stdout.flush()

    print(f"{'='*65}")

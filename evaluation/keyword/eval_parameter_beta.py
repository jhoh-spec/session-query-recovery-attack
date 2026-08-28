"""
Beta Sensitivity

Wikidata SPARQL, |W|=500, N_SEEDS=5
Vary beta in {0.2, 0.4, 0.6, 0.8, 1.0}
Test both THRESHOLD(20min) and DENSITY(20min, m=3)

beta=0: frequency only, no co-occurrence
beta=1: co-occurrence only, no frequency
"""
import sys, os, random
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

TSV_FILE = os.path.join(_here, '..', '..', 'data_sources', 'Wikidata SPARQL Logs', 'I1_status2xx_userData_Joined.tsv')
N_KW     = 500
N_SEEDS  = 5
TOP_K    = 5
BATCH    = 5
BETAS    = [0.2, 0.4, 0.6, 0.8, 1.0]

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


def run_seed(seed, filtered, kw_to_tok, beta, seg):
    random.seed(seed)
    shuffled = filtered[:]
    random.shuffle(shuffled)
    half        = len(shuffled) // 2
    train_pairs = shuffled[:half]
    test_sorted = sorted(shuffled[half:], key=lambda x: x[1])

    tok_seq = [(kw_to_tok[kw], ts) for kw, ts in test_sorted]
    n_test  = len(test_sorted)

    sbr = SessionBasedRecovery(
        segmenter=seg, cooc_version=2,
        top_k=TOP_K, beta=beta, batch_size=BATCH, dedup=False,
    )
    pred = sbr.recover(tok_seq, {'global': train_pairs})
    return sum(1 for kw, _ in test_sorted if pred.get(kw_to_tok[kw]) == kw) / n_test


if __name__ == '__main__':
    print(f"Loading Wikidata SPARQL log...", flush=True)
    filtered, top_kws, kw_to_tok = load_wikidata(TSV_FILE, N_KW)
    print(f"  |W|={N_KW}  filtered pairs: {len(filtered):,}", flush=True)

    print(f"\n{'='*55}")
    print(f"  Beta (|W|={N_KW}, {N_SEEDS} seeds)")
    print(f"{'='*55}")
    header = f"  {'beta':>6}  " + '  '.join(f"{label:>12}" for label, _ in SEG_CONFIGS)
    print(header)
    print(f"  {'-'*44}")

    for beta in BETAS:
        row = f"  {beta:>6.1f}  "
        for label, seg in SEG_CONFIGS:
            accs = [run_seed(s, filtered, kw_to_tok, beta, seg) for s in range(N_SEEDS)]
            avg  = sum(accs) / len(accs)
            row += f"  {avg*100:>11.2f}%"
        print(row)
        sys.stdout.flush()

    print(f"{'='*55}")

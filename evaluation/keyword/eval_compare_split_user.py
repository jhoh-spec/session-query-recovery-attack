"""
Outdated Auxiliary Logs (Section 5.3.2)

Setting  : 10 users from top-10% most active TAIR users
Split    : chronological — earlier half as auxiliary, later half as victim
           (same user, different time periods)
|W|      : 50, 100  (user's most-frequent keywords)
Auxiliary: first half of user's log filtered to their keyword universe
Victim   : second half of user's log filtered to their keyword universe

Methods  :
  THRESHOLD  TimeGapSegmenter(delta=1hr)
  DENSITY    DBSCANSegmenter(eps=3hr, min_samples=3)
  MAPLE      MarkovDecoding
  IHOP       MarkovIHOP(pfree=0.25, niters=3)

Params   : top_k=5, RefSpeed=5, beta=0.5, dedup=False

Output   : per-user accuracy (Table 5), overall avg
"""
import sys, os
import logging
from collections import Counter

import numpy as np
np.random.seed(42)

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
from leaker.whoosh_interface import WhooshBackend


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

DATASET     = 'tair_ql'
N_USERS     = 10
NKW_LIST    = [50, 100]
TOP_K       = 5
BATCH_SIZE  = 5    # RefSpeed=5
BETA        = 0.5
IHOP_NITERS = 3

SEG_CONFIGS = [
    ('THRESHOLD', TimeGapSegmenter(delta_minutes=60)),              # 1 hour
    ('DENSITY',   DBSCANSegmenter(eps_minutes=180, min_samples=3)), # 3 hours
]
METHODS = ['THRESHOLD', 'DENSITY', 'MAPLE', 'IHOP']


def run_user(full_log, n_kw):
    """Run all 4 methods for chronological split of one user's log."""
    kw_counts = Counter(kw for kw, _ in full_log)
    top_kws   = {kw for kw, _ in kw_counts.most_common(n_kw)}
    filtered  = [(kw, ts) for kw, ts in full_log if kw in top_kws]
    if len(filtered) < 10:
        return None

    mid        = len(filtered) // 2
    train_pairs = filtered[:mid]
    test_pairs  = filtered[mid:]
    if not train_pairs or not test_pairs:
        return None

    vocab     = sorted(top_kws)
    kw_to_tok = {kw: str(i) for i, kw in enumerate(vocab)}
    test_tok_ts = [(kw_to_tok[kw], ts) for kw, ts in test_pairs]
    test_int    = [int(kw_to_tok[kw]) for kw, _ in test_pairs]
    n_test      = len(test_pairs)
    res = {}

    aux_similar = {'self': train_pairs}
    for label, seg in SEG_CONFIGS:
        try:
            sbr = SessionBasedRecovery(
                segmenter=seg, cooc_version=2,
                top_k=TOP_K, beta=BETA, batch_size=BATCH_SIZE, dedup=False,
            )
            pred = sbr.recover(test_tok_ts, aux_similar)
            res[label] = sum(1 for kw, _ in test_pairs
                             if pred.get(kw_to_tok[kw]) == kw) / n_test
        except Exception:
            res[label] = 0.0

    train_kws = [kw for kw, _ in train_pairs]
    q_seq = make_query_sequence(train_kws, vocab)
    try:
        rec = MarkovDecoding(q_seq).recover(test_int)
        res['MAPLE'] = sum(1 for (kw, _), r in zip(test_pairs, rec) if kw == r) / n_test
    except Exception:
        res['MAPLE'] = 0.0

    try:
        # IHOP: use raw list — intentionally skips when train coverage < test distinct tokens
        rec = MarkovIHOP([train_kws], pfree=0.25, niters=IHOP_NITERS, ep=1e-20).recover(test_int)
        res['IHOP'] = sum(1 for (kw, _), r in zip(test_pairs, rec) if kw == r) / n_test
    except Exception:
        res['IHOP'] = 0.0

    res['train'] = len(train_pairs)
    res['test']  = len(test_pairs)
    return res


if __name__ == '__main__':
    backend = WhooshBackend()
    q_log   = backend.load_querylog(
        DATASET, pickle_description="test",
        min_user_count=0, max_user_count=200, reverse=False,
    )

    all_uids   = list(q_log.user_ids())
    uid_counts = [(uid, len(q_log.queries_with_times(uid))) for uid in all_uids]
    uid_counts.sort(key=lambda x: x[1], reverse=True)
    top_users  = [uid for uid, _ in uid_counts[:N_USERS]]

    print(f"\nDataset: {DATASET}  |  top {N_USERS} users  |  chronological split")
    user_log = {uid: q_log.queries_with_times(uid) for uid in top_users}

    for n_kw in NKW_LIST:
        print(f"\n{'='*72}")
        print(f"  |W| = {n_kw}  |  THRESHOLD(1hr)  DENSITY(3hr,m=3)  MAPLE  IHOP(n=3)")
        print(f"{'='*72}")
        print(f"  {'#':>3}  {'User':<22} {'Train':>5}{'Test':>5}  "
              + '  '.join(f"{m:>11}" for m in METHODS))
        print(f"  {'-'*68}")

        overall = {m: [] for m in METHODS}

        for idx, uid in enumerate(top_users, 1):
            res = run_user(user_log[uid], n_kw)
            if res is None:
                print(f"  {idx:>3}  {str(uid):<22}  -- skipped (too few queries) --")
                continue

            row = (f"  {idx:>3}  {str(uid):<22} {res['train']:>5}{res['test']:>5}  "
                   + '  '.join(f"{res.get(m,0)*100:>10.2f}%" for m in METHODS))
            print(row)
            sys.stdout.flush()

            for m in METHODS:
                overall[m].append(res.get(m, 0.0))

        print(f"  {'-'*68}")
        n_valid = len(overall[METHODS[0]])
        avg_row = f"  {'Avg':<28}{'':>10}  " + '  '.join(
            f"{(sum(overall[m])/n_valid*100 if n_valid else 0):>10.2f}%" for m in METHODS
        )
        print(avg_row)
        print(f"{'='*72}")

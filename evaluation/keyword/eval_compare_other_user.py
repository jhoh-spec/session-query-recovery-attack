"""
Other-User Auxiliary Logs (Section 5.3.1)

Setting  : 10 users from top-10% most active TAIR users
Pairs    : ALL 10x9 = 90 ordered (auxiliary ua, victim uv) pairs
|W|      : 50, 100  (victim's most-frequent keywords)
Auxiliary: ua's full log filtered to victim's keyword universe
Victim   : uv's full log filtered to its own keyword universe

Methods  :
  THRESHOLD  TimeGapSegmenter(delta=1hr)
  DENSITY    DBSCANSegmenter(eps=3hr, min_samples=3)
  MAPLE      MarkovDecoding
  IHOP       MarkovIHOP(pfree=0.25, niters=3)

Params   : top_k=5, RefSpeed=5, beta=0.5, dedup=False

Output   : per-auxiliary-user avg[min,max] over 9 victims (Table 4)
           overall avg over all 90 pairs
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
            t_mat[i] = 1.0 / n   # uniform for unseen keywords
        else:
            t_mat[i] /= s
    return QuerySequence(transition_matrix=t_mat, num_states=n, query_list=keyword_list,
                         keyword_to_state=kw2st, alt_state_map=None, original_transition_matrix=t_mat)

DATASET      = 'tair_ql'
N_USERS      = 10
NKW_LIST     = [50, 100]
TOP_K        = 5
BATCH_SIZE   = 5    # RefSpeed=5
BETA         = 0.5
IHOP_NITERS  = 3

SEG_CONFIGS = [
    ('THRESHOLD', TimeGapSegmenter(delta_minutes=60)),              # 1 hour
    ('DENSITY',   DBSCANSegmenter(eps_minutes=180, min_samples=3)), # 3 hours
]
METHODS = ['THRESHOLD', 'DENSITY', 'MAPLE', 'IHOP']


def run_pair(ua_log, uv_log, top_kws):
    ua_filt = [(kw, ts) for kw, ts in ua_log if kw in top_kws]
    uv_filt = [(kw, ts) for kw, ts in uv_log if kw in top_kws]
    if not ua_filt or len(uv_filt) < 5:
        return None

    vocab     = sorted(top_kws)
    kw_to_tok = {kw: str(i) for i, kw in enumerate(vocab)}
    test_tok_ts = [(kw_to_tok[kw], ts) for kw, ts in uv_filt]
    test_int    = [int(kw_to_tok[kw]) for kw, _ in uv_filt]
    n_test      = len(uv_filt)
    res = {}

    aux_similar = {'aux': ua_filt}
    for label, seg in SEG_CONFIGS:
        try:
            sbr = SessionBasedRecovery(
                segmenter=seg, cooc_version=2,
                top_k=TOP_K, beta=BETA, batch_size=BATCH_SIZE, dedup=False,
            )
            pred = sbr.recover(test_tok_ts, aux_similar)
            res[label] = sum(1 for kw, _ in uv_filt
                             if pred.get(kw_to_tok[kw]) == kw) / n_test
        except Exception:
            res[label] = 0.0

    train_kws = [kw for kw, _ in ua_filt]
    q_seq = make_query_sequence(train_kws, vocab)
    try:
        rec = MarkovDecoding(q_seq).recover(test_int)
        res['MAPLE'] = sum(1 for (kw, _), r in zip(uv_filt, rec) if kw == r) / n_test
    except Exception:
        import traceback; traceback.print_exc()
        res['MAPLE'] = 0.0

    try:
        # IHOP: use raw list — intentionally skips when ua coverage < uv distinct tokens
        rec = MarkovIHOP([train_kws], pfree=0.25, niters=IHOP_NITERS, ep=1e-20).recover(test_int)
        res['IHOP'] = sum(1 for (kw, _), r in zip(uv_filt, rec) if kw == r) / n_test
    except Exception:
        res['IHOP'] = 0.0

    return res


def fmt(vals):
    if not vals:
        return 'N/A'
    avg = sum(vals) / len(vals)
    return f"{avg*100:6.2f}%  [{min(vals)*100:.1f},{max(vals)*100:.1f}]"


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

    print(f"\nDataset: {DATASET}  |  top {N_USERS} users")
    for i, uid in enumerate(top_users, 1):
        print(f"  {i:2}. {uid}  ({dict(uid_counts)[uid]} queries)")

    user_log = {uid: q_log.queries_with_times(uid) for uid in top_users}

    for n_kw in NKW_LIST:
        print(f"\n{'='*75}")
        print(f"  |W| = {n_kw}  |  THRESHOLD(1hr)  DENSITY(3hr,m=3)  MAPLE  IHOP(n=3)")
        print(f"{'='*75}")
        print(f"  {'Auxiliary user':<22} {'#pairs':>6}  "
              + '  '.join(f"{m:>22}" for m in METHODS))
        print(f"  {'-'*72}")

        overall = {m: [] for m in METHODS}

        for ua in top_users:
            acc_ua  = {m: [] for m in METHODS}
            n_valid = 0

            for uv in top_users:
                if uv == ua:
                    continue
                uv_kws  = Counter(kw for kw, _ in user_log[uv])
                top_kws = {kw for kw, _ in uv_kws.most_common(n_kw)}
                res = run_pair(user_log[ua], user_log[uv], top_kws)
                if res is None:
                    continue
                n_valid += 1
                for m in METHODS:
                    acc_ua[m].append(res.get(m, 0.0))
                    overall[m].append(res.get(m, 0.0))

            row = f"  {str(ua):<22} {n_valid:>6}  "
            row += '  '.join(f"{fmt(acc_ua[m]):>22}" for m in METHODS)
            print(row)
            sys.stdout.flush()

        print(f"  {'-'*72}")
        overall_row = f"  {'Overall':<22} {len(overall[METHODS[0]]):>6}  "
        overall_row += '  '.join(f"{fmt(overall[m]):>22}" for m in METHODS)
        print(overall_row)
        print(f"{'='*75}")

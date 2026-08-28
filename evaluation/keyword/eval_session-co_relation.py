"""
Table 3: Session Co-occurrence Relation (Section 5.2)

Measures how similar auxiliary and victim query logs are in terms of
the features used by session-based attacks (co-occurrence) and
transition-based attacks (Markov transitions).

Metric: Top-K keyword overlap @ K in {1, 2, 3, 5}

Settings :
  Other-user  10 users, all 90 ordered (ua, uv) pairs
  Outdated    10 users, chronological split (same user)

|W|     : 50 (victim's most-frequent keywords)
Segmenter: TimeGapSegmenter(delta=6hr) for session feature ranking
"""
import sys, os
import logging
from collections import Counter, defaultdict

import numpy as np

_here = os.path.dirname(os.path.abspath(__file__))
os.chdir(_here)
sys.path.insert(0, os.path.join(_here, '..', '..'))

logging.basicConfig(level=logging.WARNING,
                    format='{asctime} {levelname:8.8} {name}: {message}', style='{',
                    handlers=[logging.StreamHandler(sys.stdout)])

from leaker.attack.session_recovery import (
    TimeGapSegmenter, build_weighted_cooccurrence, _parse_time,
)
from leaker.whoosh_interface import WhooshBackend

DATASET   = 'tair_ql'
N_USERS   = 10
N_KW      = 50
K_LIST    = [1, 2, 3, 5]
SEG_6HR   = TimeGapSegmenter(delta_minutes=360)   # 6-hour sessions


def parse_log(log):
    """Convert [(kw, ts_str), ...] to [(kw, datetime), ...]."""
    return [(kw, _parse_time(ts)) for kw, ts in log]


def top_k_by_row_sum(matrix, items, k):
    """Return top-k items ranked by their total co-occurrence row sum."""
    row_sums = matrix.sum(axis=1)
    top_idx  = np.argsort(row_sums)[::-1][:k]
    return {items[i] for i in top_idx}


def transition_top_k(log, items, k):
    """Rank keywords by how often they appear followed by any other keyword."""
    bigram_count = Counter()
    for i in range(len(log) - 1):
        q_now = log[i][0]
        q_next = log[i + 1][0]
        if q_now in items and q_next in items and q_now != q_next:
            bigram_count[q_now] += 1
    ranked = [kw for kw, _ in bigram_count.most_common(k)]
    # pad with frequency-ranked if too few
    if len(ranked) < k:
        freq = Counter(kw for kw, _ in log if kw in items)
        for kw, _ in freq.most_common():
            if kw not in ranked:
                ranked.append(kw)
            if len(ranked) >= k:
                break
    return set(ranked[:k])


def overlap_at_k(aux_log, vic_log, top_kws, k):
    """
    Compute Top-K overlap using Session and Transition features.
    Returns (session_overlap@k, transition_overlap@k).
    """
    items = list(top_kws)

    # Session feature: segment → co-occurrence → row sum
    aux_sessions = SEG_6HR.segment(parse_log(aux_log))
    vic_sessions = SEG_6HR.segment(parse_log(vic_log))

    try:
        Ca, _ = build_weighted_cooccurrence(aux_sessions, items, dedup=False)
        Cv, _ = build_weighted_cooccurrence(vic_sessions, items, dedup=False)
        aux_top_sess = top_k_by_row_sum(Ca, items, k)
        vic_top_sess = top_k_by_row_sum(Cv, items, k)
        sess_overlap = len(aux_top_sess & vic_top_sess) / k
    except Exception:
        sess_overlap = 0.0

    # Transition feature: bigram frequency
    aux_filt = [(kw, ts) for kw, ts in aux_log if kw in top_kws]
    vic_filt = [(kw, ts) for kw, ts in vic_log if kw in top_kws]
    try:
        aux_top_trans = transition_top_k(aux_filt, top_kws, k)
        vic_top_trans = transition_top_k(vic_filt, top_kws, k)
        trans_overlap = len(aux_top_trans & vic_top_trans) / k
    except Exception:
        trans_overlap = 0.0

    return sess_overlap, trans_overlap


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

    print(f"\nDataset: {DATASET}  |  top {N_USERS} users  |  |W|={N_KW}  |  TG=6hr")
    for i, uid in enumerate(top_users, 1):
        print(f"  {i:2}. {uid}  ({dict(uid_counts)[uid]} queries)")

    user_log = {uid: q_log.queries_with_times(uid) for uid in top_users}

    # ── Other-user setting ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Other-User Setting  (90 ordered pairs)")
    print(f"{'='*60}")

    ou_sess  = defaultdict(list)
    ou_trans = defaultdict(list)

    for ua in top_users:
        for uv in top_users:
            if ua == uv:
                continue
            uv_kws  = Counter(kw for kw, _ in user_log[uv])
            top_kws = {kw for kw, _ in uv_kws.most_common(N_KW)}
            ua_filt = [(kw, ts) for kw, ts in user_log[ua] if kw in top_kws]
            uv_filt = [(kw, ts) for kw, ts in user_log[uv] if kw in top_kws]
            if not ua_filt or len(uv_filt) < 5:
                continue
            for k in K_LIST:
                s, t = overlap_at_k(ua_filt, uv_filt, top_kws, k)
                ou_sess[k].append(s)
                ou_trans[k].append(t)

    print(f"  {'Feature':<12} " + '  '.join(f"@{k:>2}" for k in K_LIST))
    print(f"  {'-'*40}")
    sess_vals  = [sum(ou_sess[k])/len(ou_sess[k]) if ou_sess[k] else 0 for k in K_LIST]
    trans_vals = [sum(ou_trans[k])/len(ou_trans[k]) if ou_trans[k] else 0 for k in K_LIST]
    print(f"  {'Session':<12} " + '  '.join(f"{v:>4.3f}" for v in sess_vals))
    print(f"  {'Transition':<12} " + '  '.join(f"{v:>4.3f}" for v in trans_vals))

    # ── Outdated (split) setting ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Outdated Setting  (chronological split, {N_USERS} users)")
    print(f"{'='*60}")

    sp_sess  = defaultdict(list)
    sp_trans = defaultdict(list)

    for uid in top_users:
        full_log = user_log[uid]
        kw_counts = Counter(kw for kw, _ in full_log)
        top_kws   = {kw for kw, _ in kw_counts.most_common(N_KW)}
        filtered  = [(kw, ts) for kw, ts in full_log if kw in top_kws]
        if len(filtered) < 10:
            continue
        mid   = len(filtered) // 2
        train = filtered[:mid]
        test  = filtered[mid:]
        for k in K_LIST:
            s, t = overlap_at_k(train, test, top_kws, k)
            sp_sess[k].append(s)
            sp_trans[k].append(t)

    print(f"  {'Feature':<12} " + '  '.join(f"@{k:>2}" for k in K_LIST))
    print(f"  {'-'*40}")
    sess_vals  = [sum(sp_sess[k])/len(sp_sess[k]) if sp_sess[k] else 0 for k in K_LIST]
    trans_vals = [sum(sp_trans[k])/len(sp_trans[k]) if sp_trans[k] else 0 for k in K_LIST]
    print(f"  {'Session':<12} " + '  '.join(f"{v:>4.3f}" for v in sess_vals))
    print(f"  {'Transition':<12} " + '  '.join(f"{v:>4.3f}" for v in trans_vals))
    print(f"{'='*60}")

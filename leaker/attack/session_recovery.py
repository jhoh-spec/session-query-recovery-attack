"""
Session-Based Query Recovery Attack

Leakage  : search pattern (query equality + timestamps)
Knowledge: other users' plaintext query logs (non-target)
Goal     : recover encrypted query tokens -> plaintext keywords
"""

import numpy as np
from abc import ABC, abstractmethod
from collections import defaultdict, Counter
from datetime import datetime
from typing import Dict, List, Set, Tuple, Union

from leaker.api.attack import KeywordQueryAttack

Token = str
Keyword = str


def _parse_time(ts: str) -> datetime:
    return datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Session Segmentation
# ─────────────────────────────────────────────────────────────────────────────

class BaseSegmenter(ABC):
    @abstractmethod
    def segment(self, queries_with_times: List[Tuple]) -> List[List[Tuple]]:
        """Split [(query, datetime), ...] into list of sessions."""
        ...


class TimeGapSegmenter(BaseSegmenter):
    """
    Version 1 — Fixed threshold.
    gap < δ  → same session
    gap ≥ δ  → new session starts
    """

    def __init__(self, delta_minutes: float = 30.0):
        self.delta_seconds = delta_minutes * 60

    def segment(self, queries_with_times: List[Tuple]) -> List[List[Tuple]]:
        if not queries_with_times:
            return []
        sorted_q = sorted(queries_with_times, key=lambda x: x[1])
        sessions, current = [], [sorted_q[0]]
        for i in range(1, len(sorted_q)):
            gap = (sorted_q[i][1] - sorted_q[i - 1][1]).total_seconds()
            if gap >= self.delta_seconds:
                sessions.append(current)
                current = []
            current.append(sorted_q[i])
        sessions.append(current)
        return sessions


class DBSCANSegmenter(BaseSegmenter):
    """
    Version 2 — Density-based (DBSCAN on 1-D timestamps).
    Queries in dense time regions → same session.
    Isolated queries (noise) → singleton sessions.

    Parameters
    ----------
    eps_minutes  : neighbourhood radius (default 30 min)
    min_samples  : minimum points to form a dense core (default 2)
    """

    def __init__(self, eps_minutes: float = 30.0, min_samples: int = 2):
        self.eps_seconds = eps_minutes * 60
        self.min_samples = min_samples

    def segment(self, queries_with_times: List[Tuple]) -> List[List[Tuple]]:
        from sklearn.cluster import DBSCAN

        if not queries_with_times:
            return []
        sorted_q = sorted(queries_with_times, key=lambda x: x[1])
        base = sorted_q[0][1]
        times = np.array(
            [(q[1] - base).total_seconds() for q in sorted_q], dtype=float
        ).reshape(-1, 1)

        labels = DBSCAN(
            eps=self.eps_seconds, min_samples=self.min_samples
        ).fit_predict(times)

        buckets: Dict = defaultdict(list)
        for i, label in enumerate(labels):
            key = f"noise_{i}" if label == -1 else label
            buckets[key].append(sorted_q[i])

        result = list(buckets.values())
        result.sort(key=lambda s: s[0][1])
        return result


class FixedLengthSegmenter(BaseSegmenter):
    """
    No-timestamp segmenter: split the ordered query sequence into
    non-overlapping chunks of exactly `window` queries each.
    The last chunk may be shorter than `window`.
    """

    def __init__(self, window: int = 10):
        self.window = window

    def segment(self, queries_with_times: List[Tuple]) -> List[List[Tuple]]:
        if not queries_with_times:
            return []
        sorted_q = sorted(queries_with_times, key=lambda x: x[1])
        return [sorted_q[i:i + self.window]
                for i in range(0, len(sorted_q), self.window)]


class SlidingWindowSegmenter(BaseSegmenter):
    """
    No-timestamp segmenter: create overlapping sessions using a sliding window
    of size `window` and step `stride` over the ordered query sequence.
    """

    def __init__(self, window: int = 10, stride: int = 5):
        self.window = window
        self.stride = stride

    def segment(self, queries_with_times: List[Tuple]) -> List[List[Tuple]]:
        if not queries_with_times:
            return []
        sorted_q = sorted(queries_with_times, key=lambda x: x[1])
        sessions = []
        for i in range(0, len(sorted_q), self.stride):
            chunk = sorted_q[i:i + self.window]
            if chunk:
                sessions.append(chunk)
        return sessions


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Co-occurrence Matrix Construction
# ─────────────────────────────────────────────────────────────────────────────

def build_simple_cooccurrence(
    sessions: List[List[Tuple]], items: List
) -> Tuple[np.ndarray, Dict]:
    """
    Version 1 — Simple +1.
    Every pair within the same session contributes +1 regardless of distance.
    """
    item_to_idx = {item: i for i, item in enumerate(items)}
    n = len(items)
    matrix = np.zeros((n, n), dtype=np.float32)

    for session in sessions:
        seen: Set = set()
        present = []
        for q, _ in session:
            if q in item_to_idx and q not in seen:
                seen.add(q)
                present.append(item_to_idx[q])
        for a, idx1 in enumerate(present):
            for b, idx2 in enumerate(present):
                if a != b:
                    matrix[idx1, idx2] += 1.0

    return matrix, item_to_idx


def _row_normalize(M: np.ndarray) -> np.ndarray:
    """Row-sum normalization: each row sums to 1 (like a probability distribution)."""
    rs = M.sum(axis=1, keepdims=True)
    rs[rs == 0] = 1.0
    return M / rs


def build_weighted_cooccurrence(
    sessions: List[List[Tuple]], items: List, dedup: bool = True
) -> Tuple[np.ndarray, Dict]:
    """
    Version 2 — Distance-weighted  weight(i,j) = 1 / |i - j|
    Normalized by number of sessions (not row sum):
      C[i,j] = (sum of 1/|pos_i - pos_j| over all sessions) / n_sessions

    dedup=True : each keyword counted once per session (first occurrence position)
    dedup=False: all positional occurrences counted (may double-count repeated keywords)
    """
    item_to_idx = {item: i for i, item in enumerate(items)}
    n = len(items)
    matrix = np.zeros((n, n), dtype=np.float32)
    n_sessions = max(len(sessions), 1)

    for session in sessions:
        if dedup:
            seen: Set = set()
            indexed = []
            for pos, (q, _) in enumerate(session):
                if q in item_to_idx and q not in seen:
                    seen.add(q)
                    indexed.append((item_to_idx[q], pos))
        else:
            indexed = [
                (item_to_idx[q], pos)
                for pos, (q, _) in enumerate(session)
                if q in item_to_idx
            ]
        for a, (idx1, pos_a) in enumerate(indexed):
            for b, (idx2, pos_b) in enumerate(indexed):
                if a != b:
                    matrix[idx1, idx2] += 1.0 / abs(pos_a - pos_b)

    return matrix / n_sessions, item_to_idx


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Anchor Finding
# ─────────────────────────────────────────────────────────────────────────────

def find_anchors(
    token_freqs: Dict[Token, int],
    kw_freqs: Dict[Keyword, int],
    top_k: int,
) -> List[Tuple[Token, Keyword]]:
    """
    1. Compute distinctiveness of each token = min frequency gap to nearest neighbour.
    2. Select top-K most distinctive tokens.
    3. Greedily match each to the closest-frequency unused keyword.
    """
    tokens = list(token_freqs.keys())
    keywords = list(kw_freqs.keys())
    t_vals = np.array([token_freqs[t] for t in tokens], dtype=float)
    k_vals = np.array([kw_freqs[k] for k in keywords], dtype=float)

    def _distinctiveness(vals: np.ndarray) -> np.ndarray:
        result = []
        for i, v in enumerate(vals):
            others = np.delete(vals, i)
            result.append(np.min(np.abs(others - v)) if len(others) > 0 else 0.0)
        return np.array(result)

    t_dist = _distinctiveness(t_vals)
    k = min(top_k, len(tokens), len(keywords))
    top_idxs = np.argsort(t_dist)[::-1][:k]

    anchors: List[Tuple[Token, Keyword]] = []
    used: Set[Keyword] = set()

    for t_idx in top_idxs:
        t = tokens[t_idx]
        t_freq = t_vals[t_idx]
        best_kw, best_gap = None, float("inf")
        for j, kw in enumerate(keywords):
            if kw in used:
                continue
            gap = abs(t_freq - k_vals[j])
            if gap < best_gap:
                best_gap, best_kw = gap, kw
        if best_kw is not None:
            anchors.append((t, best_kw))
            used.add(best_kw)

    return anchors


# ─────────────────────────────────────────────────────────────────────────────
# Main Attack
# ─────────────────────────────────────────────────────────────────────────────

class SessionBasedRecovery:
    """
    Session-Based Query Recovery using non-target query logs.

    Parameters
    ----------
    segmenter     : TimeGapSegmenter (default) or DBSCANSegmenter
    cooc_version  : 1 = simple +1,  2 = distance-weighted 1/|i-j|  (default 2)
    top_k         : number of frequency-anchor pairs (Phase 3)
    beta          : weight for co-occurrence term vs frequency term in Phase 4
                    score = beta * ||Cr_sub - Cs_sub|| + (1-beta) * |freq_diff|
    """

    def __init__(
        self,
        segmenter: BaseSegmenter = None,
        cooc_version: int = 2,
        top_k: int = 5,
        beta: float = 0.5,
        batch_size: int = 10,
        dedup: bool = True,
    ):
        self.segmenter = segmenter or TimeGapSegmenter()
        self.dedup = dedup
        from functools import partial
        if cooc_version == 2:
            self.cooc_fn = partial(build_weighted_cooccurrence, dedup=dedup)
        else:
            self.cooc_fn = build_simple_cooccurrence
        self.top_k = top_k
        self.beta = beta
        self.batch_size = batch_size

    # ── vectorized Phase 4 ───────────────────────────────────────────────────

    def _iterative_recovery_vectorized(
        self,
        Cr: np.ndarray, Cs: np.ndarray,
        token_to_idx: Dict, kw_to_idx: Dict,
        tokens: List, keywords: List,
        recovered: Dict[Token, Keyword],
        token_freqs: Dict, kw_freqs: Dict,
        batch_size: int = 1,
    ) -> None:
        """
        Vectorized iterative recovery (Phase 4).

        Key optimisation: maintain a (n_t, n_k) squared-distance matrix and
        update it incrementally — O(n²) numpy per iteration instead of
        O(n²) Python loops → ~100x faster.
        """
        remaining_tokens = [t for t in tokens if t not in recovered]
        remaining_kws    = [kw for kw in keywords if kw not in set(recovered.values())]
        if not remaining_tokens or not remaining_kws:
            return

        n_t = len(remaining_tokens)
        n_k = len(remaining_kws)

        # Row indices into Cr / Cs for the remaining items
        t_idxs = np.array([token_to_idx.get(t, 0) for t in remaining_tokens])
        k_idxs = np.array([kw_to_idx.get(kw, 0) for kw in remaining_kws])

        # Static frequency-difference matrix (n_t, n_k)
        t_freqs_arr = np.array([token_freqs.get(t, 0) for t in remaining_tokens], dtype=np.float32)
        k_freqs_arr = np.array([kw_freqs.get(kw, 0) for kw in remaining_kws],    dtype=np.float32)
        max_freq    = float(max(t_freqs_arr.max(), k_freqs_arr.max(), 1.0))
        freq_diff   = np.abs(t_freqs_arr[:, None] - k_freqs_arr[None, :]) / max_freq  # (n_t, n_k)

        # Co-occurrence squared-distance matrix — incremental update
        coo_sq = np.zeros((n_t, n_k), dtype=np.float32)

        # Seed with anchor contributions
        for tok, kw in recovered.items():
            if tok not in token_to_idx or kw not in kw_to_idx:
                continue
            cr_col = Cr[t_idxs, token_to_idx[tok]]  # (n_t,)
            cs_col = Cs[k_idxs, kw_to_idx[kw]]      # (n_k,)
            coo_sq += (cr_col[:, None] - cs_col[None, :]) ** 2

        # Boolean masks for active rows / columns
        active_t = np.ones(n_t, dtype=bool)
        active_k = np.ones(n_k, dtype=bool)

        while active_t.any() and active_k.any():
            act_t = np.where(active_t)[0]
            act_k = np.where(active_k)[0]

            # Score sub-matrix for active items
            coo_sub   = coo_sq[np.ix_(act_t, act_k)]
            score_sub = self.beta * np.sqrt(coo_sub) + (1 - self.beta) * freq_diff[np.ix_(act_t, act_k)]

            # Certainty = gap between 1st and 2nd smallest score in each row
            if score_sub.shape[1] >= 2:
                part = np.partition(score_sub, 1, axis=1)
                certainty = part[:, 1] - part[:, 0]
            else:
                certainty = np.full(len(act_t), np.inf)

            n_batch = min(batch_size, len(act_t), len(act_k))
            top_local_t = np.argsort(certainty)[::-1][:n_batch]

            newly_recovered = []
            used_k_locals: Set = set()
            for local_t in top_local_t:
                scores_row = score_sub[local_t].copy()
                for used in used_k_locals:
                    scores_row[used] = np.inf
                local_k = int(np.argmin(scores_row))
                newly_recovered.append((act_t[local_t], act_k[local_k],
                                        remaining_tokens[act_t[local_t]],
                                        remaining_kws[act_k[local_k]]))
                used_k_locals.add(local_k)

            for t_global, k_global, best_token, best_kw in newly_recovered:
                recovered[best_token] = best_kw
                active_t[t_global] = False
                active_k[k_global] = False

            rem_t = np.where(active_t)[0]
            rem_k = np.where(active_k)[0]
            if len(rem_t) and len(rem_k):
                for _, _, best_token, best_kw in newly_recovered:
                    if best_token in token_to_idx and best_kw in kw_to_idx:
                        cr_col = Cr[t_idxs[rem_t], token_to_idx[best_token]]
                        cs_col = Cs[k_idxs[rem_k], kw_to_idx[best_kw]]
                        coo_sq[np.ix_(rem_t, rem_k)] += (cr_col[:, None] - cs_col[None, :]) ** 2

    # ── main entry ────────────────────────────────────────────────────────────

    def recover(
        self,
        target_tokens_with_times: List[Tuple[Token, str]],
        similar_logs: Dict[str, List[Tuple[Keyword, str]]],
    ) -> Dict[Token, Keyword]:
        """
        Parameters
        ----------
        target_tokens_with_times
            [(token_id, "YYYY-MM-DD HH:MM:SS"), ...]
            Encrypted query tokens of the target user with timestamps.

        similar_logs
            {user_id: [(keyword, "YYYY-MM-DD HH:MM:SS"), ...], ...}
            Plaintext query logs of other (non-target) users.

        Returns
        -------
        {token_id: recovered_keyword, ...}
        """
        # Parse timestamps
        target = [(t, _parse_time(ts)) for t, ts in target_tokens_with_times]
        similar = {
            uid: [(kw, _parse_time(ts)) for kw, ts in log]
            for uid, log in similar_logs.items()
        }

        # ── Phase 1 ──────────────────────────────────────────────────────────
        target_sessions = self.segmenter.segment(target)
        similar_sessions: List[List[Tuple]] = []
        for log in similar.values():
            similar_sessions.extend(self.segmenter.segment(log))

        # ── Phase 2 ──────────────────────────────────────────────────────────
        tokens = list(dict.fromkeys(t for t, _ in target))
        keywords = list(
            dict.fromkeys(kw for log in similar.values() for kw, _ in log)
        )

        Cr, token_to_idx = self.cooc_fn(target_sessions, tokens)
        Cs, kw_to_idx = self.cooc_fn(similar_sessions, keywords)

        token_freqs = Counter(t for t, _ in target)
        kw_freqs = Counter(kw for log in similar.values() for kw, _ in log)
        max_freq = float(
            max(max(token_freqs.values(), default=1), max(kw_freqs.values(), default=1))
        )

        # ── Phase 3 ──────────────────────────────────────────────────────────
        recovered: Dict[Token, Keyword] = {}
        used_kws: Set[Keyword] = set()
        for token, kw in find_anchors(token_freqs, kw_freqs, self.top_k):
            recovered[token] = kw
            used_kws.add(kw)

        # ── Phase 4 (vectorized) ─────────────────────────────────────────────
        self._iterative_recovery_vectorized(
            Cr, Cs, token_to_idx, kw_to_idx,
            tokens, keywords, recovered, token_freqs, kw_freqs,
            batch_size=self.batch_size,
        )

        return recovered


# ─────────────────────────────────────────────────────────────────────────────
# MAPLE-compatible KeywordQueryAttack wrapper
# ─────────────────────────────────────────────────────────────────────────────

class SessionRecoveryQueryAttack(KeywordQueryAttack):
    """
    Wraps SessionBasedRecovery for the MAPLE KeywordQueryAttack evaluation framework.

    Since MAPLE doesn't provide timestamps, sessions are approximated by
    fixed-size positional windows (every `window_size` consecutive queries
    form one session).

    Parameters
    ----------
    known        : List[List[str]]  — other users' keyword sequences (OTHER_USERS scenario)
    window_size  : int              — number of queries per positional session window
    cooc_version : int              — 1 = simple +1,  2 = distance-weighted 1/|i-j|
    top_k        : int              — number of anchor pairs in Phase 3
    beta         : float            — weight for co-occurrence vs frequency score
    """

    def __init__(self, known: Union[object, List[List[str]]],
                 window_size: int = 20, stride: int = None,
                 cooc_version: int = 2,
                 top_k: int = 5, beta: float = 0.5, batch_size: int = 1):
        super().__init__(known)
        self._window_size = window_size
        self._stride = stride if stride is not None else window_size
        self._beta = beta
        self._top_k = top_k
        self._batch_size = batch_size
        cooc_fn = (build_weighted_cooccurrence if cooc_version == 2
                   else build_simple_cooccurrence)
        self._cooc_fn = cooc_fn

        # In OTHER_USERS scenario `known` is List[List[str]]
        known_seqs: List[List[str]] = known if isinstance(known, list) else []

        self._keywords: List[str] = list(
            dict.fromkeys(kw for seq in known_seqs for kw in seq)
        )
        self._kw_freqs: Dict[str, int] = Counter(
            kw for seq in known_seqs for kw in seq
        )

        # Build sessions by positional window across all known users
        all_sessions: List[List[Tuple]] = []
        for seq in known_seqs:
            for start in range(0, len(seq), self._stride):
                chunk = seq[start: start + window_size]
                all_sessions.append(
                    [(kw, start + j) for j, kw in enumerate(chunk)]
                )

        self._Cs, self._kw_to_idx = cooc_fn(all_sessions, self._keywords)

    @classmethod
    def name(cls) -> str:
        return "SessionBasedRecovery"

    @classmethod
    def required_leakage(cls) -> list:
        return []

    def recover(self, queries: List[int]) -> List[str]:
        tokens = [str(q) for q in queries]
        unique_tokens: List[str] = list(dict.fromkeys(tokens))
        token_freqs: Dict[str, int] = Counter(tokens)

        # Segment target sequence by positional window
        target_sessions: List[List[Tuple]] = []
        for start in range(0, len(tokens), self._stride):
            chunk = tokens[start: start + self._window_size]
            target_sessions.append(
                [(tok, start + j) for j, tok in enumerate(chunk)]
            )

        Cr, token_to_idx = self._cooc_fn(target_sessions, unique_tokens)

        # Phase 3: anchors
        recovered: Dict[str, str] = {}
        for token, kw in find_anchors(token_freqs, self._kw_freqs, self._top_k):
            recovered[token] = kw

        # Phase 4: reuse vectorized method via a temporary holder
        _run_iterative_recovery(
            Cr, self._Cs, token_to_idx, self._kw_to_idx,
            unique_tokens, self._keywords, recovered,
            token_freqs, self._kw_freqs, self._beta,
            batch_size=self._batch_size,
        )

        return [recovered.get(str(q), "") for q in queries]


def _run_iterative_recovery(
    Cr: np.ndarray, Cs: np.ndarray,
    token_to_idx: Dict, kw_to_idx: Dict,
    tokens: List, keywords: List,
    recovered: Dict,
    token_freqs: Dict, kw_freqs: Dict,
    beta: float,
    batch_size: int = 1,
) -> None:
    """Standalone vectorized Phase 4 (extracted so it can be shared)."""
    remaining_tokens = [t for t in tokens if t not in recovered]
    remaining_kws    = [kw for kw in keywords if kw not in set(recovered.values())]
    if not remaining_tokens or not remaining_kws:
        return

    n_t = len(remaining_tokens)
    n_k = len(remaining_kws)

    t_idxs = np.array([token_to_idx.get(t, 0) for t in remaining_tokens])
    k_idxs = np.array([kw_to_idx.get(kw, 0) for kw in remaining_kws])

    t_freqs_arr = np.array([token_freqs.get(t, 0)  for t in remaining_tokens], dtype=np.float32)
    k_freqs_arr = np.array([kw_freqs.get(kw, 0)    for kw in remaining_kws],   dtype=np.float32)
    max_freq    = float(max(t_freqs_arr.max(), k_freqs_arr.max(), 1.0))
    freq_diff   = np.abs(t_freqs_arr[:, None] - k_freqs_arr[None, :]) / max_freq

    coo_sq = np.zeros((n_t, n_k), dtype=np.float32)

    for tok, kw in recovered.items():
        if tok not in token_to_idx or kw not in kw_to_idx:
            continue
        cr_col = Cr[t_idxs, token_to_idx[tok]]
        cs_col = Cs[k_idxs, kw_to_idx[kw]]
        coo_sq += (cr_col[:, None] - cs_col[None, :]) ** 2

    active_t = np.ones(n_t, dtype=bool)
    active_k = np.ones(n_k, dtype=bool)

    while active_t.any() and active_k.any():
        act_t = np.where(active_t)[0]
        act_k = np.where(active_k)[0]

        coo_sub   = coo_sq[np.ix_(act_t, act_k)]
        score_sub = beta * np.sqrt(coo_sub) + (1 - beta) * freq_diff[np.ix_(act_t, act_k)]

        if score_sub.shape[1] >= 2:
            part      = np.partition(score_sub, 1, axis=1)
            certainty = part[:, 1] - part[:, 0]
        else:
            certainty = np.full(len(act_t), np.inf)

        # Select top batch_size most certain tokens this round
        n_batch = min(batch_size, len(act_t), len(act_k))
        top_local_t = np.argsort(certainty)[::-1][:n_batch]

        newly_recovered = []
        used_k_locals: Set = set()
        for local_t in top_local_t:
            scores_row = score_sub[local_t].copy()
            for used in used_k_locals:
                scores_row[used] = np.inf
            local_k = int(np.argmin(scores_row))
            t_global = act_t[local_t]
            k_global = act_k[local_k]
            newly_recovered.append((t_global, k_global,
                                    remaining_tokens[t_global],
                                    remaining_kws[k_global]))
            used_k_locals.add(local_k)

        for t_global, k_global, best_token, best_kw in newly_recovered:
            recovered[best_token] = best_kw
            active_t[t_global] = False
            active_k[k_global] = False

        rem_t = np.where(active_t)[0]
        rem_k = np.where(active_k)[0]
        if len(rem_t) and len(rem_k):
            for _, _, best_token, best_kw in newly_recovered:
                if best_token in token_to_idx and best_kw in kw_to_idx:
                    cr_col = Cr[t_idxs[rem_t], token_to_idx[best_token]]
                    cs_col = Cs[k_idxs[rem_k], kw_to_idx[best_kw]]
                    coo_sq[np.ix_(rem_t, rem_k)] += (cr_col[:, None] - cs_col[None, :]) ** 2

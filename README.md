> *"Queries Stay Together: Session-Based Query Recovery from Non-Exact Query Logs"*
> 
This artifact is built on the [LEAKER](https://github.com/encryptogroup/LEAKER) framework.



---

## Requirements

**Python 3.8** is required. A conda environment is strongly recommended.

### Step 1 — Create conda environment

```bash
conda create -n maple python=3.8
conda activate maple
```

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Install LEAKER in editable mode

```bash
pip install -e .
```

---

## Data Sources

Download the datasets and place them in the corresponding paths under `data_sources/`.  
Experiments in this paper use **TAIR** and **Wikidata SPARQL Logs**.

| Dataset | Where to Download | Place at |
|---------|-------------------|----------|
| TAIR Query Log | [IPK Gatersleben](https://doi.ipk-gatersleben.de/DOI/a8d78c11-bb09-43a9-8eb4-591fa1266133/9462b38e-bb71-44ba-b95d-42bebf1cbf81/2) | `data_sources/TAIR/query_log/` |
| Wikidata SPARQL | [TU Dresden](https://iccl.inf.tu-dresden.de/web/Wikidata_SPARQL_Logs/en) | `data_sources/Wikidata SPARQL Logs/I1_status2xx_userData_Joined.tsv` |

---

## Indexing

Before running evaluations, index the raw query logs into Whoosh format. Index scripts are in `evaluation/keyword/` and must be run from that directory.

```bash
cd evaluation/keyword
```

### TAIR — required for Figures 3, 4 and Table 3

```bash
python index_tair_with_times.py
```

This reads `data_sources/TAIR/query_log/TAIR_query_log.txt` and builds the `tair_ql` index.

### Wikidata SPARQL — required for Figures 5, 6 and Appendix B

No indexing step needed. The evaluation scripts read the TSV file directly:
```
data_sources/Wikidata SPARQL Logs/I1_status2xx_userData_Joined.tsv
```

---

## Running Evaluations

All evaluation scripts live in `evaluation/keyword/`. Run them from that directory:

```bash
cd evaluation/keyword
python <script_name>.py
```

### Evaluation Scripts

| Script | Paper | Dataset | Description |
|--------|-------|---------|-------------|
| `eval_compare_other_user.py` | §5.3.1 · Fig. 3 | TAIR | Other-user auxiliary: 10 users, 90 ordered pairs, \|W\| ∈ {50, 100} |
| `eval_compare_split_user.py` | §5.3.2 · Fig. 4 | TAIR | Outdated auxiliary: chronological split per user, \|W\| ∈ {50, 100} |
| `eval_large_keyword.py` | §5.3.3 · Fig. 5/6 | Wikidata | Large keyword universe, 5 seeds, \|W\| ∈ {500, 1000, 2000} |
| `eval_session-co_relation.py` | §5.2 · Table 3 | TAIR | Session co-occurrence vs. transition feature overlap @ K ∈ {1,2,3,5} |
| `eval_parameter_session_threshold.py` | Appendix B.1 | Wikidata | Sensitivity to THRESHOLD δ ∈ {10, 20, 30, 60} min |
| `eval_parameter_min_samples.py` | Appendix B.2 | Wikidata | Sensitivity to DENSITY min\_samples ∈ {2, 3, 5, 10} |
| `eval_parameter_beta.py` | Appendix B.3 | Wikidata | Sensitivity to β ∈ {0.2, 0.4, 0.6, 0.8, 1.0} |
| `eval_parameter_refspeed.py` | Appendix B.4 | Wikidata | Sensitivity to RefSpeed ∈ {5, 10, 20, 50, 100} |

### `eval_large_keyword.py` — keyword universe size option

```bash
python eval_large_keyword.py --n_kw 500
python eval_large_keyword.py --n_kw 1000
python eval_large_keyword.py --n_kw 2000
```

> **Note:** MAPLE and IHOP are skipped with a 500-second timeout at \|W\| ≥ 1000 due to computational cost.

### Methods Compared in Each Script

| Method | Segmenter | Description |
|--------|-----------|-------------|
| **THRESHOLD** | `TimeGapSegmenter(δ)` | Splits queries into sessions by time gap |
| **DENSITY** | `DBSCANSegmenter(eps, m)` | Density-based session segmentation |
| **MAPLE** | `MarkovDecoding` | Frequency + Markov HMM baseline [[MAPLE'23]](https://doi.org/10.1109/SP46215.2023.10179407) |
| **IHOP** | `MarkovIHOP` | Hungarian-algorithm Markov baseline [[OK22]](https://doi.org/10.48550/arXiv.2110.04180) |

---

## Attack Implementation

The session-based attack proposed in this paper is implemented in:

```
leaker/attack/session_recovery.py
```

### Key Classes

| Class | Role |
|-------|------|
| `SessionBasedRecovery` | Main attack — builds session co-occurrence from auxiliary logs, recovers victim tokens |
| `TimeGapSegmenter` | Segments a query sequence into sessions by time gap δ |
| `DBSCANSegmenter` | Segments a query sequence into sessions via DBSCAN |

### Parameters of `SessionBasedRecovery`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `segmenter` | `TimeGapSegmenter()` | Session segmentation strategy |
| `top_k` | `5` | Candidate keywords per token in Phase 3 |
| `beta` | `0.5` | Weight between frequency (0) and co-occurrence (1) signals |
| `batch_size` | `10` | Tokens recovered per refinement pass (RefSpeed) |
| `dedup` | `True` | Deduplicate keyword occurrences within one session |
| `cooc_version` | `2` | Co-occurrence weighting scheme (2 = weighted, 1 = simple) |

All paper experiments use `dedup=False` and `batch_size=5`.

---

## Project Structure

```
artifact/
├── leaker/
│   ├── attack/
│   │   ├── session_recovery.py      ← MAPLE attack (this paper)
│   │   └── markov/                  ← MarkovDecoding & MarkovIHOP baselines
│   └── whoosh_interface.py
├── evaluation/
│   └── keyword/
│       ├── eval_compare_other_user.py        (Fig. 3)
│       ├── eval_compare_split_user.py        (Fig. 4)
│       ├── eval_large_keyword.py             (Fig. 5/6)
│       ├── eval_session-co_relation.py       (Table 3)
│       ├── eval_parameter_session_threshold.py  (Appendix B.1)
│       ├── eval_parameter_min_samples.py        (Appendix B.2)
│       ├── eval_parameter_beta.py               (Appendix B.3)
│       ├── eval_parameter_refspeed.py           (Appendix B.4)
│       └── index_tair_with_times.py
├── data_sources/          ← raw datasets (download separately)
│   ├── TAIR/
│   └── Wikidata SPARQL Logs/
├── data/                  ← created automatically at runtime
│   ├── whoosh/            
│   ├── pickle/            ← cached query logs
│   └── cache/
└── requirements.txt
```

---

## Acknowledgements

This artifact extends the [LEAKER framework](https://github.com/encryptedsystems/Leaker) by Patrick Ehrler, Abdelkarim Kati, Johannes Leupold, Tobias Stöckert, Amos Treiber, and Michael Yonli.

The `MarkovDecoding` and `MarkovIHOP` baselines build on the IHOP implementation by [Simon Oya](https://github.com/simon-oya/USENIX22-ihop-code).

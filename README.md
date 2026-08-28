# Queries Stay Together: Session-Based Query Recovery from Non-Exact Query Logs

This repository contains the artifact for:

> *"Queries Stay Together: Session-Based Query Recovery from Non-Exact Query Logs"*

It includes the implementation of our **session-based query recovery attack**, the **MAPLE** and **IHOP** baselines, and the evaluation scripts used to reproduce the experimental results reported in the paper.

This artifact is built on the [LEAKER](https://github.com/encryptogroup/LEAKER) framework.

---

## Requirements

**Python 3.8** is required. We strongly recommend using a conda environment.

### Step 1 — Create a conda environment

```bash
conda create -n session-recovery python=3.8
conda activate session-recovery
```

### Step 2 — Install dependencies

From the repository root:

```bash
pip install -r requirements.txt
```

### Step 3 — Install the artifact in editable mode

From the repository root:

```bash
pip install -e .
```

---

## Data Sources

The raw datasets are **not redistributed with this artifact**. Please download them from their original sources and place them in the corresponding paths under `data_sources/`.

Experiments in this paper use **TAIR Query Logs** and **Wikidata SPARQL Logs**.

| Dataset | Where to Download | Place at |
|---|---|---|
| TAIR Query Log | [IPK Gatersleben](https://doi.ipk-gatersleben.de/DOI/a8d78c11-bb09-43a9-8eb4-591fa1266133/9462b38e-bb71-44ba-b95d-42bebf1cbf81/2) | `data_sources/TAIR/query_log/` |
| Wikidata SPARQL Logs | [TU Dresden](https://iccl.inf.tu-dresden.de/web/Wikidata_SPARQL_Logs/en) | `data_sources/Wikidata SPARQL Logs/I1_status2xx_userData_Joined.tsv` |

After downloading the datasets, the relevant directory structure should be:

```text
data_sources/
├── TAIR/
│   └── query_log/
│       └── TAIR_query_log.txt
└── Wikidata SPARQL Logs/
    └── I1_status2xx_userData_Joined.tsv
```

---

## Getting Started

After installing the dependencies and downloading the required datasets, experiments can be executed from:

```bash
cd evaluation/keyword
```

For experiments using the **TAIR Query Log**, the dataset must first be preprocessed as described below.

For experiments using the **Wikidata SPARQL Logs**, no separate preprocessing step is required.

The evaluation scripts directly compare our two session-based variants (**THRESHOLD** and **DENSITY**) with the **MAPLE** and **IHOP** baselines.

---

## Data Preprocessing

Before running the TAIR evaluations, preprocess the raw TAIR query log.

All preprocessing commands should be executed from:

```bash
cd evaluation/keyword
```

### TAIR — required for Figures 3, 4 and Table 3

Run:

```bash
python index_tair_with_times.py
```

The script reads:

```text
data_sources/TAIR/query_log/TAIR_query_log.txt
```

and prepares the TAIR data required by the evaluation scripts.

The processed data and index files are stored under:

```text
evaluation/keyword/data/
```

### Wikidata SPARQL — required for large-scale and parameter experiments

No preprocessing step is required.

The corresponding evaluation scripts read the TSV file directly from:

```text
data_sources/Wikidata SPARQL Logs/I1_status2xx_userData_Joined.tsv
```

---

## Running Evaluations

All evaluation scripts are located in:

```text
evaluation/keyword/
```

Run the experiments from this directory:

```bash
cd evaluation/keyword
python <script_name>.py
```

### Evaluation Scripts

| Script | Paper | Dataset | Description |
|---|---|---|---|
| `eval_compare_other_user.py` | §5.3.1 · Fig. 3 | TAIR | Other-user auxiliary setting: 10 users, 90 ordered user pairs, \|W\| ∈ {50, 100} |
| `eval_compare_split_user.py` | §5.3.2 · Fig. 4 | TAIR | Outdated auxiliary setting: chronological split for each user, \|W\| ∈ {50, 100} |
| `eval_large_keyword.py` | §5.3.3 · Fig. 5/6 | Wikidata | Large keyword universe, 5 seeds, \|W\| ∈ {500, 1000, 2000} |
| `eval_session-co_relation.py` | §5.2 · Table 3 | TAIR | Session co-occurrence vs. transition feature overlap at K ∈ {1, 2, 3, 5} |
| `eval_parameter_session_threshold.py` | Appendix B.1 | Wikidata | Sensitivity to THRESHOLD δ ∈ {10, 20, 30, 60} min |
| `eval_parameter_min_samples.py` | Appendix B.2 | Wikidata | Sensitivity to DENSITY `min_samples` ∈ {2, 3, 5, 10} |
| `eval_parameter_beta.py` | Appendix B.3 | Wikidata | Sensitivity to β ∈ {0.2, 0.4, 0.6, 0.8, 1.0} |
| `eval_parameter_refspeed.py` | Appendix B.4 | Wikidata | Sensitivity to RefSpeed ∈ {5, 10, 20, 50, 100} |

---

## Reproducing the Main Results

### Figure 3 — Other-User Auxiliary Logs

Dataset: **TAIR**

```bash
python eval_compare_other_user.py
```

This experiment evaluates the attacks when the auxiliary query log comes from a different user.

The evaluation considers 10 users, corresponding to 90 ordered victim–auxiliary user pairs, with:

```text
|W| ∈ {50, 100}
```

Methods compared:

- THRESHOLD
- DENSITY
- MAPLE
- IHOP

---

### Figure 4 — Outdated Auxiliary Logs

Dataset: **TAIR**

```bash
python eval_compare_split_user.py
```

This experiment chronologically splits each user's query log and uses the earlier portion as the auxiliary log and the later portion as the victim query log.

The experiment evaluates:

```text
|W| ∈ {50, 100}
```

Methods compared:

- THRESHOLD
- DENSITY
- MAPLE
- IHOP

---

### Figures 5/6 — Large Keyword Universe

Dataset: **Wikidata SPARQL Logs**

The keyword universe size can be specified using `--n_kw`:

```bash
python eval_large_keyword.py --n_kw 500
python eval_large_keyword.py --n_kw 1000
python eval_large_keyword.py --n_kw 2000
```

The experiments use five random seeds for each keyword-universe size.

> **Note:** MAPLE and IHOP are skipped after a 500-second timeout for |W| ≥ 1000 because of their computational cost.

---

### Table 3 — Session Co-occurrence Analysis

Dataset: **TAIR**

```bash
python eval_session-co_relation.py
```

This experiment compares the feature overlap obtained from **session co-occurrence** and **query-transition information** at:

```text
K ∈ {1, 2, 3, 5}
```

It corresponds to the effectiveness analysis in §5.2.

---

## Parameter Sensitivity Experiments

The following scripts reproduce the parameter analyses reported in Appendix B.

### Appendix B.1 — Session Threshold δ

```bash
python eval_parameter_session_threshold.py
```

Evaluated values:

```text
δ ∈ {10, 20, 30, 60} minutes
```

### Appendix B.2 — DBSCAN `min_samples`

```bash
python eval_parameter_min_samples.py
```

Evaluated values:

```text
min_samples ∈ {2, 3, 5, 10}
```

### Appendix B.3 — β

```bash
python eval_parameter_beta.py
```

Evaluated values:

```text
β ∈ {0.2, 0.4, 0.6, 0.8, 1.0}
```

### Appendix B.4 — RefSpeed

```bash
python eval_parameter_refspeed.py
```

Evaluated values:

```text
RefSpeed ∈ {5, 10, 20, 50, 100}
```

---

## Methods

The evaluation compares the following query-recovery attacks.

| Method | Segmenter / Model | Description |
|---|---|---|
| **THRESHOLD** | `TimeGapSegmenter(δ)` | Our session-based attack using time-gap session segmentation |
| **DENSITY** | `DBSCANSegmenter(eps, m)` | Our session-based attack using density-based session segmentation |
| **MAPLE** | `MarkovDecoding` | Frequency + Markov HMM baseline ([MAPLE, PoPETs 2024](https://doi.org/10.56553/popets-2024-0025)) |
| **IHOP** | `MarkovIHOP` | Hungarian-algorithm Markov baseline ([IHOP, USENIX Security 2022](https://doi.org/10.48550/arXiv.2110.04180)) |

---

## Attack Implementation

The session-based query recovery attack proposed in this paper is implemented in:

```text
leaker/attack/session_recovery.py
```

### Key Classes

| Class | Role |
|---|---|
| `SessionBasedRecovery` | Main attack: builds session co-occurrence information from auxiliary logs and progressively recovers victim query tokens |
| `TimeGapSegmenter` | Segments a query sequence into sessions according to a time-gap threshold δ |
| `DBSCANSegmenter` | Segments a query sequence into sessions using DBSCAN |

### `SessionBasedRecovery` Parameters

| Parameter | Default | Description |
|---|---|---|
| `segmenter` | `TimeGapSegmenter()` | Session segmentation strategy |
| `top_k` | `5` | Number of candidate keywords per token in Phase 3 |
| `beta` | `0.5` | Weight balancing frequency (`0`) and session co-occurrence (`1`) signals |
| `batch_size` | `10` | Number of tokens recovered per refinement pass (RefSpeed) |
| `dedup` | `True` | Whether to deduplicate keyword occurrences within a session |
| `cooc_version` | `2` | Co-occurrence weighting scheme (`2` = weighted, `1` = simple) |

The table above lists the implementation defaults.



Experiment-specific parameters are defined in the corresponding evaluation scripts.

---

## Expected Results

The evaluation scripts report the query recovery performance of the evaluated attacks under the corresponding experimental settings.

Because the experiments involve keyword sampling and other randomized components, individual runs may differ slightly from the exact values reported in the paper. However, the overall trends should remain consistent with the paper.

---

## Project Structure

```text
artifact/
├── README.md
├── requirements.txt
├── leaker/
│   ├── attack/
│   │   ├── session_recovery.py
│   │   │   └── session-based query recovery attack 
│   │   └── markov/
│   │       └── MarkovDecoding and MarkovIHOP baselines
│   └── whoosh_interface.py
│
├── evaluation/
│   └── keyword/
│       ├── eval_compare_other_user.py
│       ├── eval_compare_split_user.py
│       ├── eval_large_keyword.py
│       ├── eval_session-co_relation.py
│       ├── eval_parameter_session_threshold.py
│       ├── eval_parameter_min_samples.py
│       ├── eval_parameter_beta.py
│       ├── eval_parameter_refspeed.py
│       ├── index_tair_with_times.py
│       └── data/
│           ├── whoosh/
│           ├── pickle/
│           └── cache/
│
└── data_sources/
    ├── TAIR/
    └── Wikidata SPARQL Logs/
```

The directories under `evaluation/keyword/data/` are generated or populated automatically during preprocessing and evaluation.

---

## Acknowledgements

This artifact is built on the [LEAKER](https://github.com/encryptogroup/LEAKER) framework.

The `MarkovDecoding` and `MarkovIHOP` baselines build on the IHOP implementation by [Simon Oya](https://github.com/simon-oya/USENIX22-ihop-code).

We thank the authors of these projects for making their implementations publicly available.

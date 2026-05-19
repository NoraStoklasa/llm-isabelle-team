"""
get_magnus_sample.py — Stream a small sample from the MagnusData HuggingFace dataset.

WHAT IT DOES
------------
Streams the first N rows from the "Simontwice/premise_selection_in_isabelle"
HuggingFace dataset without downloading the full multi-GB corpus, then saves
them as a JSON array to datasets/magnusdata/sample_dataset.json (or a path
you specify with --out).

WHY WE SAMPLE
-------------
This is part of the 3806ICT Griffith University group assignment building an
LLM-powered theorem prover for Isabelle/HOL. The full MagnusData corpus is
several GB, which exceeds practical disk/bandwidth limits for assignment
development. A 10 000-row sample is enough to validate the pipeline and train
lightweight fine-tuning experiments without committing large binaries to git.

HOW TO RUN
----------
    # Default: first 10 000 rows → datasets/magnusdata/sample_dataset.json
    python datasets/get_magnus_sample.py

    # With a HuggingFace token (required if the dataset is gated or rate-limited)
    HF_TOKEN=hf_your_token_here python datasets/get_magnus_sample.py

    # Custom count and output path
    python datasets/get_magnus_sample.py --n 5000 --out /tmp/my_sample.json

    # Generate a read token at: https://huggingface.co/settings/tokens

DEPENDENCIES
------------
    pip install -U datasets

FALLBACK
--------
If streaming fails (network issues, HF outages, gated access), download one
parquet shard manually from:
  https://huggingface.co/datasets/Simontwice/premise_selection_in_isabelle/tree/main
Then load it locally with:
  import pandas as pd, json
  df = pd.read_parquet("train-00000-of-NNNNN.parquet")
  json.dump(df.to_dict(orient="records"), open("sample_dataset.json", "w"))
"""

import argparse
import json
import os
import sys

_FALLBACK_MSG = (
    "FALLBACK: download one parquet shard manually from\n"
    "  https://huggingface.co/datasets/Simontwice/premise_selection_in_isabelle/tree/main\n"
    "then convert it with:\n"
    "  import pandas as pd, json\n"
    "  df = pd.read_parquet('train-00000-of-NNNNN.parquet')\n"
    "  json.dump(df.to_dict(orient='records'), open('sample_dataset.json', 'w'))\n\n"
    "If the dataset is gated or rate-limited, set HF_TOKEN before running:\n"
    "  HF_TOKEN=hf_your_token_here python datasets/get_magnus_sample.py\n"
    "Generate a read token at: https://huggingface.co/settings/tokens"
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Stream a sample from MagnusData (Simontwice/premise_selection_in_isabelle)."
    )
    p.add_argument(
        "--n",
        type=int,
        default=10_000,
        metavar="N",
        help="Number of rows to sample (default: 10000).",
    )
    p.add_argument(
        "--out",
        default=os.path.join(
            os.path.dirname(__file__), "magnusdata", "sample_dataset.json"
        ),
        metavar="PATH",
        help="Output JSON file path (default: datasets/magnusdata/sample_dataset.json).",
    )
    return p.parse_args()


def stream_sample(n: int, out_path: str) -> None:
    try:
        from datasets import load_dataset
    except ImportError:
        print(
            "ERROR: the 'datasets' package is not installed.\n"
            "Run:  pip install -U datasets\n"
            "then retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    token = os.environ.get("HF_TOKEN") or None  # None → unauthenticated
    token_status = "set" if token else "not set"
    print(
        f"Streaming up to {n} rows from Simontwice/premise_selection_in_isabelle "
        f"(HF_TOKEN: {token_status}) …"
    )

    try:
        ds = load_dataset(
            "Simontwice/premise_selection_in_isabelle",
            split="train",
            streaming=True,
            trust_remote_code=False,
            token=token,
        )
    except Exception as exc:
        print(
            f"ERROR: could not open the streaming dataset: {exc}\n\n"
            + _FALLBACK_MSG,
            file=sys.stderr,
        )
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    rows = []
    try:
        for i, row in enumerate(ds):
            if i >= n:
                break
            rows.append(row)
            if (i + 1) % 1000 == 0:
                print(f"  … collected {i + 1} rows")
    except Exception as exc:
        print(
            f"ERROR: streaming interrupted after {len(rows)} rows: {exc}\n\n"
            + _FALLBACK_MSG,
            file=sys.stderr,
        )
        if not rows:
            sys.exit(1)
        print(f"Saving partial result ({len(rows)} rows) …")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"Done. Saved {len(rows)} rows → {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    args = parse_args()
    stream_sample(args.n, args.out)

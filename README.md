# market-history-etl

ETL for Polymarket market history: extract/slim by type/slug/flag, build per-tick indicator snapshots, condense training JSONL for audit, and scrape BTC up/down outcomes.

## Why it exists

The 5-minute crypto up/down trading engine records every market it watches into a large `market_history.jsonl` (full replay per market: tick array + event stream). That file is too big and too raw for research. This repo is the data-prep layer that slices it into focused subsets, compresses it into compact per-checkpoint feature snapshots, and independently scrapes settled outcomes from Polymarket — the inputs for strategy discovery and backtesting.

## What's inside

| Script | Purpose |
| --- | --- |
| `extract_markets.py` | Filter the big `market_history.jsonl` by `--type T1..T6` (classifier mirrors the bot's `_v5_classify_live`), `--slugs`, `--bn-flipped`, `--winner`, date range, `--limit`. Writes matching full records. |
| `extract_markets_slim.py` | Same filters, but strips heavy analysis blocks and downsamples ticks (`--downsample N`, default 3) for much smaller output. Keeps only what's needed to re-simulate fires. |
| `extract_one_market.py` | Dump one full market record (hardcoded slug `1777475400`) to `extracted_market.json` and print its schema/top-level keys — a quick structure probe. |
| `extract_market_snapshots.py` | Convert a directory of `replay_btc-updown-5m-*.json` into one compact `market_snapshots.jsonl` (schema v2): per-checkpoint buckets (T-200…T-5), velocity sub-features, settlement-aware peaks, pre-classification flags, and event markers. |
| `condense_training.py` | Audit any strategy training JSONL: print field summary + side/winner accuracy + PnL, flag unknown fields, and write a `*_condensed.jsonl` (first 5 + last 50 records, bulk tick arrays stripped). |
| `poly_outcome_collector.py` | Bulk-scrape settled UP/DN outcomes for `btc-updown-5m-*` markets over the last N days (threaded, checkpointed) into `polymarket_outcomes.json`. |
| `poly_daily_updater.py` | Daily incremental version of the collector: backfill gaps, then run Markov-3/Markov-4 sequence pattern analysis with z-scores. |

## Requirements

- Python 3.8+ (standard library only — `json`, `argparse`, `urllib`, `concurrent.futures`, `glob`). No third-party pip dependencies.
- The scrapers (`poly_outcome_collector.py`, `poly_daily_updater.py`) need outbound HTTPS access to `polymarket.com`.
- No wallet, private key, or CLOB credentials — these scripts never trade or touch funds.

## Usage

```bash
# Extract all T6 markets from the big history file
python3 extract_markets.py /path/to/market_history.jsonl T6.jsonl --type T6

# Slim + downsample a bn-flip candidate subset (smaller output)
python3 extract_markets_slim.py /path/to/market_history.jsonl bnflip.jsonl --bn-flipped --limit 50

# Build compact v2 snapshots from a directory of replay files
python3 extract_market_snapshots.py /path/to/replay_dir/ -o market_snapshots.jsonl

# Audit a training JSONL (prints stats, writes *_condensed.jsonl)
python3 condense_training.py btc_snipe_training.jsonl

# Scrape the last 7 days of settled outcomes
python3 poly_outcome_collector.py 7
```

## Data

Every script reads or writes `.json`/`.jsonl`. Inputs (`market_history.jsonl`, `replay_*.json`, training JSONLs) are **not** included here — they live in the private `polymarket-data` repo and are referenced by path on the VPS (e.g. `/home/polybot/polymarket-bot/data/market_history.jsonl`). Point the path arguments at your local checkout of that data. `.gitignore` excludes all `*.json*`/`*.csv`/`*.parquet` so no dataset is ever committed.

> Private research software. No warranty; use at your own risk.

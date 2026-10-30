# market-history-etl

Data-prep scripts for the 5-minute crypto up/down trading engine: slice the big `market_history.jsonl`, build compact per-checkpoint feature snapshots, condense training JSONL for audit, and scrape settled BTC up/down outcomes.

Inputs are the engine's `market_history.jsonl` (full per-market replay: tick array plus event stream) and directories of `replay_btc-updown-5m-*.json`. Outputs feed strategy discovery and backtesting.

## Scripts

- `extract_markets.py`: filter `market_history.jsonl` by `--type T1..T6` (classifier mirrors the bot's `_v5_classify_live`), `--slugs`, `--bn-flipped`, `--winner`, `--after`/`--before`, `--limit`. Writes matching full records.
- `extract_markets_slim.py`: same filters, but strips heavy analysis blocks and downsamples ticks (`--downsample N`, default 3). Keeps slug, winner, ts, `market_wide`, `ticks`, `tick_columns`. Much smaller output.
- `extract_one_market.py`: dump one full record (hardcoded slug `1777475400`) to `extracted_market.json` and print its top-level keys. Structure probe.
- `extract_market_snapshots.py`: convert a directory of `replay_btc-updown-5m-*.json` into one `market_snapshots.jsonl` (schema v2): per-checkpoint buckets (T-200 to T-5), velocity sub-features, settlement-aware peaks, pre-classification flags, event markers. v2 is backward-compatible with v1 readers.
- `condense_training.py`: audit a training JSONL. Prints field summary, side/winner accuracy, PnL, and unknown-field flags. Writes `<input>_condensed.jsonl` (first 5 plus last 50 records, bulk tick arrays stripped).
- `poly_outcome_collector.py`: threaded, checkpointed scrape of settled UP/DN outcomes for `btc-updown-5m-*` markets over the last N days. Writes `polymarket_outcomes.json`.
- `poly_daily_updater.py`: daily incremental collector. Backfills gaps, then runs Markov-3/Markov-4 sequence analysis with z-scores.

## Usage

```bash
# Extract all T6 markets from the big history file
python3 extract_markets.py $DATA_DIR/market_history.jsonl T6.jsonl --type T6

# Slim + downsample a bn-flip candidate subset
python3 extract_markets_slim.py $DATA_DIR/market_history.jsonl bnflip.jsonl --bn-flipped --limit 50

# Build v2 snapshots from a directory of replay files
python3 extract_market_snapshots.py $DATA_DIR/replay_dir/ market_snapshots.jsonl

# Audit a training JSONL (writes *_condensed.jsonl)
python3 condense_training.py btc_snipe_training.jsonl

# Scrape the last 7 days of settled outcomes
python3 poly_outcome_collector.py 7
```

## Requirements

Python 3.8+, standard library only (`json`, `argparse`, `urllib`, `concurrent.futures`, `glob`). The scrapers need outbound HTTPS to `polymarket.com`. No wallet, key, or CLOB credentials; these scripts never trade or touch funds.

## Data

Datasets are not included. Point path arguments at your local checkout of the private `polymarket-data` repo (e.g. `$DATA_DIR/market_history.jsonl`). `.gitignore` excludes `*.json*`, `*.csv`, `*.parquet`, so no dataset is committed.

## Feedback

Suggestions, improvements, or something not working? Please
[open an issue](https://github.com/needmoneyforhoes/market-history-etl/issues/new). Pull requests are welcome too.

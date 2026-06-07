#!/usr/bin/env python3
"""
Extract + SLIM markets from the big market_history.jsonl.

Strips heavy fields we don't need for strategy analysis (keeps only what matters
for simulating fires at various cds).

USAGE:
    python3 extract_markets_slim.py INPUT OUTPUT --type T6
    python3 extract_markets_slim.py INPUT OUTPUT --bn-flipped --limit 50

Slim keeps:
    - slug, winner, ts
    - market_wide (classification stats)
    - ticks (compacted to reduce size)
    - tick_columns

Slim removes:
    - entry_analysis, volatility_profile, depth_profile, hedge_analysis
    - counterfactuals, bn_correlation, collapse_analysis
    - trade_tape, rolling stats, sim_vs_live_slippage
    - fill_shares/fill_cd/fill_price (bot-run info, not market structure)
"""
import sys, json, argparse

SLIM_KEEP_KEYS = {
    "slug", "winner", "ts",
    "settle_price", "window_open_price", "bn_delta_final",
    "tick_columns", "ticks",
    "market_wide",
    "hour_utc", "day_of_week",
}

def classify_market(mw, bn_start, bn_end):
    if not mw: return "unknown"
    lc = mw.get('lead_changes', 0)
    flipped = mw.get('bn_flipped_sign', False)
    bn_mag = max(abs(bn_start or 0), abs(bn_end or 0))
    if lc >= 4: return "T4"
    if lc == 0 and not flipped:
        return "T1" if bn_mag > 0.02 else "T6"
    if lc == 0 and flipped: return "T6"
    if 1 <= lc <= 3 and not flipped: return "T2"
    if 1 <= lc <= 3 and flipped: return "T3"
    return "unknown"

def slim_record(rec, downsample=None):
    """Return trimmed version keeping only fields we need."""
    out = {k: rec[k] for k in SLIM_KEEP_KEYS if k in rec}

    # Optionally downsample ticks (every Nth tick) to reduce size
    if downsample and "ticks" in out and out["ticks"]:
        out["ticks"] = out["ticks"][::downsample]

    return out

def matches_filter(rec, args):
    if args.slugs and rec.get('slug') not in args.slugs:
        return False
    if args.type:
        mw = rec.get('market_wide', {})
        mt = classify_market(mw, mw.get('bn_delta_start'), mw.get('bn_delta_end'))
        if mt not in args.type:
            return False
    if args.bn_flipped:
        mw = rec.get('market_wide', {})
        if not mw.get('bn_flipped_sign'):
            return False
    if args.winner and rec.get('winner') not in args.winner:
        return False
    return True

def main():
    parser = argparse.ArgumentParser(
        description="Slim-extract markets (smaller output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--slugs", nargs="+")
    parser.add_argument("--type", nargs="+",
                        choices=["T1","T2","T3","T4","T5","T6","unknown"])
    parser.add_argument("--bn-flipped", action="store_true")
    parser.add_argument("--winner", nargs="+", choices=["UP","DN"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--downsample", type=int, default=3,
                        help="Keep every Nth tick (default 3 = ~3x smaller ticks)")
    args = parser.parse_args()

    if not any([args.slugs, args.type, args.bn_flipped, args.winner]):
        print("ERROR: Need at least one filter.", file=sys.stderr)
        sys.exit(1)

    if args.slugs:
        args.slugs = set(args.slugs)

    extracted = 0
    type_counts = {}
    scanned = 0

    with open(args.input) as fin, open(args.output, "w") as fout:
        for line in fin:
            if not line.strip(): continue
            scanned += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue

            if matches_filter(rec, args):
                slim = slim_record(rec, downsample=args.downsample)
                fout.write(json.dumps(slim, separators=(",", ":")) + "\n")
                extracted += 1

                mw = rec.get('market_wide', {})
                mt = classify_market(mw, mw.get('bn_delta_start'), mw.get('bn_delta_end'))
                type_counts[mt] = type_counts.get(mt, 0) + 1

                if scanned % 500 == 0:
                    print(f"  scanned {scanned}, extracted {extracted}...", file=sys.stderr)

                if args.limit and extracted >= args.limit:
                    break

    print(f"\nDONE. Scanned: {scanned}, Extracted: {extracted} → {args.output}",
          file=sys.stderr)
    if type_counts:
        print(f"By type:", file=sys.stderr)
        for mt, n in sorted(type_counts.items()):
            print(f"  {mt}: {n}", file=sys.stderr)

    # Report file size
    import os
    size_mb = os.path.getsize(args.output) / (1024*1024)
    print(f"Output size: {size_mb:.1f} MB", file=sys.stderr)

if __name__ == "__main__":
    main()

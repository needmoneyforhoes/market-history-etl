#!/usr/bin/env python3
"""
Extract specific markets from the big market_history.jsonl file.

USAGE EXAMPLES (run on VPS where market_history.jsonl lives):

# 1. Extract all T6 markets (uses same classifier as live bot)
python3 extract_markets.py /home/polybot/polymarket-bot/market_history.jsonl T6.jsonl --type T6

# 2. Extract specific markets by slug
python3 extract_markets.py /home/polybot/polymarket-bot/market_history.jsonl subset.jsonl \
    --slugs btc-updown-5m-1776508500 btc-updown-5m-1776509700

# 3. Extract with limit (just first 20 T6 markets)
python3 extract_markets.py /home/polybot/polymarket-bot/market_history.jsonl T6_sample.jsonl \
    --type T6 --limit 20

# 4. Extract multiple types
python3 extract_markets.py /home/polybot/polymarket-bot/market_history.jsonl mixed.jsonl \
    --type T3 T6 --limit 30

# 5. Extract markets where bn_flipped=True (bn_flip candidates)
python3 extract_markets.py /home/polybot/polymarket-bot/market_history.jsonl bnflip_cands.jsonl \
    --bn-flipped --limit 50

# 6. Extract T6 markets where bn_flipped=True
python3 extract_markets.py /home/polybot/polymarket-bot/market_history.jsonl t6_bnflip.jsonl \
    --type T6 --bn-flipped
"""
import sys, json, argparse

def classify_market(mw, bn_start, bn_end):
    """Classify as T1/T2/T3/T4/T6 using final state. Mirrors bot's _v5_classify_live."""
    if not mw:
        return "unknown"
    lc = mw.get('lead_changes', 0)
    flipped = mw.get('bn_flipped_sign', False)
    bn_mag = max(abs(bn_start or 0), abs(bn_end or 0))

    if lc >= 4:
        return "T4"
    if lc == 0 and not flipped:
        return "T1" if bn_mag > 0.02 else "T6"
    if lc == 0 and flipped:
        return "T6"
    if 1 <= lc <= 3 and not flipped:
        return "T2"
    if 1 <= lc <= 3 and flipped:
        return "T3"
    return "unknown"

def matches_filter(rec, args):
    """True if record matches extraction filters."""
    if args.slugs:
        if rec.get('slug') not in args.slugs:
            return False

    if args.type:
        mw = rec.get('market_wide', {})
        mtype = classify_market(mw, mw.get('bn_delta_start'), mw.get('bn_delta_end'))
        if mtype not in args.type:
            return False

    if args.bn_flipped:
        mw = rec.get('market_wide', {})
        if not mw.get('bn_flipped_sign'):
            return False

    if args.winner:
        if rec.get('winner') not in args.winner:
            return False

    if args.after or args.before:
        ts = rec.get('ts', '')
        if args.after and ts < args.after:
            return False
        if args.before and ts > args.before:
            return False

    return True

def main():
    parser = argparse.ArgumentParser(
        description="Extract markets from big jsonl history file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="Input jsonl file path")
    parser.add_argument("output", help="Output jsonl file path")
    parser.add_argument("--slugs", nargs="+", help="Specific slug(s) to extract")
    parser.add_argument("--type", nargs="+",
                        choices=["T1","T2","T3","T4","T5","T6","unknown"],
                        help="Market type(s) to extract")
    parser.add_argument("--bn-flipped", action="store_true",
                        help="Only markets where bn_flipped_sign=True (bn_flip candidates)")
    parser.add_argument("--winner", nargs="+", choices=["UP","DN"],
                        help="Filter by winner")
    parser.add_argument("--after", help="Only markets with ts >= this")
    parser.add_argument("--before", help="Only markets with ts <= this")
    parser.add_argument("--limit", type=int, help="Max records to extract")
    args = parser.parse_args()

    if not any([args.slugs, args.type, args.bn_flipped, args.winner, args.after, args.before]):
        print("ERROR: Need at least one filter. See --help.", file=sys.stderr)
        sys.exit(1)

    if args.slugs:
        args.slugs = set(args.slugs)

    type_counts = {}
    total_scanned = 0
    extracted = 0

    with open(args.input) as fin, open(args.output, "w") as fout:
        for line in fin:
            if not line.strip():
                continue
            total_scanned += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue

            if matches_filter(rec, args):
                fout.write(line)
                extracted += 1

                mw = rec.get('market_wide', {})
                mt = classify_market(mw, mw.get('bn_delta_start'), mw.get('bn_delta_end'))
                type_counts[mt] = type_counts.get(mt, 0) + 1

                if total_scanned % 500 == 0:
                    print(f"  scanned {total_scanned}, extracted {extracted}...", file=sys.stderr)

                if args.limit and extracted >= args.limit:
                    break

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"DONE", file=sys.stderr)
    print(f"Scanned: {total_scanned}", file=sys.stderr)
    print(f"Extracted: {extracted} → {args.output}", file=sys.stderr)
    if type_counts:
        print(f"By type:", file=sys.stderr)
        for mt, n in sorted(type_counts.items()):
            print(f"  {mt}: {n}", file=sys.stderr)

if __name__ == "__main__":
    main()

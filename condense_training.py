#!/usr/bin/env python3
"""
Condense any strategy training JSONL file for audit.
Keeps all fields, strips bulk (ticks arrays), saves first 5 + last 50 records.

Usage:
  python3 condense_training.py <input_file> [output_file]

Examples:
  python3 condense_training.py btc_snipe_training.jsonl
  python3 condense_training.py v1b_training_btc.jsonl v1b_condensed.jsonl
  python3 condense_training.py depth_winner_training.jsonl

Output: <input>_condensed.jsonl (or specified output path)
Also prints field summary, accuracy stats, and unique field check to terminal.
"""

import json, sys, os
from collections import Counter

def condense(input_file, output_file=None):
    if not output_file:
        base = os.path.splitext(input_file)[0]
        output_file = f"{base}_condensed.jsonl"

    # Load all records
    records = []
    with open(input_file) as f:
        for line in f:
            try:
                records.append(json.loads(line.strip()))
            except:
                pass

    print(f"{'='*70}")
    print(f"TRAINING FILE AUDIT: {input_file}")
    print(f"{'='*70}")
    print(f"Total records: {len(records)}")
    print(f"File size: {os.path.getsize(input_file) / 1024 / 1024:.1f} MB")

    if not records:
        print("  EMPTY FILE — nothing to condense")
        return

    # ── Field summary ──
    print(f"\n{'─'*70}")
    print(f"ALL FIELDS ({len(records[0].keys())}):")
    print(f"{'─'*70}")
    for k in sorted(records[0].keys()):
        vals = [r.get(k) for r in records if r.get(k) is not None]
        if not vals:
            print(f"  {k}: all None")
            continue
        if isinstance(vals[0], (int, float)):
            print(f"  {k}: min={min(vals):.6f} max={max(vals):.6f} "
                  f"mean={sum(vals)/len(vals):.6f} N={len(vals)}")
        elif isinstance(vals[0], str):
            c = Counter(vals)
            print(f"  {k}: {dict(c.most_common(5))}")
        elif isinstance(vals[0], list):
            print(f"  {k}: list, avg_len={sum(len(v) for v in vals)/len(vals):.1f}")
        elif isinstance(vals[0], dict):
            print(f"  {k}: dict, keys={sorted(vals[0].keys())[:8]}")
        elif isinstance(vals[0], bool):
            trues = sum(1 for v in vals if v)
            print(f"  {k}: True={trues} False={len(vals)-trues}")

    # ── Accuracy (auto-detect field names) ──
    print(f"\n{'─'*70}")
    print("ACCURACY:")
    print(f"{'─'*70}")

    # Find winner field
    winner_field = None
    for f in ["actual_winner", "winner", "outcome"]:
        if any(r.get(f) for r in records):
            winner_field = f
            break

    # Find side field
    side_field = None
    for f in ["fired_side", "side", "entry_crowd_side", "signal_side"]:
        if any(r.get(f) for r in records):
            side_field = f
            break

    # Find fired field
    fired_field = None
    for f in ["signal_fired", "fired", "fill_yn", "ever_filled"]:
        if any(r.get(f) for r in records):
            fired_field = f
            break

    if winner_field and side_field:
        fired_recs = [r for r in records if r.get(fired_field)]
        with_outcome = [r for r in fired_recs if r.get(winner_field)]
        if with_outcome:
            correct = sum(1 for r in with_outcome if r[side_field] == r[winner_field])
            wrong = len(with_outcome) - correct
            print(f"  Side field: {side_field} | Winner field: {winner_field}")
            print(f"  Correct: {correct}/{len(with_outcome)} = {correct/len(with_outcome)*100:.1f}%")
            print(f"  Wrong:   {wrong}/{len(with_outcome)} = {wrong/len(with_outcome)*100:.1f}%")

            # Flip check
            print(f"  Flipped: {wrong}/{len(with_outcome)} = {wrong/len(with_outcome)*100:.1f}% "
                  f"(if we bet opposite)")
        else:
            print(f"  No records with both {side_field} and {winner_field}")
    else:
        print(f"  Could not auto-detect side/winner fields")

    # ── PnL if available ──
    pnl_field = None
    for f in ["pnl_gross", "pnl_realized", "pnl", "pnl_net"]:
        vals = [r.get(f) for r in records if r.get(f) is not None and r.get(f) != 0]
        if vals:
            pnl_field = f
            break

    if pnl_field:
        pnl_vals = [r[pnl_field] for r in records if r.get(pnl_field) is not None]
        print(f"\n  PnL ({pnl_field}): sum=${sum(pnl_vals):+.4f} "
              f"mean=${sum(pnl_vals)/len(pnl_vals):+.4f} N={len(pnl_vals)}")

    # ── Fields NOT in replay ticks (unique check) ──
    print(f"\n{'─'*70}")
    print("UNIQUE FIELD CHECK (vs replay ticks + event_stream):")
    print(f"{'─'*70}")

    # Known replay/metadata fields
    known = {
        "slug", "ts", "version", "asset",
        "actual_winner", "winner", "outcome",
        "signal_fired", "fired", "fill_yn", "ever_filled",
        "fired_side", "side", "entry_crowd_side", "signal_side",
        "fill_price", "entry_price", "limit_price", "tok_px", "tok_ask",
        "pnl_gross", "pnl_realized", "pnl", "pnl_net",
        "live_order", "gtc_filled", "gtc_fill_price", "gtc_fill_size",
        "direction_correct", "correct", "filled",
        # Replay tick equivalents
        "entry_secs_left", "secs", "secs_left", "fired_secs",
        "entry_conviction", "entry_velocity",
        "entry_sr_winner", "entry_sr_loser",
        "entry_loser_ask", "entry_loser_depth", "entry_winner_depth",
        "entry_depth_asymmetry",
        "entry_loser_depth_velocity", "entry_winner_depth_velocity",
        "entry_loser_zc", "entry_winner_zc",
        "both_sides_collapsing",
        "loser_max_bid_after_entry",
        "sim_targets",
        # Snipe-specific (already audited)
        "fired_delta", "fired_side", "fired_secs",
        "window_open", "settle_price", "entry_type",
        "ticks", "n_ticks", "first_tick", "last_tick",
        # BN/CL data
        "delta_bn", "delta_cl", "bn_d3s", "bn_d10", "bn_d30",
        "bn_spread", "cl_age",
    }

    actual = set(records[0].keys())
    unknown = actual - known
    if unknown:
        print(f"  ⚠️ FIELDS NOT IN KNOWN LIST — NEED INVESTIGATION:")
        for f in sorted(unknown):
            vals = [r.get(f) for r in records if r.get(f) is not None]
            if vals and isinstance(vals[0], (int, float)):
                print(f"    {f}: {type(vals[0]).__name__} min={min(vals):.4f} max={max(vals):.4f}")
            elif vals:
                print(f"    {f}: {type(vals[0]).__name__} sample={str(vals[0])[:80]}")
            else:
                print(f"    {f}: all None")
    else:
        print(f"  ✅ All {len(actual)} fields accounted for")

    # ── Write condensed file ──
    out = []
    for r in records[:5] + records[-50:]:
        condensed = {}
        for k, v in r.items():
            if k == "ticks" and isinstance(v, list):
                condensed["n_ticks"] = len(v)
                if v:
                    condensed["first_tick"] = v[0]
                    condensed["last_tick"] = v[-1]
            elif isinstance(v, list) and len(v) > 100:
                condensed[k] = f"[{len(v)} items]"
            else:
                condensed[k] = v
        out.append(condensed)

    with open(output_file, "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")

    print(f"\n{'='*70}")
    print(f"Wrote {output_file} ({len(out)} records, "
          f"{os.path.getsize(output_file)/1024:.1f} KB)")
    print(f"Upload this file for deep audit.")
    print(f"{'='*70}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 condense_training.py <input.jsonl> [output.jsonl]")
        sys.exit(1)
    condense(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

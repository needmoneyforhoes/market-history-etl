#!/usr/bin/env python3
"""
Extract per-tick indicator snapshots from full replay files into compact JSONL.

v2 FORMAT CHANGES (Apr 17, 2026):
  - Added settlement-aware peaks (`settle` block)
  - Added per-bucket velocity features (`v` sub-object in each bucket)
  - Added pre-classification flags (`class` block)
  - Added event markers (`events` block)
  - Added finer buckets: T-45, T-20, T-10, T-5 (for flip dynamics)
  - Schema version: `v`=2 at top-level

v2 is fully backward-compatible: all v1 fields preserved.
Old readers that don't know about `v`, `settle`, `class`, `events` ignore them.

INPUT:
  Directory of replay_btc-updown-5m-*.json files (one per market).

OUTPUT:
  Single file: market_snapshots.jsonl

USAGE:
  python3 extract_market_snapshots.py /path/to/replay/dir /path/to/output.jsonl
  python3 extract_market_snapshots.py --help
"""

import json
import os
import sys
import glob
import argparse
from pathlib import Path

# Checkpoint times (seconds remaining). v2 adds finer buckets in T-60 to T-0.
# v1: [200, 150, 120, 105, 90, 75, 60, 30]
# v2: adds 45, 20, 10, 5
CHECKPOINTS = [200, 150, 120, 105, 90, 75, 60, 45, 30, 20, 10, 5]

# Tolerance when matching ticks to checkpoints (seconds)
CHECKPOINT_TOLERANCE = 3.0

# Schema version written into each record
SCHEMA_VERSION = 2


def tick_to_dict(tick_row, columns):
    """Convert a tick row (list) into a dict using tick_columns as keys."""
    if not tick_row or len(tick_row) != len(columns):
        return None
    return dict(zip(columns, tick_row))


def find_tick_at(ticks, columns, target_cd):
    """Find the tick closest to target_cd. Returns dict or None if no tick within tolerance."""
    if not ticks:
        return None
    cd_idx = columns.index('cd')
    best = None
    best_diff = float('inf')
    for t in ticks:
        if not t or len(t) <= cd_idx:
            continue
        cd = t[cd_idx]
        if cd is None:
            continue
        diff = abs(cd - target_cd)
        if diff < best_diff:
            best_diff = diff
            best = t
    if best is None or best_diff > CHECKPOINT_TOLERANCE:
        return None
    return tick_to_dict(best, columns)


def compute_trade_counts(event_stream, cd_lo, cd_hi):
    """Count buys on cheap vs expensive side within (cd_lo, cd_hi] time window."""
    cheap_count = exp_count = 0
    cheap_size = exp_size = 0.0
    for e in event_stream:
        if e.get('ev') != 't':
            continue
        cd = e.get('cd')
        if cd is None or not (cd_lo < cd <= cd_hi):
            continue
        if e.get('s') != 'BUY':
            continue
        p = e.get('p', 0) or 0
        sz = e.get('sz', 0) or 0
        if p < 0.40:
            cheap_count += 1
            cheap_size += sz
        elif p > 0.60:
            exp_count += 1
            exp_size += sz
    return cheap_count, exp_count, round(cheap_size, 2), round(exp_size, 2)


def time_near_5050(ticks, columns, threshold=0.55):
    """Seconds spent with max(up_bid, dn_bid) < threshold."""
    try:
        ub_idx = columns.index('up_bid')
        db_idx = columns.index('dn_bid')
    except ValueError:
        return None
    count = 0
    for t in ticks:
        if not t or len(t) <= max(ub_idx, db_idx):
            continue
        ub = t[ub_idx] or 0
        db = t[db_idx] or 0
        if max(ub, db) < threshold:
            count += 1
    return count


def lead_changes_up_to(ticks, columns, cd_cutoff):
    """Count leader (UP vs DN) flips up to and including the tick at cd_cutoff."""
    try:
        cd_idx = columns.index('cd')
        ub_idx = columns.index('up_bid')
        db_idx = columns.index('dn_bid')
        bn_idx = columns.index('bn_delta_pct')
    except ValueError:
        return None, None
    prev_leader = None
    lead_changes = 0
    bn_first_sign = None
    bn_flipped = False
    for t in ticks:
        if not t or len(t) <= max(cd_idx, ub_idx, db_idx, bn_idx):
            continue
        cd = t[cd_idx]
        if cd is None or cd < cd_cutoff:
            continue
        ub = t[ub_idx] or 0
        db = t[db_idx] or 0
        leader = 'UP' if ub > db else ('DN' if db > ub else prev_leader)
        if leader and prev_leader is not None and leader != prev_leader:
            lead_changes += 1
        if leader:
            prev_leader = leader
        bn = t[bn_idx]
        if bn is not None and bn != 0:
            sign = 1 if bn > 0 else -1
            if bn_first_sign is None:
                bn_first_sign = sign
            elif sign != bn_first_sign:
                bn_flipped = True
    return lead_changes, bn_flipped


def extract_bucket_features(ticks, columns, target_cd, events_before_cd, event_cd_floor):
    """Extract v1 features at the given checkpoint."""
    tick = find_tick_at(ticks, columns, target_cd)
    if tick is None:
        return None

    cs_raw = tick.get('crowd_side')
    if cs_raw == 1:
        cs_decoded = 'UP'
    elif cs_raw == -1:
        cs_decoded = 'DN'
    else:
        cs_decoded = None

    f = {
        'cd':     round(tick['cd'], 1),
        'ub':     round(tick.get('up_bid', 0) or 0, 4),
        'ua':     round(tick.get('up_ask', 0) or 0, 4),
        'db':     round(tick.get('dn_bid', 0) or 0, 4),
        'da':     round(tick.get('dn_ask', 0) or 0, 4),
        'ud':     round(tick.get('up_depth', 0) or 0, 1),
        'dd':     round(tick.get('dn_depth', 0) or 0, 1),
        'uzc':    round(tick.get('up_zc', 0) or 0, 2),
        'dzc':    round(tick.get('dn_zc', 0) or 0, 2),
        'usr':    round(tick.get('up_sr', 0) or 0, 2),
        'dsr':    round(tick.get('dn_sr', 0) or 0, 2),
        'bn_d':   round(tick.get('bn_delta_pct', 0) or 0, 4),
        'cs':     cs_decoded,
        'cv':     round(tick.get('crowd_conviction', 0) or 0, 3),
        'dvu':    round(tick.get('depth_velocity_up', 0) or 0, 2),
        'dvd':    round(tick.get('depth_velocity_dn', 0) or 0, 2),
        'asum':   round(tick.get('ask_sum', 0) or 0, 3),
    }
    cheap_n, exp_n, cheap_sz, exp_sz = compute_trade_counts(events_before_cd, target_cd, event_cd_floor)
    f['tcn'] = cheap_n
    f['ten'] = exp_n
    f['tcs'] = cheap_sz
    f['tes'] = exp_sz
    f['trat'] = round(cheap_n / max(1, exp_n), 3)
    return f


def compute_velocity_features(buckets, tk_order):
    """
    v2 NEW: Add `v` sub-object to each bucket with pre-computed velocity/ratio features.
    For bucket at index i, compute deltas vs i-1, i-2, i-3 (and ratios vs i-1).

    Modifies buckets in place. First bucket has no `v` (no prior).
    """
    ordered_tks = [tk for tk in tk_order if tk in buckets]
    for i, tk in enumerate(ordered_tks):
        if i == 0:
            continue  # first bucket: no previous
        b = buckets[tk]
        b1 = buckets[ordered_tks[i - 1]]
        b2 = buckets[ordered_tks[i - 2]] if i >= 2 else None
        b3 = buckets[ordered_tks[i - 3]] if i >= 3 else None

        v = {}
        # 1-bucket velocities (deltas + ratios)
        for field, out_delta, out_ratio in [
            ('ua', 'v1_ua', 'r_ua'),
            ('da', 'v1_da', 'r_da'),
            ('ub', 'v1_ub', None),
            ('db', 'v1_db', None),
            ('cv', 'v1_cv', None),
            ('ud', 'v1_ud', 'r_ud'),
            ('dd', 'v1_dd', 'r_dd'),
        ]:
            cur = b.get(field, 0) or 0
            prev = b1.get(field, 0) or 0
            v[out_delta] = round(cur - prev, 4)
            if out_ratio is not None:
                v[out_ratio] = round(cur / prev, 3) if prev not in (0, None) else 1.0

        # bn_d signed + absolute
        cur_bn = b.get('bn_d', 0) or 0
        prev_bn = b1.get('bn_d', 0) or 0
        v['v1_bn_d']   = round(cur_bn - prev_bn, 4)
        v['v1_bn_abs'] = round(abs(cur_bn - prev_bn), 4)

        # 2-bucket deltas
        if b2 is not None:
            for field, out_name in [('cv', 'v2_cv'), ('ud', 'v2_ud'), ('dd', 'v2_dd')]:
                v[out_name] = round((b.get(field, 0) or 0) - (b2.get(field, 0) or 0), 4)

        # 3-bucket deltas
        if b3 is not None:
            for field, out_name in [('cv', 'v3_cv')]:
                v[out_name] = round((b.get(field, 0) or 0) - (b3.get(field, 0) or 0), 4)

        b['v'] = v


def compute_settle(buckets, winner):
    """v2 NEW: Settlement-aware peak computation."""
    up_final = 1.00 if winner == 'UP' else 0.00
    dn_final = 1.00 if winner == 'DN' else 0.00
    ua_vals = [b.get('ua', 0) or 0 for b in buckets.values() if b.get('ua') is not None]
    da_vals = [b.get('da', 0) or 0 for b in buckets.values() if b.get('da') is not None]
    peak_up = max(ua_vals) if ua_vals else up_final
    peak_dn = max(da_vals) if da_vals else dn_final
    return {
        'winner': winner,
        'up_final_val': up_final,
        'dn_final_val': dn_final,
        'up_peak_incl_settle': round(max(peak_up, up_final), 4),
        'dn_peak_incl_settle': round(max(peak_dn, dn_final), 4),
    }


def compute_classification(buckets, winner, tk_order):
    """v2 NEW: Pre-classification flags for fast filtering."""
    # Flipped across 50/50
    flipped = False
    prev_leader = None
    for tk in tk_order:
        b = buckets.get(tk)
        if not b:
            continue
        ub = b.get('ub', 0) or 0
        db = b.get('db', 0) or 0
        if ub == db:
            continue
        lead = 'UP' if ub > db else 'DN'
        if prev_leader and lead != prev_leader:
            flipped = True
        prev_leader = lead

    # Cheap min asks
    cheap_min_up = 1.0; cheap_min_up_tk = None
    cheap_min_dn = 1.0; cheap_min_dn_tk = None
    for tk in tk_order:
        b = buckets.get(tk)
        if not b:
            continue
        ua = b.get('ua', 0) or 0
        da = b.get('da', 0) or 0
        if 0 < ua < cheap_min_up:
            cheap_min_up = ua
            cheap_min_up_tk = tk
        if 0 < da < cheap_min_dn:
            cheap_min_dn = da
            cheap_min_dn_tk = tk

    # Cheap side won?
    cheap_side = None
    cheap_min = 1.0
    if cheap_min_up < cheap_min_dn:
        cheap_side = 'UP'; cheap_min = cheap_min_up
    elif cheap_min_dn < cheap_min_up:
        cheap_side = 'DN'; cheap_min = cheap_min_dn
    cheap_won = (winner == cheap_side) and (cheap_min < 0.40)

    return {
        'flipped_across_50': flipped,
        'cheap_side_won': cheap_won,
        'cheap_side_winner': cheap_side if cheap_won else None,
        'cheap_min_ask_up': round(cheap_min_up, 4),
        'cheap_min_ask_dn': round(cheap_min_dn, 4),
        'cheap_min_tk_up': cheap_min_up_tk,
        'cheap_min_tk_dn': cheap_min_dn_tk,
    }


def compute_events(buckets, tk_order):
    """v2 NEW: Event markers — first/last occurrences of key dynamics."""
    ev = {}
    ordered_tks = [tk for tk in tk_order if tk in buckets]

    # BN flip moment (across sign)
    first_bn_sign = None
    for tk in ordered_tks:
        b = buckets[tk]
        bn = b.get('bn_d')
        if bn is None or bn == 0:
            continue
        sign = 1 if bn > 0 else -1
        if first_bn_sign is None:
            first_bn_sign = sign
        elif sign != first_bn_sign and 'bn_flip_tk' not in ev:
            ev['bn_flip_tk'] = tk
            ev['bn_flip_mag'] = round(abs(bn), 4)
            break

    # cv crossings
    for tk in ordered_tks:
        cv = buckets[tk].get('cv', 0) or 0
        if cv >= 0.90 and 'first_cv_ge_90_tk' not in ev:
            ev['first_cv_ge_90_tk'] = tk
        if cv >= 0.95 and 'first_cv_ge_95_tk' not in ev:
            ev['first_cv_ge_95_tk'] = tk
        if cv >= 0.98 and 'first_cv_ge_98_tk' not in ev:
            ev['first_cv_ge_98_tk'] = tk

    # last ask <= $0.05 per side
    last_cheap_up = None
    last_cheap_dn = None
    for tk in ordered_tks:
        b = buckets[tk]
        if 0 < (b.get('ua') or 0) <= 0.05:
            last_cheap_up = tk
        if 0 < (b.get('da') or 0) <= 0.05:
            last_cheap_dn = tk
    ev['last_ask_le_05_up_tk'] = last_cheap_up
    ev['last_ask_le_05_dn_tk'] = last_cheap_dn

    # max udp / ddp
    max_ud = -1; max_ud_tk = None
    max_dd = -1; max_dd_tk = None
    for tk in ordered_tks:
        b = buckets[tk]
        ud = b.get('ud', 0) or 0
        dd = b.get('dd', 0) or 0
        if ud > max_ud:
            max_ud = ud; max_ud_tk = tk
        if dd > max_dd:
            max_dd = dd; max_dd_tk = tk
    ev['max_udp_tk'] = max_ud_tk
    ev['max_ddp_tk'] = max_dd_tk

    # first fdp drop 30%+ (r_dd <= 0.7 for UP side; r_ud <= 0.7 for DN side)
    first_fdp_drop_up = None
    first_fdp_drop_dn = None
    for tk in ordered_tks:
        b = buckets[tk]
        v = b.get('v') or {}
        # UP-side fdp = dd (opposing depth). UP's fdp drop is when r_dd <= 0.7.
        if 'r_dd' in v and v['r_dd'] <= 0.7 and first_fdp_drop_up is None:
            first_fdp_drop_up = tk
        if 'r_ud' in v and v['r_ud'] <= 0.7 and first_fdp_drop_dn is None:
            first_fdp_drop_dn = tk
    ev['first_fdp_drop_30pct_up_tk'] = first_fdp_drop_up
    ev['first_fdp_drop_30pct_dn_tk'] = first_fdp_drop_dn

    return ev


def extract_market(filepath):
    """Extract compact snapshot record from a full replay file (v2 format)."""
    try:
        with open(filepath) as fp:
            m = json.load(fp)
    except Exception as e:
        return {'slug': os.path.basename(filepath), 'error': f'load_fail: {e}'}

    slug = m.get('slug', os.path.basename(filepath).replace('.json', '').replace('replay_', ''))
    ticks = m.get('ticks') or []
    columns = m.get('tick_columns') or []
    event_stream = m.get('event_stream') or []

    if not ticks or not columns:
        return {'slug': slug, 'error': 'no_ticks_or_columns'}

    # Top-level fields (v1-compat)
    out = {
        'v':        SCHEMA_VERSION,   # v2 NEW: schema version
        'slug':     slug,
        'ts':       m.get('ts'),
        'winner':   m.get('winner'),
        'bn_final': round(m.get('bn_delta_final') or 0, 4),
        'win_open': round(m.get('window_open_price') or 0, 2),
        'hour_utc': m.get('hour_utc'),
        'day_of_week': m.get('day_of_week'),
    }

    # Full-market rollups
    t5050 = time_near_5050(ticks, columns)
    if t5050 is not None:
        out['t5050'] = t5050

    # Final-market BN/lead data (at cd≤5)
    last = find_tick_at(ticks, columns, 0)
    if last:
        out['last_ua'] = round(last.get('up_ask', 0) or 0, 3)
        out['last_da'] = round(last.get('dn_ask', 0) or 0, 3)

    # Per-checkpoint snapshots (now includes T-45, T-20, T-10, T-5)
    buckets = {}
    for cp in CHECKPOINTS:
        trade_floor = cp + 30  # trades in 30s before this checkpoint
        feats = extract_bucket_features(ticks, columns, cp, event_stream, trade_floor)
        if feats is not None:
            buckets[f'T-{cp}'] = feats

    # Define canonical bucket order
    tk_order = [f'T-{cp}' for cp in CHECKPOINTS]

    # v2 NEW: Add velocity features per bucket
    compute_velocity_features(buckets, tk_order)

    out['bk'] = buckets

    # v2 NEW: Settlement-aware peaks
    winner = out.get('winner')
    if winner in ('UP', 'DN'):
        out['settle'] = compute_settle(buckets, winner)
        out['class']  = compute_classification(buckets, winner, tk_order)
        out['events'] = compute_events(buckets, tk_order)

    # Lead changes up to T-120 (used in classification)
    lc_at_120, flipped_at_120 = lead_changes_up_to(ticks, columns, 120)
    if lc_at_120 is not None:
        out['lc_120'] = lc_at_120
        out['flip_120'] = flipped_at_120

    # Final LC and flip state
    lc_final, flipped_final = lead_changes_up_to(ticks, columns, 0)
    if lc_final is not None:
        out['lc_final'] = lc_final
        out['flip_final'] = flipped_final

    return out


def main():
    ap = argparse.ArgumentParser(description='Extract per-tick indicator snapshots from replay files (v2 format)')
    ap.add_argument('inputs', nargs='+', help='Directory with replay_*.json files, OR list of replay_*.json files')
    ap.add_argument('-o', '--output', default='market_snapshots.jsonl',
                    help='Output JSONL file (default: market_snapshots.jsonl)')
    ap.add_argument('--pattern', default='replay_*.json',
                    help='Glob pattern when inputs is a directory (default: replay_*.json)')
    ap.add_argument('--verbose', '-v', action='store_true', help='Print per-file progress')
    args = ap.parse_args()

    # Smart input handling: accept directory OR file list
    files = []
    if len(args.inputs) == 1 and Path(args.inputs[0]).is_dir():
        # Directory path
        in_dir = Path(args.inputs[0])
        files = sorted(glob.glob(str(in_dir / args.pattern)))
        if not files:
            print(f"ERROR: no files matching {args.pattern} in {in_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"Processing {len(files)} replay files from {in_dir} (v2 format) ...")
    else:
        # File list (from shell glob expansion like `replay_*.json`)
        for arg in args.inputs:
            p = Path(arg)
            if p.is_file():
                files.append(str(p))
            else:
                # Skip non-files (e.g. output filename accidentally passed)
                if not arg.endswith('.jsonl'):
                    print(f"WARNING: skipping non-existent file: {arg}", file=sys.stderr)
        if not files:
            print(f"ERROR: no valid files in arguments", file=sys.stderr)
            sys.exit(1)
        print(f"Processing {len(files)} replay files (v2 format) ...")

    out_count = 0
    err_count = 0
    cheap_won_count = 0
    with open(args.output, 'w') as out_fp:
        for i, fp in enumerate(files, 1):
            rec = extract_market(fp)
            if 'error' in rec:
                err_count += 1
                if args.verbose:
                    print(f"  [{i}/{len(files)}] ERROR {rec['slug']}: {rec['error']}")
            else:
                out_fp.write(json.dumps(rec) + '\n')
                out_count += 1
                if rec.get('class', {}).get('cheap_side_won'):
                    cheap_won_count += 1
                if args.verbose or i % 100 == 0:
                    print(f"  [{i}/{len(files)}] {rec['slug']} winner={rec.get('winner')}")

    print(f"\n✅ Wrote {out_count} records ({err_count} errors) to {args.output}")
    print(f"   Schema version: v{SCHEMA_VERSION}")
    print(f"   Cheap-side-won markets: {cheap_won_count}")


if __name__ == '__main__':
    main()

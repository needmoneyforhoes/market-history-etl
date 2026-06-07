#!/usr/bin/env python3
"""
Run this on your VPS:
  python3 extract_one_market.py
It reads ./market_history.jsonl
and dumps the full record for market 1777475400 to extracted_market.json
"""
import json

TARGET = '1777475400'
PATH   = './data/market_history.jsonl'

found = False
with open(PATH) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        slug = d.get('slug', '')
        if TARGET in slug:
            with open('extracted_market.json', 'w') as out:
                json.dump(d, out, indent=2)
            found = True

            # Print summary so you can see what's available without opening the full file
            print(f"slug        : {d.get('slug')}")
            print(f"winner      : {d.get('winner')}")
            print(f"ts          : {d.get('ts')}")
            print()
            print("=== TOP-LEVEL KEYS ===")
            for k, v in d.items():
                if isinstance(v, list):
                    print(f"  {k:35} list  len={len(v)}")
                elif isinstance(v, dict):
                    print(f"  {k:35} dict  keys={list(v.keys())[:6]}")
                else:
                    print(f"  {k:35} {type(v).__name__:8} = {str(v)[:60]}")
            print()

            # If there's a ticks / tick_data / ticks_compressed key, show structure
            for tk in ['ticks', 'tick_data', 'tick_rows', 'rows', 'data',
                       'tick_columns', 'compressed_ticks', 'price_ticks']:
                if tk in d:
                    val = d[tk]
                    if isinstance(val, list) and len(val) > 0:
                        print(f"=== {tk} (first row) ===")
                        print(f"  {val[0]}")
                        print(f"  total rows: {len(val)}")
                    elif isinstance(val, dict):
                        print(f"=== {tk} (dict keys) ===")
                        print(f"  {list(val.keys())}")
            break

if not found:
    print(f"Market {TARGET} not found in {PATH}")
    print("Checking first 3 slugs in file for reference:")
    with open(PATH) as f:
        for i, line in enumerate(f):
            if i >= 3: break
            try:
                d = json.loads(line)
                print(f"  {d.get('slug','?')}")
            except:
                pass

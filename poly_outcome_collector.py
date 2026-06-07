"""Polymarket BTC up/down outcome collector — pulls historical outcomes via web scraping.

Usage: python3 poly_outcome_collector.py [days_back]
"""
import urllib.request, re, json, time, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_FILE = '/home/claude/output/polymarket_outcomes.json'
CHECKPOINT_INTERVAL = 100  # save every N markets

def fetch_outcome(ts):
    slug = f"btc-updown-5m-{ts}"
    url = f"https://polymarket.com/event/{slug}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
    except Exception:
        return ts, None
    
    m = re.search(r'"outcomes":\s*(\[[^\]]+\])\s*,\s*"outcomePrices":\s*(\[[^\]]+\])', content)
    if not m:
        return ts, None
    try:
        outcomes = json.loads(m.group(1))
        prices = json.loads(m.group(2))
    except Exception:
        return ts, None
    for o, p in zip(outcomes, prices):
        if str(p) == '1':
            if 'Up' in str(o): return ts, 'UP'
            if 'Down' in str(o): return ts, 'DN'
    return ts, None


def collect(days_back):
    end_ts = (int(time.time()) // 300) * 300 - 1800
    start_ts = end_ts - days_back * 86400
    start_ts = (start_ts // 300) * 300
    timestamps = list(range(start_ts, end_ts, 300))
    
    # Load existing checkpoint
    results = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                d = json.load(f)
                results = {int(k): v for k, v in d.get('outcomes', {}).items()}
            print(f"Loaded {len(results)} existing outcomes from checkpoint")
        except Exception as e:
            print(f"Could not load checkpoint: {e}")
    
    # Filter timestamps already done
    todo = [ts for ts in timestamps if ts not in results]
    print(f"Total markets needed: {len(timestamps)}, already have: {len(results)}, to fetch: {len(todo)}")
    
    if not todo:
        print("All done!")
        return results
    
    start = time.time()
    completed = 0
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(fetch_outcome, ts) for ts in todo]
        for fut in as_completed(futures):
            ts, outcome = fut.result()
            if outcome:
                results[ts] = outcome
            completed += 1
            
            if completed % CHECKPOINT_INTERVAL == 0:
                # Save checkpoint
                _save(results)
                elapsed = time.time() - start
                rate = completed / elapsed
                eta = (len(todo) - completed) / rate
                print(f"  {completed}/{len(todo)} | {rate:.1f}/s | ETA {eta:.0f}s | total resolved: {len(results)}")
    
    _save(results)
    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s. Total resolved: {len(results)}")
    return results


def _save(results):
    with open(OUTPUT_FILE, 'w') as f:
        json.dump({
            'outcomes': {str(k): v for k, v in sorted(results.items())},
            'count': len(results),
        }, f)


if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    results = collect(days)
    
    # Summary
    ups = sum(1 for v in results.values() if v == 'UP')
    dns = sum(1 for v in results.values() if v == 'DN')
    total = ups + dns
    print(f"\nFinal: UP={ups} ({ups/max(1,total)*100:.1f}%), DN={dns} ({dns/max(1,total)*100:.1f}%)")

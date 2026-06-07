"""
poly_daily_updater.py — Daily Polymarket outcome collector

Run on your VPS daily:
  python3 poly_daily_updater.py

Pulls last 24h of outcomes, appends to dataset, re-runs pattern analysis.
After 30+ days of accumulated data, patterns become statistically robust.
"""
import urllib.request, re, json, time, os, sys, math
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

DATA_FILE = os.path.join(os.path.dirname(__file__), 'polymarket_outcomes.json')


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


def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            d = json.load(f)
            return {int(k): v for k, v in d.get('outcomes', {}).items()}
    return {}


def save(results):
    with open(DATA_FILE, 'w') as f:
        json.dump({
            'outcomes': {str(k): v for k, v in sorted(results.items())},
            'count': len(results),
        }, f)


def update_recent(days=2):
    """Pull last N days, fill gaps."""
    results = load_existing()
    print(f"Loaded {len(results)} existing outcomes")
    
    end_ts = (int(time.time()) // 300) * 300 - 1800
    start_ts = end_ts - days * 86400
    start_ts = (start_ts // 300) * 300
    
    needed = [ts for ts in range(start_ts, end_ts + 300, 300) if ts not in results]
    if not needed:
        print(f"All {days} days already covered, nothing to fetch")
        return results
    
    print(f"Fetching {len(needed)} missing markets...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=5) as ex:
        for fut in as_completed([ex.submit(fetch_outcome, ts) for ts in needed]):
            ts, outcome = fut.result()
            if outcome:
                results[ts] = outcome
    
    save(results)
    print(f"Done in {time.time()-t0:.0f}s. Total: {len(results)}")
    return results


def analyze(results):
    items = sorted(results.items())
    sequence = [v for _, v in items]
    N = len(sequence)
    n_up = sequence.count('UP')
    p_up = n_up / N
    
    print(f"\n{'='*70}")
    print(f"PATTERN ANALYSIS — {N:,} markets ({(N*5)/(60*24):.1f} days)")
    print(f"{'='*70}")
    print(f"UP: {n_up} ({p_up*100:.2f}%), DN: {N-n_up} ({(1-p_up)*100:.2f}%)")
    print()
    
    # Markov-3 and Markov-4 patterns
    for k in [3, 4]:
        print(f"\nMarkov-{k} patterns (n>=50):")
        m = defaultdict(lambda: [0, 0])
        for i in range(N - k):
            key = ''.join(sequence[i:i+k])
            m[key][1] += 1
            if sequence[i+k] == 'UP':
                m[key][0] += 1
        
        rs = []
        for key, (uc, t) in m.items():
            if t < 50: continue
            p = uc / t
            se = math.sqrt(p_up * (1-p_up) / t)
            z = (p - p_up) / se
            rs.append((key, t, p, (p-p_up)*100, z))
        
        rs.sort(key=lambda x: -abs(x[4]))
        for key, t, p, d, z in rs[:5]:
            sig = "✓✓" if abs(z) > 2.58 else "✓" if abs(z) > 1.96 else ""
            side = 'UP' if d > 0 else 'DN'
            print(f"  {key:<10} {p*100:>5.2f}% (Δ{d:+.2f}pp) n={t:<5} z={z:+.2f} {sig} → {side}")


if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    results = update_recent(days)
    analyze(results)

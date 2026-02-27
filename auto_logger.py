import json
import datetime
import os
import sys
import subprocess

# --- Settings ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "stock_rankings_log.txt")
LOG_FILE = os.path.join(SCRIPT_DIR, "auto_logger.log")

CAP_1B = 1_000_000_000
CAP_10B = 10_000_000_000
CAP_100B = 100_000_000_000

def log_message(message, level="INFO"):
      """Simple logging"""
      timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      log_line = f"{timestamp} [{level}] {message}"
      print(message if level != "DEBUG" else "") 
    try:
              with open(LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(log_line + "\n")
    except Exception:
              pass

def get_us_eastern_now():
      """Get US Eastern Time (ET) using only standard library"""
      utc_now = datetime.datetime.utcnow()
      year = utc_now.year

    # DST calculation (2nd Sunday of March to 1st Sunday of November)
      march_1 = datetime.datetime(year, 3, 1)
      march_second_sunday = march_1 + datetime.timedelta(days=(6 - march_1.weekday()) % 7 + 7)
      dst_start = march_second_sunday.replace(hour=7) # UTC 7:00

    nov_1 = datetime.datetime(year, 11, 1)
    nov_first_sunday = nov_1 + datetime.timedelta(days=(6 - nov_1.weekday()) % 7)
    dst_end = nov_first_sunday.replace(hour=6) # UTC 6:00

    if dst_start <= utc_now < dst_end:
              # EDT (UTC-4)
              et_now = utc_now - datetime.timedelta(hours=4)
              tz_name = "EDT"
else:
          # EST (UTC-5)
          et_now = utc_now - datetime.timedelta(hours=5)
          tz_name = "EST"

    return et_now, tz_name

import subprocess

def get_market_data_standard():
      """Fetch data using curl (to avoid Python SSL issues)"""
      url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true"
      headers = [
          "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
      ]

    log_message("Fetching from NASDAQ API (using curl)...")

    try:
              # Build curl command
              cmd = ["curl", "-s", url] + headers

        # Execute with subprocess
              result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

        if result.returncode != 0:
                      log_message(f"curl error: {result.stderr}", "ERROR")
                      return []

        data = json.loads(result.stdout)
        return data['data']['rows']

except Exception as e:
        log_message(f"Data fetch error: {e}", "ERROR")
        return []

def parse_currency(value):
      if not value or value == "NA": return 0.0
            try:
                      return float(value.replace('$', '').replace(',', ''))
                  except: return 0.0

def parse_percent(value):
      if not value or value == "NA": return 0.0
            try:
                      return float(value.replace('%', '').replace(',', ''))
                  except: return 0.0

def parse_market_cap(value):
      if not value or value == "NA": return 0.0
            try:
                      clean_val = value.replace(',', '')
                      multiplier = 1.0
                      if clean_val.endswith('T'): multiplier = 1_000_000_000_000; clean_val = clean_val[:-1]
elif clean_val.endswith('B'): multiplier = 1_000_000_000; clean_val = clean_val[:-1]
elif clean_val.endswith('M'): multiplier = 1_000_000; clean_val = clean_val[:-1]
        return float(clean_val) * multiplier
    except: return 0.0

def format_ranking_text(rows, market_date, et_now, tz_name):
      """Format ranking text from list of dicts"""
    lines = []

    # Header
    date_str = market_date.strftime("%Y/%m/%d")
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_str = weekday_names[market_date.weekday()]
    exec_time = et_now.strftime("%H:%M")

    lines.append("=" * 50)
    lines.append(f"{date_str}({weekday_str})   US Stock Ranking (by Market Cap)")
    lines.append(f"  Time: {exec_time} {tz_name} (US Eastern Time)")
    lines.append("=" * 50)

    # Data processing
    processed_rows = []
    for row in rows:
              processed_rows.append({
                            'symbol': row.get('symbol', ''),
                            'name': row.get('name', ''),
                            'lastsale': parse_currency(row.get('lastsale', '0')),
                            'pctchangeValue': parse_percent(row.get('pctchange', '0')),
                            'marketCapValue': parse_market_cap(row.get('marketCap', '0'))
              })

    # Grouping
    group3 = [r for r in processed_rows if r['marketCapValue'] >= CAP_100B]
    group2 = [r for r in processed_rows if CAP_10B <= r['marketCapValue'] < CAP_100B]
    group1 = [r for r in processed_rows if CAP_1B <= r['marketCapValue'] < CAP_10B]

    groups = [
              ("[Group 3] Mega Cap (over $100B)", group3),
              ("[Group 2] Large Cap ($10B-$100B)", group2),
              ("[Group 1] Mid Cap ($1B-$10B)", group1)
    ]

    for title, group_data in groups:
              lines.append(f"\n{title}")

        if not group_data:
                      lines.append("N/A")
                      continue

        # Top 50 gainers
        top50 = sorted(group_data, key=lambda x: x['pctchangeValue'], reverse=True)[:50]
        lines.append("Top 50 Gainers\n")
        for idx, row in enumerate(top50, 1):
                      pct = row['pctchangeValue']
                      sign = "+" if pct >= 0 else ""
                      lines.append(f"{idx}.  {row['symbol']}: {sign}{pct:.2f}%")

        # Worst 50 losers
        worst50 = sorted(group_data, key=lambda x: x['pctchangeValue'])[:50]
        lines.append("\nWorst 50 Losers\n")
        for idx, row in enumerate(worst50, 1):
                      pct = row['pctchangeValue']
                      sign = "+" if pct >= 0 else ""
                      lines.append(f"{idx}.  {row['symbol']}: {sign}{pct:.2f}%")

    return "\n".join(lines)

def main():
      print("=" * 50)
    print("  US Stock Ranking Auto Logger")
    print("=" * 50)

    # Time
    et_now, tz_name = get_us_eastern_now()

    # Market date (based on 16:00 ET)
    market_close_hour = 16
    if et_now.hour >= market_close_hour:
              market_date = et_now.date()
else:
        market_date = et_now.date() - datetime.timedelta(days=1)

      # Correct for weekend
      while market_date.weekday() >= 5:
                market_date -= datetime.timedelta(days=1)

    log_message(f"Market Date: {market_date.strftime('%Y/%m/%d')} ({tz_name})")

    # Weekend check
    if et_now.weekday() >= 5:
              log_message("Skipping for weekend.", "INFO")
              return

    # Duplicate check
    if os.path.exists(OUTPUT_FILE):
              with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                            if market_date.strftime("%Y/%m/%d") in f.read():
                                              log_message("Data already recorded for today.", "INFO")
                                              return

                    # Fetch
                    rows = get_market_data_standard()
    if not rows:
              log_message("Failed to fetch data.", "ERROR")
        return

    log_message(f"Fetched {len(rows)} items.")

    # Format and save
    try:
              text = format_ranking_text(rows, market_date, et_now, tz_name)

        if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
                      with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                                        f.write("\n\n")

        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                      f.write(text)

        log_message(f"Saved to {OUTPUT_FILE}")
        print("\n" + text[:500] + "\n...(truncated)...")

except Exception as e:
        log_message(f"Process error: {e}", "ERROR")

if __name__ == "__main__":
      main()

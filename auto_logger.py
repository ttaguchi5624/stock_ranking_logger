import subprocess
import json
import datetime
import os
import sys
import logging

# ログ設定: 標準出力(GitHub Actionsの画面)とファイルの両方に出力
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("auto_logger.log", encoding="utf-8")
    ]
)

CAP_1B = 1_000_000_000
CAP_10B = 10_000_000_000
CAP_100B = 100_000_000_000

def get_us_eastern_now():
    """米国東部時間(ET)取得 (標準ライブラリのみ)"""
    utc_now = datetime.datetime.utcnow()
    year = utc_now.year
    
    # DST計算 (3月第2日曜 〜 11月第1日曜)
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

def fetch_nasdaq_data():
    try:
        logging.info("NASDAQ API からデータを取得中 (curl使用)...")
        # URLにdownload=trueを付けて全件取得する
        command = [
            "curl", "-s",
            "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-H", "Accept: application/json",
            "-H", "Origin: https://www.nasdaq.com",
            "-H", "Referer: https://www.nasdaq.com/"
        ]
        
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        
        if not result.stdout:
            logging.error("APIからの応答が空です。")
            return []

        data = json.loads(result.stdout)
        
        if data.get('status', {}).get('rCode') != 200:
            logging.error(f"APIがエラーを返しました: {data.get('status', {}).get('bCodeMessage', 'Unknown Error')}")
            return []

        rows = data['data']['rows']
        if not rows:
            logging.warning("データ行が見つかりません。市場が休場か、データが更新されていない可能性があります。")
            return []

        return rows

    except subprocess.CalledProcessError as e:
        logging.error(f"curl コマンドの実行に失敗しました: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"JSONの解析に失敗しました: {e}")
        return []
    except Exception as e:
        logging.error(f"予期せぬエラーが発生しました: {e}")
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
    """辞書リストからランキングテキストを作成"""
    lines = []
    
    date_str = market_date.strftime("%Y/%m/%d")
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][market_date.weekday()]
    exec_time = et_now.strftime("%H:%M")
    
    lines.append("=" * 50)
    lines.append(f"{date_str}({weekday_jp})   米国株 前日比ランキング (時価総額別)")
    lines.append(f"  取得時刻: {exec_time} {tz_name} (米国東部時間)")
    lines.append("=" * 50)
    
    processed_rows = []
    for row in rows:
        processed_rows.append({
            'symbol': row.get('symbol', ''),
            'name': row.get('name', ''),
            'lastsale': parse_currency(row.get('lastsale', '0')),
            'pctchangeValue': parse_percent(row.get('pctchange', '0')),
            'marketCapValue': parse_market_cap(row.get('marketCap', '0'))
        })

    group3 = [r for r in processed_rows if r['marketCapValue'] >= CAP_100B]
    group2 = [r for r in processed_rows if CAP_10B <= r['marketCapValue'] < CAP_100B]
    group1 = [r for r in processed_rows if CAP_1B <= r['marketCapValue'] < CAP_10B]
    
    groups = [
        ("【Group 3】Mega Cap ($100B以上)", group3),
        ("【Group 2】Large Cap ($10B-$100B)", group2),
        ("【Group 1】Mid Cap ($1B-$10B)", group1)
    ]
    
    for title, group_data in groups:
        lines.append(f"\n{title}")
        
        if not group_data:
            lines.append("該当なし")
            continue
            
        top50 = sorted(group_data, key=lambda x: x['pctchangeValue'], reverse=True)[:50]
        lines.append("■上昇 Top 50\n")
        for idx, row in enumerate(top50, 1):
            pct = row['pctchangeValue']
            sign = "+" if pct >= 0 else ""
            lines.append(f"{idx}.  {row['symbol']}: {sign}{pct:.2f}%")
            
        worst50 = sorted(group_data, key=lambda x: x['pctchangeValue'])[:50]
        lines.append("\n■下落 Worst 50\n")
        for idx, row in enumerate(worst50, 1):
            pct = row['pctchangeValue']
            sign = "+" if pct >= 0 else ""
            lines.append(f"{idx}.  {row['symbol']}: {sign}{pct:.2f}%")
            
    return "\n".join(lines)

def main():
    logging.info("=" * 50)
    logging.info("  米国株ランキング 自動取得ロガー")
    logging.info("=" * 50)
    
    et_now, tz_name = get_us_eastern_now()
    
    market_close_hour = 16
    if et_now.hour >= market_close_hour:
        market_date = et_now.date()
    else:
        market_date = et_now.date() - datetime.timedelta(days=1)
        
    while market_date.weekday() >= 5:
        market_date -= datetime.timedelta(days=1)
        
    logging.info(f"米国市場日付: {market_date.strftime('%Y/%m/%d')} ({tz_name})")
    
    # 週末チェック (当日が土日なら実行しない)
    if et_now.weekday() >= 5:
        logging.info("週末のためスキップします。")
        return

    output_file = "stock_rankings_log.txt"

    # 重複チェック (同日のデータがすでに書き込まれていたら実行しない)
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            if market_date.strftime("%Y/%m/%d") in f.read():
                logging.info("既に本日のデータは記録済みです。")
                return

    rows = fetch_nasdaq_data()
    if not rows:
        logging.error("データの取得に失敗しました。")
        return
        
    logging.info(f"{len(rows)} 件のデータを取得しました。")
    
    try:
        text = format_ranking_text(rows, market_date, et_now, tz_name)
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write("\n\n")
                
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(text)
            
        logging.info(f"データを {output_file} に保存しました。")
        
    except Exception as e:
        logging.error(f"処理エラー: {e}")

if __name__ == "__main__":
    main()

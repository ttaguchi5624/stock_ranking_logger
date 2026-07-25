import datetime
import hashlib
import json
import logging
import os
import statistics
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("auto_logger.log", encoding="utf-8"),
    ],
)

CAP_1B = 1_000_000_000
CAP_10B = 10_000_000_000
CAP_100B = 100_000_000_000

RANK_DEPTH = 200
TEXT_LOG = "stock_rankings_log.txt"
STATE_FILE = Path("_logger_state.json")


# --------------------------------------------------------------------------
# 時刻
# --------------------------------------------------------------------------
def get_us_eastern_now():
    """米国東部時間(ET)取得 (標準ライブラリのみ)"""
    # utcnow() は Python 3.12 で非推奨。aware で取得して naive に戻す。
    utc_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    year = utc_now.year

    # DST: 3月第2日曜 02:00 EST (=07:00 UTC) 〜 11月第1日曜 02:00 EDT (=06:00 UTC)
    march_1 = datetime.datetime(year, 3, 1)
    march_second_sunday = march_1 + datetime.timedelta(
        days=(6 - march_1.weekday()) % 7 + 7
    )
    dst_start = march_second_sunday.replace(hour=7)

    nov_1 = datetime.datetime(year, 11, 1)
    nov_first_sunday = nov_1 + datetime.timedelta(days=(6 - nov_1.weekday()) % 7)
    dst_end = nov_first_sunday.replace(hour=6)

    if dst_start <= utc_now < dst_end:
        return utc_now - datetime.timedelta(hours=4), "EDT"
    return utc_now - datetime.timedelta(hours=5), "EST"


# --------------------------------------------------------------------------
# 取得
# --------------------------------------------------------------------------
def fetch_nasdaq_data():
    try:
        logging.info("NASDAQ API からデータを取得中 (curl使用)...")
        command = [
            "curl", "-s", "--max-time", "60",
            "https://api.nasdaq.com/api/screener/stocks"
            "?tableonly=true&limit=25&offset=0&download=true",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-H", "Accept: application/json",
            "-H", "Origin: https://www.nasdaq.com",
            "-H", "Referer: https://www.nasdaq.com/",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)

        if not result.stdout:
            logging.error("APIからの応答が空です。")
            return []

        data = json.loads(result.stdout)
        if data.get("status", {}).get("rCode") != 200:
            msg = data.get("status", {}).get("bCodeMessage", "Unknown Error")
            logging.error(f"APIがエラーを返しました: {msg}")
            return []

        rows = data["data"]["rows"]
        if not rows:
            logging.warning("データ行が見つかりません。休場か未更新の可能性があります。")
            return []

        # 初回実行時に実際のキー構成をログで確認できるようにしておく
        logging.info(f"APIの列: {sorted(rows[0].keys())}")
        return rows

    except subprocess.CalledProcessError as e:
        logging.error(f"curl コマンドの実行に失敗しました: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"JSONの解析に失敗しました: {e}")
    except Exception as e:
        logging.error(f"予期せぬエラーが発生しました: {e}")
    return []


# --------------------------------------------------------------------------
# パース
# --------------------------------------------------------------------------
def parse_currency(value):
    if not value or value == "NA":
        return 0.0
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return 0.0


def parse_percent(value):
    if not value or value == "NA":
        return 0.0
    try:
        return float(str(value).replace("%", "").replace(",", ""))
    except ValueError:
        return 0.0


def parse_market_cap(value):
    if not value or value == "NA":
        return 0.0
    try:
        clean = str(value).replace(",", "").replace("$", "").strip()
        mult = 1.0
        if clean.endswith("T"):
            mult, clean = 1_000_000_000_000, clean[:-1]
        elif clean.endswith("B"):
            mult, clean = 1_000_000_000, clean[:-1]
        elif clean.endswith("M"):
            mult, clean = 1_000_000, clean[:-1]
        return float(clean) * mult
    except ValueError:
        return 0.0


def normalize(rows):
    out = []
    for r in rows:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "pct": parse_percent(r.get("pctchange")),
            "cap": parse_market_cap(r.get("marketCap")),
            "lastsale": parse_currency(r.get("lastsale")),
            "sector": (r.get("sector") or "N/A").strip(),
            "industry": (r.get("industry") or "N/A").strip(),
        })
    return out


# --------------------------------------------------------------------------
# 休場日検出（内容ハッシュ）
# --------------------------------------------------------------------------
def fingerprint(records):
    """価格データの指紋。市場が閉まっていれば前営業日と完全一致する。"""
    payload = "\n".join(
        f"{r['symbol']}|{r['lastsale']:.4f}|{r['pct']:.4f}"
        for r in sorted(records, key=lambda x: x["symbol"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logging.warning("state ファイルが壊れています。初期化します。")
    return {"last_fingerprint": None, "last_date": None}


def save_state(fp, date_key):
    STATE_FILE.write_text(
        json.dumps({"last_fingerprint": fp, "last_date": date_key}, indent=2),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# 整形
# --------------------------------------------------------------------------
def summary_line(data):
    """201位以下が見えない問題を、分布統計で代替する1行"""
    pcts = sorted(r["pct"] for r in data)
    n = len(pcts)
    adv = sum(1 for p in pcts if p > 0)
    dec = sum(1 for p in pcts if p < 0)
    ratio = f"{adv / dec:.2f}" if dec else "N/A"
    q1 = statistics.quantiles(pcts, n=4)[0] if n >= 4 else pcts[0]
    q3 = statistics.quantiles(pcts, n=4)[2] if n >= 4 else pcts[-1]
    med = statistics.median(pcts)
    return (f"  構成: {n}銘柄 | 上昇 {adv} / 下落 {dec} | 騰落レシオ {ratio} | "
            f"中央値 {med:+.2f}% | 四分位 {q1:+.2f}% / {q3:+.2f}%")


def format_ranking_text(records, market_date, et_now, tz_name, depth=RANK_DEPTH):
    lines = []
    date_str = market_date.strftime("%Y/%m/%d")
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][market_date.weekday()]

    lines.append("=" * 50)
    lines.append(f"{date_str}({weekday_jp})   米国株 前日比ランキング (時価総額別)")
    lines.append(f"  取得時刻: {et_now.strftime('%H:%M')} {tz_name} (米国東部時間)")
    lines.append("=" * 50)

    groups = [
        ("【Group 3】Mega Cap ($100B以上)",
         [r for r in records if r["cap"] >= CAP_100B]),
        ("【Group 2】Large Cap ($10B-$100B)",
         [r for r in records if CAP_10B <= r["cap"] < CAP_100B]),
        ("【Group 1】Mid Cap ($1B-$10B)",
         [r for r in records if CAP_1B <= r["cap"] < CAP_10B]),
    ]

    for title, data in groups:
        lines.append(f"\n{title}")
        if not data:
            lines.append("該当なし")
            continue

        lines.append(summary_line(data))

        for label, reverse in [("■上昇 Top", True), ("■下落 Worst", False)]:
            ranked = sorted(data, key=lambda x: x["pct"], reverse=reverse)[:depth]
            lines.append(f"\n{label} {min(depth, len(data))}\n")
            for idx, r in enumerate(ranked, 1):
                sign = "+" if r["pct"] >= 0 else ""
                lines.append(
                    f"{idx}.  {r['symbol']}: {sign}{r['pct']:.2f}%"
                    f"  [{r['sector']}/{r['industry']}]"
                )

    return "\n".join(lines)


# --------------------------------------------------------------------------
def main():
    logging.info("=" * 50)
    logging.info("  米国株ランキング 自動取得ロガー")
    logging.info("=" * 50)

    et_now, tz_name = get_us_eastern_now()

    market_date = et_now.date() if et_now.hour >= 16 \
        else et_now.date() - datetime.timedelta(days=1)
    while market_date.weekday() >= 5:
        market_date -= datetime.timedelta(days=1)

    logging.info(f"米国市場日付: {market_date.strftime('%Y/%m/%d')} ({tz_name})")

    dry_run = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
    if dry_run:
        logging.warning("*" * 60)
        logging.warning("DRY_RUN モード: 週末/重複/休場判定を無視します。")
        logging.warning("出力先は stock_rankings_log_TEST.txt。本番ログは変更しません。")
        logging.warning("*" * 60)

    if et_now.weekday() >= 5 and not dry_run:
        logging.info("週末のためスキップします。")
        return

    date_key = market_date.strftime("%Y/%m/%d")
    out_file = "stock_rankings_log_TEST.txt" if dry_run else TEXT_LOG

    if not dry_run and os.path.exists(TEXT_LOG):
        with open(TEXT_LOG, "r", encoding="utf-8") as f:
            if date_key in f.read():
                logging.info("既に本日のデータは記録済みです。")
                return

    rows = fetch_nasdaq_data()
    if not rows:
        logging.error("データの取得に失敗しました。")
        return

    records = normalize(rows)
    logging.info(f"{len(records)} 件のデータを取得しました。")

    # --- 休場日検出 ------------------------------------------------------
    state = load_state()
    fp = fingerprint(records)
    if fp == state.get("last_fingerprint") and not dry_run:
        logging.warning(
            f"前回記録({state.get('last_date')})とデータが完全一致しました。"
            f"市場休場と判断し、{date_key} は記録しません。"
        )
        return
    # ---------------------------------------------------------------------

    try:
        text = format_ranking_text(records, market_date, et_now, tz_name)

        if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
            with open(out_file, "a", encoding="utf-8") as f:
                f.write("\n\n")
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(text)
        print(text)

        if not dry_run:
            save_state(fp, date_key)
        logging.info(f"データを {out_file} に保存しました。")

        # --- 検証用サマリー ---
        logging.info("-" * 50)
        logging.info(f"検証: 総取得数 {len(records)}")
        sectors = {}
        for r in records:
            sectors[r["sector"]] = sectors.get(r["sector"], 0) + 1
        na = sectors.get("N/A", 0)
        logging.info(f"検証: sector が N/A の銘柄 {na} 件 "
                     f"({na / len(records) * 100:.1f}%)  ← 高すぎるならキー名を要確認")
        logging.info(f"検証: 検出セクター {sorted(k for k in sectors if k != 'N/A')}")
        logging.info("-" * 50)

    except Exception as e:
        logging.error(f"処理エラー: {e}")


if __name__ == "__main__":
    main()

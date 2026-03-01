import subprocess
import json
import pandas as pd
from datetime import datetime
import tabulate
import os
import sys
import logging

# ログ設定 (GitHub Actions / Local)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("auto_logger.log", encoding="utf-8")
    ]
)

def fetch_nasdaq_data():
    try:
        # curl を使って API からデータを取得
        logging.info("NASDAQ API からデータを取得中...")
        command = [
            "curl", "-s",
            "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-H", "Accept: application/json",
            "-H", "Origin: https://www.nasdaq.com",
            "-H", "Referer: https://www.nasdaq.com/"
        ]
        
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        
        if not result.stdout:
            logging.error("APIからの応答が空です。")
            return None

        data = json.loads(result.stdout)
        
        # エラーチェック
        if data.get('status', {}).get('rCode') != 200:
            logging.error(f"APIがエラーを返しました: {data.get('status', {}).get('bCodeMessage', 'Unknown Error')}")
            return None

        # データ抽出
        rows = data['data']['table']['rows']
        if not rows:
            logging.warning("データ行が見つかりません。市場が休場か、データが更新されていない可能性があります。")
            return None

        # DataFrame に変換
        df = pd.DataFrame(rows)
        
        # 必要な列だけ抽出してリネーム (列名が存在するか安全にチェック)
        columns_to_keep = ['symbol', 'name', 'lastsale', 'netchange', 'pctchange', 'marketCap']
        # 実際に存在する列のみを抽出
        existing_columns = [col for col in columns_to_keep if col in df.columns]
        df = df[existing_columns]
        
        rename_map = {
            'symbol': 'Ticker',
            'name': 'Company Name',
            'lastsale': 'Last Sale',
            'netchange': 'Net Change',
            'pctchange': '% Change',
            'marketCap': 'Market Cap'
        }
        df.rename(columns=rename_map, inplace=True)
        return df

    except subprocess.CalledProcessError as e:
        logging.error(f"curl コマンドの実行に失敗しました: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"JSONの解析に失敗しました: {e}\nAPIの応答内容:\n{result.stdout[:500]}") # 最初の500文字だけログに出す
        return None
    except Exception as e:
        logging.error(f"予期せぬエラーが発生しました: {e}")
        return None

def main():
    logging.info("--- 処理開始 ---")
    df = fetch_nasdaq_data()
    
    if df is not None and not df.empty:
        # 現在の日時を取得
        jst_time = datetime.now() # GitHub ActionsはUTCだが、ログにはそのまま記録し、ファイル名等で管理するのもあり。
                                  # ここではわかりやすくUTCのまま出しておく。
        timestamp = jst_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        output_file = "stock_rankings_log.txt"
        
        try:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{timestamp}]\n")
                f.write(tabulate.tabulate(df, headers='keys', tablefmt='plain', showindex=False))
                f.write("\n" + "-"*50 + "\n")
            logging.info(f"データを {output_file} に追記しました。\n")
        except Exception as e:
             logging.error(f"ファイルへの書き込みに失敗しました: {e}")
    else:
        logging.info("処理するデータがありませんでした。休場日、または取得エラーの可能性があります。\n")

if __name__ == "__main__":
    main()

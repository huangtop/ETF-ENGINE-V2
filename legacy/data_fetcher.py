"""
股價資料獲取模組
使用 TWSE（台股）和 Alp        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            return {}ge（美股）作為資料來源
包含智能快取機制，避免重複調用 API
"""

import pandas as pd
import requests
import os
import json
from datetime import datetime, timedelta
import time
import urllib3
import yfinance as yf

# 抑制 SSL 警告 (用於 TWSE API)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Alpha Vantage API key（從環境變數讀取，不寫到程式中）
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'demo')

# 🚨 全局Alpha Vantage API失敗標記
_ALPHA_VANTAGE_FAILED = False

def mark_alpha_vantage_failed():
    """標記Alpha Vantage API為失敗狀態，後續調用將被跳過"""
    global _ALPHA_VANTAGE_FAILED
    _ALPHA_VANTAGE_FAILED = True

def download_etf_info_yfinance(ticker):
    """
    使用 yfinance 下載 ETF 的、管理費、股息殖利率及配息月份
    
    Returns:
        dict: {'turnover': float, 'expense': float, 'dividend_yield': float, 'dividend_months': list}
    """
    try:
        etf = yf.Ticker(ticker)
        info = etf.info
        
        # 費用率
        expense = info.get('annualReportExpenseRatio', 'N/A')
        # 股息殖利率
        div_yield = info.get('trailingAnnualDividendYield', info.get('yield', 'N/A'))
        
        # 配息月份獲取
        div_months = []
        try:
            dividends = etf.dividends
            if not dividends.empty:
                # 獲取最近一年的配息月份
                last_year = pd.Timestamp.now(tz=dividends.index.tz) - pd.Timedelta(days=365)
                recent_divs = dividends[dividends.index > last_year]
                div_months = sorted(list(set(recent_divs.index.month.tolist())))
        except:
            pass

        if expense != 'N/A' and expense is not None:
            expense = round(float(expense) * 100, 2)
        if div_yield != 'N/A' and div_yield is not None:
            div_yield = round(float(div_yield) * 100, 2)
            
        return {
            'expense': expense if expense is not None else 'N/A',
            'dividend_yield': div_yield if div_yield is not None else 'N/A',
            'dividend_months': div_months
        }
    except Exception as e:
        return {'turnover': 'N/A', 'expense': 'N/A', 'dividend_yield': 'N/A', 'dividend_months': []}

def is_alpha_vantage_failed():
    """檢查Alpha Vantage API是否已被標記為失敗"""
    return _ALPHA_VANTAGE_FAILED

# 快取設定
CACHE_DIR = 'cache'
CACHE_FILE = os.path.join(CACHE_DIR, 'alpha_vantage_cache.json')
CACHE_VALIDITY_DAYS = 7  # 快取有效期（天）

# 確保快取目錄存在（靜默）
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def is_local_environment():
    """檢查是否為本地環境（非 GitHub Actions）"""
    return not os.getenv('GITHUB_ACTIONS', False)

def should_use_cache():
    """決定是否使用快取機制 - 只在本地環境使用"""
    return is_local_environment()


def load_cache():
    """從 JSON 檔案讀取快取（僅限本地環境）"""
    if not should_use_cache():
        return {}
    
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            print(f"✅ 載入快取: {CACHE_FILE}")
            return cache
        except Exception as e:
            print(f"⚠️  快取讀取失敗: {e}，將重新獲取資料")
            return {}
    return {}


def save_cache(cache):
    """將快取寫入 JSON 檔案（僅限本地環境）"""
    if not should_use_cache():
        return
    
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        print(f"✅ 快取已保存: {CACHE_FILE}")
    except Exception as e:
        print(f"⚠️  快取保存失敗: {e}")


def is_cache_valid(cached_item):
    """檢查快取是否仍有效"""
    if 'timestamp' not in cached_item:
        return False
    
    cached_time = datetime.fromisoformat(cached_item['timestamp'])
    now = datetime.now()
    days_old = (now - cached_time).days
    
    return days_old < CACHE_VALIDITY_DAYS


def fetch_twse_price(ticker, start_date, end_date):
    """
    從 TWSE 官方 REST API 抓取台股 ETF 股價
    完全使用官方 API，不依賴任何第三方金融服務
    
    Args:
        ticker: 股票代碼（如 '0050.TW' 或 '0050'）
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 結束日期 (YYYY-MM-DD)
    
    Returns:
        pd.DataFrame: OHLCV 資料，index 為日期
    """
    
    # 新增本地快取：每支ETF一個CSV，僅補抓缺失天數
    ticker_clean = ticker.replace('.TW', '').strip()
    cache_dir = 'cache/twse'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    cache_file = os.path.join(cache_dir, f'{ticker_clean}.csv')

    # 讀取快取
    df_cache = None
    if os.path.exists(cache_file):
        try:
            df_cache = pd.read_csv(cache_file, parse_dates=['Date'], index_col='Date')
            df_cache = df_cache.sort_index()
        except Exception as e:
            print(f"⚠️  快取讀取失敗: {e}，將重新獲取資料")
            df_cache = None

    # 判斷快取範圍
    start_date_dt = pd.to_datetime(start_date)
    end_date_dt = pd.to_datetime(end_date)
    need_download = True
    all_data = []

    if df_cache is not None and not df_cache.empty:
        cache_start = df_cache.index.min()
        cache_end = df_cache.index.max()
        # 如果快取已經涵蓋所需範圍，直接回傳切片
        if cache_start <= start_date_dt and cache_end >= end_date_dt:
            print(f"♻️  {ticker} 使用本地快取 {cache_file} ({len(df_cache)} 天)")
            return df_cache.loc[start_date_dt:end_date_dt].copy()
        # 如果快取部分涵蓋，先收集已快取部分
        if cache_start <= end_date_dt and cache_end >= start_date_dt:
            df_in = df_cache.loc[start_date_dt:end_date_dt].copy()
            all_data.append(df_in)
            # 只補抓缺失區間
            if start_date_dt < cache_start:
                download_start = start_date
                download_end = (cache_start - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                print(f"  📥 {ticker} 補抓 {download_start}~{download_end} (前段)")
                df_pre = fetch_twse_price_no_cache(ticker, download_start, download_end)
                if not df_pre.empty:
                    all_data.insert(0, df_pre)
            if cache_end < end_date_dt:
                download_start = (cache_end + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                download_end = end_date
                print(f"  📥 {ticker} 補抓 {download_start}~{download_end} (後段)")
                df_post = fetch_twse_price_no_cache(ticker, download_start, download_end)
                if not df_post.empty:
                    all_data.append(df_post)
            if all_data:
                df_all = pd.concat(all_data).sort_index()
                df_all = df_all[~df_all.index.duplicated(keep='last')]
                # 更新快取
                df_all.to_csv(cache_file)
                print(f"♻️  {ticker} 快取已更新 {cache_file} ({len(df_all)} 天)")
                return df_all.loc[start_date_dt:end_date_dt].copy()
    # 沒有快取或完全沒涵蓋
    print(f"  📥 {ticker} 首次下載 {start_date}~{end_date}")
    df_new = fetch_twse_price_no_cache(ticker, start_date, end_date)
    if not df_new.empty:
        df_new.to_csv(cache_file)
        print(f"♻️  {ticker} 快取已建立 {cache_file} ({len(df_new)} 天)")
        return df_new.copy()
    print(f"  ❌ {ticker} 無資料")
    return pd.DataFrame()

# 在 fetch_twse_price_no_cache 外層加一個全域標記
TWSE_API_FAILED = False

def fetch_twse_price_no_cache(ticker, start_date, end_date):
    global TWSE_API_FAILED
    if TWSE_API_FAILED:
        print(f"  🚫 TWSE API 已標記為失敗，直接用 yfinance 備援 {ticker}")
        try:
            import yfinance as yf
            yf_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if not yf_df.empty:
                yf_df = yf_df[['Close', 'Open', 'High', 'Low', 'Volume']]
                if yf_df.index.name != 'Date':
                    yf_df.index.name = 'Date'
                print(f"  ✅ {ticker} yfinance備援成功 ({len(yf_df)} 天)")
                return yf_df
            else:
                print(f"  ❌ {ticker} yfinance也無資料")
        except Exception as e:
            print(f"  ❌ {ticker} yfinance備援失敗: {e}")
        return pd.DataFrame()
    
    ticker_clean = ticker.replace('.TW', '').strip()
    try:
        all_data = []
        start_date_dt = pd.to_datetime(start_date)
        end_date_dt = pd.to_datetime(end_date)
        current_date = start_date_dt
        while current_date <= end_date_dt:
            year = current_date.year
            month = current_date.month
            query_date = f"{year}{month:02d}01"
            url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
            params = {
                'response': 'json',
                'date': query_date,
                'stockNo': ticker_clean
            }
            try:
                max_retries = 2
                for retry in range(max_retries):
                    try:
                        response = requests.get(url, params=params, timeout=5, verify=False)
                        data = response.json()
                        break
                    except (requests.Timeout, requests.ConnectionError) as e:
                        if retry < max_retries - 1:
                            print(f"  ⏰ TWSE請求超時，重試中... ({retry+1}/{max_retries})")
                            time.sleep(1)
                            continue
                        else:
                            print(f"  ❌ TWSE請求失敗 (已重試{max_retries}次): {e}")
                            TWSE_API_FAILED = True
                            return fetch_twse_price_no_cache(ticker, start_date, end_date)
                    except Exception as e:
                        print(f"  ❌ TWSE請求異常: {e}")
                        TWSE_API_FAILED = True
                        return fetch_twse_price_no_cache(ticker, start_date, end_date)
                if data.get('data'):
                    for row in data['data']:
                        try:
                            date_str = row[0]
                            parts = date_str.split('/')
                            roc_year = int(parts[0])
                            gregorian_year = roc_year + 1911
                            gregorian_date_str = f"{gregorian_year}/{parts[1]}/{parts[2]}"
                            date = pd.to_datetime(gregorian_date_str)
                            if start_date_dt <= date <= end_date_dt:
                                all_data.append({
                                    'Date': date,
                                    'Open': float(row[3].replace(',', '')),
                                    'High': float(row[4].replace(',', '')),
                                    'Low': float(row[5].replace(',', '')),
                                    'Close': float(row[6].replace(',', '')),
                                    'Volume': int(row[1].replace(',', ''))
                                })
                        except (ValueError, IndexError) as e:
                            continue
            except requests.exceptions.RequestException as e:
                print(f"  ⚠️ {year}-{month:02d} 網路問題: {str(e)[:50]}...")
            except Exception as e:
                print(f"  ❌ {year}-{month:02d} 處理異常: {str(e)[:50]}...")
            try:
                if month == 12:
                    current_date = pd.to_datetime(f"{year+1}-01-01")
                else:
                    current_date = pd.to_datetime(f"{year}-{month+1:02d}-01")
                if current_date.year > 2030:
                    print(f"  ⚠️ 年份異常 ({current_date.year})，強制退出")
                    break
            except Exception as date_error:
                print(f"  ❌ 日期處理異常，強制退出: {date_error}")
                break
        if all_data:
            df = pd.DataFrame(all_data)
            df.set_index('Date', inplace=True)
            df = df.sort_index()
            df = adjust_for_stock_splits(df)
            print(f"  ✅ 獲取 {ticker} {len(df)} 天資料（TWSE 官方 API）")
            return df
        else:
            print(f"  ❌ {ticker} 無資料")
            return pd.DataFrame()
    except Exception as e:
        print(f"  ❌ {ticker} 下載失敗: {e}")
        return pd.DataFrame()

    # TWSE官方API失敗時自動用yfinance備援
    if df is None or df.empty or len(df) < 5:
        print(f"  ⚠️ {ticker} TWSE官方API無資料，嘗試用yfinance備援...")
        try:
            import yfinance as yf
            yf_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if not yf_df.empty:
                yf_df = yf_df[['Close', 'Open', 'High', 'Low', 'Volume']]
                if yf_df.index.name != 'Date':
                    yf_df.index.name = 'Date'
                print(f"  ✅ {ticker} yfinance備援成功 ({len(yf_df)} 天)")
                return yf_df
            else:
                print(f"  ❌ {ticker} yfinance也無資料")
        except Exception as e:
            print(f"  ❌ {ticker} yfinance備援失敗: {e}")
        return pd.DataFrame()

def fetch_us_stock_price(symbol, start_date, end_date, api_key=None):
    """
    從 Alpha Vantage 抓取美股股價（優先使用快取）
    
    Args:
        symbol: 股票代碼（如 'VOO', 'GSPC'）
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 結束日期 (YYYY-MM-DD)
        api_key: Alpha Vantage API key（若為 None 則使用預設）
    
    Returns:
        pd.DataFrame: OHLCV 資料，index 為日期
    """
    
    # 🚨 檢查Alpha Vantage API是否已被標記為失敗
    if is_alpha_vantage_failed():
        print(f"  🚫 跳過 {symbol} - Alpha Vantage API 已標記為失敗")
        return pd.DataFrame()
    
    if api_key is None:
        api_key = ALPHA_VANTAGE_API_KEY
    
    # 移除指數符號前綴
    if symbol.startswith('^'):
        symbol = symbol[1]  # 移除 ^
    
    # 檢查快取
    cache = load_cache()
    cache_key = f"av_{symbol}"
    
    if cache_key in cache:
        cached_item = cache[cache_key]
        if is_cache_valid(cached_item):
            print(f"  ♻️  從快取讀取 {symbol} 股價...")
            try:
                # 從快取恢復 DataFrame
                df_data = cached_item['data']
                df = pd.DataFrame(df_data)
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                
                # 篩選日期範圍
                start = pd.to_datetime(start_date)
                end = pd.to_datetime(end_date)
                df = df[(df.index >= start) & (df.index <= end)]
                
                print(f"  ✅ 從快取獲取 {symbol} {len(df)} 天資料")
                return df
            except Exception as e:
                print(f"  ⚠️  快取恢復失敗: {e}，重新獲取...")
    
    # 快取失效或不存在，從 API 獲取
    try:
        print(f"  📥 從 Alpha Vantage 下載 {symbol} 股價...")
        
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'TIME_SERIES_DAILY',
            'symbol': symbol,
            'outputsize': 'full',
            'apikey': api_key
        }
        
        response = requests.get(url, params=params, timeout=5)  # 5秒超時 - 適合API檢查
        data = response.json()
        
        # 🔧 Alpha Vantage 免費版限制：每秒最多1次請求
        time.sleep(2)  # 等待2秒，確保不超過API限制
        
        # 🚀 快速檢查 - 如果API有問題立刻放棄
        if not isinstance(data, dict):
            print(f"  ❌ {symbol} API 回應格式錯誤，立刻放棄")
            return pd.DataFrame()
            
        # 檢查 API 錯誤
        if 'Error Message' in data:
            print(f"  ❌ {symbol} API 錯誤: {data['Error Message']}，立刻放棄")
            return pd.DataFrame()
        
        if 'Note' in data:
            print(f"  ❌ {symbol} API 限制: {data['Note']}，立刻放棄")
            return pd.DataFrame()
            
        # 檢查關鍵字段 - Information 表示API配額問題
        if 'Information' in data:
            print(f"  ❌ {symbol} API 配額問題，立刻放棄")
            return pd.DataFrame()
        
        if 'Time Series (Daily)' not in data:
            print(f"  ❌ {symbol} 無資料或API問題，立刻放棄")
            print(f"     回應鍵: {list(data.keys())[:3]}")
            return pd.DataFrame()
        
        # 轉換為 DataFrame
        time_series = data['Time Series (Daily)']
        df_list = []
        
        for date_str, values in time_series.items():
            try:
                df_list.append({
                    'Date': date_str,
                    'Open': float(values['1. open']),
                    'High': float(values['2. high']),
                    'Low': float(values['3. low']),
                    'Close': float(values['4. close']),
                    'Volume': int(float(values['5. volume']))
                })
            except (KeyError, ValueError):
                continue
        
        if not df_list:
            print(f"  ❌ {symbol} 無法解析資料")
            return pd.DataFrame()
        
        df = pd.DataFrame(df_list)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        df = df.sort_index()
        
        # 保存到快取
        cache[cache_key] = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'data': df.reset_index().to_dict('records')  # 轉換為可序列化格式
        }
        save_cache(cache)
        
        # 篩選日期範圍
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        df = df[(df.index >= start) & (df.index <= end)]
        
        print(f"  ✅ 獲取 {symbol} {len(df)} 天資料（已快取）")
        return df
        
    except requests.exceptions.Timeout:
        print(f"  ⚡ {symbol} API 超時 (0.2秒) - 標記全局失敗")
        mark_alpha_vantage_failed()
        return pd.DataFrame()
    except requests.exceptions.ConnectionError:
        print(f"  ⚡ {symbol} 連線錯誤 - 標記全局失敗")
        mark_alpha_vantage_failed()
        return pd.DataFrame()
    except requests.exceptions.RequestException as e:
        print(f"  ⚡ {symbol} 網路錯誤 - 標記全局失敗: {e}")
        mark_alpha_vantage_failed()
        return pd.DataFrame()
    except Exception as e:
        print(f"  ⚡ {symbol} API 失敗 - 標記全局失敗: {e}")
        mark_alpha_vantage_failed()
        return pd.DataFrame()


def detect_stock_splits(df, split_threshold=-0.3):
    """
    檢測股票分割事件
    
    Args:
        df: 價格數據 DataFrame
        split_threshold: 分割檢測閾值（預設 -30%）
        
    Returns:
        list: 分割事件日期列表
    """
    if len(df) < 2:
        return []
    
    # 計算日報酬率
    daily_returns = df['Close'].pct_change()
    
    # 檢測異常跌幅（可能的分割事件）
    split_events = []
    for date, return_rate in daily_returns.items():
        if return_rate < split_threshold and not pd.isna(return_rate):
            split_events.append(date)
            print(f"  🔍 檢測到可能的分割事件: {date.strftime('%Y-%m-%d')} (跌幅: {return_rate:.1%})")
    
    return split_events


def adjust_for_stock_splits(df):
    """
    調整股票分割造成的價格失真
    
    Args:
        df: 原始價格數據
        
    Returns:
        pd.DataFrame: 調整後的價格數據
    """
    if df.empty:
        return df
    
    # 檢測分割事件
    split_events = detect_stock_splits(df)
    
    if not split_events:
        return df
    
    print(f"  🔧 調整 {len(split_events)} 個分割事件...")
    
    adjusted_df = df.copy()
    
    for split_date in split_events:
        try:
            # 獲取分割前後的價格
            split_idx = adjusted_df.index.get_loc(split_date)
            
            if split_idx > 0:
                before_price = adjusted_df['Close'].iloc[split_idx - 1]
                after_price = adjusted_df['Close'].iloc[split_idx]
                
                # 計算分割比例
                split_ratio = float(before_price / after_price)
                
                # 只有當比例在合理範圍內才調整（避免誤判）
                if 1.5 <= split_ratio <= 10:
                    print(f"    📊 {split_date.strftime('%Y-%m-%d')}: 調整比例 {split_ratio:.2f}:1")
                    
                    # 調整分割前的所有價格 (強制轉換資料類型避免 pandas dtype 衝突)
                    mask = adjusted_df.index < split_date
                    for col in ['Open', 'High', 'Low', 'Close']:
                        adjusted_df.loc[mask, col] = adjusted_df.loc[mask, col].astype(float) / split_ratio
                    
                    # 調整成交量（乘以分割比例）
                    adjusted_df.loc[mask, 'Volume'] = adjusted_df.loc[mask, 'Volume'].astype(float) * split_ratio
        
        except Exception as e:
            print(f"    ⚠️  調整 {split_date} 失敗: {e}")
            continue
    
    return adjusted_df


def is_us_stock(ticker):
    """
    判斷是否為美國本土股票（需用 Alpha Vantage）
    
    Args:
        ticker: 股票代碼
    
    Returns:
        bool: True 表示美股，False 表示台股
    """
    # 美股指數和本土 ETF
    us_symbols = ['^GSPC', 'GSPC', 'VOO']
    
    return ticker.upper() in us_symbols or (not ticker.endswith('.TW') and not ticker.isdigit())


def download_price_data(ticker, start_date=None, end_date=None, config_type='default'):
    """
    下載股價資料主入口
    """
    # 🚀 修正：針對 VOO, QQQ 等美股大盤標的，直接跳過 Alpha Vantage 使用 yfinance
    # 這樣可以避開 API 配額問題
    if ticker in ['VOO', 'QQQ', 'IVV', 'SPY']:
        print(f"📊 {ticker} 為美股標的，直接使用 yfinance 下載...")
        try:
            import yfinance as yf
            yf_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if not yf_df.empty:
                # yfinance 返回的是 MultiIndex 或單層 Index 視版本而定
                yf_df = yf_df[['Close', 'Open', 'High', 'Low', 'Volume']]
                # 確保索引為 Date 名稱
                if yf_df.index.name != 'Date': yf_df.index.name = 'Date'
                return yf_df
        except Exception as e:
            print(f"⚠️ {ticker} yfinance 下載失敗: {e}")
            # 失敗了再走原本流程嘗試 (通常也會失敗，但作為保險)
    
    # 原本的資料下載流程...
    if ticker.endswith('.TW'):
        # 台股 → TWSE
        df = fetch_twse_price(ticker, start_date, end_date)
    else:
        # 美股或指數 → Alpha Vantage
        df = fetch_us_stock_price(ticker, start_date, end_date)
    
    return df if df is not None else pd.DataFrame()


def set_alpha_vantage_key(api_key):
    """
    設定 Alpha Vantage API key
    
    Args:
        api_key: 你的 Alpha Vantage API key
    """
    global ALPHA_VANTAGE_API_KEY
    ALPHA_VANTAGE_API_KEY = api_key
    print(f"✅ Alpha Vantage API key 已設定")


def clear_cache():
    """清除所有快取"""
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            print(f"✅ 快取已清除: {CACHE_FILE}")
    except Exception as e:
        print(f"❌ 快取清除失敗: {e}")


def clear_cache_item(symbol):
    """清除特定股票的快取"""
    cache = load_cache()
    cache_key = f"av_{symbol}"
    if cache_key in cache:
        del cache[cache_key]
        save_cache(cache)
        print(f"✅ 已清除 {symbol} 的快取")
    else:
        print(f"⚠️  {symbol} 無快取")



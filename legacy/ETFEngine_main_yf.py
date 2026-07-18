import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.font_manager import FontProperties
import platform
import time
import os
import sys
import json
import warnings
import signal
from data_fetcher import download_price_data, set_alpha_vantage_key, download_etf_info_yfinance
from generate_all_charts import generate_performance_chart, plot_turnover_bar, plot_radar_chart, plot_price_trend, plot_multi_metrics_comparison, plot_dividend_calendar
from font_config import setup_chinese_font_enhanced, update_font_sizes, FONT_SIZE_CONFIG
from config_loader import load_etf_config

# 抑制警告
warnings.filterwarnings('ignore')

# 超時處理：60 分鐘（足以處理大量ETF的下載和分析）
def timeout_handler(signum, frame):
    print("\n❌ 程式執行超時（60 分鐘），強制退出")
    sys.exit(1)

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(5400)  # 90 分鐘

# 設定環境變數，避免 tkinter 衝突
os.environ['MPLBACKEND'] = 'Agg'

# 確保 matplotlib 使用正確後端
matplotlib.use('Agg', force=True)
plt.ioff()  # 關閉互動模式

# 設置中文字體和字體大小
setup_chinese_font_enhanced()
update_font_sizes()

# --- 歷史備份讀取 ---
def load_previous_csv(etf_type_prefix):
    """從上一版的 CSV 讀取備份資料 (股息、換手率等)"""
    try:
        path = f"Output_{etf_type_prefix.replace('_','')}etf_comparison_unified.csv"
        # 修正：由於資料夾路徑可能不同，嘗試多個可能路徑
        possible_paths = [
            os.path.join(f"Output_{etf_type_prefix.replace('_','')}_ETF", f"{etf_type_prefix}etf_comparison_unified.csv"),
            f"charts_output/{etf_type_prefix}etf_comparison_unified.csv"
        ]
        for p in possible_paths:
            if os.path.exists(p):
                df = pd.read_csv(p)
                return df.set_index('證券代碼')
    except:
        pass
    return None

# --- 控制開關 ---
# 🚀 修正：檢查是否在 GitHub Action 環境執行
import os
is_github_action = os.getenv('GITHUB_ACTIONS') == 'true'

# 本地預設畫圖 (True)，遠端預設不畫圖 (False)
GENERATE_CHARTS = not is_github_action

# 風險無風險報酬率（全域常數）
risk_free_rate = 0.015

def get_output_folder(config_type='active_etf'):
    """根據配置類型創建對應的輸出資料夾"""
    folder_mapping = {
        'active_etf': 'Output_Active_ETF',
        'dividend_etf': 'Output_Dividend_ETF',
        'high_dividend_etf': 'Output_HighDividend_ETF',
        'us_etf': 'Output_US_ETF',
        'industry_etf': 'Output_Industry_ETF',
        'market_cap_etf': 'Output_MarketCap_ETF'
    }
    
    folder_name = folder_mapping.get(config_type, f'Output_{config_type}')
    output_path = os.path.join(os.getcwd(), folder_name)
    
    # 如果資料夾不存在則創建
    if not os.path.exists(output_path):
        os.makedirs(output_path)
        print(f"✅ 創建輸出資料夾: {output_path}")
    
    return output_path


def find_common_start_date(etf_list, initial_start_date, end_date, config_type='default', use_fixed_start=False):
    """🔥 全新邏輯：不下載，直接計算日期
    
    Args:
        etf_list: ETF 列表
        initial_start_date: 初始起始日期  
        end_date: 結束日期
        use_fixed_start: 是否使用固定起始日期
    """
    from datetime import datetime, timedelta
    
    if use_fixed_start:
        # 主動式ETF：直接使用2025-07-22
        print(f"📅 主動式ETF使用固定起始日期: {initial_start_date}")
        print(f"📊 統一比較期間: {initial_start_date} 至 {end_date}")
        return initial_start_date
    else:
        # 其他ETF：今天倒推3年
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        three_years_ago = end_dt - timedelta(days=3*365)
        calculated_start = three_years_ago.strftime('%Y-%m-%d')
        print(f"� 其他ETF使用3年期間: {calculated_start} 至 {end_date}")
        print(f"📊 統一比較期間: {calculated_start} 至 {end_date}")
        return calculated_start

# --- 核心計算邏輯修正 ---

def calculate_returns(prices, annualize=True):
    try:
        if len(prices) < 2: return np.nan, np.nan
        p = prices.iloc[:, 0] if isinstance(prices, pd.DataFrame) else prices
        
        years = len(p) / 252
        total_ret = (p.iloc[-1] / p.iloc[0]) - 1
        
        if annualize and years > 0:
            return (p.iloc[-1] / p.iloc[0]) ** (1 / years) - 1, years
        return total_ret, years
    except:
        return np.nan, np.nan

def calculate_sharpe(cagr, volatility, rf=0.015):
    if pd.isna(volatility) or volatility == 0: return np.nan
    return (cagr - rf) / volatility

def calculate_max_drawdown(prices):
    p = prices.iloc[:, 0] if isinstance(prices, pd.DataFrame) else prices
    return ((p - p.cummax()) / p.cummax()).min()

def calculate_alpha_beta(etf_returns, benchmark_returns, rf_rate=0.015):
    """ 修正：計算更穩健的 Alpha/Beta """
    try:
        # 🚀 修正：對齊索引
        common = etf_returns.index.intersection(benchmark_returns.index)
        if len(common) < 20: 
            print(f"  ⚠️ 樣本數不足 ({len(common)})，無法計算 Alpha/Beta")
            return 0.0, 1.0
        
        e_ret, b_ret = etf_returns.loc[common], benchmark_returns.loc[common]
        
        # 統一處理為 numpy array 以避免協方差矩陣問題
        e_arr = e_ret.values.flatten()
        b_arr = b_ret.values.flatten()
        
        # Beta 計算
        cov_matrix = np.cov(e_arr, b_arr)
        if cov_matrix[1, 1] == 0: return 0.0, 1.0
        beta = cov_matrix[0, 1] / cov_matrix[1, 1]
        
        # 年化 Alpha (修正為更精確的 CAPM 公式)
        # e_annual: 本身年化報酬率
        # b_annual: 基準年化報酬率
        years = len(common) / 252
        e_cum = (1 + e_ret).prod() - 1
        b_cum = (1 + b_ret).prod() - 1
        
        e_annual = (1 + e_cum) ** (1/years) - 1 if years > 0 else 0
        b_annual = (1 + b_cum) ** (1/years) - 1 if years > 0 else 0
        
        # CAPM Alpha = 實際年化 - [無風險 + Beta * (基準年化 - 無風險)]
        alpha = (e_annual - (rf_rate + beta * (b_annual - rf_rate))) * 100
        
        return round(alpha, 2), round(beta, 2)
    except Exception as e:
        print(f"  ⚠️ Alpha/Beta 計算異常: {e}")
        return 0.0, 1.0

def get_etf_data(ticker, common_start_date, end_date, benchmark_returns, risk_free_rate, config, config_type='default', annualize=True, prev_df=None):
    try:
        ticker = ticker.strip()
        
        # 🚀 強制間隔，防止大量下載被 yfinance 封鎖
        time.sleep(1.5) 
        
        # 實作增量更新邏輯：檢查歷史資料
        cached_df = None
        if prev_df is not None and ticker in prev_df.index:
            try:
                # 解析歷史存儲的『趨勢數據』
                cache_str = prev_df.loc[ticker, '趨勢數據']
                if pd.notna(cache_str):
                    rows = [pair.split(':') for pair in cache_str.split('|')]
                    cached_df = pd.DataFrame(rows, columns=['Date', 'Close'])
                    cached_df['Date'] = pd.to_datetime(cached_df['Date'], format='%Y%m%d')
                    cached_df['Close'] = cached_df['Close'].astype(float)
                    cached_df.set_index('Date', inplace=True)
                    
                    last_cached_date = cached_df.index.max().strftime('%Y-%m-%d')
                    # 如果緩存到昨天為止，且我們需要到今天，則只需要抓取從最後日期開始的新數據
                    if last_cached_date < end_date:
                        print(f"  📥 {ticker} 發現緩存 (至 {last_cached_date})，僅抓取新數據 (yfinance)... ")
                        import yfinance as yf
                        tk = yf.Ticker(ticker)
                        new_data = tk.history(start=last_cached_date, end=end_date)
                        
                        if not new_data.empty:
                            # 🚀 修正：使用更穩健的屬性轉換方式處理時區
                            try:
                                new_data.index = pd.to_datetime(new_data.index).tz_localize(None)
                            except:
                                pass
                            # 合併並去重
                            df = pd.concat([cached_df, new_data[['Close']]])
                            df = df[~df.index.duplicated(keep='last')].sort_index()
                        else:
                            df = cached_df
                    else:
                        print(f"  ✅ {ticker} 緩存已是最新")
                        df = cached_df
            except Exception as e:
                print(f"  ⚠️ {ticker} 緩存讀取失敗: {e}")
                df = download_price_data(ticker, start_date=common_start_date, end_date=end_date, config_type=config_type)
        else:
            # 無緩存，全量下載 (🚀 統一使用 yfinance)
            print(f"  📡 {ticker} 無緩存，全量下載中...")
            import yfinance as yf
            tk = yf.Ticker(ticker)
            df = tk.history(start=common_start_date, end=end_date)
            if not df.empty:
                try:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                except:
                    pass

        if df is None or df.empty or len(df) < 5: 
            print(f"  ⚠️ {ticker} 資料抓取為空")
            return None
        
        # 確保價格欄位名稱一致性
        if 'Close' not in df.columns and 'Adj Close' in df.columns:
            df['Close'] = df['Adj Close']
        
        prices = df['Close']
        returns = prices.pct_change().dropna()
        
        # 1. 績效計算
        cagr, years = calculate_returns(prices, annualize=annualize)
        mdd = calculate_max_drawdown(prices)
        vol = returns.std() * np.sqrt(252)
        sharpe = calculate_sharpe(cagr, vol, risk_free_rate)
        
        # 2. Alpha/Beta
        alpha, beta = calculate_alpha_beta(returns, benchmark_returns, risk_free_rate)
        
        # 3. 追蹤誤差
        te = np.nan
        if benchmark_returns is not None:
            common = returns.index.intersection(benchmark_returns.index)
            if len(common) > 10:
                te = (returns.loc[common] - benchmark_returns.loc[common]).std() * np.sqrt(252)

        # 4. 獲取配置項 (股息、費用等)
        yf_info = download_etf_info_yfinance(ticker)
        
        # 讀取備份 (防止 yfinance 故障)
        prev_row = prev_df.loc[ticker] if (prev_df is not None and ticker in prev_df.index) else None

        # 🚀 徹底移除換手率更新邏輯
        # turnover = yf_info['turnover']
        # if turnover == 'N/A' and prev_row is not None:
        #     turnover = prev_row.get('換手率 (%)', 'N/A')
        # if turnover == 'N/A':
        #     turnover = config.get('turnover_ratio', {}).get(ticker, 'N/A')
            
        # 管理費
        expense = yf_info['expense']
        if expense == 'N/A' and prev_row is not None:
            expense = prev_row.get('管理費 (%)', 'N/A')
        if expense == 'N/A':
            expense = config.get('expense_ratio', {}).get(ticker, 'N/A')
            
        # 股息殖利率
        div_yield = yf_info['dividend_yield']
        if div_yield == 'N/A' and prev_row is not None:
            div_yield = prev_row.get('股息殖利率 (%)', 'N/A')
        if div_yield == 'N/A':
            div_dict = config.get('dividend', config.get('devidend', {}))
            div_yield = div_dict.get(ticker, 'N/A')
        
        # 取得名稱
        etf_name = '未知'
        for item in config.get('etf_list', []):
            t = item.get('ticker') if isinstance(item, dict) else item[0]
            if t == ticker:
                etf_name = item.get('name') if isinstance(item, dict) else item[1]
                break

        # 整理結果
        result = {
            '證券代碼': ticker,
            '名稱': etf_name,
            '數據天數': len(df),
            '資料期間 (年)': round(years, 2),
            '漲幅': round(cagr * 100, 2) if not pd.isna(cagr) else 0,
            'Alpha': round(alpha, 2) if not pd.isna(alpha) else 0,
            'Beta': round(beta, 2) if not pd.isna(beta) else 1,
            '夏普比率': round(sharpe, 2) if not pd.isna(sharpe) else 0,
            '年化波動率 (%)': round(vol * 100, 2) if not pd.isna(vol) else 0,
            '最大回撤 (%)': round(mdd * 100, 2) if not pd.isna(mdd) else 0,
            '追蹤誤差': round(te * 100, 2) if not pd.isna(te) else 0,
            '管理費 (%)': expense,
            '股息殖利率 (%)': div_yield,
            '_div_months': yf_info['dividend_months'], # 私有欄位用於繪製配息表
            '_price_data': df
        }
        
        # 🚀 新增：將股價序列(Normalized to 100) 扁平化為字串存入 CSV 供 PHP 繪圖
        # 為了對齊，我們將這段時間的價格全部轉為 "起始點=100" 的累計報酬
        p_series = df['Close']
        normalized_series = (p_series / p_series.iloc[0] * 100).round(2)
        # 格式：日期:值|日期:值
        price_str = "|".join([f"{d.strftime('%Y%m%d')}:{v}" for d, v in normalized_series.items()])
        result['趨勢數據'] = price_str

        return result
    except Exception as e:
        print(f"❌ {ticker} 分析出錯: {e}")
        return None

# --- 主程式與流程控制 ---

def run_engine_for_config(config_type):
    """將原本的主程式邏輯封裝成函數，方便批次執行"""
    print(f"\n🚀 開始處理類別: {config_type}")
    try:
        config = load_etf_config(config_type)
    except Exception as e:
        print(f"❌ 無法載入配置 {config_type}: {e}")
        return

    today = datetime.now()
    latest_date = today.strftime('%Y-%m-%d')
    start_date = (today - timedelta(days=3*365)).strftime('%Y-%m-%d')
    if config_type == 'active_etf': start_date = '2025-07-22'
    
    # 建立資料夾
    output_folder = get_output_folder(config_type)
    
    # Set file prefix based on config type
    if config_type == 'active_etf':
        etf_type_prefix = 'Active_'
    elif config_type == 'high_dividend_etf':
        etf_type_prefix = 'HighDividend_'
    elif config_type == 'industry_etf':
        etf_type_prefix = 'Industry_'
    elif config_type == 'market_cap_etf':
        etf_type_prefix = 'MarketCap_'
    elif config_type == 'us_etf':
        etf_type_prefix = 'US_'
    else:
        etf_type_prefix = f"{config_type.capitalize()}_"

    # 0. 讀取歷史備份
    prev_df = load_previous_csv(etf_type_prefix)

    # 🚀 修正：為了讓 PHP 繪圖，每個類別的 CSV 都要包含 0050 的趨勢作為 Benchmark
    # 先初始化為空，確保在 yfinance 失敗時不會噴 NoneType 錯誤
    benchmark_price_str = ""
    benchmark_returns = None
    
    # 1. 下載基準 0050 (🚀 統一使用 yfinance 抓取 0050)
    print(f"📡 正在抓取 0050 基準數據 ({start_date} to {latest_date})...")
    import yfinance as yf
    try:
        tk_0050 = yf.Ticker("0050.TW")
        benchmark_df = tk_0050.history(start=start_date, end=latest_date)
        if not benchmark_df.empty:
            # 使用 pd.to_datetime 強制轉換索引並移除時區
            benchmark_df.index = pd.to_datetime(benchmark_df.index).tz_localize(None)
            benchmark_returns = benchmark_df['Close'].pct_change().dropna()
            
            b_p = benchmark_df['Close']
            b_norm = (b_p / b_p.iloc[0] * 100).round(2)
            benchmark_price_str = "|".join([f"{d.strftime('%Y%m%d')}:{v}" for d, v in b_norm.items()])
            print(f"✅ 基準 (0050) 下載完成客，共 {len(benchmark_df)} 筆資料")
        else:
            print("⚠️ 警告：0050 數據內容為空")
            benchmark_df = pd.DataFrame()
    except Exception as e:
        print(f"❌ 抓取 0050 基準失敗: {e}")
        benchmark_df = pd.DataFrame()

    # 2. 跑所有 ETF 循環
    results = []
    etf_data_map = {}
    should_annualize = (config_type != 'active_etf')

    # 🚀 修正：為了讓 PHP 繪圖，每個類別的 CSV 都要包含 0050 的趨勢作為 Benchmark
    # 我們將基準數據 (0050) 的 Normalized 數值加入到 result 字典中
    benchmark_price_str = ""
    if benchmark_returns is not None and not benchmark_df.empty:
        b_p = benchmark_df['Close']
        b_norm = (b_p / b_p.iloc[0] * 100).round(2)
        benchmark_price_str = "|".join([f"{d.strftime('%Y%m%d')}:{v}" for d, v in b_norm.items()])

    for item in config['etf_list']:
        ticker = item.get('ticker') if isinstance(item, dict) else item[0]
        data = get_etf_data(ticker, start_date, latest_date, benchmark_returns, 0.015, config, config_type, should_annualize, prev_df)
        if data:
            results.append(data)
            etf_data_map[ticker] = data['_price_data']

    # 3. 儲存與繪圖
    if results:
        df_final = pd.DataFrame(results)
        
        # 🚀 修正：為了讓 PHP 繪圖，每個類別的 CSV 都要包含 0050 的趨勢作為 Benchmark
        # 將第一列設為 0050 基準資料
        benchmark_row = {
            '證券代碼': '0050.TW',
            '名稱': '大盤基準 (0050)',
            '數據天數': len(benchmark_df) if not benchmark_df.empty else 0,
            '資料期間 (年)': round(len(benchmark_df)/252, 2) if not benchmark_df.empty else 0,
            '漲幅': 0.0, # 基準漲幅設為 0 或實際漲幅，此處設為 0 以作為 0 準位
            'Alpha': 0.0,
            'Beta': 1.0,
            '夏普比率': 0.0,
            '年化波動率 (%)': 0.0,
            '最大回撤 (%)': 0.0,
            '追蹤誤差': 0.0,
            '管理費 (%)': 0.0,
            '股息殖利率 (%)': 0.0,
            '_div_months': '[]',
            '趨勢數據': benchmark_price_str,
            '基準趨勢': benchmark_price_str
        }
        
        # 將 0050 插入原本結果的最前面
        df_benchmark = pd.DataFrame([benchmark_row])
        df_final = pd.concat([df_benchmark, df_final], ignore_index=True)
        
        # 確保基準趨勢數據填滿每一行（方便 PHP 讀取）
        df_final['基準趨勢'] = benchmark_price_str
        
        csv_save = df_final.drop(columns=['_price_data'], errors='ignore')
        
        # 儲存到 etf.php 預期整合的路徑 charts_output/
        unified_csv_name = f'{etf_type_prefix}etf_comparison_unified.csv'
        csv_path = os.path.join(output_folder, unified_csv_name)
        # 在 CSV 中保存一行 0050 的基準數據，方便 PHP 讀取
        csv_save['基準趨勢'] = benchmark_price_str
        csv_save.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        charts_output_folder = os.path.join(os.getcwd(), 'charts_output')
        if not os.path.exists(charts_output_folder): os.makedirs(charts_output_folder)
        github_ready_csv_path = os.path.join(charts_output_folder, unified_csv_name)
        csv_save.to_csv(github_ready_csv_path, index=False, encoding='utf-8-sig')
        
        if GENERATE_CHARTS:
            try:
                plot_dividend_calendar(results, etf_type_prefix, output_folder)
                ret_1y_dict = {row['證券代碼']: row['漲幅'] for _, row in df_final.iterrows()}
                ret_3y_dict = {row['證券代碼']: row.get('漲幅', 0) for _, row in df_final.iterrows()} 
                generate_performance_chart(df_final, ret_1y_dict, ret_3y_dict, None, etf_type_prefix, output_folder)
                plot_radar_chart(df_final, config, etf_type_prefix, output_folder)
                plot_multi_metrics_comparison(df_final, etf_type_prefix, output_folder)
                plot_price_trend(config['etf_list'], config, start_date, latest_date, etf_type_prefix, output_folder, etf_data_dict=etf_data_map)
                print(f"🎨 {config_type} 圖表生成成功！")
            except Exception as e:
                print(f"⚠️ {config_type} 繪圖流程失敗: {e}")

if __name__ == '__main__':
    print("📂 讀取 default_portfolio.json 執行全自動掃描並產出所有類別...")
    try:
        # 🚀 修正：default_portfolio 只是用來獲取 include 清單，不應使用 load_etf_config 進行校驗
        # 因為 load_etf_config 會檢查 etf_list 等欄位，而 portfolio 檔沒有這些欄位。
        portfolio_path = os.path.join('etf_configs', 'default_portfolio.json')
        with open(portfolio_path, 'r', encoding='utf-8') as f:
            portfolio = json.load(f)
            
        configs_to_run = list(set(portfolio.get('include', []))) # 使用 set 去重
        print(f"📋 預計執行類別: {configs_to_run}")
        for cfg in configs_to_run:
            run_engine_for_config(cfg)
    except Exception as e:
        print(f"❌ 執行失敗，請檢查配置檔。錯誤: {e}")
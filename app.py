import yfinance as yf
import streamlit as st
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import requests
import urllib3
import warnings 
import time
from datetime import datetime

# 忽略警告
warnings.filterwarnings('ignore')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 頁面配置 ---
st.set_page_config(page_title="台股極短線動能掃描", layout="wide")
st.title("台股極短線衝浪：法人籌碼與進階回測版")

# --- 1. 動態爬取全市場股票代碼 + 名稱與產業 (快取 1 天) ---
@st.cache_data(ttl=86400, show_spinner=False)
def get_all_taiwan_stocks_info():
    stock_dict = {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    for mode, suffix in [(2, '.TW'), (4, '.TWO')]:
        try:
            url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
            res = requests.get(url, headers=headers, verify=False)
            res.encoding = 'big5'
            rows = res.text.split('<tr')[1:] 
            for row in rows:
                if '<td' not in row: continue
                cols = row.split('<td')
                if len(cols) > 5: # 確保欄位足夠
                    first_col = cols[1].split('>')[1].split('<')[0].strip()
                    industry = cols[5].split('>')[1].split('<')[0].strip()
                    code_name = first_col.split('　')
                    if len(code_name) == 2:
                        code, name = code_name
                        if len(code) == 4 and code.isdigit():
                            stock_dict[f"{code}{suffix}"] = {
                                "name": name,
                                "industry": industry if industry else "其他"
                            }
        except Exception:
            pass
    return stock_dict

# --- 2. 獲取當日三大法人籌碼資料 (快取 1 小時) ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_institutional_chips():
    chip_data = {}
    try:
        res = requests.get("https://openapi.twse.com.tw/v1/fund/T86_ALL", timeout=10)
        if res.status_code == 200:
            for item in res.json():
                code = item.get('Code', '')
                if len(code) == 4:
                    fi_diff = float(item.get('ForeignInvestorDifference', '0').replace(',', ''))
                    it_diff = float(item.get('InvestmentTrustDifference', '0').replace(',', ''))
                    chip_data[f"{code}.TW"] = {
                        "foreign_buy": fi_diff,
                        "trust_buy": it_diff
                    }
    except Exception:
        pass
        
    if not chip_data:
        get_institutional_chips.clear()
        
    return chip_data

# --- 3. 批量下載歷史數據 (yfinance 引擎，快取 1 小時) ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bulk_market_data(tickers):
    # 一次性下載所有股票過去一年的數據
    return yf.download(tickers, period="1y", group_by='ticker', progress=False)

# --- 4. 進階歷史回測引擎 (含盈虧比與MDD) ---
def calculate_advanced_backtest(df, vol_mult, rsi_min, rsi_max, pct_threshold, require_ema_bull, holding_days):
    trades = []
    max_drawdown = 0.0 # 最大回撤
    
    for i in range(20, len(df) - 1): 
        is_signal = (
            (float(df['Volume'].iloc[i]) > float(df['Vol_Avg5'].iloc[i]) * vol_mult) and 
            (rsi_min < float(df['RSI9'].iloc[i]) < rsi_max) and 
            (float(df['Pct_Change'].iloc[i]) > pct_threshold)
        )
        if require_ema_bull:
            is_signal = is_signal and (float(df['Close'].iloc[i]) > float(df['EMA5'].iloc[i])) and \
                        (float(df['EMA3'].iloc[i]) > float(df['EMA20'].iloc[i]))
            
        if is_signal and (i + holding_days < len(df)):
            entry_price = float(df['Close'].iloc[i])
            exit_price = float(df['Close'].iloc[i + holding_days])
            ret = ((exit_price - entry_price) / entry_price) * 100
            trades.append(ret)
            
            # 計算持有期間的 MDD (最大潛在虧損)
            lowest_price = float(df['Low'].iloc[i : i + holding_days + 1].min())
            drawdown = ((lowest_price - entry_price) / entry_price) * 100
            if drawdown < max_drawdown:
                max_drawdown = drawdown
                
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    
    # 計算盈虧比 (賺錢的平均幅度 / 賠錢的平均幅度)
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else (99.99 if avg_win > 0 else 0.0)
    avg_ret = (sum(trades) / len(trades)) if trades else 0.0
    
    return len(trades), win_rate, avg_ret, pl_ratio, max_drawdown

# --- 5. 控制台與動態參數設定 ---
st.sidebar.markdown("### ⚙️ 系統控制台")

scan_limit = st.sidebar.slider("掃描數量上限", 10, 1750, 1750)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎛️ 濾網參數微調 (即時套用)")

with st.sidebar.expander("點此展開並調整短線策略參數", expanded=True):
    vol_mult = st.number_input(
        "🔥 爆量倍數 (預設 2.0)", 
        min_value=1.0, max_value=10.0, value=2.0, step=0.1,
        help="【參數說明】當日成交量必須是「過去5日均量」的幾倍。\n\n📉 調低(如 1.5)：條件變寬鬆，能抓到溫和起漲的股票。\n📈 調高(如 3.0)：極度嚴格，只抓主力不計代價瘋狂倒錢的極端爆量股。"
    )
    
    rsi_min, rsi_max = st.slider(
        "📈 RSI(9) 動能區間", 
        min_value=0, max_value=100, value=(65, 85), step=1,
        help="【參數說明】RSI 代表短線的熱度。\n\n📉 調低範圍(如 50~70)：抓剛從底部翻揚、還沒引起市場注意的股票。\n📈 調高範圍(如 70~90)：抓已經在飆、強勢噴出的妖股，但追高被套的風險較大。"
    )
    
    pct_threshold = st.number_input(
        "🚀 當日最低漲幅 % (預設 4.0)", 
        min_value=0.0, max_value=10.0, value=4.0, step=0.5,
        help="【參數說明】當天必須拉出幾 % 的實體紅 K 線。\n\n📉 調低(如 2.0)：抓偷偷吃貨、慢慢爬的股票。\n📈 調高(如 7.0)：只抓半根停板或即將漲停的極度強勢股。"
    )
    
    require_ema_bull = st.checkbox(
        "🛡️ 開啟超短線均線防護", 
        value=True,
        help="【參數說明】打勾代表：股價必須站上 5 日線，且 3 日線 > 20 日線。\n取消打勾：代表放棄均線判斷，專心抓跌深爆量反彈、或無畏均線反壓的異動股。"
    )
    
st.sidebar.markdown("---")
require_chip_buy = st.checkbox(
    "💰 強制法人跟車 (外資或投信買超)", 
    value=False,
    help="打勾後，只有在最新交易日「外資或投信呈現淨買超」的股票才會入選。"
)
holding_days = st.number_input("⏱️ 回測預計持有天數", min_value=1, max_value=20, value=3, step=1)

# --- 6. 執行掃描邏輯 ---
if st.sidebar.button("🚀 開始全火力掃描", type="primary", use_container_width=True):
        
    with st.status("🔍 正在執行雷達掃描與大數據回測...", expanded=True) as status:
        stock_info_dict = get_all_taiwan_stocks_info()
        tickers = list(stock_info_dict.keys())[:scan_limit]
        
        chip_data = get_institutional_chips()
        
        st.write(f"3. 正在從 Yahoo Finance 批量下載 {len(tickers)} 檔股票數據 (約需 1~2 分鐘)...")
        data = fetch_bulk_market_data(tickers)

        hits = []
        progress_bar = st.progress(0)
        
        for idx, ticker in enumerate(tickers):
            
            if ticker not in data: continue
            df = data[ticker].copy().dropna()
            if len(df) < 20: 
                progress_bar.progress((idx + 1) / len(tickers))
                continue
            
            try:
                # 籌碼過濾 (如果開啟)
                stock_chip = chip_data.get(ticker, {"foreign_buy": 0, "trust_buy": 0})
                if require_chip_buy:
                    if stock_chip["foreign_buy"] <= 0 and stock_chip["trust_buy"] <= 0:
                        progress_bar.progress((idx + 1) / len(tickers))
                        continue # 這裡的 time.sleep 也拿掉了

                # 指標計算
                df['EMA3'] = ta.ema(df['Close'], length=3).round(2)
                df['EMA5'] = ta.ema(df['Close'], length=5).round(2)
                df['EMA20'] = ta.ema(df['Close'], length=20).round(2)
                df['RSI9'] = ta.rsi(df['Close'], length=9).round(2)
                df['Vol_Avg5'] = df['Volume'].rolling(window=5).mean().round(2)
                df['Pct_Change'] = (df['Close'].pct_change() * 100).round(2)
                
                # 訊號判斷
                ema_condition = True
                if require_ema_bull:
                    ema_condition = (float(df['Close'].iloc[-1]) > float(df['EMA5'].iloc[-1])) and \
                                    (float(df['EMA3'].iloc[-1]) > float(df['EMA20'].iloc[-1]))
                
                is_breakout = (
                    ema_condition and 
                    (float(df['Volume'].iloc[-1]) > float(df['Vol_Avg5'].iloc[-1]) * vol_mult) and 
                    (rsi_min < float(df['RSI9'].iloc[-1]) < rsi_max) and 
                    (float(df['Pct_Change'].iloc[-1]) > pct_threshold)
                )
                
                if is_breakout:
                    # 執行進階回測
                    t_count, w_rate, a_ret, pl_ratio, mdd = calculate_advanced_backtest(
                        df, vol_mult, rsi_min, rsi_max, pct_threshold, require_ema_bull, holding_days
                    )
                    
                    hits.append({
                        "ticker": ticker, 
                        "info": stock_info_dict.get(ticker, {"name": "未知", "industry": "未知"}),
                        "chip": stock_chip,
                        "df": df, 
                        "rsi": float(df['RSI9'].iloc[-1]),
                        "bt_count": t_count,
                        "bt_win_rate": w_rate,
                        "bt_avg_ret": a_ret,
                        "bt_pl_ratio": pl_ratio,
                        "bt_mdd": mdd
                    })
            except Exception:
                pass
                
            progress_bar.progress((idx + 1) / len(tickers))
            # 這裡的 time.sleep 也徹底刪除了，現在迴圈會用光速跑完！

        status.update(label="✅ 掃描與回測完成！", state="complete", expanded=False)

    # --- 7. 排序並顯示結果 ---
    if hits:
        # 排序：盈虧比優先，接著看勝率
        hits_sorted = sorted(hits, key=lambda x: (x['bt_pl_ratio'], x['bt_win_rate']), reverse=True)[:10]
        st.subheader(f"🎯 發現 {len(hits)} 檔極短線爆發，為您精選最強 {len(hits_sorted)} 檔標的")
        
        for h in hits_sorted:
            last_price = round(float(h['df']['Close'].iloc[-1]), 2)
            sl_price = round(float(h['df']['Low'].iloc[-1]), 2)
            tp_price = round(last_price * 1.07, 2)
            
            # 轉換籌碼顯示單位 (張)
            f_buy_lots = round(h['chip']['foreign_buy'] / 1000, 2)
            t_buy_lots = round(h['chip']['trust_buy'] / 1000, 2)
            chip_text = f"外資: {f_buy_lots} 張 | 投信: {t_buy_lots} 張"
            
            win_color = "green" if h['bt_win_rate'] >= 60 else ("orange" if h['bt_win_rate'] >= 40 else "red")
            pl_color = "green" if h['bt_pl_ratio'] >= 1.5 else "white"

            with st.container(border=True):
                col1, col2 = st.columns([2, 3])
                
                with col1:
                    # 顯示產業與股票名稱
                    st.markdown(f"#### 🏷️ `[{h['info']['industry']}]` **{h['info']['name']} ({h['ticker']})**")
                    st.markdown(f"""
                    **籌碼動向**：`{chip_text}`
                    
                    ### ⚡ 交易指令
                    - 🟢 進場位： `{last_price:.2f}`
                    - 🔴 停損位： `{sl_price:.2f}`
                    
                    ---
                    ### 📊 進階歷史回測 (持倉 {holding_days} 天)
                    過去出現訊號 **{h['bt_count']}** 次
                    - 🏆 **歷史勝率**：<span style='color:{win_color}; font-weight:bold;'>{h['bt_win_rate']:.2f}%</span>
                      <br><span style='color:#aaaaaa; font-size:14px;'>*(只要進場，最終獲利出場的機率)*</span>
                    - ⚖️ **盈虧比**：<span style='color:{pl_color}; font-weight:bold;'>{h['bt_pl_ratio']:.2f}</span>
                      <br><span style='color:#aaaaaa; font-size:14px;'>*(平均賺的錢 ÷ 平均賠的錢，> 1.5 為極佳)*</span>
                    - 📉 **最大回撤 (MDD)**：`{h['bt_mdd']:.2f}%`
                      <br><span style='color:#aaaaaa; font-size:14px;'>*(持倉期間曾遭遇的最大帳面跌幅，用來衡量洗盤深度)*</span>
                    """, unsafe_allow_html=True)
                
                with col2:
                    df_p = h['df'].tail(40)
                    fig = go.Figure(data=[go.Candlestick(
                        x=df_p.index, open=df_p['Open'], high=df_p['High'], 
                        low=df_p['Low'], close=df_p['Close'], name="K線"
                    )])
                    fig.add_hline(y=sl_price, line_dash="dash", line_color="red", 
                                  annotation_text=f"防守 {sl_price:.2f}", annotation_position="bottom left")
                    
                    fig.update_layout(height=280, margin=dict(l=0,r=0,t=0,b=0), 
                                      xaxis_rangeslider_visible=False, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("今日暫無符合您目前參數設定的標的。您可以嘗試放寬條件，或是取消勾選「強制法人跟車」。")
import yfinance as yf
import streamlit as st
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import requests
import urllib3
import warnings 

# 忽略警告
warnings.filterwarnings('ignore')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 頁面配置 ---
st.set_page_config(page_title="台股極短線動能掃描", layout="wide")
st.title("台股極短線衝浪：高階實戰濾網版 🛡️")

with st.expander("📖 系統使用說明與進階參數指南 (初次使用請點此展開)", expanded=False):
    st.markdown("""
    ### 🛡️ 三大專業級濾網：選股階段的防護罩

    **1. 正乖離率控制 (Bias)**
    *   **白話解釋：** 股價（收盤價）距離 5 日均線有多遠。就像放風箏，風箏（股價）飛得離手（5日線）太遠，線就容易斷（容易引發獲利了結的回檔賣壓）。
    *   **如何使用：** 
        *   在系統參數中設定一個上限（例如 8% 或 10%）。
        *   當系統掃描到一檔爆量強勢股時，如果它已經連續拉了兩根漲停，乖離率通常會過高，這時系統會將其剔除。
    *   **實戰意義：** 確保您買進的位置，距離防守點（5日線）不會太遠。這樣即使判斷錯誤發生回檔，也不會因為買在「半山腰」而承受過巨大的未實現虧損。

    **2. 真實波動幅度 (ATR)**
    *   **白話解釋：** 衡量這檔股票近期的「活潑程度」。ATR / 股價 > 3%，代表這檔股票平均每天的振幅有超過 3%。
    *   **如何使用：**
        *   極短線衝浪最怕買到「死魚股」（買進後一整天價格都不動，浪費資金與時間效率）。
        *   透過設定 ATR 下限（例如 3% 或 4%），系統只會挑選出主力正在積極作價、股性活潑、上下震幅夠大的標的。
    *   **實戰意義：** 確保進場後，股票有足夠的動能可以迅速拉開獲利空間。

    **3. 盤整量縮後爆量 (量價配合型態)**
    *   **白話解釋：** 尋找「平時沒人理，今天突然大爆發」的股票。
    *   **如何使用：**
        *   這是一個型態辨識開關。前 3 天的均量小於 20 日均量，代表散戶沒興趣、籌碼正在安靜沉澱（無賣壓）。
        *   今天的量卻是近 5 日最大，這叫「旱地拔蔥」或「第一根帶量起漲」。
    *   **實戰意義：** 這是極短線勝率最高的型態之一。因為這代表大資金剛剛點火，且上方沒有昨天或前天剛套牢的散戶急著賣出解套，上漲阻力最小。

    ---

    ### ⚡ 交易指令執行須知：進出場的鐵血紀律
    > 極短線交易的成敗，往往不在選股，而在於「執行的紀律」。

    **1. 進場價 (明日開盤價，跳空 > 9.5% 放棄)**
    *   **如何使用：**
        *   今天盤後系統選出股票後，明天早上 09:00 開盤時的價格，就是您的進場價。
        *   **為什麼 >9.5% 要放棄？** 如果這檔股票太強勢，一開盤就跳空大漲 9.5%（逼近台股 10% 漲停板），代表「潛在獲利空間只剩 0.5%，但往下回檔的風險高達 10% 以上」。這是一筆盈虧比極差的交易。
    *   **實戰意義：** 寧可錯過，絕不追在毫無肉可以吃的漲停板邊緣。

    **2. 停損價 (進場價的 -5%)**
    *   **如何使用：** 這是整套系統的保命符。停損的基準是「您實際買到的開盤價」，而不是昨天的收盤價。
    *   **實務操作：** 假設您明天以 100 元開盤價買進，請立刻（真的是立刻）在券商 APP 設定一筆「觸價單（洗價單）」，設定條件為：當價格 <= 95 元時，自動以市價（或跌停價）賣出。
    *   **實戰意義：** 絕不盯盤猶豫，絕不心存僥倖凹單。只要打到 -5% 停損線，代表這筆突破是「假突破」，請立刻把資金抽出來，尋找下一個機會。
    """)

# --- 1. 動態爬取全市場股票代碼 (快取 1 天) ---
@st.cache_data(ttl=86400, show_spinner=False)
def get_all_taiwan_stocks_info():
    stock_dict = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for mode, suffix in [(2, '.TW'), (4, '.TWO')]:
        try:
            res = requests.get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}", headers=headers, verify=False)
            res.encoding = 'big5'
            for row in res.text.split('<tr')[1:]:
                if '<td' not in row: continue
                cols = row.split('<td')
                if len(cols) > 5:
                    code_name = cols[1].split('>')[1].split('<')[0].strip().split('　')
                    if len(code_name) == 2 and code_name[0].isdigit():
                        stock_dict[f"{code_name[0]}{suffix}"] = {
                            "name": code_name[1], "industry": cols[5].split('>')[1].split('<')[0].strip() or "其他"
                        }
        except Exception:
            pass
    return stock_dict

# --- 2. 獲取當日三大法人籌碼資料 ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_institutional_chips():
    chip_data = {}
    try:
        res_tw = requests.get("https://openapi.twse.com.tw/v1/fund/T86_ALL", timeout=5)
        for item in res_tw.json() if res_tw.status_code == 200 else []:
            if len(item.get('Code', '')) == 4:
                chip_data[f"{item['Code']}.TW"] = {
                    "foreign_buy": float(item.get('ForeignInvestorDifference', '0').replace(',', '')),
                    "trust_buy": float(item.get('InvestmentTrustDifference', '0').replace(',', ''))
                }
    except: pass
    try:
        res_otc = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_3itrade_hedge", timeout=5)
        for item in res_otc.json() if res_otc.status_code == 200 else []:
            if len(item.get('SecuritiesCompanyCode', '')) == 4:
                chip_data[f"{item['SecuritiesCompanyCode']}.TWO"] = {
                    "foreign_buy": float(item.get('ForeignInvestorsBuySellDifference', '0').replace(',', '')),
                    "trust_buy": float(item.get('SecuritiesInvestmentTrustCompaniesBuySellDifference', '0').replace(',', ''))
                }
    except: pass
    return chip_data

# --- 3. 抓取大盤指數 ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_market_regime():
    try:
        twii = yf.download("^TWII", period="2mo", progress=False)
        if isinstance(twii.columns, pd.MultiIndex): twii = twii.xs('^TWII', axis=1, level=1)
        twii = twii.dropna()
        twii_close = float(twii['Close'].iloc[-1])
        twii_20ma = twii['Close'].rolling(20).mean().iloc[-1]
        return twii_close > twii_20ma 
    except:
        return True 

# --- 4. 批量下載歷史數據 ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bulk_market_data(tickers):
    return yf.download(tickers, period="1y", group_by='ticker', progress=False)

# --- 5. 實戰級進階歷史回測引擎 ---
def calculate_real_combat_backtest(df, vol_mult, rsi_min, rsi_max, pct_threshold, require_ema_bull, holding_days, max_bias_pct, min_atr_pct, require_vol_pattern):
    trades = []
    max_drawdown = 0.0 
    
    for i in range(25, len(df) - 1): # 預留空間計算更長天期的均量
        # 1. 基礎動能訊號
        is_signal = (
            (float(df['Volume_Lots'].iloc[i]) > float(df['Vol_Avg5_Lots'].iloc[i]) * vol_mult) and 
            (rsi_min < float(df['RSI9'].iloc[i]) < rsi_max) and 
            (float(df['Pct_Change'].iloc[i]) > pct_threshold)
        )
        
        # 2. 趨勢與高階濾網
        if require_ema_bull:
            is_signal = is_signal and (float(df['Close'].iloc[i]) > float(df['EMA5'].iloc[i])) and \
                        (float(df['EMA3'].iloc[i]) > float(df['EMA20'].iloc[i]))
                        
        if is_signal:
            if float(df['Bias_EMA5'].iloc[i]) > max_bias_pct: is_signal = False
            if float(df['ATR_Pct'].iloc[i]) < min_atr_pct: is_signal = False
            
            if require_vol_pattern:
                # 今日是否為近5日最大量
                if float(df['Volume_Lots'].iloc[i]) != float(df['Vol_Max5'].iloc[i]): is_signal = False
                # 突破前(昨日為止)的近3日均量 < 20日均量 (量縮沉澱)
                if float(df['Vol_Avg3'].iloc[i-1]) >= float(df['Vol_Avg20'].iloc[i-1]): is_signal = False
            
        # 3. 執行回測邏輯 (固定 10% 停損)
        if is_signal and (i + 1 < len(df)):
            entry_price = float(df['Open'].iloc[i + 1]) 
            stop_loss_price = entry_price * 0.90 
            
            prev_close = float(df['Close'].iloc[i])
            is_limit_up = (entry_price == float(df['High'].iloc[i + 1])) and (entry_price / prev_close >= 1.090)
            
            if entry_price > 0 and not is_limit_up:
                exit_price = 0
                trade_dd = 0.0
                trade_duration = min(holding_days, len(df) - i - 1)
                
                for j in range(1, trade_duration + 1):
                    current_low = float(df['Low'].iloc[i + j])
                    current_dd = ((current_low - entry_price) / entry_price) * 100
                    if current_dd < trade_dd:
                        trade_dd = current_dd
                        
                    if current_low <= stop_loss_price:
                        exit_price = stop_loss_price 
                        break
                        
                if exit_price == 0:
                    exit_price = float(df['Close'].iloc[i + trade_duration])

                ret = ((exit_price - entry_price) / entry_price) * 100
                trades.append(ret)
                
                if trade_dd < max_drawdown: max_drawdown = trade_dd
                
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    pl_ratio = abs((sum(wins) / len(wins)) / (sum(losses) / len(losses))) if losses else (99.99 if wins else 0.0)
    
    return len(trades), win_rate, pl_ratio, max_drawdown

# --- 6. 控制台與動態參數設定 ---
st.sidebar.markdown("### ⚙️ 系統控制台")
scan_limit = st.sidebar.slider("掃描數量上限", 10, 1750, 1750)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ 第一層：實戰基礎濾網")
require_twii_bull = st.sidebar.checkbox("📈 大盤環境濾網 (多頭才掃)", value=True)
min_vol_lots = st.sidebar.number_input("💧 最低 5 日均量 (張)", min_value=100, max_value=10000, value=1000, step=100)
require_chip_buy = st.sidebar.checkbox("💰 強制法人跟車 (買超)", value=False)

st.sidebar.markdown("---")
with st.sidebar.expander("🔥 第二層：高階型態與動能濾網", expanded=True):
    # 新增的三大濾網參數設定
    max_bias_pct = st.number_input("📏 EMA5 正乖離率上限 %", min_value=1.0, max_value=20.0, value=8.0, step=1.0, help="避免追買離均線太遠的標的")
    min_atr_pct = st.number_input("⚡ 近期股性波動下限 % (ATR)", min_value=1.0, max_value=10.0, value=3.0, step=0.5, help="數值越高代表近期洗盤或攻擊的幅度越大")
    require_vol_pattern = st.checkbox("🌊 開啟盤整量縮後爆量濾網", value=True, help="嚴格要求今日為近5日最大量，且前3日呈現量縮狀態。")
    
    st.markdown("---")
    vol_mult = st.number_input("🔥 爆量倍數", min_value=1.0, max_value=10.0, value=2.0, step=0.1)
    rsi_min, rsi_max = st.slider("📈 RSI(9) 動能區間", 0, 100, (65, 85))
    pct_threshold = st.number_input("🚀 最低漲幅 %", min_value=0.0, max_value=10.0, value=4.0, step=0.5)

holding_days = st.sidebar.number_input("⏱️ 回測預計持有天數", min_value=1, max_value=20, value=3, step=1)

# --- 7. 執行掃描邏輯 ---
if st.sidebar.button("🚀 開始全火力掃描", type="primary", use_container_width=True):
    
    is_market_bull = get_market_regime()
    if require_twii_bull and not is_market_bull:
        st.error("🚨 警告：目前加權指數跌破月線。系統暫停掃描！")
        st.stop()
        
    with st.status("🔍 正在執行高階雷達掃描與回測...", expanded=True) as status:
        stock_info_dict = get_all_taiwan_stocks_info()
        tickers = list(stock_info_dict.keys())[:scan_limit]
        chip_data = get_institutional_chips()
        data = fetch_bulk_market_data(tickers)

        hits = []
        progress_bar = st.progress(0)
        
        for idx, ticker in enumerate(tickers):
            try:
                df = data[ticker].copy().dropna() if isinstance(data.columns, pd.MultiIndex) else data.copy().dropna()
            except:
                progress_bar.progress((idx + 1) / len(tickers))
                continue
                
            if len(df) < 30: 
                progress_bar.progress((idx + 1) / len(tickers))
                continue
            
            try:
                # 基礎量能計算
                df['Volume_Lots'] = (df['Volume'] / 1000).round(0)
                df['Vol_Avg5_Lots'] = df['Volume_Lots'].rolling(window=5).mean().round(0)
                
                if float(df['Vol_Avg5_Lots'].iloc[-1]) < min_vol_lots:
                    continue

                stock_chip = chip_data.get(ticker, {"foreign_buy": 0, "trust_buy": 0})
                if require_chip_buy and (stock_chip["foreign_buy"] <= 0 and stock_chip["trust_buy"] <= 0):
                    continue 

                # 指標計算
                df['EMA3'] = ta.ema(df['Close'], length=3).round(2)
                df['EMA5'] = ta.ema(df['Close'], length=5).round(2)
                df['EMA20'] = ta.ema(df['Close'], length=20).round(2)
                df['RSI9'] = ta.rsi(df['Close'], length=9).round(2)
                df['Pct_Change'] = (df['Close'].pct_change() * 100).round(2)
                
                # --- 新增高階濾網指標計算 ---
                # 1. 乖離率
                df['Bias_EMA5'] = ((df['Close'] - df['EMA5']) / df['EMA5'] * 100).round(2)
                # 2. 真實波動幅度 (ATR)
                df['ATR14'] = ta.atr(df['High'], df['Low'], df['Close'], length=14).round(2)
                df['ATR_Pct'] = (df['ATR14'] / df['Close'] * 100).round(2)
                # 3. 量能型態輔助
                df['Vol_Avg3'] = df['Volume_Lots'].rolling(window=3).mean().round(0)
                df['Vol_Avg20'] = df['Volume_Lots'].rolling(window=20).mean().round(0)
                df['Vol_Max5'] = df['Volume_Lots'].rolling(window=5).max().round(0)
                
                # --- 最終訊號判定 ---
                is_bias_ok = float(df['Bias_EMA5'].iloc[-1]) <= max_bias_pct
                is_atr_ok = float(df['ATR_Pct'].iloc[-1]) >= min_atr_pct
                
                is_vol_pattern = True
                if require_vol_pattern:
                    is_max_5 = float(df['Volume_Lots'].iloc[-1]) == float(df['Vol_Max5'].iloc[-1])
                    is_contraction = float(df['Vol_Avg3'].iloc[-2]) < float(df['Vol_Avg20'].iloc[-2]) # 判斷到昨日為止是否量縮
                    is_vol_pattern = is_max_5 and is_contraction

                ema_condition = (float(df['Close'].iloc[-1]) > float(df['EMA5'].iloc[-1])) and \
                                (float(df['EMA3'].iloc[-1]) > float(df['EMA20'].iloc[-1]))
                
                is_breakout = (
                    ema_condition and 
                    (float(df['Volume_Lots'].iloc[-1]) > float(df['Vol_Avg5_Lots'].iloc[-1]) * vol_mult) and 
                    (rsi_min < float(df['RSI9'].iloc[-1]) < rsi_max) and 
                    (float(df['Pct_Change'].iloc[-1]) > pct_threshold) and
                    is_bias_ok and is_atr_ok and is_vol_pattern
                )
                
                if is_breakout:
                    t_count, w_rate, pl_ratio, mdd = calculate_real_combat_backtest(
                        df, vol_mult, rsi_min, rsi_max, pct_threshold, True, holding_days, max_bias_pct, min_atr_pct, require_vol_pattern
                    )
                    
                    hits.append({
                        "ticker": ticker, 
                        "info": stock_info_dict.get(ticker, {"name": "未知", "industry": "未知"}),
                        "chip": stock_chip,
                        "df": df, 
                        "bt_count": t_count,
                        "bt_win_rate": w_rate,
                        "bt_pl_ratio": pl_ratio,
                        "bt_mdd": mdd
                    })
            except Exception:
                pass
                
            progress_bar.progress((idx + 1) / len(tickers))

        status.update(label="✅ 高階掃描與回測完成！", state="complete", expanded=False)

    # --- 8. 排序並顯示結果 ---
    if hits:
        hits_sorted = sorted(hits, key=lambda x: (x['bt_pl_ratio'], x['bt_win_rate']), reverse=True)[:10]
        st.subheader(f"🎯 嚴格篩選後發現 {len(hits)} 檔標的，為您精選最強 {len(hits_sorted)} 檔")
        
        for h in hits_sorted:
            last_price = float(h['df']['Close'].iloc[-1])
            est_sl_price = last_price * 0.90 
            
            f_buy_lots = float(h['chip']['foreign_buy'] / 1000)
            t_buy_lots = float(h['chip']['trust_buy'] / 1000)
            
            win_color = "green" if h['bt_win_rate'] >= 50 else ("orange" if h['bt_win_rate'] >= 35 else "red")
            pl_color = "green" if h['bt_pl_ratio'] >= 1.5 else "white"

            with st.container(border=True):
                col1, col2 = st.columns([2, 3])
                
                with col1:
                    st.markdown(f"#### 🏷️ `[{h['info']['industry']}]` {h['info']['name']} ({h['ticker']})")
                    st.markdown(f"""
                    - **籌碼與量能：** 5日均量 `{float(h['df']['Vol_Avg5_Lots'].iloc[-1]):.0f} 張` | 外資 `{f_buy_lots:.2f}` 張 / 投信 `{t_buy_lots:.2f}` 張
                    - **高階體檢：** 股性波動 (ATR) `{float(h['df']['ATR_Pct'].iloc[-1]):.2f}%` | 5日線乖離 `{float(h['df']['Bias_EMA5'].iloc[-1]):.2f}%`
                    
                    ### ⚡ 交易指令
                    - 🟢 進場位： 明日開盤價 (若跳空漲停請放棄)
                    - 🔴 停損位： `實際進場價 × 0.90` (參考預估：`{est_sl_price:.2f}`)
                    
                    ---
                    ### 📊 實戰級回測 (持倉 {holding_days} 天)
                    - 🏆 歷史勝率：<span style='color:{win_color}; font-weight:bold;'>{h['bt_win_rate']:.2f}%</span> (共 {h['bt_count']} 次訊號)
                    - ⚖️ 盈虧比：<span style='color:{pl_color}; font-weight:bold;'>{h['bt_pl_ratio']:.2f}</span>
                    - 📉 盤中最大回撤：`{h['bt_mdd']:.2f}%`
                    """, unsafe_allow_html=True)
                
                with col2:
                    df_p = h['df'].tail(40)
                    fig = go.Figure(data=[go.Candlestick(
                        x=df_p.index, open=df_p['Open'], high=df_p['High'], 
                        low=df_p['Low'], close=df_p['Close'], name="K線"
                    )])
                    fig.add_hline(y=est_sl_price, line_dash="dash", line_color="red", 
                                  annotation_text=f"5% 預估停損線 {est_sl_price:.2f}", annotation_position="bottom left")
                    
                    fig.update_layout(height=280, margin=dict(l=0,r=0,t=0,b=0), 
                                      xaxis_rangeslider_visible=False, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("今日暫無符合「高階實戰濾網」條件之標的。大盤震盪或資金未明顯點火，請保留現金實力！")
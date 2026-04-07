import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import json, os

st.set_page_config(page_title="Wyckoff Screener", layout="wide", page_icon="📈")

# ─── CSS ───────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stStatusWidget"]       { display: none !important; }
[data-testid="stToolbar"]            { display: none !important; }
#MainMenu                            { display: none !important; }
button[kind="header"]                { display: none !important; }
.stAppDeployButton                   { display: none !important; }

@keyframes slideRight {
    0%   { left: -30px; }
    100% { left: 100%; }
}
/* Animasyon barı — butonun üst kısmı */
.runner-top {
    background: #1a3a5c;
    border: 1px solid #2d5a8e;
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    height: 22px;
    position: relative;
    overflow: hidden;
    margin-bottom: 0px;
}
.runner-on-btn {
    position: absolute;
    font-size: 17px;
    top: 2px;
    pointer-events: none;
    animation: slideRight 2.7s linear infinite;
}
/* Durdur butonu — alt kısım, üst köşeler düz */
div[data-testid="stButton"] > button[kind="secondary"] {
    border-radius: 0 0 8px 8px !important;
    border-top: none !important;
    background: #1a3a5c !important;
    border-color: #2d5a8e !important;
    color: white !important;
    margin-top: 0 !important;
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    background: #243f6a !important;
}
</style>
""", unsafe_allow_html=True)

# ─── AYAR KAYDET / YÜKLE ───────────────────────────────────
AYAR_DOSYASI = os.path.join(os.path.dirname(__file__), "ayarlar.json")

VARSAYILAN_SEMBOLLER = """BTC/USDT
ETH/USDT
SOL/USDT
BNB/USDT
XRP/USDT
ADA/USDT
DOGE/USDT
AVAX/USDT
DOT/USDT
LINK/USDT"""

VARSAYILAN = {
    "semboller_text": VARSAYILAN_SEMBOLLER,
    "periyot":       "1h",
    "pivot_len":     7,
    "lookback":      20,
    "tolerans":      2.0,
    "min_height":    3.5,
    "max_depth":     15.0,
    "min_bars":      3,
    "limit":         200,
}

def ayar_yukle():
    if os.path.exists(AYAR_DOSYASI):
        with open(AYAR_DOSYASI, "r", encoding="utf-8") as f:
            return {**VARSAYILAN, **json.load(f)}
    return VARSAYILAN.copy()

def ayar_kaydet(ayarlar):
    with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(ayarlar, f, indent=2, ensure_ascii=False)

ayarlar = ayar_yukle()

# ─── SESSION STATE ─────────────────────────────────────────
for k, v in [
    ("scanning",               False),
    ("stop_requested",         False),
    ("scan_results",           []),
    ("selected_symbol",        None),
    ("show_chart_in_screener", False),
]:
    if k not in st.session_state:
        st.session_state[k] = v


# ─── SIDEBAR ───────────────────────────────────────────────
st.sidebar.title("⚙️ Ayarlar")

sembol_text = st.sidebar.text_area(
    "Semboller (her satıra bir tane)",
    value=ayarlar.get("semboller_text", VARSAYILAN_SEMBOLLER),
    height=260,
)
SEMBOLLER = [s.strip().upper() for s in sembol_text.strip().splitlines() if s.strip()]

PERIYOT_LISTESI = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
PERIYOT = st.sidebar.selectbox(
    "Periyot", PERIYOT_LISTESI,
    index=PERIYOT_LISTESI.index(ayarlar.get("periyot", "1h"))
)

with st.sidebar.expander("🔧 Parametreler"):
    PIVOT_LEN      = st.slider("Pivot uzunluğu",        3,   20,   ayarlar["pivot_len"])
    LOOKBACK       = st.slider("Lookback (bar)",         5,   100,  ayarlar["lookback"])
    TOLERANS_PCT   = st.slider("Tolerans %",             0.5, 5.0,  ayarlar["tolerans"],   0.5)
    MIN_HEIGHT_ATR = st.slider("Min. yükseklik (ATR)",   0.5, 10.0, ayarlar["min_height"], 0.5)
    MAX_DEPTH_PCT  = st.slider("Max. derinlik %",        1.0, 30.0, ayarlar["max_depth"],  1.0)
    MIN_BARS       = st.slider("Min. bar arası",         1,   20,   ayarlar["min_bars"])
    LIMIT          = st.slider("Bar sayısı",             100, 1000, ayarlar["limit"],      50)

st.sidebar.markdown("---")
if st.sidebar.button("💾 Ayarları Kaydet", use_container_width=True):
    ayar_kaydet({
        "semboller_text": sembol_text,
        "periyot":    PERIYOT,
        "pivot_len":  PIVOT_LEN,
        "lookback":   LOOKBACK,
        "tolerans":   TOLERANS_PCT,
        "min_height": MIN_HEIGHT_ATR,
        "max_depth":  MAX_DEPTH_PCT,
        "min_bars":   MIN_BARS,
        "limit":      LIMIT,
    })
    st.sidebar.success("Kaydedildi ✓")

# ─── FONKSİYONLAR ──────────────────────────────────────────
PERIYOT_MAP = {"1m":"1","5m":"5","15m":"15","1h":"60","4h":"240","1d":"D","1w":"W"}

@st.cache_data(ttl=60)
def veri_cek(sembol, periyot, limit):
    import requests
    symbol = sembol.replace("/", "")
    interval = PERIYOT_MAP.get(periyot, "60")
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    rows = data["result"]["list"]
    rows = sorted(rows, key=lambda x: int(x[0]))
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","turnover"])
    df = df[["timestamp","open","high","low","close","volume"]].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df

def pivot_high(high, length):
    pivots = [None] * len(high)
    for i in range(length, len(high) - length):
        if high[i] == max(high[i - length: i + length + 1]):
            pivots[i] = high[i]
    return pivots

def pivot_low(low, length):
    pivots = [None] * len(low)
    for i in range(length, len(low) - length):
        if low[i] == min(low[i - length: i + length + 1]):
            pivots[i] = low[i]
    return pivots

def atr(df, period=14):
    high = df["high"]; low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def wyckoff_tespit(df):
    highs  = df["high"].values
    lows   = df["low"].values
    opens  = df["open"].values
    closes = df["close"].values
    atr_v  = atr(df).values

    ph_list = pivot_high(highs, PIVOT_LEN)
    pl_list = pivot_low(lows,   PIVOT_LEN)

    ph_vals, ph_idxs = [], []
    pl_vals, pl_idxs = [], []
    sinyaller = []
    son_spring_ph_idx = -1
    son_thrust_pl_idx = -1

    for i in range(len(df)):
        if ph_list[i] is not None:
            ph_vals.insert(0, ph_list[i]); ph_idxs.insert(0, i)
            if len(ph_vals) > 30: ph_vals.pop(); ph_idxs.pop()
        if pl_list[i] is not None:
            pl_vals.insert(0, pl_list[i]); pl_idxs.insert(0, i)
            if len(pl_vals) > 30: pl_vals.pop(); pl_idxs.pop()

        if not ph_vals or not pl_vals: continue
        av = atr_v[i]
        if np.isnan(av): continue

        # ── SPRING ──
        ph_val = ph_vals[0]; ph_idx = ph_idxs[0]
        pl_val = pl_vals[0]; pl_idx = pl_idxs[0]

        if pl_idx > ph_idx:
            prev_pl_val = prev_pl_idx = None
            for j in range(len(pl_idxs)):
                if pl_idxs[j] < ph_idx:
                    prev_pl_val = pl_vals[j]; prev_pl_idx = pl_idxs[j]; break
            if prev_pl_val is not None:
                lb = max(0, i - LOOKBACK)
                if (max(highs[lb:i+1]) >= ph_val * (1 - TOLERANS_PCT / 100) and
                    min(lows[lb:i+1])  <  prev_pl_val and
                    closes[i] > ph_val and opens[i] < ph_val and
                    (closes[i] - opens[i]) > (highs[i] - lows[i]) * 0.5 and
                    (ph_val - prev_pl_val) > av * MIN_HEIGHT_ATR and
                    pl_val >= prev_pl_val * (1 - MAX_DEPTH_PCT / 100) and
                    (ph_idx - prev_pl_idx) >= MIN_BARS and
                    (pl_idx - ph_idx)      >= MIN_BARS and
                    ph_idx != son_spring_ph_idx):
                    son_spring_ph_idx = ph_idx
                    sinyaller.append({"bar": i, "tip": "spring",
                        "prev_pl_val": prev_pl_val, "prev_pl_idx": prev_pl_idx,
                        "ph_val": ph_val, "ph_idx": ph_idx,
                        "pl_val": pl_val, "pl_idx": pl_idx})

        # ── UPTHRUST ──
        pl_val2 = pl_vals[0]; pl_idx2 = pl_idxs[0]
        ph_val2 = ph_vals[0]; ph_idx2 = ph_idxs[0]

        if ph_idx2 > pl_idx2:
            prev_ph_val = prev_ph_idx = None
            for j in range(len(ph_idxs)):
                if ph_idxs[j] < pl_idx2:
                    prev_ph_val = ph_vals[j]; prev_ph_idx = ph_idxs[j]; break
            if prev_ph_val is not None:
                lb = max(0, i - LOOKBACK)
                if (min(lows[lb:i+1])  <= pl_val2 * (1 + TOLERANS_PCT / 100) and
                    max(highs[lb:i+1]) >  prev_ph_val and
                    closes[i] < pl_val2 and opens[i] > pl_val2 and
                    (opens[i] - closes[i]) > (highs[i] - lows[i]) * 0.5 and
                    (prev_ph_val - pl_val2) > av * MIN_HEIGHT_ATR and
                    ph_val2 <= prev_ph_val * (1 + MAX_DEPTH_PCT / 100) and
                    (pl_idx2 - prev_ph_idx) >= MIN_BARS and
                    (ph_idx2 - pl_idx2)     >= MIN_BARS and
                    pl_idx2 != son_thrust_pl_idx):
                    son_thrust_pl_idx = pl_idx2
                    sinyaller.append({"bar": i, "tip": "upthrust",
                        "prev_ph_val": prev_ph_val, "prev_ph_idx": prev_ph_idx,
                        "pl_val": pl_val2, "pl_idx": pl_idx2,
                        "ph_val": ph_val2, "ph_idx": ph_idx2})

    return sinyaller

def grafik_ciz(sembol, df, sinyaller):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.8, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=sembol,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350"
    ), row=1, col=1)
    colors = ["#26a69a" if c >= o else "#ef5350" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"],
        marker_color=colors, name="Hacim", opacity=0.6), row=2, col=1)

    for s in sinyaller:
        i = s["bar"]
        if i >= len(df): continue
        t = df.index[i]
        if s["tip"] == "spring":
            fig.add_shape(type="line",
                x0=df.index[max(0, s["prev_pl_idx"])], x1=t,
                y0=s["prev_pl_val"], y1=s["prev_pl_val"],
                line=dict(color="rgba(100,149,237,0.7)", width=1, dash="dash"), row=1, col=1)
            fig.add_shape(type="line",
                x0=df.index[max(0, s["ph_idx"])], x1=t,
                y0=s["ph_val"], y1=s["ph_val"],
                line=dict(color="rgba(255,80,80,0.7)", width=1, dash="dash"), row=1, col=1)
            fig.add_annotation(x=t, y=df["low"].iloc[i],
                text="▲ SPRING", showarrow=True, arrowhead=2,
                arrowcolor="#00e676", font=dict(color="#00e676", size=11),
                ax=0, ay=35, row=1, col=1)
        elif s["tip"] == "upthrust":
            fig.add_shape(type="line",
                x0=df.index[max(0, s["prev_ph_idx"])], x1=t,
                y0=s["prev_ph_val"], y1=s["prev_ph_val"],
                line=dict(color="rgba(255,80,80,0.7)", width=1, dash="dash"), row=1, col=1)
            fig.add_shape(type="line",
                x0=df.index[max(0, s["pl_idx"])], x1=t,
                y0=s["pl_val"], y1=s["pl_val"],
                line=dict(color="rgba(100,149,237,0.7)", width=1, dash="dash"), row=1, col=1)
            fig.add_annotation(x=t, y=df["high"].iloc[i],
                text="▼ UPTHRUST", showarrow=True, arrowhead=2,
                arrowcolor="#ff5252", font=dict(color="#ff5252", size=11),
                ax=0, ay=-35, row=1, col=1)

    fig.update_layout(
        title=f"{sembol} — Wyckoff Spring & Upthrust ({PERIYOT})",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        dragmode="pan",
        height=600,
        showlegend=False,
        margin=dict(t=50, b=20)
    )
    return fig

# ─── ANA SAYFA ─────────────────────────────────────────────
st.title("📈 Wyckoff Spring & Upthrust")
st.caption("Binance Futures • Sol panelden sembol ve ayarları düzenleyebilirsin")

tab1, tab2 = st.tabs(["🔍 Screener", "📊 Grafik"])

# ── TAB 1: SCREENER ────────────────────────────────────────
with tab1:
    btn_area = st.empty()

    if st.session_state.scanning:
        with btn_area.container():
            st.markdown('<div class="runner-top"><span class="runner-on-btn">🏃</span></div>', unsafe_allow_html=True)
            if st.button("⏹️ Durdur", use_container_width=True, key="durdur_btn"):
                st.session_state.scanning       = False
                st.session_state.stop_requested = False
                st.rerun()
    else:
        if btn_area.button("🚀 Tara", type="primary", use_container_width=True):
            st.session_state.scanning               = True
            st.session_state.stop_requested         = False
            st.session_state.scan_results           = []
            st.session_state.show_chart_in_screener = False
            st.rerun()

    # Tarama döngüsü
    if st.session_state.scanning and not st.session_state.stop_requested:
        progress = st.progress(0, text="Taranıyor...")
        for idx, sembol in enumerate(SEMBOLLER):
            if st.session_state.stop_requested:
                break
            progress.progress((idx + 1) / len(SEMBOLLER), text=f"{sembol} taranıyor...")
            try:
                df       = veri_cek(sembol, PERIYOT, LIMIT)
                sinyaller = wyckoff_tespit(df)
                aktif    = [s for s in sinyaller if s["bar"] >= len(df) - 5]
                bars_ago = (len(df) - 1 - sinyaller[-1]["bar"]) if sinyaller else None

                st.session_state.scan_results.append({
                    "sembol":    sembol,
                    "sinyal":    (aktif[-1]["tip"] if aktif else None),
                    "fiyat":     round(df["close"].iloc[-1], 4),
                    "bars_ago":  bars_ago,
                    "df":        df,
                    "sinyaller": sinyaller,
                })
            except Exception as e:
                st.session_state.scan_results.append({
                    "sembol": sembol, "sinyal": "hata", "fiyat": 0,
                    "bars_ago": None, "df": None, "sinyaller": [],
                    "hata_msg": str(e),
                })
        progress.empty()
        st.session_state.scanning = False
        st.rerun()

    # Sonuçları göster
    if st.session_state.scan_results:
        aktif_list = [r for r in st.session_state.scan_results if r["sinyal"] in ("spring", "upthrust")]
        sessiz_list = [r for r in st.session_state.scan_results if r["sinyal"] is None]

        col1, col2 = st.columns(2)
        col1.metric("Aktif Sinyal", len(aktif_list))
        col2.metric("Sinyal Yok",   len(sessiz_list))
        st.markdown("---")

        # Aktif sinyaller — tıklanabilir satırlar
        if aktif_list:
            st.subheader("🎯 Aktif Sinyaller")
            for r in aktif_list:
                is_spring = r["sinyal"] == "spring"
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
                c1.markdown(f"**{r['sembol']}**")
                if is_spring:
                    c2.markdown(":green[▲ SPRING]")
                else:
                    c2.markdown(":red[▼ UPTHRUST]")
                c3.markdown(f"`{r['fiyat']}`")
                c4.markdown(f"_{r['bars_ago']} bar önce_" if r["bars_ago"] is not None else "—")
                if c5.button("📊", key=f"chart_{r['sembol']}"):
                    st.session_state.selected_symbol = r["sembol"]
                    st.session_state.show_chart_in_screener = True
            st.markdown("---")

        # Tüm semboller tablosu
        st.subheader("Tüm Semboller")
        tablo = []
        for r in st.session_state.scan_results:
            if r["sinyal"] == "spring":      sinyal_str = "▲ SPRING"
            elif r["sinyal"] == "upthrust":  sinyal_str = "▼ UPTHRUST"
            elif r["sinyal"] == "hata":      sinyal_str = f"HATA: {r.get('hata_msg','')[:60]}"
            else:                            sinyal_str = "—"
            tablo.append({
                "Sembol":      r["sembol"],
                "Sinyal":      sinyal_str,
                "Fiyat":       r["fiyat"],
                "Son Sinyal":  f"{r['bars_ago']} bar önce" if r.get("bars_ago") is not None else "—",
            })
        st.dataframe(pd.DataFrame(tablo), use_container_width=True, hide_index=True)

        # Tıklanan sembolün grafiği
        if st.session_state.show_chart_in_screener and st.session_state.selected_symbol:
            sel   = st.session_state.selected_symbol
            match = next((r for r in st.session_state.scan_results if r["sembol"] == sel), None)
            if match and match["df"] is not None:
                st.markdown(f"---\n### 📊 {sel} — {PERIYOT}")
                fig = grafik_ciz(sel, match["df"], match["sinyaller"])
                st.plotly_chart(fig, use_container_width=True, config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                })

# ── TAB 2: GRAFİK ──────────────────────────────────────────
with tab2:
    col1, col2 = st.columns([3, 1])
    with col1:
        secili = st.selectbox("Sembol seç", SEMBOLLER if SEMBOLLER else ["BTC/USDT"])
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        goster = st.button("📊 Grafiği Göster", type="primary", use_container_width=True)

    if goster:
        with st.spinner(f"{secili} verisi çekiliyor..."):
            try:
                df        = veri_cek(secili, PERIYOT, LIMIT)
                sinyaller = wyckoff_tespit(df)
                spring_n  = sum(1 for s in sinyaller if s["tip"] == "spring")

                c1, c2, c3 = st.columns(3)
                c1.metric("Toplam Bar", len(df))
                c2.metric("Spring",     spring_n)
                c3.metric("Upthrust",   len(sinyaller) - spring_n)

                fig = grafik_ciz(secili, df, sinyaller)
                st.plotly_chart(fig, use_container_width=True, config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                })
            except Exception as e:
                st.error(f"Hata: {e}")

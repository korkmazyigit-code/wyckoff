import streamlit as st
import streamlit.components.v1 as components
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
    "semboller_text":   VARSAYILAN_SEMBOLLER,
    "periyot":          "1h",
    "pivot_window":     3,
    "max_bars_between": 50,
    "max_bars_signal":  25,
    "trend_lookback":   60,
    "min_trend_drop":   15.0,
    "body_pct":         0.4,
    "min_signal_gap":   30,
    "limit":            600,
    "pattern_mod":      "İkisi de",
    "min_neckline_pct": 7.0,
}

def ayar_yukle():
    if os.path.exists(AYAR_DOSYASI):
        with open(AYAR_DOSYASI, "r", encoding="utf-8") as f:
            d = json.load(f)
            return {**VARSAYILAN, **{k: v for k, v in d.items() if k in VARSAYILAN}}
    return VARSAYILAN.copy()

def ayar_kaydet(ayarlar):
    try:
        with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(ayarlar, f, indent=2, ensure_ascii=False)
    except OSError:
        pass  # Streamlit Cloud'da dosya sistemi read-only, sessizce geç

ayarlar = ayar_yukle()

PERIYOT_LISTESI = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

# ─── SESSION STATE ─────────────────────────────────────────
for k, v in [
    ("scanning",               False),
    ("stop_requested",         False),
    ("scan_results",           []),
    ("selected_symbol",        None),
    ("show_chart_in_screener", False),
    ("grafik_gosteriliyor",    False),
    ("switch_to_grafik",       False),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# Periyot: ayarlardan başlat, widget key ile yönetilir
if "periyot_select" not in st.session_state:
    st.session_state["periyot_select"] = ayarlar.get("periyot", "1h")

# Sembol listesi: ayarlardan başlat, session_state ile yönetilir
if "sembol_text" not in st.session_state:
    st.session_state["sembol_text"] = ayarlar.get("semboller_text", VARSAYILAN_SEMBOLLER)

# ─── SIDEBAR ───────────────────────────────────────────────
st.sidebar.title("⚙️ Ayarlar")

sembol_text = st.sidebar.text_area(
    "Semboller (her satıra bir tane)",
    key="sembol_text",
    height=180,
)
all_semboller = [s.strip().upper() for s in sembol_text.strip().splitlines() if s.strip()]

# Yeni eklenen semboller için checkbox state başlat (varsayılan: seçili)
for sym in all_semboller:
    if f"cb_{sym}" not in st.session_state:
        st.session_state[f"cb_{sym}"] = True

st.sidebar.markdown("**Taranacak semboller:**")
SEMBOLLER = []
for sym in all_semboller:
    if st.sidebar.checkbox(sym, key=f"cb_{sym}"):
        SEMBOLLER.append(sym)

st.sidebar.markdown("---")
st.sidebar.markdown("**Pattern Filtresi:**")
_MOD_LISTESI = ["DB + DT", "Likidite Alımı", "Hepsi"]
PATTERN_MOD = st.sidebar.radio(
    "Gösterim modu",
    _MOD_LISTESI,
    index=_MOD_LISTESI.index(ayarlar.get("pattern_mod", "DB + DT"))
          if ayarlar.get("pattern_mod", "DB + DT") in _MOD_LISTESI else 0,
    label_visibility="collapsed",
)
SADECE_LQ = (PATTERN_MOD == "Likidite Alımı")

with st.sidebar.expander("🔧 Parametreler"):
    _cur_periyot = st.session_state.get("periyot_select", "1h")
    _TREND_DEFAULTS   = {"1m": 1.0, "5m": 2.0, "15m": 3.0, "1h": 5.0, "4h": 8.0, "1d": 15.0, "1w": 25.0}
    _NECKLINE_DEFAULTS = {"1m": 0.5, "5m": 0.8, "15m": 1.2, "1h": 2.0, "4h": 3.5, "1d": 7.0, "1w": 10.0}
    _trend_default    = _TREND_DEFAULTS.get(_cur_periyot, 15.0)
    _neckline_default = _NECKLINE_DEFAULTS.get(_cur_periyot, 7.0)

    PIVOT_WINDOW     = st.slider("Pivot penceresi (bar)",     2,  15,  ayarlar.get("pivot_window", 5))
    MAX_BARS_BETWEEN = st.slider("Max. bar (dip arası)",     5,  80,  ayarlar["max_bars_between"])
    MAX_BARS_SIGNAL  = st.slider("Max. bar (breakout'a)",    1,  30,  ayarlar["max_bars_signal"])
    TREND_LOOKBACK   = st.slider("Trend lookback (bar)",     10, 100, ayarlar["trend_lookback"])
    MIN_TREND_DROP   = st.slider("Min. trend düşüş %",       1.0, 40.0, _trend_default, 0.5)
    BODY_PCT         = st.slider("Breakout gövde oranı",     0.2, 0.9, ayarlar["body_pct"], 0.05)
    MIN_SIGNAL_GAP   = st.slider("Min. sinyal arası (bar)",  5,  50,  ayarlar["min_signal_gap"])
    LIMIT            = st.slider("Bar sayısı",               100, 1500, ayarlar["limit"], 50)
    MIN_NECKLINE_PCT = st.slider("Min. neckline yüksekliği %", 0.3, 15.0, _neckline_default, 0.1)

st.sidebar.markdown("---")
if st.sidebar.button("💾 Ayarları Kaydet", use_container_width=True):
    ayar_kaydet({
        "semboller_text":   sembol_text,
        "periyot":          st.session_state.get("periyot_select", "1h"),
        "pivot_window":     PIVOT_WINDOW,
        "max_bars_between": MAX_BARS_BETWEEN,
        "max_bars_signal":  MAX_BARS_SIGNAL,
        "trend_lookback":   TREND_LOOKBACK,
        "min_trend_drop":   MIN_TREND_DROP,
        "body_pct":         BODY_PCT,
        "min_signal_gap":   MIN_SIGNAL_GAP,
        "limit":            LIMIT,
        "pattern_mod":      PATTERN_MOD,
        "min_neckline_pct": MIN_NECKLINE_PCT,
    })
    st.sidebar.success("Kaydedildi ✓")

# ─── FONKSİYONLAR ──────────────────────────────────────────
YF_PERIYOT = {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk"}
YF_PERIOD  = {"1m":"7d","5m":"60d","15m":"60d","1h":"730d","4h":"730d","1d":"max","1w":"max"}

def _binance(sembol, periyot, limit):
    exchange = ccxt.binance({"options": {"defaultType": "future"}})
    ohlcv = exchange.fetch_ohlcv(sembol, periyot, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df

def _yfinance(sembol, periyot, limit):
    import yfinance as yf
    base     = sembol.split("/")[0]
    ticker   = f"{base}-USD"
    interval = YF_PERIYOT.get(periyot, "1h")
    period   = YF_PERIOD.get(periyot, "60d")
    df = yf.download(ticker, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"{sembol} için veri alınamadı")
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df = df[["open","high","low","close","volume"]].tail(limit)
    if periyot == "4h":
        df = df.resample("4h").agg({"open":"first","high":"max",
                                    "low":"min","close":"last","volume":"sum"}).dropna()
    return df

# Streamlit Cloud'da STREAMLIT_SERVER_HEADLESS=true olur → Binance bloklu, yfinance kullan
_IS_CLOUD = os.getenv("STREAMLIT_SERVER_HEADLESS", "false").lower() == "true"

@st.cache_data(ttl=60)
def veri_cek(sembol, periyot, limit):
    if _IS_CLOUD:
        return _yfinance(sembol, periyot, limit)
    try:
        return _binance(sembol, periyot, limit)
    except Exception:
        return _yfinance(sembol, periyot, limit)

# ─── ANA TESPİT FONKSİYONU ────────────────────────────────
def _pivot_lows(lows, window):
    """Her iki yanda `window` bar boyunca en düşük olan barları döndür."""
    n = len(lows)
    pivots = []
    for i in range(window, n - window):
        lo = lows[i]
        if lo == np.min(lows[i - window: i + window + 1]):
            pivots.append(i)
    return pivots


def _pivot_highs(highs, window):
    """Her iki yanda `window` bar boyunca en yüksek olan barları döndür."""
    n = len(highs)
    pivots = []
    for i in range(window, n - window):
        hi = highs[i]
        if hi == np.max(highs[i - window: i + window + 1]):
            pivots.append(i)
    return pivots


def _b2_pencere_close_kontrol(closes, b2, b1_low, n):
    """B2 ±2 bar penceresinde herhangi bir close B1 low altında mı?"""
    w_start = max(0, b2 - 2)
    w_end   = min(n, b2 + 3)
    return any(closes[j] < b1_low for j in range(w_start, w_end))


def double_bottom_tespit(df):
    """
    Pivot tabanlı Double Bottom Spring tespiti (orijinal):
      - B2-centric: her pivot için geriye bakıp B1 adayları toplanır
      - B2.low < B1.low (wick bazlı)
      - Aralarında neckline, neckline kırılımı + güçlü gövdeli breakout
    """
    highs  = df["high"].values
    lows   = df["low"].values
    opens  = df["open"].values
    closes = df["close"].values
    n      = len(df)

    pivot_idx      = _pivot_lows(lows, PIVOT_WINDOW)
    pivot_high_idx = _pivot_highs(highs, PIVOT_WINDOW)

    signals         = []
    last_signal_bar = -999

    for pi2, b2 in enumerate(pivot_idx):
        if b2 <= last_signal_bar:
            continue
        candidates = []
        for pi1 in range(pi2 - 1, -1, -1):
            b1 = pivot_idx[pi1]
            if b2 - b1 > MAX_BARS_BETWEEN:
                break
            if b2 - b1 < PIVOT_WINDOW * 2:
                continue

            ts = max(0, b1 - TREND_LOOKBACK)
            recent_ph = [p for p in pivot_high_idx if ts <= p < b1]
            if not recent_ph:
                continue
            prior_high = float(highs[recent_ph[-1]])
            if prior_high == 0:
                continue
            drop_pct = (prior_high - lows[b1]) / prior_high * 100
            if drop_pct < MIN_TREND_DROP:
                continue
            # B2 ±2 pencerede en az bir close B1 wick low altında kapanmalı
            if not _b2_pencere_close_kontrol(closes, b2, lows[b1], n):
                continue

            # B1 ile B2 arasında B1 wick'inden düşük pivot olmamalı
            ara_pivotlar = [p for p in pivot_idx if b1 < p < b2]
            if any(lows[p] < lows[b1] for p in ara_pivotlar):
                continue

            nk_arr = highs[b1 + 1: b2]
            if len(nk_arr) == 0:
                continue
            neckline     = float(np.max(nk_arr))
            neckline_idx = int(np.argmax(highs[b1 + 1: b2])) + b1 + 1
            if neckline < lows[b1] * (1 + MIN_NECKLINE_PCT / 100):
                continue

            candidates.append((b1, neckline, neckline_idx))

        if not candidates:
            continue

        b1, neckline, neckline_idx = min(candidates, key=lambda c: lows[c[0]])

        for i in range(b2 + 1, min(b2 + MAX_BARS_SIGNAL + 1, n)):
            if i <= last_signal_bar:
                continue
            body   = closes[i] - opens[i]
            candle = highs[i]  - lows[i]
            if body <= 0 or candle == 0:
                continue
            if body / candle < BODY_PCT:
                continue
            if closes[i] <= neckline:
                continue

            last_signal_bar = i + MIN_SIGNAL_GAP
            signals.append({
                "bar":          i,
                "tip":          "double_bottom",
                "b1_idx":       b1,
                "b1_low":       float(lows[b1]),
                "b2_idx":       b2,
                "b2_low":       float(lows[b2]),
                "neckline":     neckline,
                "neckline_idx": neckline_idx,
            })
            break

    return signals


def likidite_alimi_tespit(df):
    """
    Likidite Alımı tespiti:
      - B2 wick'i B1 low altına iner (sweep)
      - B2 ±2 bar pencerede HİÇBİR close B1 low altında kapanmaz
      - Neckline şartı yok — sinyal B2 barının kapanışında
    """
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    n      = len(df)

    pivot_idx      = _pivot_lows(lows, PIVOT_WINDOW)
    pivot_high_idx = _pivot_highs(highs, PIVOT_WINDOW)

    signals         = []
    last_signal_bar = -999

    for pi2, b2 in enumerate(pivot_idx):
        if b2 <= last_signal_bar:
            continue
        candidates = []
        for pi1 in range(pi2 - 1, -1, -1):
            b1 = pivot_idx[pi1]
            if b2 - b1 > MAX_BARS_BETWEEN:
                break
            if b2 - b1 < PIVOT_WINDOW * 2:
                continue

            ts = max(0, b1 - TREND_LOOKBACK)
            recent_ph = [p for p in pivot_high_idx if ts <= p < b1]
            if not recent_ph:
                continue
            prior_high = float(highs[recent_ph[-1]])
            if prior_high == 0:
                continue
            drop_pct = (prior_high - lows[b1]) / prior_high * 100
            if drop_pct < MIN_TREND_DROP:
                continue

            # Wick sweep şartı
            if lows[b2] >= lows[b1]:
                continue

            # B2 ±2 bar penceresinde HİÇBİR close B1 altında olmamalı
            if _b2_pencere_close_kontrol(closes, b2, lows[b1], n):
                continue

            candidates.append(b1)

        if not candidates:
            continue

        b1 = min(candidates, key=lambda x: lows[x])

        last_signal_bar = b2 + MIN_SIGNAL_GAP
        signals.append({
            "bar":      b2,
            "tip":      "likidite_alimi",
            "b1_idx":   b1,
            "b1_low":   float(lows[b1]),
            "b2_idx":   b2,
            "b2_low":   float(lows[b2]),
            "b2_close": float(closes[b2]),
        })

    return signals


def double_top_tespit(df):
    """
    Double Top tespiti (double_bottom_tespit'in aynası):
      - T2-centric: her pivot high için geriye bakıp T1 adayları toplanır
      - T2.high > T1.high (wick bazlı)
      - T2 ±2 pencerede en az bir close T1 high üstünde kapanmalı
      - Aralarında neckline (en düşük low), neckline kırılımı + güçlü gövdeli breakdown
      - T1 öncesinde yükselen trend: yakın pivot low'dan T1'e yükseliş >= MIN_TREND_DROP
    """
    highs  = df["high"].values
    lows   = df["low"].values
    opens  = df["open"].values
    closes = df["close"].values
    n      = len(df)

    pivot_idx      = _pivot_highs(highs, PIVOT_WINDOW)
    pivot_low_idx  = _pivot_lows(lows, PIVOT_WINDOW)

    signals         = []
    last_signal_bar = -999

    for pi2, t2 in enumerate(pivot_idx):
        if t2 <= last_signal_bar:
            continue
        candidates = []
        for pi1 in range(pi2 - 1, -1, -1):
            t1 = pivot_idx[pi1]
            if t2 - t1 > MAX_BARS_BETWEEN:
                break
            if t2 - t1 < PIVOT_WINDOW * 2:
                continue

            # Yükselen trend: T1 öncesinde yakın pivot low bulunmalı
            ts = max(0, t1 - TREND_LOOKBACK)
            recent_pl = [p for p in pivot_low_idx if ts <= p < t1]
            if not recent_pl:
                continue
            prior_low = float(lows[recent_pl[-1]])
            if prior_low == 0:
                continue
            rise_pct = (highs[t1] - prior_low) / prior_low * 100
            if rise_pct < MIN_TREND_DROP:
                continue

            # T2 wick T1 high üstüne çıkmalı
            if highs[t2] <= highs[t1]:
                continue

            # T2 ±2 pencerede en az bir close T1 high üstünde kapanmalı
            w_start = max(0, t2 - 2)
            w_end   = min(n, t2 + 3)
            if not any(closes[j] > highs[t1] for j in range(w_start, w_end)):
                continue

            # T1 ile T2 arasında T1 high'ından yüksek pivot olmamalı
            ara_pivotlar = [p for p in pivot_idx if t1 < p < t2]
            if any(highs[p] > highs[t1] for p in ara_pivotlar):
                continue

            # Neckline: T1-T2 arası en düşük low
            nk_arr = lows[t1 + 1: t2]
            if len(nk_arr) == 0:
                continue
            neckline     = float(np.min(nk_arr))
            neckline_idx = int(np.argmin(lows[t1 + 1: t2])) + t1 + 1
            if neckline > highs[t1] * (1 - MIN_NECKLINE_PCT / 100):
                continue

            candidates.append((t1, neckline, neckline_idx))

        if not candidates:
            continue

        t1, neckline, neckline_idx = max(candidates, key=lambda c: highs[c[0]])

        for i in range(t2 + 1, min(t2 + MAX_BARS_SIGNAL + 1, n)):
            if i <= last_signal_bar:
                continue
            body   = opens[i] - closes[i]
            candle = highs[i] - lows[i]
            if body <= 0 or candle == 0:
                continue
            if body / candle < BODY_PCT:
                continue
            if closes[i] >= neckline:
                continue

            last_signal_bar = i + MIN_SIGNAL_GAP
            signals.append({
                "bar":          i,
                "tip":          "double_top",
                "t1_idx":       t1,
                "t1_high":      float(highs[t1]),
                "t2_idx":       t2,
                "t2_high":      float(highs[t2]),
                "neckline":     neckline,
                "neckline_idx": neckline_idx,
                "breakout_bar": i,
            })
            break

    return signals


# ─── GRAFİK ────────────────────────────────────────────────
def grafik_ciz(sembol, df, sinyaller, periyot):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.8, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=sembol,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350"
    ), row=1, col=1)
    colors = ["#26a69a" if c >= o else "#ef5350"
              for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"],
        marker_color=colors, name="Hacim", opacity=0.6), row=2, col=1)

    for s in sinyaller:
        i    = s["bar"]
        tip  = s.get("tip", "double_bottom")
        if i >= len(df):
            continue
        t    = df.index[i]

        if tip == "double_top":
            t_t1   = df.index[s["t1_idx"]]
            t_t2   = df.index[s["t2_idx"]]
            t_neck = df.index[s["neckline_idx"]]

            fig.add_shape(type="rect",
                x0=t_t1, x1=t,
                y0=s["neckline"] * 0.998,
                y1=max(s["t2_high"], s["t1_high"]) * 1.002,
                fillcolor="rgba(255,80,80,0.04)",
                line=dict(color="rgba(255,100,100,0.4)", width=1),
                row=1, col=1)
            fig.add_shape(type="line",
                x0=t_t1, x1=t,
                y0=s["neckline"], y1=s["neckline"],
                line=dict(color="rgba(255,160,0,0.8)", width=1, dash="dash"),
                row=1, col=1)
            fig.add_annotation(x=t_t1, y=s["t1_high"],
                text="①", showarrow=True, arrowhead=2,
                arrowcolor="#ff6060", font=dict(color="#ff6060", size=12),
                ax=0, ay=-28, row=1, col=1)
            fig.add_annotation(x=t_t2, y=s["t2_high"],
                text="②", showarrow=True, arrowhead=2,
                arrowcolor="#ff6060", font=dict(color="#ff6060", size=12),
                ax=0, ay=-28, row=1, col=1)
            fig.add_annotation(x=t, y=s["neckline"],
                text="▼ BREAKDOWN", showarrow=True, arrowhead=2,
                arrowcolor="#ff4444", font=dict(color="#ff4444", size=11),
                ax=0, ay=-35, row=1, col=1)
            continue

        t_b1 = df.index[s["b1_idx"]]
        t_b2 = df.index[s["b2_idx"]]

        if tip == "double_bottom":
            t_neck = df.index[s["neckline_idx"]]

            # Pattern alanı dikdörtgen (hafif yeşil)
            fig.add_shape(type="rect",
                x0=t_b1, x1=t,
                y0=min(s["b2_low"], s["b1_low"]) * 0.998,
                y1=s["neckline"] * 1.002,
                fillcolor="rgba(0,230,118,0.04)",
                line=dict(color="rgba(0,230,118,0.25)", width=1),
                row=1, col=1)

            # B1 destek seviyesi (mavi kesik çizgi)
            fig.add_shape(type="line",
                x0=t_b1, x1=t,
                y0=s["b1_low"], y1=s["b1_low"],
                line=dict(color="rgba(100,149,237,0.7)", width=1, dash="dash"),
                row=1, col=1)

            # Neckline (turuncu kesik çizgi)
            fig.add_shape(type="line",
                x0=t_neck, x1=t,
                y0=s["neckline"], y1=s["neckline"],
                line=dict(color="rgba(255,165,0,0.8)", width=1, dash="dash"),
                row=1, col=1)

            # Bottom 1 işareti
            fig.add_annotation(x=t_b1, y=s["b1_low"],
                text="①", showarrow=True, arrowhead=2,
                arrowcolor="#6495ed", font=dict(color="#6495ed", size=12),
                ax=0, ay=28, row=1, col=1)

            # Bottom 2 işareti
            fig.add_annotation(x=t_b2, y=s["b2_low"],
                text="②", showarrow=True, arrowhead=2,
                arrowcolor="#ff6b6b", font=dict(color="#ff6b6b", size=12),
                ax=0, ay=28, row=1, col=1)

            # Breakout (sinyal) işareti
            fig.add_annotation(x=t, y=df["low"].iloc[i],
                text="▲ SPRING", showarrow=True, arrowhead=2,
                arrowcolor="#00e676", font=dict(color="#00e676", size=11),
                ax=0, ay=35, row=1, col=1)

        elif tip == "likidite_alimi":
            # Pattern alanı (hafif mavi)
            fig.add_shape(type="rect",
                x0=t_b1, x1=t_b2,
                y0=s["b2_low"] * 0.998,
                y1=s["b1_low"] * 1.002,
                fillcolor="rgba(0,150,255,0.06)",
                line=dict(color="rgba(0,150,255,0.3)", width=1),
                row=1, col=1)

            # B1 destek seviyesi (mavi kesik çizgi)
            fig.add_shape(type="line",
                x0=t_b1, x1=t_b2,
                y0=s["b1_low"], y1=s["b1_low"],
                line=dict(color="rgba(100,149,237,0.7)", width=1, dash="dash"),
                row=1, col=1)

            # Bottom 1 işareti
            fig.add_annotation(x=t_b1, y=s["b1_low"],
                text="①", showarrow=True, arrowhead=2,
                arrowcolor="#6495ed", font=dict(color="#6495ed", size=12),
                ax=0, ay=28, row=1, col=1)

            # Likidite alımı (B2 = sinyal barı)
            fig.add_annotation(x=t_b2, y=s["b2_low"],
                text="💧 LQ", showarrow=True, arrowhead=2,
                arrowcolor="#00bfff", font=dict(color="#00bfff", size=11),
                ax=0, ay=35, row=1, col=1)

    # ── Son fiyat etiketi (Y ekseninde, TradingView stili) ────
    last_close = float(df["close"].iloc[-1])
    last_open  = float(df["open"].iloc[-1])
    px_color   = "#26a69a" if last_close >= last_open else "#ef5350"
    px_str     = f"{last_close:,.4f}" if last_close < 10 else f"{last_close:,.2f}"

    fig.add_annotation(
        x=1.0, xref="paper",
        y=last_close, yref="y",
        text=f" {px_str} ",
        showarrow=False,
        font=dict(color="white", size=10, family="monospace"),
        bgcolor=px_color,
        bordercolor=px_color,
        borderpad=3,
        xanchor="left",
        yanchor="middle",
    )

    fig.update_layout(
        title=f"{sembol} — Double Bottom Spring ({periyot})",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        dragmode="pan",
        height=620,
        showlegend=False,
        margin=dict(t=50, b=60, r=75),
        newshape=dict(line_color="#00e676", line_width=2),
        updatemenus=[{
            "type":        "buttons",
            "showactive":  False,
            "bgcolor":     "rgba(30,30,30,0.85)",
            "bordercolor": "#555",
            "font":        {"color": "white", "size": 11},
            "y":           0.18,
            "x":           0.5,
            "xanchor":     "center",
            "yanchor":     "bottom",
            "buttons": [{
                "label":  "⊡  Autoscale",
                "method": "relayout",
                "args":   [{"yaxis.autorange":  True,
                             "xaxis.autorange":  True,
                             "yaxis2.autorange": True}]
            }]
        }]
    )
    return fig

GRAFIK_CONFIG = {
    "scrollZoom":              True,
    "displayModeBar":          True,
    "modeBarButtonsToRemove":  ["lasso2d", "select2d"],
    "modeBarButtonsToAdd":     ["drawcircle", "drawrect", "drawopenpath",
                                "drawline", "eraseshape"],
}

# ─── ANA SAYFA ─────────────────────────────────────────────
st.title("📈 Wyckoff Double Bottom Screener")
st.caption("Binance Futures • Sol panelden sembol ve ayarları düzenleyebilirsin")

# ── Periyot + Grafiği Göster (tab'ların üstünde) ───────────
_col_p, _col_g = st.columns([2, 1])
with _col_p:
    PERIYOT = st.selectbox(
        "Periyot", PERIYOT_LISTESI,
        key="periyot_select",
        label_visibility="collapsed",
    )
with _col_g:
    if st.button("📊 Grafiği Göster", type="primary", use_container_width=True):
        st.session_state.grafik_gosteriliyor = True
        st.session_state.switch_to_grafik    = True

# Grafik tabına otomatik geç
if st.session_state.switch_to_grafik:
    st.session_state.switch_to_grafik = False
    components.html("""
    <script>
    setTimeout(function() {
        var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.indexOf('Grafik') >= 0) {
                tabs[i].click();
                break;
            }
        }
    }, 150);
    </script>
    """, height=1)

tab1, tab2 = st.tabs(["🔍 Screener", "📊 Grafik"])

# Çizim: otomatik pan + erase sabit stil + renk seçici
components.html("""
<script>
(function() {
    var pDoc;
    try { pDoc = window.parent.document; } catch(e) { return; }

    var DRAW_MODES = ['drawcircle','drawrect','drawopenpath','drawline','drawclosedpath'];
    var STORAGE_KEY = 'wyckoff_draw_color';

    function applyNewShapeColor(plot, color) {
        [plot.layout, plot._fullLayout].forEach(function(l) {
            if (!l) return;
            if (!l.newshape)      l.newshape      = {};
            if (!l.newshape.line) l.newshape.line = {};
            l.newshape.line.color = color;
        });
    }

    function recolorShape(plot, idx, color) {
        if (idx < 0) return;
        var gs = plot.querySelectorAll('.shapelayer > g');
        if (idx < gs.length) {
            gs[idx].querySelectorAll('path,line,polyline').forEach(function(el) {
                el.setAttribute('stroke', color);
            });
        }
        [plot.layout, plot._fullLayout].forEach(function(l) {
            if (l && l.shapes && l.shapes[idx]) {
                if (!l.shapes[idx].line) l.shapes[idx].line = {};
                l.shapes[idx].line.color = color;
            }
        });
    }

    // Erase: drawline butonunun grubundaki son buton = eraseshape
    function styleEraseBtn(plot) {
        if (plot._eraseBtnStyled) return;

        // Yöntem 1: doğrudan data-val
        var btn = plot.querySelector('[data-val="eraseshape"]');

        // Yöntem 2: drawline/drawcircle'ın parent grubundaki son buton
        if (!btn) {
            var ref = plot.querySelector('[data-val="drawline"]') ||
                      plot.querySelector('[data-val="drawcircle"]');
            if (ref) {
                var grp = ref.parentElement;
                while (grp && !grp.classList.contains('modebar-group'))
                    grp = grp.parentElement;
                if (grp) {
                    var all = grp.querySelectorAll('a.modebar-btn');
                    if (all.length) btn = all[all.length - 1];
                }
            }
        }

        // Yöntem 3: tüm butonlarda data-title / innerHTML içinde "eras" ara
        if (!btn) {
            var btns = plot.querySelectorAll('a.modebar-btn');
            for (var i = 0; i < btns.length; i++) {
                var s = (btns[i].getAttribute('data-title') || '') +
                        (btns[i].getAttribute('data-val')   || '') +
                        btns[i].innerHTML;
                if (s.toLowerCase().indexOf('eras') >= 0) { btn = btns[i]; break; }
            }
        }

        if (!btn) return;
        plot._eraseBtnStyled = true;

        // Pan butonu gibi sabit koyu görünsün
        var panBtn = plot.querySelector('[data-val="pan"]');
        if (panBtn) {
            var cs = pDoc.defaultView.getComputedStyle(panBtn);
            btn.style.background   = cs.background   || 'rgba(55,55,55,0.9)';
            btn.style.borderRadius = cs.borderRadius || '3px';
            btn.style.opacity      = '1';
        } else {
            btn.style.background   = 'rgba(55,55,55,0.9)';
            btn.style.borderRadius = '3px';
        }
        btn.style.border = '1px solid rgba(255,255,255,0.25)';
    }

    function addColorPicker(plot) {
        if (plot._colorPickerAdded) return;
        var modebar = plot.querySelector('.modebar');
        if (!modebar) return;
        plot._colorPickerAdded = true;
        plot._lastShapeIdx = -1;

        var savedColor = localStorage.getItem(STORAGE_KEY) || '#00e676';
        applyNewShapeColor(plot, savedColor);

        var group = pDoc.createElement('div');
        group.style.cssText = 'display:inline-flex;align-items:center;padding:0 5px;' +
            'border-left:1px solid rgba(255,255,255,0.15);';
        var picker = pDoc.createElement('input');
        picker.type  = 'color';
        picker.value = savedColor;
        picker.title = 'Çizim rengi';
        picker.style.cssText = 'width:22px;height:18px;border:none;border-radius:3px;' +
            'cursor:pointer;padding:1px;background:transparent;';
        group.appendChild(picker);
        modebar.appendChild(group);

        // Hangi shape tıklandı: elementsFromPoint ile katman sırasına bakmaksızın bul
        plot.addEventListener('mousedown', function(e) {
            var els = pDoc.elementsFromPoint(e.clientX, e.clientY);
            var gs  = plot.querySelectorAll('.shapelayer > g');
            for (var j = 0; j < els.length; j++) {
                for (var i = 0; i < gs.length; i++) {
                    if (gs[i] === els[j] || gs[i].contains(els[j])) {
                        plot._lastShapeIdx = i;
                        return;
                    }
                }
            }
        });

        picker.addEventListener('input', function() {
            var c = picker.value;
            localStorage.setItem(STORAGE_KEY, c);
            applyNewShapeColor(plot, c);
            recolorShape(plot, plot._lastShapeIdx, c);
        });
    }

    function attachRelayout(plot) {
        if (plot._drawAutoOff) return;
        plot._drawAutoOff = true;
        plot.on('plotly_relayout', function(ed) {
            if (ed.hasOwnProperty('shapes')) {
                var dm = plot._fullLayout && plot._fullLayout.dragmode;
                if (DRAW_MODES.indexOf(dm) >= 0) {
                    setTimeout(function() {
                        var btn = plot.querySelector('[data-attr="dragmode"][data-val="pan"]');
                        if (btn) btn.click();
                    }, 100);
                }
            }
        });
    }

    setInterval(function() {
        pDoc.querySelectorAll('.js-plotly-plot').forEach(function(plot) {
            styleEraseBtn(plot);
            addColorPicker(plot);
            attachRelayout(plot);
        });
    }, 500);
})();
</script>
""", height=1)

# ── TAB 1: SCREENER ────────────────────────────────────────
with tab1:
    btn_area = st.empty()

    if st.session_state.scanning:
        with btn_area.container():
            st.markdown(
                '<div class="runner-top"><span class="runner-on-btn">🏃</span></div>',
                unsafe_allow_html=True)
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
            progress.progress((idx + 1) / len(SEMBOLLER),
                               text=f"{sembol} taranıyor...")
            try:
                df      = veri_cek(sembol, PERIYOT, LIMIT)
                db_sin  = double_bottom_tespit(df)
                lq_sin  = likidite_alimi_tespit(df)
                dt_sin  = double_top_tespit(df)

                if PATTERN_MOD == "Likidite Alımı":
                    sinyaller = lq_sin
                elif PATTERN_MOD == "Hepsi":
                    sinyaller = db_sin + lq_sin + dt_sin
                else:  # DB + DT
                    sinyaller = db_sin + dt_sin

                aktif    = [s for s in sinyaller if s["bar"] >= len(df) - 5]
                tum_sin  = db_sin + lq_sin + dt_sin
                bars_ago = (len(df) - 1 - tum_sin[-1]["bar"]) if tum_sin else None

                # Aktif sinyal tipi belirle
                if aktif:
                    tipler = {s["tip"] for s in aktif}
                    if "double_top" in tipler and "double_bottom" in tipler:
                        sinyal_tip = "db_dt"
                    elif "double_top" in tipler:
                        sinyal_tip = "double_top"
                    elif "double_bottom" in tipler and "likidite_alimi" in tipler:
                        sinyal_tip = "her_ikisi"
                    elif "likidite_alimi" in tipler:
                        sinyal_tip = "likidite_alimi"
                    else:
                        sinyal_tip = "double_bottom"
                else:
                    sinyal_tip = None

                st.session_state.scan_results.append({
                    "sembol":    sembol,
                    "sinyal":    sinyal_tip,
                    "fiyat":     round(df["close"].iloc[-1], 4),
                    "bars_ago":  bars_ago,
                    "df":        df,
                    "sinyaller": sinyaller,
                    "db_count":  len(db_sin),
                    "lq_count":  len(lq_sin),
                    "dt_count":  len(dt_sin),
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
        aktif_list  = [r for r in st.session_state.scan_results if r["sinyal"]]
        sessiz_list = [r for r in st.session_state.scan_results if r["sinyal"] is None]

        col1, col2, col3 = st.columns(3)
        col1.metric("Aktif Sinyal",    len(aktif_list))
        col2.metric("Double Bottom",   sum(1 for r in st.session_state.scan_results if r.get("db_count", 0) > 0))
        col3.metric("Likidite Alımı",  sum(1 for r in st.session_state.scan_results if r.get("lq_count", 0) > 0))
        st.markdown("---")

        if aktif_list:
            st.subheader("🎯 Aktif Sinyaller")
            for r in aktif_list:
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
                c1.markdown(f"**{r['sembol']}**")
                if r["sinyal"] == "likidite_alimi":
                    c2.markdown(":blue[💧 LİKİDİTE ALIMI]")
                elif r["sinyal"] == "her_ikisi":
                    c2.markdown(":green[▲ DB + 💧 LQ]")
                elif r["sinyal"] == "double_top":
                    c2.markdown(":red[▼ DOUBLE TOP]")
                elif r["sinyal"] == "db_dt":
                    c2.markdown(":orange[▲▼ DB + DT]")
                else:
                    c2.markdown(":green[▲ DOUBLE BOTTOM]")
                c3.markdown(f"`{r['fiyat']}`")
                c4.markdown(f"_{r['bars_ago']} bar önce_" if r["bars_ago"] is not None else "—")
                if c5.button("📊", key=f"chart_{r['sembol']}"):
                    st.session_state.selected_symbol        = r["sembol"]
                    st.session_state.show_chart_in_screener = True
            st.markdown("---")

        st.subheader("Tüm Semboller")
        tablo = []
        for r in st.session_state.scan_results:
            if r["sinyal"] == "double_bottom":
                sinyal_str = "▲ DOUBLE BOTTOM"
            elif r["sinyal"] == "likidite_alimi":
                sinyal_str = "💧 LİKİDİTE ALIMI"
            elif r["sinyal"] == "her_ikisi":
                sinyal_str = "▲ DB + 💧 LQ"
            elif r["sinyal"] == "double_top":
                sinyal_str = "▼ DOUBLE TOP"
            elif r["sinyal"] == "db_dt":
                sinyal_str = "▲▼ DB + DT"
            elif r["sinyal"] == "hata":
                sinyal_str = f"HATA: {r.get('hata_msg','')[:60]}"
            else:
                sinyal_str = "—"
            tablo.append({
                "Sembol":     r["sembol"],
                "Sinyal":     sinyal_str,
                "Fiyat":      r["fiyat"],
                "Son Sinyal": f"{r['bars_ago']} bar önce" if r.get("bars_ago") is not None else "—",
            })
        st.dataframe(pd.DataFrame(tablo), use_container_width=True, hide_index=True)

        if (st.session_state.show_chart_in_screener
                and st.session_state.selected_symbol):
            sel   = st.session_state.selected_symbol
            match = next((r for r in st.session_state.scan_results
                          if r["sembol"] == sel), None)
            if match and match["df"] is not None:
                st.markdown(f"---\n### 📊 {sel} — {PERIYOT}")
                fig = grafik_ciz(sel, match["df"], match["sinyaller"], PERIYOT)
                st.plotly_chart(fig, use_container_width=True, config=GRAFIK_CONFIG)

# ── TAB 2: GRAFİK ──────────────────────────────────────────
with tab2:
    secili_list = SEMBOLLER if SEMBOLLER else ["BTC/USDT"]
    secili = st.selectbox("Sembol seç", secili_list)

    if st.session_state.grafik_gosteriliyor:
        with st.spinner(f"{secili} verisi çekiliyor..."):
            try:
                df     = veri_cek(secili, PERIYOT, LIMIT)
                db_sin = double_bottom_tespit(df)
                lq_sin = likidite_alimi_tespit(df)
                dt_sin = double_top_tespit(df)

                if PATTERN_MOD == "Likidite Alımı":
                    sinyaller = lq_sin
                elif PATTERN_MOD == "Hepsi":
                    sinyaller = db_sin + lq_sin + dt_sin
                else:  # DB + DT
                    sinyaller = db_sin + dt_sin

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Toplam Bar",     len(df))
                c2.metric("Double Bottom",  len(db_sin))
                c3.metric("Likidite Alımı", len(lq_sin))
                c4.metric("Double Top",     len(dt_sin))

                fig = grafik_ciz(secili, df, sinyaller, PERIYOT)
                st.plotly_chart(fig, use_container_width=True, config=GRAFIK_CONFIG)
            except Exception as e:
                st.error(f"Hata: {e}")
    else:
        st.info("Yukarıdan periyot seçip **📊 Grafiği Göster** butonuna tıklayın.")

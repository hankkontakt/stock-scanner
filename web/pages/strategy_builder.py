"""
web/pages/strategy_builder.py
=============================
Strategy Builder UI för Streamlit.

Gör det möjligt att:
- Välja strategityp från dropdown
- Redigera parametrar (sliders, inputs)
- Lägga till filter (ADX, volume, etc.)
- Konfigurera risk-inställningar
- Köra backtest
- Visa equity curve, metrics table, signal chart, trade list
- Köra parameter optimization (grid search)
- Spara/ladda strategier
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

from strategy.base import (
    Strategy, run_backtest, run_parameter_sweep,
    _sharpe_ratio, _sortino_ratio, _max_drawdown, _cagr,
)
from strategy.optimizer import GridSearchCV, RandomSearchCV, WalkForwardOptimization
from strategy.costs import (
    FixedCommission, PercentageCommission,
    SlippageModel, VolumeBasedSlippage,
)
from strategy.risk import (
    PositionSizer, StopLossManager, PortfolioRiskMonitor,
    DrawdownController, CorrelationChecker,
)
from strategy.dsl import parse_strategy, validate_strategy, dsl_to_yaml


# ── Strategiregister för UI ────────────────────────────────────────────────────

_UI_STRATEGIES = {
    "Momentum - Time Series Momentum": {
        "class": "TimeSeriesMomentum",
        "module": "strategy.strategies.momentum_strategy",
        "params": {
            "lookback": {"type": "slider", "min": 20, "max": 500, "value": 252, "label": "Lookback (dagar)"},
            "hold": {"type": "slider", "min": 5, "max": 252, "value": 63, "label": "Hållperiod (dagar)"},
            "use_binary": {"type": "checkbox", "value": True, "label": "Binär signal"},
        },
    },
    "Momentum - Dual Momentum": {
        "class": "DualMomentum",
        "module": "strategy.strategies.momentum_strategy",
        "params": {
            "absolute_lookback": {"type": "slider", "min": 20, "max": 500, "value": 252, "label": "Absolut lookback"},
            "relative_lookback": {"type": "slider", "min": 20, "max": 500, "value": 126, "label": "Relativ lookback"},
        },
    },
    "Momentum - Säsongsstrategi": {
        "class": "SeasonalityStrategy",
        "module": "strategy.strategies.momentum_strategy",
        "params": {
            "month_effect": {"type": "checkbox", "value": True, "label": "Månadseffekt"},
            "day_of_week": {"type": "checkbox", "value": True, "label": "Veckodagseffekt"},
        },
    },
    "Mean Reversion - Bollinger Bands": {
        "class": "BollingerMeanReversion",
        "module": "strategy.strategies.mean_reversion_strategy",
        "params": {
            "period": {"type": "slider", "min": 5, "max": 100, "value": 20, "label": "MA-period"},
            "std_dev": {"type": "slider", "min": 1.0, "max": 4.0, "value": 2.0, "step": 0.5, "label": "Std-avvikelser"},
        },
    },
    "Mean Reversion - RSI": {
        "class": "RSIMeanReversion",
        "module": "strategy.strategies.mean_reversion_strategy",
        "params": {
            "rsi_period": {"type": "slider", "min": 5, "max": 50, "value": 14, "label": "RSI-period"},
            "oversold": {"type": "slider", "min": 10, "max": 50, "value": 30, "label": "Översåld nivå"},
            "overbought": {"type": "slider", "min": 50, "max": 90, "value": 70, "label": "Överköpt nivå"},
        },
    },
    "Mean Reversion - MA Crossover": {
        "class": "MovingAverageCrossover",
        "module": "strategy.strategies.mean_reversion_strategy",
        "params": {
            "fast": {"type": "slider", "min": 5, "max": 100, "value": 20, "label": "Snabbt MA"},
            "slow": {"type": "slider", "min": 20, "max": 500, "value": 50, "label": "Långsamt MA"},
        },
    },
    "Mean Reversion - MACD": {
        "class": "MACDStrategy",
        "module": "strategy.strategies.mean_reversion_strategy",
        "params": {
            "fast": {"type": "slider", "min": 5, "max": 30, "value": 12, "label": "Fast EMA"},
            "slow": {"type": "slider", "min": 15, "max": 60, "value": 26, "label": "Slow EMA"},
            "signal": {"type": "slider", "min": 3, "max": 20, "value": 9, "label": "Signal-period"},
        },
    },
    "Trend Following - Trend": {
        "class": "TrendFollowing",
        "module": "strategy.strategies.trend_following_strategy",
        "params": {
            "fast_ma": {"type": "slider", "min": 10, "max": 200, "value": 50, "label": "Snabbt MA"},
            "slow_ma": {"type": "slider", "min": 50, "max": 500, "value": 200, "label": "Långsamt MA"},
            "filter_adx": {"type": "slider", "min": 10, "max": 50, "value": 25, "label": "ADX-filter"},
        },
    },
    "Trend Following - Donchian Breakout": {
        "class": "DonchianBreakout",
        "module": "strategy.strategies.trend_following_strategy",
        "params": {
            "entry_period": {"type": "slider", "min": 5, "max": 100, "value": 20, "label": "Entry-period"},
            "exit_period": {"type": "slider", "min": 5, "max": 100, "value": 10, "label": "Exit-period"},
        },
    },
    "Trend Following - Supertrend": {
        "class": "SupertrendStrategy",
        "module": "strategy.strategies.trend_following_strategy",
        "params": {
            "atr_period": {"type": "slider", "min": 5, "max": 50, "value": 10, "label": "ATR-period"},
            "multiplier": {"type": "slider", "min": 1.0, "max": 5.0, "value": 3.0, "step": 0.5, "label": "Multiplikator"},
        },
    },
}

# Datakälla för strategier som använder scoring-faktorer
_FACTOR_NAMES = [
    "score_value", "score_quality", "score_momentum", "score_growth",
    "score_risk", "score_size", "score_dividend", "score_sentiment",
]


# ── Datahämtning ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _fetch_price_data(ticker: str, years: int = 3) -> pd.DataFrame:
    """Hämta prisdata för en ticker."""
    try:
        data = yf.download(ticker, period=f"{years+1}y", auto_adjust=True, progress=False)
        if data.empty:
            return pd.DataFrame()

        close = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        df = pd.DataFrame({"Close": close})
        df.index.name = "Date"

        # Lägg till High/Low om tillgängligt
        if "High" in data.columns:
            high = data["High"]
            low = data["Low"]
            volume = data.get("Volume", pd.Series(0, index=data.index))
            df["High"] = high if not isinstance(high, pd.DataFrame) else high.iloc[:, 0]
            df["Low"] = low if not isinstance(low, pd.DataFrame) else low.iloc[:, 0]
            df["Volume"] = volume if not isinstance(volume, pd.DataFrame) else volume.iloc[:, 0]

        return df
    except Exception as e:
        st.warning(f"Kunde inte hämta data för {ticker}: {e}")
        return pd.DataFrame()


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _get_strategy_instance(strategy_name: str, strategy_params: dict) -> Optional[Strategy]:
    """Skapa en Strategy-instans från UI-val."""
    strategy_info = _UI_STRATEGIES.get(strategy_name)
    if not strategy_info:
        return None

    module_name = strategy_info["module"]
    class_name = strategy_info["class"]

    try:
        import importlib
        module = importlib.import_module(module_name)
        strategy_class = getattr(module, class_name)
        return strategy_class(name=strategy_name, params=strategy_params)
    except Exception as e:
        st.error(f"Kunde inte ladda strategi {strategy_name}: {e}")
        return None


def _plot_equity_curve(result) -> go.Figure:
    """Plot equity curve från backtestresultat."""
    fig = go.Figure()

    equity = result.equity_curve
    if equity is not None and len(equity) > 0:
        fig.add_trace(go.Scatter(
            x=equity.index,
            y=equity.values,
            mode="lines",
            name="Equity",
            line=dict(color="#00d4aa", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.08)",
        ))

    # Benchmark om tillgängligt
    if result.benchmark_returns is not None:
        bench_equity = (1 + result.benchmark_returns).cumprod() * 100000
        fig.add_trace(go.Scatter(
            x=bench_equity.index,
            y=bench_equity.values,
            mode="lines",
            name="Benchmark",
            line=dict(color="#f59e0b", width=1.5, dash="dash"),
        ))

    fig.update_layout(
        title="Equity-kurva (100k startkapital)",
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#1e2230",
        height=350,
        margin=dict(t=44, b=16, l=16, r=16),
        hovermode="x unified",
        yaxis_title="Portföljvärde (kr)",
    )
    return fig


def _plot_signals(prices: pd.Series, signals: pd.Series) -> go.Figure:
    """Plot pris med signal-markeringar."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.7, 0.3],
                        vertical_spacing=0.05)

    # Pris
    fig.add_trace(go.Scatter(
        x=prices.index, y=prices.values,
        mode="lines", name="Pris",
        line=dict(color="#42a5f5", width=1.5),
    ), row=1, col=1)

    # Signal-markeringar
    long_signals = signals[signals == 1]
    short_signals = signals[signals == -1]

    fig.add_trace(go.Scatter(
        x=long_signals.index,
        y=prices.loc[long_signals.index],
        mode="markers",
        name="Köp (lång)",
        marker=dict(symbol="triangle-up", size=10, color="#4caf50"),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=short_signals.index,
        y=prices.loc[short_signals.index],
        mode="markers",
        name="Sälj (kort)",
        marker=dict(symbol="triangle-down", size=10, color="#ef5350"),
    ), row=1, col=1)

    # Signal-linje
    fig.add_trace(go.Scatter(
        x=signals.index, y=signals.values,
        mode="lines", name="Signal",
        line=dict(color="#ff9800", width=1),
        fill="tozeroy",
        fillcolor="rgba(255,152,0,0.1)",
    ), row=2, col=1)

    fig.update_layout(
        title="Pris och signaler",
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#1e2230",
        height=500,
        margin=dict(t=44, b=16, l=16, r=16),
        hovermode="x unified",
        showlegend=False,
    )
    fig.update_yaxes(title_text="Pris", row=1, col=1)
    fig.update_yaxes(title_text="Signal", row=2, col=1, tickvals=[-1, 0, 1])

    return fig


def _plot_trades_histogram(trades: pd.DataFrame) -> go.Figure:
    """Histogram över trade-avkastningar."""
    if trades.empty or "pnl" not in trades.columns:
        return go.Figure()

    pnls = trades["pnl"].dropna() * 100

    colors = ["#4caf50" if p >= 0 else "#ef5350" for p in pnls]

    fig = go.Figure(go.Bar(
        x=list(range(len(pnls))),
        y=pnls.values,
        marker_color=colors,
        name="Trade P&L (%)",
        hovertemplate="Trade %{x}<br>P&L: %{y:.2f}%<extra></extra>",
    ))

    fig.update_layout(
        title=f"Trade-fördelning ({len(pnls)} trades)",
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#1e2230",
        height=250,
        margin=dict(t=36, b=16, l=16, r=16),
        yaxis_title="P&L (%)",
        xaxis_title="Trade #",
    )
    return fig


def _render_metrics_table(metrics: dict):
    """Visa metric-kort i en grid."""
    metric_map = [
        ("CAGR", f"{metrics.get('cagr', 0)*100:.2f}%", "Årlig avkastning"),
        ("Sharpe", f"{metrics.get('sharpe', 0):.2f}", "Riskjusterad avkastning"),
        ("Sortino", f"{metrics.get('sortino', 0):.2f}", "Nedside-riskjusterad"),
        ("Calmar", f"{metrics.get('calmar', 0):.2f}", "CAGR / |Max DD|"),
        ("Volatilitet", f"{metrics.get('volatility', 0)*100:.2f}%", "Årlig volatilitet"),
        ("Max Drawdown", f"{metrics.get('max_drawdown', 0)*100:.2f}%", "Värsta nedgång"),
        ("Win Rate", f"{metrics.get('win_rate', 0)*100:.1f}%", "Andel vinnande trades"),
        ("Profit Factor", f"{metrics.get('profit_factor', 0):.2f}", "Total vinst / total förlust"),
        ("Total avkastning", f"{metrics.get('total_return', 0)*100:.2f}%", "Kumulativ avkastning"),
        ("Antal trades", f"{metrics.get('n_trades', 0)}", "Totalt antal affärer"),
    ]

    cols = st.columns(5)
    for i, (label, value, help_text) in enumerate(metric_map):
        with cols[i % 5]:
            st.metric(label=label, value=value, help=help_text)


# ── Spara/ladda strategier ────────────────────────────────────────────────────

STRATEGY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "saved_strategies"

def _ensure_strategy_dir():
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

def _save_strategy(name: str, strategy_dsl: str):
    """Spara en strategi som YAML-fil."""
    _ensure_strategy_dir()
    path = STRATEGY_DIR / f"{name.lower().replace(' ', '_')}.yaml"
    path.write_text(strategy_dsl, encoding="utf-8")
    return str(path)

def _load_strategies() -> dict:
    """Ladda alla sparade strategier."""
    _ensure_strategy_dir()
    strategies = {}
    for f in sorted(STRATEGY_DIR.glob("*.yaml")):
        try:
            content = f.read_text(encoding="utf-8")
            strategies[f.stem] = content
        except Exception:
            pass
    return strategies

def _delete_strategy(name: str):
    """Ta bort en sparad strategi."""
    path = STRATEGY_DIR / f"{name}.yaml"
    if path.exists():
        path.unlink()


# ── Huvud-sida ────────────────────────────────────────────────────────────────

def page_strategy_builder():
    """Huvudfunktion för Strategy Builder-sidan."""
    st.title("🔧 Strategy Builder")

    st.markdown("""
    Bygg och testa handelsstrategier. Välj strategityp, justera parametrar,
    lägg till filter och riskregler, och kör backtest direkt.
    """)

    # ── Spara/ladda strategier ────────────────────────────────────────────────
    saved_strategies = _load_strategies()

    with st.expander("💾 Spara/Ladda strategier", expanded=False):
        col_save, col_load, col_del = st.columns([2, 2, 1])

        with col_save:
            save_name = st.text_input("Strateginamn", key="sb_save_name",
                                       placeholder="Min strategi")
            if st.button("💾 Spara strategi", key="sb_save_btn", use_container_width=True):
                if save_name.strip():
                    # Bygg DSL
                    strategy_type = st.session_state.get("sb_strategy_type", "")
                    params = st.session_state.get("sb_params", {})
                    dsl = f"""name: "{save_name.strip()}"
type: "{strategy_type}"
params:
"""
                    for k, v in params.items():
                        if isinstance(v, str):
                            dsl += f"    {k}: \"{v}\"\n"
                        elif isinstance(v, bool):
                            dsl += f"    {k}: {str(v).lower()}\n"
                        else:
                            dsl += f"    {k}: {v}\n"

                    path = _save_strategy(save_name.strip(), dsl)
                    st.success(f"Sparad: {path}")
                    st.rerun()

        with col_load:
            if saved_strategies:
                load_name = st.selectbox("Välj strategi", list(saved_strategies.keys()),
                                         key="sb_load_name")
                if st.button("📂 Ladda strategi", key="sb_load_btn", use_container_width=True):
                    # Ladda och applicera
                    dsl = saved_strategies[load_name]
                    try:
                        strategy = parse_strategy(dsl)
                        st.session_state["sb_strategy_type"] = strategy.name
                        st.session_state["sb_params"] = strategy.params
                        st.success(f"Laddade strategi: {load_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Kunde inte ladda: {e}")
            else:
                st.info("Inga sparade strategier ännu")

        with col_del:
            if saved_strategies:
                del_name = st.selectbox("Välj att ta bort", list(saved_strategies.keys()),
                                        key="sb_del_name")
                if st.button("🗑️ Ta bort", key="sb_del_btn", use_container_width=True):
                    _delete_strategy(del_name)
                    st.success(f"Borttagen: {del_name}")
                    st.rerun()

    st.markdown("---")

    # ── Strategikonfiguration ─────────────────────────────────────────────────
    col_strategy, col_ticker, col_years = st.columns([2, 1, 1])

    with col_strategy:
        strategy_options = list(_UI_STRATEGIES.keys())
        default_idx = 0
        if "sb_strategy_type" in st.session_state:
            saved_name = st.session_state["sb_strategy_type"]
            if saved_name in strategy_options:
                default_idx = strategy_options.index(saved_name)

        strategy_name = st.selectbox(
            "Strategityp",
            options=strategy_options,
            index=default_idx,
            key="sb_strategy_type_select",
            help="Välj en strategityp att konfigurera",
        )

    with col_ticker:
        ticker = st.text_input("Ticker", value="SPY", key="sb_ticker",
                                help="Aktie/ETF att testa strategin på").upper()

    with col_years:
        years = st.slider("Data (år)", min_value=1, max_value=10, value=3, key="sb_years")

    # ── Parameter-editor ──────────────────────────────────────────────────────
    st.markdown("### 📐 Parametrar")
    strategy_info = _UI_STRATEGIES.get(strategy_name, {})
    param_defs = strategy_info.get("params", {})

    strategy_params = {}
    if param_defs:
        cols = st.columns(3)
        for i, (param_key, param_def) in enumerate(param_defs.items()):
            with cols[i % 3]:
                ptype = param_def["type"]
                label = param_def.get("label", param_key)
                key = f"sb_param_{param_key}"

                # Försök hitta tidigare värde
                saved_params = st.session_state.get("sb_params", {})
                saved_value = saved_params.get(param_key, param_def["value"])

                if ptype == "slider":
                    min_v = param_def.get("min", 0)
                    max_v = param_def.get("max", 100)
                    step = param_def.get("step", 1)
                    value = st.slider(label, min_value=min_v, max_value=max_v,
                                      value=saved_value, step=step, key=key)
                elif ptype == "checkbox":
                    value = st.checkbox(label, value=bool(saved_value), key=key)
                elif ptype == "number":
                    value = st.number_input(label, value=float(saved_value), key=key)
                else:
                    value = st.text_input(label, value=str(saved_value), key=key)

                strategy_params[param_key] = value
    else:
        st.info("Denna strategityp har inga justerbara parametrar.")

    # Spara parametrar i session state
    st.session_state["sb_params"] = strategy_params

    # ── Filter-redigerare ─────────────────────────────────────────────────────
    st.markdown("### 🔍 Filter")
    st.caption("Lägg till villkor som måste uppfyllas för att signal ska genereras")

    if "sb_filters" not in st.session_state:
        st.session_state["sb_filters"] = []

    filter_options = ["adx > 25", "volume > 1000000", "rsi_14 < 30", "rsi_14 > 70",
                      "close > ma50", "close > ma200", "volume > 500000"]

    col_filter_add, col_filter_clear = st.columns([3, 1])
    with col_filter_add:
        new_filter = st.selectbox("Lägg till filter", [""] + filter_options,
                                  key="sb_new_filter")
        if new_filter and st.button("➕ Lägg till", key="sb_add_filter"):
            if new_filter not in st.session_state["sb_filters"]:
                st.session_state["sb_filters"].append(new_filter)
                st.rerun()

    with col_filter_clear:
        if st.button("🗑️ Rensa alla", key="sb_clear_filters"):
            st.session_state["sb_filters"] = []
            st.rerun()

    if st.session_state["sb_filters"]:
        st.markdown("**Aktiva filter:**")
        for i, f in enumerate(st.session_state["sb_filters"]):
            c1, c2 = st.columns([10, 1])
            with c1:
                st.markdown(f"- `{f}`")
            with c2:
                if st.button("✕", key=f"sb_del_filter_{i}"):
                    st.session_state["sb_filters"].remove(f)
                    st.rerun()

    # ── Risk-inställningar ────────────────────────────────────────────────────
    st.markdown("### 🛡️ Risk-inställningar")

    col_risk1, col_risk2, col_risk3 = st.columns(3)

    with col_risk1:
        stop_loss = st.number_input("Stop-loss (%)", min_value=0.0, max_value=50.0,
                                     value=5.0, step=0.5, key="sb_stop_loss",
                                     help="0 = ingen stop-loss") / 100
        use_trailing = st.checkbox("Trailing stop", value=True, key="sb_trailing",
                                   help="Justerar stop-loss uppåt när priset stiger")

    with col_risk2:
        max_position = st.slider("Max position (% av kapital)", 0, 100, 20, 5,
                                 key="sb_max_pos", help="Max andel av kapital i en position")
        max_leverage = st.slider("Max hävstång", 1.0, 3.0, 1.0, 0.5, key="sb_leverage")

    with col_risk3:
        max_dd = st.slider("Stoppa vid drawdown (%)", 0, 50, 25, 5,
                           key="sb_max_dd", help="Stoppa trading om drawdown överstiger denna nivå. 0 = av")
        pos_sizing = st.selectbox("Position sizing", ["equal_weight", "kelly", "fixed_fraction"],
                                  index=0, key="sb_pos_sizing")

    # ── Kostnadsinställningar ─────────────────────────────────────────────────
    st.markdown("### 💰 Kostnadsinställningar")

    col_cost1, col_cost2, col_cost3 = st.columns(3)
    with col_cost1:
        commission_pct = st.number_input("Provision (%)", min_value=0.0, max_value=5.0,
                                          value=0.1, step=0.05, key="sb_commission") / 100
    with col_cost2:
        slippage_bps = st.number_input("Slippage (bps)", min_value=0, max_value=100,
                                        value=5, step=1, key="sb_slippage")
    with col_cost3:
        initial_capital = st.number_input("Startkapital", min_value=10000, max_value=10_000_000,
                                           value=100_000, step=10_000, key="sb_capital")

    # ── Kör backtest ──────────────────────────────────────────────────────────
    st.markdown("---")
    run_col1, run_col2 = st.columns([3, 1])
    with run_col1:
        run_bt = st.button("▶️ Kör backtest", type="primary", key="sb_run_bt",
                           use_container_width=True)
    with run_col2:
        run_opt = st.button("⚙️ Optimera parametrar", key="sb_run_opt",
                            use_container_width=True, disabled=(len(param_defs) < 2))

    if run_bt or "sb_result" in st.session_state:
        if run_bt:
            with st.spinner(f"Hämtar data för {ticker} ({years} år)..."):
                data = _fetch_price_data(ticker, years)

            if data.empty:
                st.error(f"Kunde inte hämta data för {ticker}. Kontrollera tickern.")
                st.session_state["sb_result"] = None
            else:
                with st.spinner("Kör backtest..."):
                    strategy = _get_strategy_instance(strategy_name, strategy_params)
                    if strategy is None:
                        st.error("Kunde inte skapa strategi-instans")
                        st.session_state["sb_result"] = None
                    else:
                        # Kör backtest
                        result = run_backtest(strategy, data, initial_capital)

                        # Applicera kostnader
                        commission = PercentageCommission(pct=commission_pct)
                        slippage = SlippageModel(fixed_bps=slippage_bps)
                        from strategy.costs import apply_costs
                        result = apply_costs(result, commission=commission, slippage=slippage)

                        st.session_state["sb_result"] = result
                        st.session_state["sb_data"] = data

        result = st.session_state.get("sb_result")
        data = st.session_state.get("sb_data")

        if result is not None:
            st.markdown("## 📊 Resultat")

            # Metrics
            _render_metrics_table(result.metrics)

            # Flikar
            tab1, tab2, tab3, tab4 = st.tabs([
                "📈 Equity-kurva", "📶 Signaler", "📋 Trades", "📊 Data"
            ])

            with tab1:
                fig_eq = _plot_equity_curve(result)
                st.plotly_chart(fig_eq, use_container_width=True)

            with tab2:
                if data is not None and "Close" in data.columns:
                    fig_sig = _plot_signals(data["Close"], result.signals)
                    st.plotly_chart(fig_sig, use_container_width=True)

            with tab3:
                if result.trades is not None and not result.trades.empty:
                    # Trade-historik
                    trades_display = result.trades.copy()
                    if "entry_date" in trades_display.columns:
                        trades_display["entry_date"] = trades_display["entry_date"].dt.strftime("%Y-%m-%d")
                    if "exit_date" in trades_display.columns:
                        trades_display["exit_date"] = trades_display["exit_date"].dt.strftime("%Y-%m-%d")
                    if "pnl" in trades_display.columns:
                        trades_display["pnl_pct"] = trades_display["pnl"] * 100

                    display_cols = [c for c in ["entry_date", "exit_date", "direction", "pnl_pct"]
                                    if c in trades_display.columns]
                    if display_cols:
                        st.dataframe(
                            trades_display[display_cols].round(2),
                            use_container_width=True,
                            hide_index=True,
                            height=300,
                        )

                    # Trade-histogram
                    fig_trades = _plot_trades_histogram(result.trades)
                    st.plotly_chart(fig_trades, use_container_width=True)
                else:
                    st.info("Inga trades genomfördes")

            with tab4:
                if data is not None:
                    st.dataframe(data.tail(20).round(2), use_container_width=True)
                st.download_button(
                    "📥 Ladda ner CSV",
                    data=data.to_csv() if data is not None else "",
                    file_name=f"backtest_{ticker}_{datetime.now():%Y%m%d}.csv",
                    mime="text/csv",
                )

            # ── Parameteroptimering ───────────────────────────────────────────
            if run_opt:
                st.markdown("---")
                st.subheader("⚙️ Parameteroptimering")

                # Bygg param_grid från UI-parametrar
                if param_defs:
                    param_grid = {}
                    for key, defn in param_defs.items():
                        if defn["type"] == "slider":
                            min_v = defn.get("min", 0)
                            max_v = defn.get("max", 100)
                            step = defn.get("step", 1)
                            # 5 steg mellan min och max
                            n_steps = min(5, int((max_v - min_v) / step) + 1)
                            values = [min_v + i * (max_v - min_v) / (n_steps - 1) for i in range(n_steps)]
                            param_grid[key] = [round(v, 1) if isinstance(step, float) else int(round(v)) for v in values]
                        elif defn["type"] == "checkbox":
                            param_grid[key] = [True, False]

                    if len(param_grid) >= 2:
                        with st.spinner("Kör grid search..."):
                            opt_result = run_parameter_sweep(
                                strategy.__class__, data, param_grid,
                                scoring="sharpe", initial_capital=initial_capital
                            )

                        st.dataframe(opt_result.head(10).round(4), use_container_width=True, height=300)

                        if not opt_result.empty and "sharpe" in opt_result.columns:
                            st.subheader("Bästa parametrar")
                            best = opt_result.iloc[0]
                            best_params = {k: best[k] for k in param_grid.keys() if k in best.index or k in best}
                            st.json(best_params)
                    else:
                        st.info("Behöver minst 2 parametrar för optimering")
                else:
                    st.info("Denna strategi har inga optimerbara parametrar")
        else:
            st.info("Tryck på 'Kör backtest' för att se resultat")

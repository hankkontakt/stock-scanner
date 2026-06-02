"""
monte_carlo.py -- Monte Carlo Simulation for Portfolio Returns
==============================================================
Simulerar framtida portföljutveckling med Monte Carlo-metoder.

Innehåller:
1. Standard Monte Carlo (normalfördelad)
2. Geometric Brownian Motion
3. Bootstrap-simulering (ingen distribution-antagande)
4. Plotly-visualisering
5. Sannolikhetsberäkningar (förlust, VaR)

Användning:
    from portfolio.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator()
    result = sim.simulate(returns, n_simulations=10000)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MonteCarloSimulator:
    """
    Monte Carlo-simulator för portföljavkastning.

    Simulerar framtida prisutveckling med olika metoder:
      - Standard normalfördelade returns
      - Geometric Brownian Motion
      - Bootstrap från historik
    """

    def __init__(self, random_seed: Optional[int] = None):
        """
        Args:
            random_seed: Seed för reproducibilitet (None = slump)
        """
        if random_seed is not None:
            np.random.seed(random_seed)

    # ── Standard Monte Carlo ───────────────────────────────────────────────

    def simulate(self,
                 returns: np.ndarray,
                 n_simulations: int = 10000,
                 n_days: int = 252,
                 initial_value: float = 1.0) -> np.ndarray:
        """
        Standard Monte Carlo-simulering.

        Drar returns från historikens fördelning (bootstrap) och simulerar
        framtida prisutveckling.

        Args:
            returns: Historiska avkastningar (T,)
            n_simulations: Antal simuleringar
            n_days: Antal dagar framåt
            initial_value: Startvärde (t.ex. portföljvärde)

        Returns:
            Array (n_simulations x n_days+1) med simulerade portföljvärden
        """
        returns = np.asarray(returns, dtype=float)
        returns = returns[~np.isnan(returns)]

        if len(returns) < 20:
            logger.warning(f"För få observationer för simulering: {len(returns)}")
            # Fallback: antag normalfördelning
            mu = 0.0005  # ~12% yearly
            sigma = 0.02  # ~30% yearly
            returns = np.random.normal(mu, sigma, 500)

        # Bootstrap från historik
        n_hist = len(returns)

        # Alla simuleringar
        simulations = np.zeros((n_simulations, n_days + 1))
        simulations[:, 0] = initial_value

        for i in range(n_simulations):
            # Dra slumpmässiga returns från historiken
            sampled = np.random.choice(returns, size=n_days, replace=True)
            # Kumulativ produkt
            simulations[i, 1:] = initial_value * np.cumprod(1 + sampled)

        return simulations

    # ── Geometric Brownian Motion ──────────────────────────────────────────

    @staticmethod
    def geometric_brownian(mu: float,
                           sigma: float,
                           S0: float = 1.0,
                           n_days: int = 252,
                           n_sims: int = 1000) -> np.ndarray:
        """
        Geometric Brownian Motion (GBM) simulering.

        dS = μS dt + σS dW

        Den vanligaste modellen för aktieprisrörelser.

        Args:
            mu: Årlig drift (förväntad avkastning, t.ex. 0.10 = 10%)
            sigma: Årlig volatilitet (t.ex. 0.20 = 20%)
            S0: Startpris
            n_days: Antal dagar
            n_sims: Antal simuleringar

        Returns:
            Array (n_sims x n_days+1) med simulerade priser
        """
        dt = 1.0 / 252  # Daglig tidssteg
        n = n_days

        # Standard Brownian increments
        Z = np.random.normal(0, 1, (n_sims, n))

        # GBM: S(t+dt) = S(t) * exp((μ - σ²/2) dt + σ * sqrt(dt) * Z)
        drift = (mu - 0.5 * sigma ** 2) * dt
        diffusion = sigma * np.sqrt(dt) * Z

        # Log-returns
        log_returns = drift + diffusion

        # Pris-sökvägar
        log_price_path = np.zeros((n_sims, n + 1))
        log_price_path[:, 0] = np.log(S0)
        log_price_path[:, 1:] = log_price_path[:, [0]] + np.cumsum(log_returns, axis=1)

        price_path = np.exp(log_price_path)

        return price_path

    # ── Bootstrap ──────────────────────────────────────────────────────────

    @staticmethod
    def bootstrap_simulation(historical_returns: np.ndarray,
                              n_sims: int = 1000) -> np.ndarray:
        """
        Bootstrap-simulering från historisk data.

        Drar slumpmässiga hela år från historiken (block bootstrap),
        vilket bevarar auto-korrelation och volatilitetsclustering.

        Args:
            historical_returns: Historiska avkastningar (T,)
            n_sims: Antal simuleringar

        Returns:
            Array (n_sims, T) med omsamplade returns
        """
        returns = np.asarray(historical_returns, dtype=float)
        returns = returns[~np.isnan(returns)]
        n_hist = len(returns)

        if n_hist < 20:
            logger.warning(f"För få observationer för bootstrap: {n_hist}")
            return np.tile(returns, (n_sims, 1))

        results = np.zeros((n_sims, n_hist))
        for i in range(n_sims):
            # Omsampling med återläggning
            idx = np.random.randint(0, n_hist, size=n_hist)
            results[i] = returns[idx]

        return results

    # ── Visualiseringsdata ─────────────────────────────────────────────────

    @staticmethod
    def _simulation_quantiles(simulations: np.ndarray,
                              quantiles: list) -> dict:
        """
        Beräknar kvantiler från simuleringsdata.

        Args:
            simulations: Array (n_sims x n_steps)
            quantiles: Lista av kvantiler (t.ex. [0.05, 0.5, 0.95])

        Returns:
            dict med {f"q_{int(q*100)}": array over time}
        """
        result = {}
        for q in quantiles:
            q_label = f"q_{int(q * 100)}"
            result[q_label] = np.quantile(simulations, q, axis=0)
        return result

    @staticmethod
    def _build_figure_data(simulations: np.ndarray,
                           n_days: int,
                           quantiles: Optional[list] = None) -> dict:
        """
        Bygger data för Plotly-visualisering.

        Args:
            simulations: Simuleringsarray (n_sims x n_days+1)
            n_days: Antal dagar
            quantiles: Lista av kvantiler för shaded area

        Returns:
            dict redo för Plotly
        """
        if quantiles is None:
            quantiles = [0.05, 0.5, 0.95]

        # Tid-axel
        time_axis = np.arange(n_days + 1)

        # Kvantiler
        quants = MonteCarloSimulator._simulation_quantiles(simulations, quantiles)

        # Median (50:e percentil)
        median_path = quants.get("q_50", np.median(simulations, axis=0))

        # Lower/upper band (t.ex. 5:e och 95:e percentil)
        q_keys = sorted(quants.keys())
        lower_key = q_keys[0]
        upper_key = q_keys[-1]

        lower_band = quants.get(lower_key, median_path - np.std(simulations, axis=0))
        upper_band = quants.get(upper_key, median_path + np.std(simulations, axis=0))

        # Visa bara ett urval av enskilda sökvägar (max 50)
        n_paths = min(50, simulations.shape[0])
        sampled_paths = simulations[np.random.choice(
            simulations.shape[0], n_paths, replace=False
        )]

        return {
            "time_axis": time_axis.tolist(),
            "median": median_path.tolist(),
            "lower_band": lower_band.tolist(),
            "upper_band": upper_band.tolist(),
            "sampled_paths": sampled_paths.tolist(),
            "n_simulations": simulations.shape[0],
            "n_days": n_days,
        }

    # ── Plotly-figur ───────────────────────────────────────────────────────

    @staticmethod
    def plot_simulations(simulations: np.ndarray,
                          quantiles: Optional[list] = None,
                          title: str = "Monte Carlo-simulering") -> dict:
        """
        Genererar Plotly-figurdata för Monte Carlo-simulering.

        Returnerar en dict som kan skickas till plotly.graph_objects.Figure
        eller streamlit plotly_chart.

        Args:
            simulations: Array (n_sims x n_steps)
            quantiles: Kvantiler för shaded area
            title: Diagramtitel

        Returns:
            Plotly figure data (trace config)
        """
        import plotly.graph_objects as go

        if quantiles is None:
            quantiles = [0.05, 0.5, 0.95]

        fig_data = MonteCarloSimulator._build_figure_data(
            simulations, simulations.shape[1] - 1, quantiles
        )

        fig = go.Figure()

        # Transparenta sökvägar (sample)
        for path in fig_data["sampled_paths"][:30]:  # Max 30
            fig.add_trace(go.Scatter(
                x=fig_data["time_axis"],
                y=path,
                mode="lines",
                line=dict(width=0.5, color="rgba(76,155,232,0.15)"),
                showlegend=False,
                hoverinfo="skip",
            ))

        # Osäkerhetsband (shaded area)
        fig.add_trace(go.Scatter(
            x=list(fig_data["time_axis"]) + list(fig_data["time_axis"])[::-1],
            y=fig_data["upper_band"] + fig_data["lower_band"][::-1],
            fill="toself",
            fillcolor="rgba(76,155,232,0.1)",
            line=dict(width=0),
            name=f"{int(quantiles[0]*100)}-{int(quantiles[-1]*100)}% konfidens",
        ))

        # Median
        fig.add_trace(go.Scatter(
            x=fig_data["time_axis"],
            y=fig_data["median"],
            mode="lines",
            line=dict(width=2, color="#4c9be8"),
            name="Median",
        ))

        # Layout
        fig.update_layout(
            title=title,
            template="plotly_dark",
            paper_bgcolor="#131722",
            plot_bgcolor="#1e2230",
            xaxis_title="Dagar framåt",
            yaxis_title="Portföljvärde",
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            margin=dict(t=50, b=30, l=50, r=20),
            height=450,
        )

        # Referenslinje vid startvärdet
        start_val = simulations[:, 0].mean() if simulations.ndim > 1 else simulations[0]
        fig.add_hline(
            y=start_val,
            line_dash="dot",
            line_color="#64748b",
            annotation_text="Startvärde",
        )

        return fig

    # ── Sannolikhetsberäkningar ────────────────────────────────────────────

    @staticmethod
    def probability_of_loss(simulations: np.ndarray,
                             target_return: float = 0.0) -> dict:
        """
        Beräknar sannolikhet för förlust (eller under en viss avkastningströskel).

        Args:
            simulations: Array (n_sims x n_days+1)
            target_return: Tröskel för förlust (t.ex. 0.0 = förlust, 0.1 = missa 10%)

        Returns:
            dict med:
                prob_loss: Sannolikhet att hamna under target_return
                below_threshold: Antal simuleringar under tröskeln
                n_simulations: Totalt antal simuleringar
                final_values: Dict med statistik för slutvärden
        """
        if simulations.ndim < 2:
            return {"prob_loss": 0.0, "below_threshold": 0,
                    "n_simulations": 0, "final_values": {}}

        # Slutvärden (sista kolumnen)
        final_values = simulations[:, -1]
        initial_value = simulations[0, 0]

        # Avkastning
        returns_from_start = final_values / initial_value - 1.0

        # Räkna simuleringar under target
        n_below = int(np.sum(returns_from_start < target_return))
        n_total = len(returns_from_start)
        prob_loss = n_below / n_total if n_total > 0 else 0.0

        # Statistik för slutvärden
        p5 = float(np.percentile(final_values, 5))
        p25 = float(np.percentile(final_values, 25))
        p50 = float(np.percentile(final_values, 50))
        p75 = float(np.percentile(final_values, 75))
        p95 = float(np.percentile(final_values, 95))

        return {
            "prob_loss": round(prob_loss, 4),
            "prob_loss_pct": round(prob_loss * 100, 1),
            "below_threshold": n_below,
            "n_simulations": n_total,
            "final_values": {
                "min": round(float(final_values.min()), 0),
                "p5": round(p5, 0),
                "p25": round(p25, 0),
                "median": round(p50, 0),
                "p75": round(p75, 0),
                "p95": round(p95, 0),
                "max": round(float(final_values.max()), 0),
                "mean": round(float(final_values.mean()), 0),
                "std": round(float(final_values.std()), 0),
            },
        }

    @staticmethod
    def var_from_simulation(simulations: np.ndarray,
                             confidence: float = 0.95) -> dict:
        """
        Beräknar Value at Risk från simulering.

        Argumentet är att simulering fångar icke-normala risker bättre
        än parametrisk VaR.

        Args:
            simulations: Array (n_sims x n_days+1)
            confidence: Konfidensnivå (t.ex. 0.95)

        Returns:
            dict med:
                var_pct: VaR i procent
                var_value: VaR i kronor (relativt startvärde)
                confidence: Konfidensnivå
                cvar_pct: Conditional VaR (förväntad förlust vid överskridning)
        """
        if simulations.ndim < 2:
            return {"var_pct": 0.0, "var_value": 0.0,
                    "confidence": confidence, "cvar_pct": 0.0}

        initial_value = simulations[0, 0]
        final_values = simulations[:, -1]

        # Return från start
        total_returns = final_values / initial_value - 1.0

        # VaR: (1-confidence)-percentilen av returns
        alpha = 1.0 - confidence
        var_pct = float(np.percentile(total_returns, alpha * 100))
        var_value = var_pct * initial_value

        # CVaR: genomsnitt av returns som är <= VaR
        tail = total_returns[total_returns <= var_pct]
        cvar_pct = float(np.mean(tail)) if len(tail) > 0 else var_pct

        return {
            "var_pct": round(var_pct, 4),
            "var_value": round(var_value, 2),
            "var_initial_pct": round(var_pct * 100, 1),
            "confidence": confidence,
            "cvar_pct": round(cvar_pct, 4),
            "tail_obs": len(tail),
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    np.random.seed(42)

    # Generera historiska returns
    hist_returns = np.random.normal(0.0005, 0.02, 500)

    sim = MonteCarloSimulator(random_seed=42)

    # Standard MC
    mc_result = sim.simulate(hist_returns, n_simulations=1000, n_days=252)
    print(f"Monte Carlo: {mc_result.shape[0]} simuleringar x {mc_result.shape[1]} dagar")

    # Förlustsannolikhet
    loss_prob = sim.probability_of_loss(mc_result)
    print(f"Sannolikhet förlust: {loss_prob['prob_loss_pct']:.1f}%")

    # VaR från simulering
    sim_var = sim.var_from_simulation(mc_result, 0.95)
    print(f"VaR (95%): {sim_var['var_pct']:.2%}")
    print(f"CVaR (95%): {sim_var['cvar_pct']:.2%}")

    # GBM
    gbm = sim.geometric_brownian(0.10, 0.20, 100, 252, 100)
    print(f"\nGBM: {gbm.shape[0]} simuleringar, slutpris mean={gbm[:,-1].mean():.2f}")

    # Bootstrap
    boot = sim.bootstrap_simulation(hist_returns, n_sims=100)
    print(f"\nBootstrap: {boot.shape[0]} x {boot.shape[1]}")

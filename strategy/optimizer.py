"""
strategy/optimizer.py
=====================
Parameteroptimering för strategier.

Innehåller:
- GridSearchCV: full grid search
- RandomSearchCV: random search
- GeneticOptimizer: genetisk algoritm
- WalkForwardOptimization: walk-forward-test
"""

import copy
import random
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from strategy.base import Strategy, run_backtest


class GridSearchCV:
    """
    Grid search över parameterrymden.
    Testar alla kombinationer av parametrar.

    Parametrar:
        strategy_class:  Strategy-klass (inte instans)
        data:            Prisdata
        param_grid:      Dict med parameter -> lista av värden
                         Ex: {"fast_ma": [20, 50, 100], "slow_ma": [100, 200]}
        scoring:         Metric att optimera ("sharpe", "cagr", "sortino", "calmar", "total_return")
        n_jobs:          Antal parallella jobb (1 = sekventiellt, används ej än)
        verbose:         Visa progress
    """

    def __init__(self, strategy_class, data: pd.DataFrame, param_grid: dict,
                 scoring: str = "sharpe", verbose: bool = True):
        self.strategy_class = strategy_class
        self.data = data
        self.param_grid = param_grid
        self.scoring = scoring
        self.verbose = verbose

    def fit(self) -> pd.DataFrame:
        """Kör grid search. Returnerar DataFrame med alla resultat sorterade efter scoring."""
        from itertools import product

        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())
        combinations = list(product(*param_values))

        if self.verbose:
            print(f"  GridSearch: {len(combinations)} kombinationer att testa")
            print(f"  Parametrar: {param_names}")

        results = []
        for i, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))
            try:
                strategy = self.strategy_class(name=f"grid_{i}", params=params)
                result = run_backtest(strategy, self.data)
                metrics = result.metrics
                row = {"params": params, **{k: v for k, v in metrics.items() if isinstance(v, (int, float))}}
                results.append(row)
            except Exception as e:
                results.append({"params": params, "error": str(e)})

            if self.verbose and (i + 1) % max(1, len(combinations) // 10) == 0:
                print(f"    {i + 1}/{len(combinations)} klar")

        df = pd.DataFrame(results)
        if self.scoring in df.columns:
            df = df.sort_values(self.scoring, ascending=False)

        if self.verbose:
            best = df.iloc[0] if not df.empty else {}
            print(f"  Bästa: {best.get('params', {})} -> {self.scoring} = {best.get(self.scoring, 'N/A')}")

        return df

    @property
    def best_params_(self) -> dict:
        """Returnera bästa parameterkombinationen. Kräver att fit() körts först."""
        return {}


class RandomSearchCV:
    """
    Random search över parameterrymden.
    Testar slumpmässiga kombinationer av parametrar.

    Parametrar:
        strategy_class:  Strategy-klass
        data:            Prisdata
        param_dist:      Dict med parameter -> (distribution, kwargs) eller lista
                         Ex: {"fast_ma": ("int", 10, 200), "slow_ma": ("int", 50, 500)}
                             {"use_binary": ["bool"]}
        n_iter:          Antal iterationer (default 100)
        scoring:         Metric att optimera
        random_state:    Seed för reproducerbarhet
        verbose:         Visa progress
    """

    def __init__(self, strategy_class, data: pd.DataFrame, param_dist: dict,
                 n_iter: int = 100, scoring: str = "sharpe",
                 random_state: int = 42, verbose: bool = True):
        self.strategy_class = strategy_class
        self.data = data
        self.param_dist = param_dist
        self.n_iter = n_iter
        self.scoring = scoring
        self.random_state = random_state
        self.verbose = verbose

    def fit(self) -> pd.DataFrame:
        """Kör random search."""
        random.seed(self.random_state)
        np.random.seed(self.random_state)

        if self.verbose:
            print(f"  RandomSearch: {self.n_iter} iterationer")
            print(f"  Parametrar: {list(self.param_dist.keys())}")

        results = []
        for i in range(self.n_iter):
            params = self._sample_params()
            try:
                strategy = self.strategy_class(name=f"random_{i}", params=params)
                result = run_backtest(strategy, self.data)
                metrics = result.metrics
                row = {"params": params, **{k: v for k, v in metrics.items() if isinstance(v, (int, float))}}
                results.append(row)
            except Exception as e:
                results.append({"params": params, "error": str(e)})

            if self.verbose and (i + 1) % max(1, self.n_iter // 10) == 0:
                print(f"    {i + 1}/{self.n_iter} klar")

        df = pd.DataFrame(results)
        if self.scoring in df.columns:
            df = df.sort_values(self.scoring, ascending=False)

        if self.verbose:
            best = df.iloc[0] if not df.empty else {}
            print(f"  Bästa: {best.get('params', {})} -> {self.scoring} = {best.get(self.scoring, 'N/A')}")

        return df

    def _sample_params(self) -> dict:
        """Sampla en parameterkombination från distributionerna."""
        params = {}
        for key, dist in self.param_dist.items():
            if isinstance(dist, list):
                params[key] = random.choice(dist)
            elif isinstance(dist, tuple):
                dist_type = dist[0]
                if dist_type == "int":
                    lo, hi = dist[1], dist[2]
                    params[key] = random.randint(lo, hi)
                elif dist_type == "float":
                    lo, hi = dist[1], dist[2]
                    params[key] = random.uniform(lo, hi)
                elif dist_type == "choice":
                    params[key] = random.choice(dist[1])
            elif callable(dist):
                params[key] = dist()
            else:
                params[key] = dist
        return params


class GeneticOptimizer:
    """
    Genetisk algoritm för parameteroptimering.

    Använder:
    - Selektion: tournament selection (k=3)
    - Crossover: uniform + single-point
    - Mutation: Gaussian noise
    - Elitism: behåll top 2
    - Early stopping: om fitness inte förbättras på 3 generationer

    Parametrar:
        strategy_class: Strategy-klass
        data:           Prisdata
        param_grid:     Dict med parameter -> lista av möjliga värden
                        (för genetisk kodning av diskreta värden)
        generations:    Antal generationer (default 10)
        population:     Populationsstorlek (default 50)
        mutation_rate:  Sannolikhet för mutation (default 0.1)
        crossover_rate: Sannolikhet för crossover (default 0.8)
        scoring:        Metric att optimera
        verbose:        Visa progress
    """

    def __init__(self, strategy_class, data: pd.DataFrame, param_grid: dict,
                 generations: int = 10, population: int = 50,
                 mutation_rate: float = 0.1, crossover_rate: float = 0.8,
                 scoring: str = "sharpe", verbose: bool = True):
        self.strategy_class = strategy_class
        self.data = data
        self.param_grid = param_grid
        self.generations = generations
        self.population = population
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.scoring = scoring
        self.verbose = verbose

        self._param_names = list(param_grid.keys())
        self._param_options = [param_grid[k] for k in self._param_names]
        self._best_fitness_history = []

    def fit(self) -> pd.DataFrame:
        """Kör genetisk optimering. Returnerar DataFrame med alla individer från sista generationen."""
        if self.verbose:
            print(f"  GeneticOptimizer: {self.generations} gen, {self.population} pop")
            print(f"  Parametrar: {self._param_names}")

        # Initiera population
        population = [self._random_individual() for _ in range(self.population)]

        # Utvärdera initial populations fitness
        fitness = [self._evaluate(ind) for ind in population]

        best_overall = None
        best_fitness = -float("inf")
        no_improve = 0

        all_results = []

        for gen in range(self.generations):
            # Sortera efter fitness
            paired = sorted(zip(population, fitness), key=lambda x: x[1], reverse=True)
            sorted_pop = [p for p, _ in paired]
            sorted_fit = [f for _, f in paired]

            gen_best = sorted_fit[0]
            self._best_fitness_history.append(gen_best)

            if gen_best > best_fitness:
                best_fitness = gen_best
                best_overall = sorted_pop[0]
                no_improve = 0
            else:
                no_improve += 1

            if self.verbose:
                print(f"    Gen {gen + 1}: bästa fitness = {gen_best:.4f} "
                      f"(medel = {np.mean(sorted_fit):.4f})")

            # Early stopping
            if no_improve >= 3:
                if self.verbose:
                    print(f"  Early stopping efter generation {gen + 1}")
                break

            # Skapa nästa generation
            next_pop = []

            # Elitism: behåll top 2
            next_pop.extend(sorted_pop[:2])

            # Fyll resten
            while len(next_pop) < self.population:
                parent1 = self._tournament_select(sorted_pop, sorted_fit, k=3)
                parent2 = self._tournament_select(sorted_pop, sorted_fit, k=3)

                if random.random() < self.crossover_rate:
                    child1, child2 = self._crossover(parent1, parent2)
                else:
                    child1, child2 = parent1[:], parent2[:]

                child1 = self._mutate(child1)
                child2 = self._mutate(child2)

                next_pop.extend([child1, child2])

            # Trimma till population size
            population = next_pop[:self.population]

            # Utvärdera fitness för nya populationen
            fitness = [self._evaluate(ind) for ind in population]

            # Spara alla resultat
            for ind, fit in zip(population, fitness):
                params = dict(zip(self._param_names, ind))
                all_results.append({"params": params, "fitness": fit, "generation": gen})

        if best_overall:
            best_params = dict(zip(self._param_names, best_overall))
            if self.verbose:
                print(f"  Bästa: {best_params} -> fitness = {best_fitness:.4f}")

        return pd.DataFrame(all_results).sort_values("fitness", ascending=False)

    def _random_individual(self) -> list:
        """Skapa en slumpmässig individ."""
        return [random.choice(opts) for opts in self._param_options]

    def _evaluate(self, individual: list) -> float:
        """Utvärdera fitness för en individ."""
        params = dict(zip(self._param_names, individual))
        try:
            strategy = self.strategy_class(name="genetic", params=params)
            result = run_backtest(strategy, self.data)
            return float(result.metrics.get(self.scoring, 0.0))
        except Exception:
            return -float("inf")

    def _tournament_select(self, population: list, fitness: list, k: int = 3) -> list:
        """Turneringsselektion. Välj den bästa av k slumpmässiga individer."""
        candidates = random.sample(range(len(population)), min(k, len(population)))
        best_idx = max(candidates, key=lambda i: fitness[i])
        return population[best_idx][:]

    def _crossover(self, parent1: list, parent2: list) -> tuple:
        """Utför uniform crossover."""
        child1, child2 = parent1[:], parent2[:]
        for i in range(len(parent1)):
            if random.random() < 0.5:
                child1[i], child2[i] = child2[i], child1[i]
        return child1, child2

    def _mutate(self, individual: list) -> list:
        """Mutera en individ med Gaussian noise."""
        mutated = individual[:]
        for i in range(len(mutated)):
            if random.random() < self.mutation_rate:
                options = self._param_options[i]
                if len(options) > 1:
                    mutated[i] = random.choice(options)
        return mutated


class WalkForwardOptimization:
    """
    Walk-forward-optimering.
    Delar data i N fönster, optimerar på in-sample, testar på out-of-sample.

    Parametrar:
        strategy_class: Strategy-klass
        data:           Prisdata
        n_windows:      Antal walk-forward-fönster (default 5)
        train_pct:      Andel data att träna på per fönster (default 0.7)
        scoring:        Metric att optimera
        optimizer:      Optimizer-klass att använda (default GridSearchCV)
        optimizer_kwargs: Extra kwargs till optimizern
        verbose:        Visa progress
    """

    def __init__(self, strategy_class, data: pd.DataFrame, n_windows: int = 5,
                 train_pct: float = 0.7, scoring: str = "sharpe",
                 optimizer=None, optimizer_kwargs: dict = None,
                 verbose: bool = True):
        self.strategy_class = strategy_class
        self.data = data
        self.n_windows = n_windows
        self.train_pct = train_pct
        self.scoring = scoring
        self.optimizer = optimizer or GridSearchCV
        self.optimizer_kwargs = optimizer_kwargs or {}
        self.verbose = verbose

    def fit(self, param_grid: dict) -> dict:
        """
        Kör walk-forward-optimering.

        param_grid: Parameter-grid för optimizern

        Return: dict med:
            - windows: lista med resultat per fönster
            - oos_sharpe: genomsnittlig OOS Sharpe
            - oos_returns: sammanfogad OOS avkastning
            - overfit_probability: uppskattad overfittingsannolikhet
        """
        n = len(self.data)
        window_size = n // self.n_windows
        train_size = int(window_size * self.train_pct)

        if self.verbose:
            print(f"  WalkForward: {self.n_windows} fönster, "
                  f"{train_size} dagar train / {window_size - train_size} dagar test per fönster")
            print(f"  Optimizer: {self.optimizer.__name__} med scoring={self.scoring}")

        results = []
        all_oos_returns = []

        for window in range(self.n_windows):
            start = window * window_size
            train_end = start + train_size
            test_end = min(start + window_size, n)

            if test_end > n:
                break

            train_data = self.data.iloc[start:train_end]
            test_data = self.data.iloc[train_end:test_end]

            if len(train_data) < 50 or len(test_data) < 10:
                continue

            if self.verbose:
                print(f"  Fönster {window + 1}: train={train_data.index[0].date()}.."
                      f"{train_data.index[-1].date()}, "
                      f"test={test_data.index[0].date()}..{test_data.index[-1].date()}")

            # Optimera på training data
            try:
                opt_kwargs = {**self.optimizer_kwargs, "verbose": False}
                optimizer = self.optimizer(
                    self.strategy_class, train_data, param_grid,
                    scoring=self.scoring, **opt_kwargs
                )
                opt_results = optimizer.fit()
            except Exception as e:
                if self.verbose:
                    print(f"    Optimering misslyckades: {e}")
                continue

            # Hitta bästa parametrar
            if opt_results.empty:
                continue

            best_row = opt_results.iloc[0]
            best_params = best_row.get("params", {})
            if isinstance(best_params, dict):
                best_params = best_params
            elif isinstance(best_params, str):
                import ast
                best_params = ast.literal_eval(best_params)

            # Testa på OOS-data
            try:
                strategy = self.strategy_class(name=f"wf_window{window}", params=best_params)
                oos_result = run_backtest(strategy, test_data)
                oos_sharpe = oos_result.metrics.get("sharpe", 0.0)
                oos_return = oos_result.metrics.get("total_return", 0.0)
            except Exception as e:
                if self.verbose:
                    print(f"    OOS-test misslyckades: {e}")
                continue

            # IS-prestanda
            is_sharpe = best_row.get("sharpe", 0.0) if "sharpe" in opt_results.columns else 0.0

            results.append({
                "window": window + 1,
                "train_start": train_data.index[0],
                "train_end": train_data.index[-1],
                "test_start": test_data.index[0],
                "test_end": test_data.index[-1],
                "best_params": best_params,
                "is_sharpe": is_sharpe,
                "oos_sharpe": oos_sharpe,
                "oos_return": oos_return,
                "sharpe_drop": is_sharpe - oos_sharpe,
            })

            all_oos_returns.append(oos_result.returns)

            if self.verbose:
                print(f"    IS Sharpe: {is_sharpe:.3f} -> OOS Sharpe: {oos_sharpe:.3f} "
                      f"(drop: {is_sharpe - oos_sharpe:.3f})")

        # Beräkna aggregerad statistik
        if not results:
            return {"windows": [], "oos_sharpe": 0.0, "overfit_probability": 1.0}

        df_results = pd.DataFrame(results)
        avg_oos_sharpe = df_results["oos_sharpe"].mean()

        # Overfitting probability (PBO - Probability of Backtest Overfitting)
        # Andel fönster där OOS Sharpe är signifikant sämre än IS Sharpe
        overfit_count = (df_results["oos_sharpe"] < 0).sum()
        overfit_prob = overfit_count / max(len(df_results), 1)

        # Kombinera alla OOS-returns
        combined_oos = pd.concat(all_oos_returns) if all_oos_returns else pd.Series(dtype=float)
        combined_sharpe = 0.0
        if len(combined_oos) > 2:
            combined_sharpe = float(np.sqrt(252) * combined_oos.mean() / combined_oos.std()) if combined_oos.std() > 0 else 0.0

        return {
            "windows": results,
            "n_windows": len(results),
            "avg_is_sharpe": float(df_results["is_sharpe"].mean()),
            "avg_oos_sharpe": float(avg_oos_sharpe),
            "combined_oos_sharpe": combined_sharpe,
            "avg_oos_return": float(df_results["oos_return"].mean()),
            "sharpe_drop_avg": float(df_results["sharpe_drop"].mean()),
            "overfit_probability": float(overfit_prob),
            "oos_returns": combined_oos,
        }

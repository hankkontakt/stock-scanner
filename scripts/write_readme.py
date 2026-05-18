"""Script to write README.md - run with: python scripts/write_readme.py"""
content = r"""# MarketScan — Quantitative Stock Scanner

En kvantitativ aktiescanner som rangordnar 800+ aktier baserat på akademiskt validerade faktorer och ger rekommendationer för portföljen.

**Designad för att fungera helt gratis** — yfinance + GitHub Actions + Streamlit Cloud + Gemini.

## Arkitekturförbättringar (2026)

| Förbättring | Beskrivning | Fil |
|---|---|---|
| **FCF Yield primär (70%)** | EV/EBITDA ersatt som primär värderingsfaktor. | core/scoring.py |
| **Piotroski F-Score med YoY-jämförelser** | Fundamental-snapshots för år-över-år. | core/piotroski.py |
| **Insider: rutin vs opportunistisk** | Historisk databas filtrerar bort brus. | core/fi_insider_fetcher.py |
| **Black-Litterman portföljoptimering** | Bayesian med IC-konfidens + shrinkage. | portfolio/black_litterman.py |
| **Half-Kelly positionsstorlek** | f* = 0.5 x (p x b - q) / b | portfolio/paper_trading.py |
| **Dynamisk ATR stop-loss** | 2.5x-1.0x baserat på SPY volatilitet. | portfolio/paper_trading.py |
| **ML-features utökade** | Fundamentala + tekniska features. | core/ml_predictor.py |

"""
tests/test_live_api.py
=======================
Live API-tester med riktiga nätverksanrop.

Dessa tester:
  - Hoppas automatiskt om API-nycklar / internetanslutning saknas
  - Kör INTE i vanlig CI (markerade med @pytest.mark.live)
  - Körs manuellt: pytest tests/test_live_api.py -m live -v
  - Körs i diagnose-workflow med: pytest -m live --timeout=60

Täcker:
  - yfinance datahämtning (live)
  - Finnhub sentiment (live)
  - DeepSeek/Gemini AI (live)
  - SMTP-anslutning (live)
  - Streamlit-webbapp HTTP (live)
  - GitHub Actions API (live)
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


# ── Hjälpmarkers ──────────────────────────────────────────────────────────────

def _has_internet() -> bool:
    """Kontrollera om det finns en internetanslutning."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


requires_internet = pytest.mark.skipif(not _has_internet(), reason="Ingen internetanslutning")


def requires_env(key: str):
    return pytest.mark.skipif(not os.getenv(key), reason=f"Miljövariabel {key} saknas")


# ── yfinance-tester ────────────────────────────────────────────────────────────

@pytest.mark.live
@requires_internet
def test_yfinance_msft_history():
    """Hämtar 5d MSFT-historik från Yahoo Finance."""
    import yfinance as yf
    hist = yf.Ticker("MSFT").history(period="5d")
    assert len(hist) > 0, "Tom DataFrame för MSFT"
    assert "Close" in hist.columns
    assert hist["Close"].iloc[-1] > 0


@pytest.mark.live
@requires_internet
def test_yfinance_aapl_info():
    """Hämtar AAPL bolagsinfo."""
    import yfinance as yf
    info = yf.Ticker("AAPL").info
    assert isinstance(info, dict)
    has_fields = any(k in info for k in ["sector", "marketCap", "longName", "shortName"])
    assert has_fields, f"Inga förväntade fält: {list(info.keys())[:10]}"


@pytest.mark.live
@requires_internet
def test_yfinance_multi_download():
    """Hämtar data för flera tickers parallellt."""
    import yfinance as yf
    data = yf.download("AAPL MSFT GOOGL", period="5d", progress=False)
    assert data is not None and len(data) > 0


@pytest.mark.live
@requires_internet
def test_core_fetch_price_history():
    """Testar core/data_fetcher.py fetch_price_history()."""
    from core.data_fetcher import fetch_price_history
    hist = fetch_price_history("MSFT", period="1y")
    assert hist is not None and len(hist) > 50
    cols_lower = [c.lower() for c in hist.columns]
    assert "close" in cols_lower, f"Kolumnen close saknas: {list(hist.columns)}"


# ── Finnhub-tester ─────────────────────────────────────────────────────────────

@pytest.mark.live
@requires_internet
@requires_env("FINNHUB_API_KEY")
def test_finnhub_sentiment():
    """Hämtar AAPL sentiment från Finnhub."""
    import requests
    key = os.environ["FINNHUB_API_KEY"]
    resp = requests.get(
        "https://finnhub.io/api/v1/news-sentiment",
        params={"symbol": "AAPL", "token": key},
        timeout=10,
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "sentiment" in data or "buzz" in data


@pytest.mark.live
@requires_internet
@requires_env("FINNHUB_API_KEY")
def test_finnhub_company_news():
    """Hämtar nyheter från Finnhub."""
    import requests
    key = os.environ["FINNHUB_API_KEY"]
    resp = requests.get(
        "https://finnhub.io/api/v1/company-news",
        params={"symbol": "AAPL", "from": "2024-01-01", "to": "2024-01-07", "token": key},
        timeout=10,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── AI API-tester ──────────────────────────────────────────────────────────────

@pytest.mark.live
@requires_internet
@requires_env("DEEPSEEK_API_KEY")
def test_deepseek_api():
    """Testar DeepSeek API med ett enkelt anrop."""
    import requests
    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Reply with just OK"}],
            "max_tokens": 5,
        },
        timeout=30,
    )
    assert resp.status_code == 200, f"DeepSeek HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "choices" in data


@pytest.mark.live
@requires_internet
@requires_env("GEMINI_API_KEY")
def test_gemini_api():
    """Testar Gemini API."""
    import requests
    key = os.environ["GEMINI_API_KEY"]
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
        json={"contents": [{"parts": [{"text": "Reply with just OK"}]}]},
        timeout=30,
    )
    assert resp.status_code == 200, f"Gemini HTTP {resp.status_code}: {resp.text[:200]}"
    assert "candidates" in resp.json()


# ── SMTP-tester ────────────────────────────────────────────────────────────────

@pytest.mark.live
@requires_internet
def test_smtp_tcp_port():
    """TCP-anslutning till smtp.gmail.com:587."""
    sock = socket.create_connection(("smtp.gmail.com", 587), timeout=10)
    sock.close()


@pytest.mark.live
@requires_internet
@requires_env("EMAIL_SENDER")
@requires_env("EMAIL_PASSWORD")
def test_smtp_starttls_auth():
    """SMTP STARTTLS + inloggning (utan att skicka mail)."""
    import smtplib
    import ssl
    sender   = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(sender, password)


# ── Streamlit / webb-tester ────────────────────────────────────────────────────

@pytest.mark.live
@requires_internet
@requires_env("STREAMLIT_URL")
def test_streamlit_http_200():
    """Streamlit Cloud svarar med HTTP 200."""
    import urllib.request
    url = os.environ["STREAMLIT_URL"].rstrip("/")
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "MarketScan-Test/1.0"}),
        timeout=20,
    ) as resp:
        assert resp.status == 200, f"HTTP {resp.status}"


@pytest.mark.live
@requires_internet
@requires_env("STREAMLIT_URL")
def test_streamlit_latency_under_8s():
    """Svarstid under 8 sekunder."""
    import urllib.request
    url = os.environ["STREAMLIT_URL"].rstrip("/")
    t0 = time.perf_counter()
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "MarketScan-Test/1.0"}),
        timeout=20,
    ) as resp:
        resp.read(512)
    ms = (time.perf_counter() - t0) * 1000
    assert ms < 8000, f"Svarstid {ms:.0f}ms > 8000ms"


# ── GitHub API-tester ─────────────────────────────────────────────────────────

@pytest.mark.live
@requires_internet
@requires_env("GITHUB_TOKEN")
@requires_env("GITHUB_REPO")
def test_github_repo_info():
    """Hämtar repo-info via GitHub API."""
    import requests
    resp = requests.get(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPO']}",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    assert resp.status_code == 200, f"GitHub API {resp.status_code}"
    assert "name" in resp.json()


@pytest.mark.live
@requires_internet
@requires_env("GITHUB_TOKEN")
@requires_env("GITHUB_REPO")
def test_github_workflow_runs_present():
    """Senaste workflow-körningar finns."""
    import requests
    resp = requests.get(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPO']}/actions/runs",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
        params={"per_page": 5},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "workflow_runs" in data
    assert len(data["workflow_runs"]) > 0


# ── Lokala data-tester (ej riktiga API-anrop) ──────────────────────────────────

@pytest.mark.live
def test_latest_parquet_scoreable():
    """Senaste parquet-fil kan läsas och innehåller scoringkolumner."""
    import pandas as pd
    parquets = sorted(ROOT.glob("data/scored_universe_*.parquet"), reverse=True)
    if not parquets:
        pytest.skip("Ingen scored_universe*.parquet hittades")
    df = pd.read_parquet(parquets[0])
    assert len(df) > 10
    assert "score_total" in df.columns, f"score_total saknas: {list(df.columns)[:10]}"
    scores = df["score_total"].dropna()
    assert (scores >= 0).all(), f"Negativa scores: {scores.min()}"
    assert (scores <= 101).all(), f"Scores > 100: {scores.max()}"


@pytest.mark.live
def test_feature_flags_file_valid():
    """feature_flags.json är giltig JSON med rätt struktur."""
    flags_path = ROOT / "data" / "feature_flags.json"
    if not flags_path.exists():
        pytest.skip("feature_flags.json saknas")
    with open(flags_path, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict), f"Förväntade dict, fick {type(data)}"
    # Flaggor kan vara direkt i roten eller under 'flags'-nyckel
    flags = data.get("flags", data)
    assert isinstance(flags, dict), f"'flags' är inte dict: {type(flags)}"
    for flag_name, flag_val in flags.items():
        assert isinstance(flag_val, bool), f"Flag {flag_name} är inte bool: {type(flag_val)}"


@pytest.mark.live
def test_ml_models_exist_and_loadable():
    """ML-modellfiler finns och kan laddas (TrainedModel-wrapper med .model)."""
    from core.ml_predictor import load_model
    for name in ["universe", "smallcap"]:
        model_path = ROOT / "models" / f"ml_{name}.pkl"
        if not model_path.exists():
            pytest.skip(f"Modell ml_{name}.pkl saknas")
        trained = load_model(name)
        assert trained is not None, f"load_model('{name}') returnerade None"
        # TrainedModel-wrapper har .model och .feature_cols
        assert hasattr(trained, "model"), f"TrainedModel '{name}' saknar .model"
        assert hasattr(trained, "feature_cols"), f"TrainedModel '{name}' saknar .feature_cols"
        # Den inre modellen bör ha predict
        assert hasattr(trained.model, "predict"), f"trained.model för '{name}' saknar predict()"

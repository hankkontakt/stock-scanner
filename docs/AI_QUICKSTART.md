# AI Quickstart — Kom igång på 60 sekunder

> **Läs detta FÖRST** om du är en AI-agent (Claude Code etc.) som börjar en ny session.
> Systemet kör på **GitHub Actions** (pipeline) och **Streamlit Cloud** (webb) — inte lokalt.

## 1. Kör briefing (0.2 sekunder)

```bash
python scripts/ai_debug.py --quick
```

Visar utan nätverksanrop: pipeline-status, CI-fel, Streamlit-fel, metrics, git-status.

Med GitHub API-koll (kräver GITHUB_TOKEN i .env):
```bash
python scripts/ai_debug.py --github
```

## 2. Hur systemet kör

| Komponent | Var | Hur jag ser det |
|-----------|-----|-----------------|
| Pipeline (scan, email, ML) | GitHub Actions (cron) | `data/health/health_YYYY-MM-DD.json` |
| Webbapp (Streamlit) | Streamlit Cloud | HTTP-koll + `data/streamlit_errors.jsonl` |
| CI-rapporter | GitHub Actions | `data/ci_reports/last_daily_scan.json` |
| Tester | GitHub Actions (på push) | `data/ci_reports/last_test_run.json` |
| Diagnos-schema | GitHub Actions (vardagar 08:30) | `data/diagnose_history.jsonl` |

Alla `data/`-filer committas av CI → jag kan läsa dem med `Read`-verktyget.

## 3. Felsökning — vad jag kollar i ordning

### Pipeline kraschade?
```bash
# 1. Se nuläget (läser lokala repo-filer)
python scripts/ai_debug.py --quick

# 2. Ladda ned exakta CI-loggar från GitHub
python scripts/fetch_ci_logs.py --save
# Sparar: data/ci_reports/latest_failure.txt

# 3. Djupdiagnos specifik sektion
python scripts/diagnose.py --section pipeline
python scripts/diagnose.py --section ml
```

### Streamlit appen inte fungerar?
```bash
# 1. HTTP-hälsokoll (pingar Streamlit Cloud URL)
python scripts/check_site.py

# 2. Kolla loggade sidkraschar (skrivs av appen, committas av CI)
cat data/streamlit_errors.jsonl

# 3. Kolla pipeline-data som Streamlit läser
python scripts/diagnose.py --section pipeline
```

### GitHub Actions-körningar misslyckas?
```bash
# 1. Visa status per workflow
python scripts/check_github.py --limit 10

# 2. Ladda ned exakta felloggar för senaste krasch
python scripts/fetch_ci_logs.py --save

# 3. Filtrera ett specifikt workflow
python scripts/fetch_ci_logs.py --workflow daily_scan --save
```

### Konfiguration / API-nycklar?
```bash
python scripts/diagnose.py --section config
python scripts/diagnose.py --section notif
```

### ML-modeller?
```bash
python scripts/diagnose.py --section ml
python -c "from core.ml_predictor import load_model; m=load_model('universe'); print(m)"
```

## 4. Filer CI commitar (mina "sensorer")

```
data/
├── health/health_YYYY-MM-DD.json       Pipeline-hälsa (varje körning)
├── ci_reports/last_daily_scan.json     Senaste pipeline-run (status, mode, URL)
├── ci_reports/last_test_run.json       Senaste pytest (täckning, status)
├── ci_reports/latest_failure.json      Senaste CI-fel (om fetch_ci_logs --save körts)
├── diagnose_history.jsonl              Diagnos-historik (vardag 08:30 via CI)
├── streamlit_errors.jsonl              Streamlit-sidkraschar (loggas automatiskt)
├── scan_log.json                       Pipeline-körningshistorik
├── fetch_errors.json                   Datahämtningsfel per ticker/batch
└── metrics/metrics_YYYYMMDD_*.json     Pipeline-körningsmätningar
```

## 5. Testa kod under utveckling

```bash
# Kör alla enhetstester (430+) — snabb verifiering före push
python scripts/test_all.py

# Bara pytest
python scripts/test_all.py --pytest

# Bara lint
python scripts/test_all.py --lint

# Specifik fil
python scripts/test_all.py --file tests/test_scoring.py
```

Tester körs också automatiskt via `.github/workflows/tests.yml` på varje push.

## 6. Snabbreferens

| Vad | Kommando |
|-----|----------|
| Snabb briefing (lokal) | `python scripts/ai_debug.py --quick` |
| Briefing + GitHub live | `python scripts/ai_debug.py --github` |
| Ladda ned CI-loggar | `python scripts/fetch_ci_logs.py --save` |
| Systemdiagnos | `python scripts/diagnose.py --quick` |
| Köra tester | `python scripts/test_all.py` |
| GitHub-status | `python scripts/check_github.py` |
| Streamlit HTTP-hälsa | `python scripts/check_site.py` |
| Specifik diagnossektion | `python scripts/diagnose.py --section [env\|config\|github\|pipeline\|ml\|notif\|flags]` |

# AI Quickstart — Kom igång på 60 sekunder

> **Läs detta FÖRST** om du är en AI-agent (Claude, Gemini etc.) som börjar en ny session.

## 1. Kör briefing (30 sekunder)

```bash
python scripts/ai_debug.py --quick
```

Visar: pipeline-status, senaste CI-fel, Streamlit-fel, metrics, git-status.

Om GITHUB_TOKEN finns i .env:
```bash
python scripts/ai_debug.py --github
```

## 2. Vad systemet kör PÅ

| Komponent | Var det kör | Hur jag ser det |
|-----------|-------------|-----------------|
| Pipeline (scan, ML) | GitHub Actions | `data/health/health_YYYY-MM-DD.json` (commitat av CI) |
| Webbapp | Streamlit Cloud | HTTP-koll på `$STREAMLIT_URL` |
| Schema | GitHub Actions cron | `.github/workflows/daily_scan.yml` |
| Tester | GitHub Actions (push) | `data/ci_reports/last_test_run.json` |

## 3. Felsökning — vad jag kollar i ordning

### Pipeline kraschade?
```bash
# 1. Läs senaste health-rapport (commitas av CI varje körning)
cat data/health/health_$(date +%Y-%m-%d).json

# 2. Läs senaste scan-loggen
cat data/scan_log.json

# 3. Ladda ned CI-loggar från GitHub (kräver GITHUB_TOKEN)
python scripts/fetch_ci_logs.py --save
# → sparar data/ci_reports/latest_failure.txt med faktiska felrader

# 4. Läs den sparade rapporten
cat data/ci_reports/latest_failure.txt
# eller: cat data/ci_reports/latest_failure.json
```

### Streamlit appen inte fungerar?
```bash
# 1. Kolla om den svarar
python scripts/check_site.py

# 2. Kolla loggade fel (skrivs av appen till repo)
cat data/streamlit_errors.jsonl

# 3. Kolla pipeline-data (Streamlit läser från data/)
python scripts/diagnose.py --section pipeline --section ml
```

### GitHub Actions-körningar misslyckas?
```bash
# 1. Visa status med job-detaljer
python scripts/check_github.py --jobs --limit 5

# 2. Ladda ned exakta felloggar
python scripts/fetch_ci_logs.py --workflow daily_scan --save

# 3. Filtrera bara fel från en viss workflow
python scripts/fetch_ci_logs.py --workflow tests --save
```

### Konfiguration / API-nycklar?
```bash
# Kontrollera alla nycklar och miljövariabler
python scripts/diagnose.py --section config

# Kontrollera e-post SMTP
python scripts/check_email.py

# Kontrollera notifieringskanaler
python scripts/diagnose.py --section notif
```

### ML-modeller fungerar inte?
```bash
# Detaljkontroll
python scripts/diagnose.py --section ml

# Ladda och testa modell manuellt
python -c "from core.ml_predictor import load_model; m = load_model('universe'); print(m)"
```

## 4. Vilka filer CI commitar (mina "sensor"-filer)

```
data/
├── health/health_YYYY-MM-DD.json      Pipeline-hälsa (varje körning)
├── ci_reports/last_daily_scan.json    Senaste pipeline-körning (status, mode, URL)
├── ci_reports/last_test_run.json      Senaste pytest-körning (täckning, status)
├── ci_reports/latest_failure.json     Senaste fel (om fetch_ci_logs.py --save körts)
├── diagnose_history.jsonl             Diagnos-historik (--save)
├── streamlit_errors.jsonl             Streamlit-appfel (loggas automatiskt)
├── scan_log.json                      Pipeline-körningshistorik
├── fetch_errors.json                  Datahämtningsfel per ticker
└── metrics/metrics_*.json             Detaljerade körningsmätningar
```

## 5. Master test-runner

```bash
# Bara pytest (430+ tester, ~3 min)
python scripts/test_all.py --fast

# Allt inkl. nätverkstester (kräver .env)
python scripts/test_all.py --all-checks

# Live API-tester (kräver API-nycklar)
pytest tests/test_live_api.py -m live -v
```

## 6. Om något går riktigt snett

```bash
# Full diagnos + spara historik
python scripts/diagnose.py --save

# Kör ALLA kontroller
python scripts/test_all.py --all-checks --json --save

# Se vad som är anders ocommittat
git status && git diff --stat
```

## 7. Snabbreferens kommandon

| Vad | Kommando |
|-----|----------|
| Snabb briefing | `python scripts/ai_debug.py --quick` |
| Full briefing | `python scripts/ai_debug.py --github` |
| CI-loggar | `python scripts/fetch_ci_logs.py --save` |
| Systemdiagnos | `python scripts/diagnose.py --quick` |
| Alla tester | `python scripts/test_all.py --fast` |
| GitHub-status | `python scripts/check_github.py` |
| E-post-test | `python scripts/check_email.py` |
| Webb-hälsa | `python scripts/check_site.py` |
| Live API-test | `pytest tests/test_live_api.py -m live -v` |

# MarketScan — Säkerhetsdokumentation

> **Uppdaterad:** 2026-06-04 · Se `docs/SYSTEM_AI.md` för fullständig systemöversikt.

## Innehåll

1. [API-nycklar och secrets](#api-nycklar-och-secrets)
2. [Åtkomstkontroll](#åtkomstkontroll)
3. [Känslig data](#känslig-data)
4. [Säkerhetsåtgärder](#säkerhetsåtgärder)
5. [Incidenthantering](#incidenthantering)
6. [Kända begränsningar](#kända-begränsningar)

---

## API-nycklar och secrets

### Var nycklar lagras

| Miljö | Lagringsplats | Format |
|-------|---------------|--------|
| Produktion (Streamlit Cloud) | Streamlit Secrets (`.streamlit/secrets.toml`) | TOML |
| CI/CD (GitHub Actions) | GitHub Repository Secrets | env-variabel |
| Lokal utveckling | `.env`-fil (gitignored) | KEY=VALUE |

**Aldrig committa nycklar till repot.** `.gitignore` exkluderar `.env` och `*.key`.

### Konfigurerade nycklar

```
FINNHUB_API_KEY    — marknadsdata (Finnhub)
DEEPSEEK_API_KEY   — AI-analys (DeepSeek)
GEMINI_API_KEY     — AI-analys (Google Gemini)
EMAIL_SENDER       — avsändare för scan-mail
EMAIL_PASSWORD     — SMTP-lösenord (app-lösenord rekommenderas)
EMAIL_TO           — mottagare
GITHUB_TOKEN       — automatisk pipeline-commit (sätts automatiskt av GitHub)
```

### Nyckelrotation

Vid misstänkt läckage:
1. **Omedelbart** — invalidera nyckeln hos leverantören
2. Generera ny nyckel
3. Uppdatera GitHub Secrets (Settings → Secrets → Actions)
4. Uppdatera Streamlit Cloud Secrets
5. Verifiera att pipeline kör utan fel

---

## Åtkomstkontroll

### Streamlit-appen

- Lösenordsskydd via `streamlit-authenticator`
- Credentials konfigureras i Streamlit Secrets under `[credentials]`
- Admin-sidan kräver admin-rollen
- Lösenordsåterställning via e-post: tokens lagras som **SHA-256-hash** (aldrig i klartext)

### Flask REST API (`/api/v1/*`)

- Alla endpoints utom `/health` och `/version` kräver API-nyckel
- Stöder `X-API-Key`-header och `Authorization: Bearer <key>`
- Rate limiting per nyckel
- API-nycklar hanteras i `web/api/auth.py`

### GitHub Actions

- `GITHUB_TOKEN` ges minsta nödvändiga behörighet (`contents: write`)
- Inga andra secrets skickas till externa tjänster utom de avsedda

---

## Känslig data

### Vad som lagras

| Data | Plats | Skydd |
|------|-------|-------|
| Portföljinnehav | `data/holdings.csv` | Gitignored i prod |
| Bevakningslista | `data/watchlist.json` | Gitignored i prod |
| E-postprenumeranter | `data/subscribers.json` | Gitignored i prod |
| ML-modeller | `models/*.pkl` | SHA-256-checksum verifieras vid laddning |
| Lösenords-reset-tokens | `data/password_reset_tokens.json` | Lagras som SHA-256-hash |

### Token-sanitering i loggar

`core/ai_analysis.py` kör alla AI-felmeddelanden genom `_token_sanitize` regex som maskerar:
- OpenAI-nycklar: `sk-*` och `sk-proj-*`
- Google-nycklar: `AIza*`
- Generiska långa tokens: 40+ alfanumeriska tecken
- DeepSeek och andra providers

---

## Säkerhetsåtgärder

### Implementerade

| Åtgärd | Fil | Status |
|--------|-----|--------|
| Flask API auth via `before_request` | `web/api/__init__.py` | ✅ |
| SHA-256 reset-tokens | `web/streamlit_app.py` | ✅ |
| ML pickle SHA-256 tamper detection | `core/ml_predictor.py` | ✅ |
| Ticker-format validering (injektionsskydd) | `core/universe_manager.py` | ✅ |
| Token-sanitering i felloggar | `core/ai_analysis.py` | ✅ |
| Atomic file writes (förhindrar korrupta filer) | Flera moduler | ✅ |

### Kvarstående att adressera

| Risknivå | Beskrivning | Fil |
|----------|-------------|-----|
| 🟡 Medel | S5: `st.query_params`-navigering utan CSRF-skydd | `streamlit_app.py` |
| 🟡 Medel | S7: 70+ `unsafe_allow_html=True` — granska varje för XSS | Flera UI-filer |
| 🟡 Medel | S8: E-postprenumerantlista via API utan extra skydd | `email_template.py` |

---

## Incidenthantering

### Vid API-nyckelläckage

```bash
# 1. Kontrollera om nyckeln är exponerad i git-historiken
git log --all -p | grep -E "sk-|AIza|dp-"

# 2. Om exponerad — kontakta GitHub support för att rensa historiken
# (git filter-branch eller BFG Repo Cleaner)

# 3. Rotera nyckel omedelbart
# 4. Granska AI-loggarna i Admin-sidan för spår av unauthorized access
```

### Vid misstänkt portföljdata-läckage

1. Kontrollera GitHub Actions-loggar för vad som committades
2. Kontrollera Streamlit Cloud access logs (Settings → Logs)
3. Byt lösenord för Streamlit-appen

---

## Kända begränsningar

1. **Streamlit single-tenant**: All data (holdings, watchlist) delas av alla inloggade användare. Multi-tenant kräver omdesign av datalagret.
2. **GitHub-repo som databas**: Känsliga CSVer commitas till repot i CI-miljön. Produktionsdrift bör använda extern databas.
3. **SMTP-lösenord**: Används rakt i e-postutskick — rekommenderas att använda app-specifika lösenord och 2FA.

# MarketScan — Framtida Implementeringsidéer

Idéer som är intressanta men sparas för senare. Implementeras inte nu.
Uppdatera detta dokument när nya idéer dyker upp under arbete.

---

## Job Posting Signal

**Vad:** Scrapar LinkedIn/Indeed/Arbetsförmedlingen för antal jobbannonser per bolag.
Starkt ökande annonser = expansionssignal, kraftigt minskande = varningssignal.

**Varför det fungerar:** AltIndex, hedgefonder och kvantfonder använder jobbannons-data som leading indicator för tillväxt. Bolaget hyr personal 3–6 månader innan tillväxten syns i boksluten.

**Datakälla:** LinkedIn Jobs, Indeed (web scraping — LinkedIn Partnership API kräver avtal).
Alternativ: Arbetsförmedlingen API för svenska bolag (gratis, officiellt).

**Implementation:**
- Ny `core/job_posting_fetcher.py` med scraping-pipeline
- Ny scoring-faktor `job_growth_signal` (trend i antal annonser, 3 månaders rullande)
- Körs i weekly-pipeline (ej dagligen — data ändras långsamt)

**Komplexitet:** Medel (~2 veckor).
**Sparas tills:** Skalning motiverar extra datakälla, eller LinkedIn/Indeed öppnar API.

---

## Reddit/X Sentiment Index

**Vad:** Analyserar r/wallstreetbets, r/investing, Twitter/X — volym + sentiment per ticker.

**Varför det fungerar:** Meme-stocks och retailinvesterare driver kortsiktiga rörelser.
Kontra-indikator: extremt positivt sentiment = varningstecken (retail säljer sist).
Kontrarian-signal: extremt negativt = möjlig köpopportunitet (overreaction).

**Datakälla:** Reddit API v2 (gratis, 100 req/min), Twitter/X Basic API ($100/mån).

**Implementation:**
- `core/sentiment_fetcher.py` — hämtar Reddit-trådar + X-mentions per ticker
- Sentiment-scoring via enkel NLP (VADER eller FinBERT)
- Ny scoring-faktor `retail_sentiment` (0–1)
- Körs i daily-pipeline med 6h cache

**Komplexitet:** Medel (~2 veckor).
**Sparas tills:** X-API-kostnad motiveras, eller gratis alternativ hittas.

---

## Mobil PWA / Push-notiser

**Vad:** Lättviktig Progressive Web App (PWA) för mobil. Visar bara:
- Dagens top-5 köpkandidater
- Portföljvärde + daglig P&L
- Aktiva larm

**Varför:** Streamlit är inte mobiloptimerat. En PWA kan installeras på hemskärmen och skicka push-notiser utan App Store.

**Stack:** React/Vue (frontend) + befintlig Flask API (backend).
Kräver att Flask API:et säkras med JWT-autentisering (S1 i audit).

**Implementation:**
- Minimal React-app (~5 sidor)
- Konsumerar `/api/holdings`, `/api/watchlist`, scoring-endpoints
- Service Worker för push-notiser (Web Push Protocol)
- Deploy på Vercel (gratis)

**Komplexitet:** Hög (~4 veckor för MVP).
**Sparas tills:** >2 aktiva användare som vill ha mobil-access.

---

## Multi-tenant Arkitektur

**Vad:** Stöd för flera separata användare med egna portföljer, bevakningslistor och inställningar.

**Varför:** Systemet är byggt som single-tenant (en uppsättning datafiler). Att lägga till en andra användare kräver fullständig omdesign av datalagret.

**Kräver:**
- Migrera från flat JSON-filer till SQLite (steg 1) eller PostgreSQL (steg 2)
- Lägg till `user_id` i alla datafiler
- Riktig autentisering (JWT + lösenordshashing med bcrypt)
- Separata portfolios/watchlists per user_id

**Implementation:**
- SQLAlchemy-datamodell (holdings, watchlist, alerts, users per user_id)
- Streamlit auth via st.login() eller custom JWT
- GitHub Actions per-user schemaläggning (svårt — kräver ny arkitektur)

**Komplexitet:** Mycket hög (~2 månader).
**Sparas tills:** Behov av >5 separata användare.

---

## Satellit- och Geospatial Data

**Vad:** Satellit-bilder av fabriksaktivitet, parkeringsplatser och containerhamnar som signal.

**Varför:** SpaceKnow, Orbital Insight m.fl. säljer satellit-data till hedgefonder.
Exempelanvändning: Mät bilar på Walmart-parkeringsplatser → retail-försäljningssignal.

**Datakälla:** Planet Labs API, Copernicus (EU, gratis), Google Earth Engine.

**Komplexitet:** Mycket hög (ML-bildanalys krävs).
**Sparas tills:** Gratis-alternativ med tillräcklig täckning hittas.

---

## Automatisk Portföljrebalansering via Broker-API

**Vad:** Koppla till Alpaca Markets (US) eller IBKR (internationell) för automatisk order-exekvering baserat på MarketScan-signaler.

**Varför:** Tar bort manuellt steg — systemet identifierar och exekverar köp/sälj automatiskt.

**Risk:** Automatisk handel kräver robust riskhantering och backtesting.

**Datakälla:** Alpaca REST + WebSocket API (gratis paper trading), IBKR TWS API.

**Komplexitet:** Mycket hög (säkerhet, riskhantering, juridik).
**Sparas tills:** Backtesting visar konsistent positiv avkastning (IC > 0.1, DSR > 0.5).

---

*Dokument skapades: 2026-06-05*
*Uppdatera detta dokument när nya idéer identifieras under arbete.*

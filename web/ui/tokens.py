"""
tokens.py -- Designtokens för MarketScan.

ENDA källan för färger, spacing, radius och typografi. All styling i web/ui och
sidorna ska referera dessa konstanter istället för hårdkodade hex-värden, så att
utseendet är konsekvent och ändras på ETT ställe.

Tidigare hade appen 5 nyanser mörkblått, 3 grå, 3 röda osv. utspritt -- en nyans
per syfte här rensar det.
"""

# ── Färger (en nyans per syfte) ──────────────────────────────────────────────
BG          = "#0e1117"   # Sidans bakgrund (djup, neutral)
SURFACE     = "#161a23"   # Kort / paneler
SURFACE_2   = "#1d222e"   # Upphöjd yta (hover, inre paneler)
BORDER      = "#272d3a"   # Kantlinjer / avdelare
BORDER_HI   = "#3a4254"   # Markerad kantlinje (hover/fokus)

TEXT        = "#e8eaf0"   # Primär text
TEXT_DIM    = "#8a93a6"   # Sekundär/dämpad text
TEXT_FAINT  = "#5c6473"   # Mycket dämpad (hjälptext, etiketter)

PRIMARY     = "#4c9be8"   # Accent / interaktiva element
PRIMARY_DIM = "#2f6db0"   # Accent nedtonad

POS         = "#26c281"   # Positivt (vinst, köp, stark)
NEG         = "#f0616d"   # Negativt (förlust, sälj, svag)
WARN        = "#f5a623"   # Varning / neutral-mitt

# Score-band (semantisk färgkodning av 0-100-poäng)
SCORE_STRONG  = POS       # >= 70
SCORE_NEUTRAL = WARN      # 50-69
SCORE_WEAK    = NEG       # < 50

def score_color(score: float) -> str:
    """Returnerar färg för ett 0-100-score (stark/neutral/svag)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return TEXT_DIM
    if s >= 70:
        return SCORE_STRONG
    if s >= 50:
        return SCORE_NEUTRAL
    return SCORE_WEAK


# ── Spacing-skala (px) ───────────────────────────────────────────────────────
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32

# ── Radius ───────────────────────────────────────────────────────────────────
RADIUS    = 10   # Standard (kort, knappar)
RADIUS_SM = 6    # Chips / taggar
RADIUS_LG = 14   # Stora paneler

# ── Typografi ────────────────────────────────────────────────────────────────
FONT = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
# Storlekar (px) -- en tydlig skala istället för ad-hoc 10/11/12/13
TYPE_HERO   = 30   # Hjältetal
TYPE_TITLE  = 22   # Sidrubrik
TYPE_H2     = 17   # Sektionsrubrik
TYPE_BODY   = 14   # Brödtext
TYPE_LABEL  = 12   # Etiketter / metric-label
TYPE_MICRO  = 11   # Mikrotext / hjälp

WEIGHT_REG  = 400
WEIGHT_MED  = 500
WEIGHT_SEMI = 600
WEIGHT_BOLD = 700

# ── Skuggor (subtil depth -- inte platt hobby-look) ───────────────────────────
SHADOW_CARD = "0 1px 3px rgba(0,0,0,0.30), 0 1px 2px rgba(0,0,0,0.20)"
SHADOW_HOVER = "0 4px 12px rgba(0,0,0,0.35)"

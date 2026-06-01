"""
icons.py — Koncept → Material Symbols-ikon.

Streamlit stödjer Material Symbols native via ":material/<namn>:" i rubriker,
knappar, st.Page(icon=...), st.metric-label m.m. Detta ersätter de 66+ emoji
som gav appen en hobby-känsla, med ett enhetligt professionellt ikonset.

Använd ICON["nyckel"] → ":material/...:" istället för emoji.
"""

ICON = {
    # Navigation / sektioner
    "home":          ":material/dashboard:",
    "market":        ":material/insights:",
    "stock":         ":material/show_chart:",
    "portfolio":     ":material/account_balance_wallet:",
    "simulation":    ":material/science:",
    "watch":         ":material/visibility:",
    "ai":            ":material/smart_toy:",
    "account":       ":material/settings:",
    "admin":         ":material/admin_panel_settings:",

    # Sidor
    "scanner":       ":material/manage_search:",
    "smallcap":      ":material/grain:",
    "search":        ":material/search:",
    "globe":         ":material/public:",
    "sector":        ":material/donut_large:",
    "technical":     ":material/candlestick_chart:",
    "holdings":      ":material/list_alt:",
    "analysis":      ":material/analytics:",
    "rebalance":     ":material/balance:",
    "manage":        ":material/edit_note:",
    "paper":         ":material/receipt_long:",
    "backtest":      ":material/history:",
    "alerts":        ":material/notifications:",
    "journal":       ":material/menu_book:",
    "settings":      ":material/tune:",
    "guide":         ":material/help:",

    # Status / signaler
    "up":            ":material/trending_up:",
    "down":          ":material/trending_down:",
    "flat":          ":material/trending_flat:",
    "strong":        ":material/bolt:",
    "warning":       ":material/warning:",
    "info":          ":material/info:",
    "check":         ":material/check_circle:",
    "error":         ":material/error:",
    "star":          ":material/star:",
    "fresh":         ":material/schedule:",

    # Åtgärder
    "run":           ":material/play_arrow:",
    "refresh":       ":material/refresh:",
    "add":           ":material/add:",
    "remove":        ":material/delete:",
    "link":          ":material/arrow_forward:",
    "download":      ":material/download:",
    "upload":        ":material/upload:",
}


def ic(key: str) -> str:
    """Hämta ikon-token för ett koncept. Tom sträng om okänd nyckel."""
    return ICON.get(key, "")

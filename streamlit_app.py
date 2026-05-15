"""
streamlit_app.py (root-shim)
============================
Streamlit Cloud konfigurerades ursprungligen med 'streamlit_app.py' som main-fil,
men efter projektomstruktureringen flyttades den riktiga appen till
'web/streamlit_app.py'. Streamlit Cloud erbjuder inte längre möjlighet att
ändra main-fil via Settings → den måste finnas på den ursprungliga sökvägen.

Den här shim-filen finns kvar i roten och kör web/streamlit_app.py med
korrekt __file__-kontext så att alla relativa sökvägar i den riktiga filen
fungerar (ROOT = Path(__file__).resolve().parent.parent → projektroten).
"""

from pathlib import Path

_REAL_APP = Path(__file__).resolve().parent / "web" / "streamlit_app.py"

# Kompilera med den verkliga sökvägen så traceback pekar på rätt fil
with open(_REAL_APP, encoding="utf-8") as _f:
    _code = compile(_f.read(), str(_REAL_APP), "exec")

# Kör med __file__ = den riktiga filens sökväg så ROOT-beräkningen blir rätt
exec(_code, {"__file__": str(_REAL_APP), "__name__": "__main__"})

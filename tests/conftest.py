"""
Pytest-konfiguration och fixtures för stock-scanner.
"""
import sys
from pathlib import Path

# Se till att projektroten är i sys.path så vi kan importera moduler
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""
core/export.py
==============
Data export module for MarketScan.
Hanterar export till CSV, Excel, PDF och email-rapporter.

Alla funktioner ar try/except-sakra och returnerar (path, success, error_message).
"""

import csv
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"


def _ensure_dir(path: Path) -> Path:
    """Skapa katalog om den inte finns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── CSV Export ───────────────────────────────────────────────────────────────────

def export_to_csv(data: list[dict], columns: list[str], path: str) -> tuple:
    """Exportera data till CSV.

    Args:
        data: Lista av dicts att exportera.
        columns: Kolumnnamn i onskad ordning.
        path: Filnamn eller full sökvag (sparas i reports/ om enbart filnamn).

    Returns:
        (path, success, error_message)
    """
    try:
        filepath = Path(path)
        if not filepath.is_absolute():
            filepath = REPORT_DIR / path
        _ensure_dir(filepath)

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in data:
                writer.writerow(row)

        return (str(filepath), True, "")
    except Exception as e:
        return (path, False, str(e))


def df_to_csv(df: pd.DataFrame, path: str) -> tuple:
    """Exportera DataFrame till CSV."""
    try:
        filepath = Path(path)
        if not filepath.is_absolute():
            filepath = REPORT_DIR / path
        _ensure_dir(filepath)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return (str(filepath), True, "")
    except Exception as e:
        return (path, False, str(e))


# ── Excel Export ─────────────────────────────────────────────────────────────────

def export_to_excel(data: dict[str, list[dict]], path: str) -> tuple:
    """Exportera data till Excel med flera sheets.

    Args:
        data: Dict med sheet_name -> list_of_dicts.
        path: Sökvag for Excel-filen.

    Returns:
        (path, success, error_message)
    """
    try:
        filepath = Path(path)
        if not filepath.is_absolute():
            filepath = REPORT_DIR / path
        _ensure_dir(filepath)

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            for sheet_name, rows in data.items():
                df = pd.DataFrame(rows)
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
                # Auto-just column widths
                worksheet = writer.sheets[sheet_name[:31]]
                for col_idx, col in enumerate(df.columns, 1):
                    max_len = max(
                        df[col].astype(str).map(len).max() if len(df) > 0 else 0,
                        len(str(col)),
                    )
                    worksheet.column_dimensions[
                        openpyxl.utils.get_column_letter(col_idx)
                    ].width = min(max_len + 4, 40)

        return (str(filepath), True, "")
    except Exception as e:
        return (path, False, str(e))


def df_to_excel(sheets: dict[str, pd.DataFrame], path: str) -> tuple:
    """Exportera flera DataFrames till Excel (ett sheet per DataFrame)."""
    try:
        filepath = Path(path)
        if not filepath.is_absolute():
            filepath = REPORT_DIR / path
        _ensure_dir(filepath)

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

        return (str(filepath), True, "")
    except Exception as e:
        return (path, False, str(e))


# ── PDF Export ───────────────────────────────────────────────────────────────────

def export_to_pdf(html_content: str, path: str) -> tuple:
    """Exportera HTML-innehall till PDF.

    Anvander weasyprint om installerat, annars sparas som HTML.

    Args:
        html_content: HTML-strang att konvertera.
        path: Sökvag for PDF/HTML-filen.

    Returns:
        (path, success, error_message)
    """
    try:
        filepath = Path(path)
        if not filepath.is_absolute():
            filepath = REPORT_DIR / path
        _ensure_dir(filepath)

        try:
            import weasyprint
            weasyprint.HTML(string=html_content).write_pdf(filepath)
            return (str(filepath), True, "")
        except ImportError:
            # Fallback: spara som HTML
            html_path = filepath.with_suffix(".html")
            html_path.write_text(html_content, encoding="utf-8")
            return (str(html_path), True, "weasyprint ej installerat - sparade som HTML")
    except Exception as e:
        return (path, False, str(e))


# ── Portfolio Report ─────────────────────────────────────────────────────────────

def export_portfolio_report(portfolio_df: pd.DataFrame, analysis_dict: dict,
                            format: str = "pdf") -> tuple:
    """Exportera en komplett portfoljorapport.

    Args:
        portfolio_df: DataFrame med portfoljdata.
        analysis_dict: Dict med analysdata (korrelation, koncentration, etc.).
        format: "pdf", "excel", eller "csv".

    Returns:
        (path, success, error_message)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfolio_report_{today}"

    try:
        if format == "csv":
            path = f"{filename}.csv"
            return df_to_csv(portfolio_df, path)

        elif format == "excel":
            sheets = {
                "Portfolio": portfolio_df,
            }
            # Lagg till analys-sheets
            for key, value in analysis_dict.items():
                if isinstance(value, pd.DataFrame):
                    sheets[key[:31]] = value
                elif isinstance(value, dict):
                    sheets[key[:31]] = pd.DataFrame([value])

            path = f"{filename}.xlsx"
            return df_to_excel(sheets, path)

        else:
            # PDF via HTML
            html = _build_portfolio_html(portfolio_df, analysis_dict)
            path = f"{filename}.pdf"
            return export_to_pdf(html, path)

    except Exception as e:
        return (filename, False, str(e))


def _build_portfolio_html(df: pd.DataFrame, analysis: dict) -> str:
    """Bygg en HTML-strang for portfoljorapport."""
    rows_html = ""
    if not df.empty:
        for _, row in df.iterrows():
            rows_html += f"<tr><td>{row.get('ticker', '')}</td>"
            rows_html += f"<td>{row.get('shares', 0)}</td>"
            rows_html += f"<td>{row.get('cost_basis', 0)}</td>"
            rows_html += f"<td>{row.get('current_price', '')}</td>"
            rows_html += f"<td>{row.get('market_value', '')}</td>"
            rows_html += f"<td>{row.get('pnl', '')}</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="sv">
<head><meta charset="UTF-8">
<title>Portfoljorapport</title>
<style>
body {{ font-family: 'Inter', sans-serif; color: #e8eaf0; background: #0e1117; padding: 40px; }}
h1 {{ color: #4c9be8; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
th {{ background: #161a23; color: #8a93a6; padding: 12px; text-align: left; border-bottom: 1px solid #272d3a; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #1d222e; }}
tr:hover {{ background: #1d222e; }}
.summary {{ margin: 20px 0; padding: 16px; background: #161a23; border-radius: 10px; }}
</style>
</head>
<body>
<h1>Portfoljorapport</h1>
<p>Genererad: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
<div class="summary">
  <strong>Totalt varde:</strong> {analysis.get("total_value", "N/A")}<br>
  <strong>Totalt investerat:</strong> {analysis.get("total_cost", "N/A")}<br>
  <strong>Vinst/Forlust:</strong> {analysis.get("total_pnl", "N/A")}
</div>
<table>
<thead><tr><th>Ticker</th><th>Antal</th><th>Inkop</th><th>Kurs</th><th>Varde</th><th>P&amp;L</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body>
</html>"""


# ── Scan Report ──────────────────────────────────────────────────────────────────

def export_scan_report(scored_df: pd.DataFrame, date_str: str = "",
                       format: str = "excel") -> tuple:
    """Exportera en scan-rapport.

    Args:
        scored_df: DataFrame med scorde data.
        date_str: Datumstrang (anvands i filnamnet).
        format: "excel", "csv", eller "pdf".

    Returns:
        (path, success, error_message)
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    filename = f"scan_report_{date_str}"

    try:
        if format == "csv":
            path = f"{filename}.csv"
            return df_to_csv(scored_df, path)

        elif format == "excel":
            # Dela upp i sheets per sektor om mojligt
            sheets = {}
            if "sector" in scored_df.columns:
                for sector in scored_df["sector"].dropna().unique():
                    sector_df = scored_df[scored_df["sector"] == sector].copy()
                    sheets[sector[:31]] = sector_df
            if not sheets:
                sheets["Scan"] = scored_df
            path = f"{filename}.xlsx"
            return df_to_excel(sheets, path)

        else:
            # PDF
            top_n = scored_df.head(20) if len(scored_df) > 20 else scored_df
            html = _build_scan_html(top_n, date_str)
            path = f"{filename}.pdf"
            return export_to_pdf(html, path)

    except Exception as e:
        return (filename, False, str(e))


def _build_scan_html(df: pd.DataFrame, date_str: str) -> str:
    """Bygg HTML-strang for scan-rapport."""
    rows_html = ""
    for _, row in df.iterrows():
        rows_html += "<tr>"
        for col in ["rank", "ticker", "score_total", "sector", "price"]:
            if col in df.columns:
                val = row.get(col, "")
                rows_html += f"<td>{val}</td>"
            else:
                rows_html += "<td>-</td>"
        rows_html += "</tr>"

    return f"""<!DOCTYPE html>
<html lang="sv">
<head><meta charset="UTF-8">
<title>Scan-rapport {date_str}</title>
<style>
body {{ font-family: 'Inter', sans-serif; color: #e8eaf0; background: #0e1117; padding: 40px; }}
h1 {{ color: #4c9be8; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
th {{ background: #161a23; color: #8a93a6; padding: 12px; text-align: left; border-bottom: 1px solid #272d3a; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #1d222e; }}
tr:hover {{ background: #1d222e; }}
</style>
</head>
<body>
<h1>Scan-rapport {date_str}</h1>
<p>Antal bolag: {len(df)}</p>
<table>
<thead><tr><th>Rank</th><th>Ticker</th><th>Score</th><th>Sektor</th><th>Kurs</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body>
</html>"""


try:
    import openpyxl
except ImportError:
    openpyxl = None

"""
web/api/docs.py
===============
API Documentation for MarketScan REST API v1.
Tillhandahaller Swagger/OpenAPI 3.0 specifikation och Swagger UI.

Endpoints:
  - GET /api/v1/swagger.json - OpenAPI 3.0 spec
  - GET /api/v1/docs - Swagger UI HTML-sida
"""

import json
from flask import jsonify, render_template_string

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarketScan API v1 - Swagger UI</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.10.3/swagger-ui.min.css">
  <style>
    body { margin: 0; background: #0e1117; }
    .swagger-ui .topbar { display: none; }
    .swagger-ui .info .title { color: #e8eaf0 !important; }
    .swagger-ui .info { margin: 20px 0; }
    .swagger-ui .scheme-container { background: #161a23; box-shadow: none; }
    .swagger-ui { color: #e8eaf0; }
    .swagger-ui .opblock-tag { color: #e8eaf0 !important; }
    .swagger-ui .opblock-tag small { color: #8a93a6 !important; }
    .swagger-ui .opblock .opblock-summary-description { color: #8a93a6 !important; }
    .swagger-ui .parameter__name { color: #e8eaf0 !important; }
    .swagger-ui .parameter__type { color: #8a93a6 !important; }
    .swagger-ui .opblock .opblock-summary { border-color: #272d3a !important; }
    .swagger-ui .opblock { background: #1d222e; border-color: #272d3a; }
    .swagger-ui .opblock .opblock-summary-path { color: #4c9be8 !important; }
    .swagger-ui .opblock .opblock-summary-description { color: #8a93a6 !important; }
    .swagger-ui .opblock-body { background: #161a23; }
    .swagger-ui .responses-inner h4, .swagger-ui .responses-inner h5 { color: #e8eaf0; }
    .swagger-ui .model-box { background: #1d222e; }
    .swagger-ui .model { color: #e8eaf0; }
    .swagger-ui table thead tr td, .swagger-ui table thead tr th { color: #8a93a6; border-color: #272d3a; }
    .swagger-ui table tbody tr td { color: #e8eaf0; border-color: #1d222e; }
    .swagger-ui .response-col_status { color: #e8eaf0; }
    .swagger-ui .response-col_description { color: #8a93a6; }
    .swagger-ui .btn { color: #e8eaf0; }
    .swagger-ui .btn.execute { background-color: #4c9be8; border-color: #4c9be8; }
    .swagger-ui select { background: #1d222e; color: #e8eaf0; border-color: #272d3a; }
    .swagger-ui input[type=text] { background: #1d222e; color: #e8eaf0; border-color: #272d3a; }
    .swagger-ui textarea { background: #1d222e; color: #e8eaf0; border-color: #272d3a; }
    .swagger-ui .info a { color: #4c9be8; }
    .swagger-ui .info p { color: #8a93a6; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.10.3/swagger-ui-bundle.min.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/api/v1/swagger.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIBundle.SwaggerUIStandalonePreset,
      ],
      layout: "BaseLayout",
      defaultModelsExpandDepth: 1,
      defaultModelExpandDepth: 1,
      docExpansion: "list",
      filter: true,
    });
  </script>
</body>
</html>"""


def get_openapi_spec() -> dict:
    """Returnera OpenAPI 3.0 specifikation for MarketScan API v1."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "MarketScan API",
            "description": "REST API for MarketScan - multifaktor-aktiescanner med AI-analys.\n\n"
                           "## Autentisering\n"
                           "De flesta endpoints kraver en API-nyckel. Skicka nyckeln i header:\n"
                           "`X-API-Key: <din-nyckel>` eller `Authorization: Bearer <din-nyckel>`\n\n"
                           "## Rate Limiting\n"
                           "Standard: 100 anrop per 60 sekunder per API-nyckel.\n"
                           "Rate limit headers inkluderas i alla svar.",
            "version": "1.0.0",
            "contact": {
                "name": "MarketScan Support",
            },
        },
        "servers": [
            {"url": "/api/v1", "description": "Local development"},
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "API-nyckel fran MarketScan admin panel.",
                },
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API-nyckel som Bearer token.",
                },
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "example": "error"},
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string", "example": "NOT_FOUND"},
                                "message": {"type": "string", "example": "Aktien hittades inte"},
                            },
                        },
                    },
                },
                "Success": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "example": "ok"},
                        "data": {"type": "object"},
                        "meta": {
                            "type": "object",
                            "properties": {
                                "took_ms": {"type": "number", "example": 123.45},
                                "source": {"type": "string", "example": "cache"},
                                "timestamp": {"type": "string", "example": "2026-06-02T12:00:00"},
                            },
                        },
                    },
                },
            },
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "System health check",
                    "description": "Kontrollerar att systemet fungerar. Delegeerar till monitoring-modulen.",
                    "tags": ["System"],
                    "security": [],
                    "responses": {
                        "200": {
                            "description": "Systemet fungerar",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Success"}}},
                        },
                    },
                },
            },
            "/version": {
                "get": {
                    "summary": "API version info",
                    "description": "Returnerar API- och app-version.",
                    "tags": ["System"],
                    "security": [],
                    "responses": {
                        "200": {
                            "description": "Version info",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Success"}}},
                        },
                    },
                },
            },
            "/stocks/{ticker}": {
                "get": {
                    "summary": "Fullstandig stock data",
                    "description": "Hämta all tillgänglig information om en aktie inklusive scoring, nyckeltal, nyheter och AI-analys.",
                    "tags": ["Stocks"],
                    "parameters": [
                        {"name": "ticker", "in": "path", "required": True,
                         "schema": {"type": "string"}, "description": "Ticker-symbol (t.ex. AAPL)"},
                    ],
                    "responses": {
                        "200": {"description": "Stock data"},
                        "404": {"description": "Aktien hittades inte", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                    },
                },
            },
            "/stocks/{ticker}/score": {
                "get": {
                    "summary": "Endast scoring",
                    "description": "Hamta enbart scoring for en aktie.",
                    "tags": ["Stocks"],
                    "parameters": [
                        {"name": "ticker", "in": "path", "required": True,
                         "schema": {"type": "string"}, "description": "Ticker-symbol"},
                    ],
                    "responses": {
                        "200": {"description": "Score data"},
                        "404": {"description": "Aktien hittades inte"},
                    },
                },
            },
            "/stocks/{ticker}/news": {
                "get": {
                    "summary": "Nyheter",
                    "description": "Hamta nyhetsartiklar for en aktie.",
                    "tags": ["Stocks"],
                    "parameters": [
                        {"name": "ticker", "in": "path", "required": True,
                         "schema": {"type": "string"}, "description": "Ticker-symbol"},
                    ],
                    "responses": {
                        "200": {"description": "Nyheter"},
                        "502": {"description": "Kunde inte hämta nyheter"},
                    },
                },
            },
            "/stocks/{ticker}/price": {
                "get": {
                    "summary": "Prisdata",
                    "description": "Hamta prisdata (1 ars historik) for en aktie.",
                    "tags": ["Stocks"],
                    "parameters": [
                        {"name": "ticker", "in": "path", "required": True,
                         "schema": {"type": "string"}, "description": "Ticker-symbol"},
                    ],
                    "responses": {
                        "200": {"description": "Prisdata"},
                        "502": {"description": "Kunde inte hämta prisdata"},
                    },
                },
            },
            "/stocks/{ticker}/options": {
                "get": {
                    "summary": "Optionskedja",
                    "description": "Hamta optionskedja for en aktie (om optionsmodul finns).",
                    "tags": ["Stocks"],
                    "parameters": [
                        {"name": "ticker", "in": "path", "required": True,
                         "schema": {"type": "string"}, "description": "Ticker-symbol"},
                    ],
                    "responses": {
                        "200": {"description": "Options data"},
                        "503": {"description": "Optionsmodul ej tillgänglig"},
                    },
                },
            },
            "/scans/latest": {
                "get": {
                    "summary": "Senaste scan-resultat",
                    "description": "Hamta senaste scan-resultat. Stodjer 'weekly' och 'smallcap' mode.",
                    "tags": ["Scans"],
                    "parameters": [
                        {"name": "mode", "in": "query", "required": False,
                         "schema": {"type": "string", "enum": ["weekly", "smallcap"], "default": "weekly"},
                         "description": "Scan-mode"},
                    ],
                    "responses": {
                        "200": {"description": "Scan resultat"},
                        "404": {"description": "Inga scan-resultat funna"},
                    },
                },
            },
            "/scans/history": {
                "get": {
                    "summary": "Scan-historik",
                    "description": "Hamta historiska scan-resultat.",
                    "tags": ["Scans"],
                    "parameters": [
                        {"name": "days", "in": "query", "required": False,
                         "schema": {"type": "integer", "default": 30},
                         "description": "Antal dagar bakåt"},
                        {"name": "mode", "in": "query", "required": False,
                         "schema": {"type": "string", "enum": ["weekly", "smallcap"], "default": "weekly"},
                         "description": "Scan-mode"},
                    ],
                    "responses": {
                        "200": {"description": "Scan-historik"},
                    },
                },
            },
            "/portfolio": {
                "get": {
                    "summary": "Portfoljdata",
                    "description": "Hamta portfoljdata med live-priser och P&L.",
                    "tags": ["Portfolio"],
                    "responses": {
                        "200": {"description": "Portfoljdata"},
                    },
                },
            },
            "/portfolio/holdings": {
                "get": {
                    "summary": "Innehav",
                    "description": "Hamta enbart innehav (utan live-priser).",
                    "tags": ["Portfolio"],
                    "responses": {
                        "200": {"description": "Innehav"},
                    },
                },
            },
            "/portfolio/analysis": {
                "get": {
                    "summary": "Portfoljanalys",
                    "description": "Hamta portfoljanalys (korrelation, koncentration, diversifiering).",
                    "tags": ["Portfolio"],
                    "responses": {
                        "200": {"description": "Analys"},
                        "503": {"description": "Analysmodul ej tillgänglig"},
                    },
                },
            },
            "/alerts": {
                "get": {
                    "summary": "Aktiva larm",
                    "description": "Hamta alla aktiva larm.",
                    "tags": ["Alerts"],
                    "responses": {
                        "200": {"description": "Larm"},
                    },
                },
            },
            "/sectors": {
                "get": {
                    "summary": "Sektor-data",
                    "description": "Hamta sektor-data baserat pa senaste scan.",
                    "tags": ["Sectors"],
                    "responses": {
                        "200": {"description": "Sektor-data"},
                    },
                },
            },
            "/markets/global": {
                "get": {
                    "summary": "Globala index",
                    "description": "Hamta globala indexkurser (via yfinance).",
                    "tags": ["Markets"],
                    "responses": {
                        "200": {"description": "Globala index"},
                    },
                },
            },
            "/markets/macro": {
                "get": {
                    "summary": "Makro-regim",
                    "description": "Hamta aktuell marknadsregim (tjur/bjorn/osaker).",
                    "tags": ["Markets"],
                    "responses": {
                        "200": {"description": "Makrodata"},
                    },
                },
            },
            "/search": {
                "get": {
                    "summary": "Ticker-sokning",
                    "description": "Sok efter aktier via yfinance Search.",
                    "tags": ["Search"],
                    "parameters": [
                        {"name": "q", "in": "query", "required": True,
                         "schema": {"type": "string"}, "description": "Sokstrang (ticker eller namn)"},
                    ],
                    "responses": {
                        "200": {"description": "Sokresultat"},
                        "400": {"description": "Sokparameter 'q' kravs"},
                    },
                },
            },
        },
    }


def register_docs_routes(blueprint):
    """Registrera dokumentations-endpoints pa en blueprint."""

    @blueprint.route("/swagger.json", methods=["GET"])
    def swagger_json():
        return jsonify(get_openapi_spec())

    @blueprint.route("/docs", methods=["GET"])
    def swagger_ui():
        return render_template_string(SWAGGER_UI_HTML)

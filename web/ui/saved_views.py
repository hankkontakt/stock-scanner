"""
saved_views.py -- Saved View System for MarketScan.

Allows users to save, load, export, and import view configurations
including filters, column selections, sort settings, and date ranges.
Persistence via data/saved_views.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from web.ui.icons import ic

# Path to saved views data file
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SAVED_VIEWS_PATH = DATA_DIR / "saved_views.json"


# ══════════════════════════════════════════════════════════════════════════════
# VIEW SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_VIEW: dict[str, Any] = {
    "page": "",
    "filters": {},
    "sort_column": "",
    "sort_order": "asc",
    "visible_columns": [],
    "date_selection": "",
    "created_at": "",
    "updated_at": "",
    "description": "",
}


# ══════════════════════════════════════════════════════════════════════════════
# MANAGER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class SavedViewsManager:
    """Manages saved view configurations with CRUD + import/export."""

    def __init__(self, username: str | None = None) -> None:
        self.username = username or st.session_state.get("username", "default")
        self._views: dict[str, dict] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load views from disk."""
        try:
            if SAVED_VIEWS_PATH.exists():
                raw = json.loads(SAVED_VIEWS_PATH.read_text(encoding="utf-8"))
                self._views = raw.get(self.username, {})
            else:
                self._views = {}
        except Exception:
            self._views = {}

    def _save(self) -> bool:
        """Save views to disk."""
        try:
            SAVED_VIEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
            all_views: dict[str, dict] = {}
            if SAVED_VIEWS_PATH.exists():
                all_views = json.loads(SAVED_VIEWS_PATH.read_text(encoding="utf-8"))
            all_views[self.username] = self._views
            SAVED_VIEWS_PATH.write_text(
                json.dumps(all_views, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def save_view(
        self,
        name: str,
        config: dict[str, Any],
        description: str = "",
    ) -> bool:
        """Save a view configuration.

        Args:
            name: Unique view name.
            config: View configuration dict (page, filters, sort, etc.).
            description: Optional human-readable description.

        Returns:
            True if saved successfully.
        """
        now = datetime.now().isoformat(timespec="seconds")
        view = dict(DEFAULT_VIEW)
        view.update(config)
        view["description"] = description or view.get("description", "")
        view["created_at"] = self._views.get(name, {}).get("created_at", now)
        view["updated_at"] = now
        self._views[name] = view
        return self._save()

    def load_view(self, name: str) -> dict[str, Any] | None:
        """Load a saved view configuration.

        Returns:
            View config dict or None if not found.
        """
        return self._views.get(name)

    def list_views(self) -> list[dict[str, Any]]:
        """List all saved views with metadata.

        Returns:
            List of dicts with name and metadata.
        """
        return [
            {
                "name": name,
                "page": v.get("page", ""),
                "description": v.get("description", ""),
                "created_at": v.get("created_at", ""),
                "updated_at": v.get("updated_at", ""),
                "filter_count": len(v.get("filters", {})),
            }
            for name, v in self._views.items()
        ]

    def delete_view(self, name: str) -> bool:
        """Delete a saved view.

        Returns:
            True if deleted, False if not found.
        """
        if name in self._views:
            del self._views[name]
            return self._save()
        return False

    def get_view_names(self) -> list[str]:
        """Get all view names."""
        return list(self._views.keys())

    # ── Import / Export ──────────────────────────────────────────────────────

    def export_view(self, name: str, fmt: str = "json") -> str | None:
        """Export a view as JSON string.

        Args:
            name: View name to export.
            fmt: Export format (currently only "json").

        Returns:
            JSON string or None if view not found.
        """
        view = self._views.get(name)
        if view is None:
            return None
        export_data = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "username": self.username,
            "view_name": name,
            "view": view,
        }
        return json.dumps(export_data, indent=2, ensure_ascii=False)

    def import_view(self, json_str: str) -> tuple[bool, str]:
        """Import a view from JSON string.

        Args:
            json_str: JSON string from export_view().

        Returns:
            (success, message) tuple.
        """
        try:
            data = json.loads(json_str)
            view_name = data.get("view_name", "")
            view_data = data.get("view", {})
            if not view_name or not view_data:
                return False, "Invalid view format: missing name or data."

            # Handle name conflicts: append suffix if already exists
            original_name = view_name
            suffix = 1
            while view_name in self._views:
                view_name = f"{original_name} (import {suffix})"
                suffix += 1

            self._views[view_name] = view_data
            self._save()
            return True, f"View '{view_name}' imported successfully."
        except json.JSONDecodeError:
            return False, "Invalid JSON format."
        except Exception as e:
            return False, f"Import failed: {e}"

    # ── Bulk operations ──────────────────────────────────────────────────────

    def clear_all(self) -> bool:
        """Delete all views for the current user."""
        self._views = {}
        return self._save()


# ══════════════════════════════════════════════════════════════════════════════
# UI COMPONENT — sidebar saved views section
# ══════════════════════════════════════════════════════════════════════════════

def render_saved_views_ui(current_config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Render saved views UI in the sidebar.

    Displays a "Saved Views" section with:
    - Search/filter views list
    - Load / Save / Delete buttons
    - Import / Export controls

    Args:
        current_config: Optional current view config to enable "Save current" button.

    Returns:
        Loaded view config if user loads one, None otherwise.
    """
    manager = SavedViewsManager()
    views = manager.list_views()

    st.markdown("---")
    st.markdown(f"### {ic('star')} Saved Views")

    # Quick action buttons
    col_save, col_ref = st.columns(2)
    with col_save:
        if current_config and st.button("Save Current", key="sv_save_btn", use_container_width=True):
            _show_save_dialog(manager, current_config)
    with col_ref:
        if st.button("Refresh", key="sv_refresh_btn", use_container_width=True):
            st.rerun()

    if not views:
        st.caption("No saved views yet. Configure your filters and click 'Save Current'.")
        return None

    # View list with search
    search = st.text_input("", placeholder="Search views...", key="sv_search", label_visibility="collapsed")
    filtered_views = views
    if search.strip():
        q = search.strip().lower()
        filtered_views = [v for v in views if q in v["name"].lower() or q in v.get("description", "").lower()]

    # Render each view as a compact card
    loaded_config = None
    for view_meta in filtered_views:
        name = view_meta["name"]
        page = view_meta.get("page", "")
        desc = view_meta.get("description", "")
        filter_count = view_meta.get("filter_count", 0)

        # Card container
        cols = st.columns([3, 1, 1])
        with cols[0]:
            st.markdown(
                f"<div style='font-size:13px;font-weight:600;color:var(--text-primary);'>{name}</div>"
                f"<div style='font-size:10px;color:var(--text-secondary);'>{page} · {filter_count} filters</div>"
                + (f"<div style='font-size:10px;color:var(--text-secondary);'>{desc}</div>" if desc else ""),
                unsafe_allow_html=True,
            )
        with cols[1]:
            if st.button("Load", key=f"sv_load_{name}", use_container_width=True):
                loaded = manager.load_view(name)
                if loaded:
                    loaded_config = loaded
                    st.success(f"Loaded view: {name}")
        with cols[2]:
            if st.button("X", key=f"sv_del_{name}", use_container_width=True):
                manager.delete_view(name)
                st.rerun()

    # Export/Import section
    with st.expander("Import / Export", expanded=False):
        view_names = manager.get_view_names()
        if view_names:
            export_name = st.selectbox("Export view", view_names, key="sv_export_select")
            if st.button("Copy Export JSON", key="sv_export_btn"):
                export_str = manager.export_view(export_name)
                if export_str:
                    st.code(export_str, language="json")
                    st.info("Copy the JSON above to share this view.")
                else:
                    st.error("Could not export view.")

        import_str = st.text_area("Paste view JSON to import", placeholder="Paste exported JSON here...", key="sv_import_area")
        if import_str.strip() and st.button("Import View", key="sv_import_btn"):
            ok, msg = manager.import_view(import_str.strip())
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    return loaded_config


def _show_save_dialog(manager: SavedViewsManager, config: dict[str, Any]) -> None:
    """Show a save dialog (inline) asking for view name and description."""
    # Store in session state that we're in save mode
    st.session_state["_sv_save_active"] = True

    if st.session_state.get("_sv_save_active"):
        with st.container():
            name = st.text_input("View name", placeholder="e.g. My Value Screener", key="sv_new_name")
            desc = st.text_input("Description (optional)", placeholder="What does this view filter?", key="sv_new_desc")
            c1, c2 = st.columns(2)
            with c1:
                if name.strip() and st.button("Save", key="sv_confirm_save", type="primary"):
                    ok = manager.save_view(name.strip(), config, description=desc.strip())
                    if ok:
                        st.success(f"Saved '{name}'!")
                        st.session_state["_sv_save_active"] = False
                        st.rerun()
                    else:
                        st.error("Failed to save view.")
            with c2:
                if st.button("Cancel", key="sv_cancel_save"):
                    st.session_state["_sv_save_active"] = False
                    st.rerun()

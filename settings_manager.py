"""
Total Commander Clone - Settings Manager
Handles loading and saving of settings.json, state.json, and bookmarks.json.
Auto-creates config files with sensible defaults on first run.
Also writes latest per-computer backups under the local user-data
directory (never into Git).
"""

import copy
import json
import os
from datetime import datetime, timezone

from config_backup import backupConfig
from app_version import APP_VERSION


# ------------------------------------------------------------
# Profile bundle (single-file import/export)
# ------------------------------------------------------------
PROFILE_FORMAT = "total-commander-clone-profile"
PROFILE_FORMAT_VERSION = 1
BOOKMARKS_FORMAT = "total-commander-clone-bookmarks"
BOOKMARKS_FORMAT_VERSION = 1
LAST_GOOD_BOOKMARKS_FILENAME = "bookmarks.last-good.json"
BOOKMARKS_FILENAME = "bookmarks.json"
PROFILE_STATE_KEYS = (
    "bookmarks",
    "libraries",
    "folder_tags",
    "saved_library_filters",
    "saved_file_filters",
    "sidebar_state",
    "recent_paths",
    "left_panel",
    "right_panel",
)


# ------------------------------------------------------------
# Default Settings
# These are written to settings.json on first run.
# ------------------------------------------------------------
DEFAULT_SETTINGS = {
    "show_hidden_files": False,
    "confirm_delete": True,
    "theme_mode": "dark",
    "default_left_path": "",
    "default_right_path": "",
    "column_widths": {
        "name": 300,
        "size": 100,
        "type": 120,
    },
    "window_geometry": {
        "x": 100,
        "y": 100,
        "width": 1400,
        "height": 800,
    },
    "sort_column": 0,
    "sort_order": "ascending",
    "font_size": 10,
    "ui_scale": 100,
    "subfolders_warning_dismissed": False,
    # Mirror (Ctrl+Shift+M): which panel navigates to match the other.
    # "to_other" = inactive panel opens the active panel's folder (default).
    # "to_active" = active panel opens the inactive panel's folder.
    "mirror_mode": "to_other",
    # Date Modified column strftime preset key (see file_panel.DATE_MODIFIED_FORMATS).
    "date_modified_format": "yyyy_mm_dd_hm",
    # Startup: compare APP_VERSION to Git remote; offer pull + rebuild.
    "check_for_updates_on_startup": True,
    # When user chooses "Skip this version", store that remote version string.
    "skip_update_version": "",
    # Cache recursive (Subfolders) scan trees in memory and on disk.
    "cache_recursive_scans": True,
}


# ------------------------------------------------------------
# Default State
# These are written to state.json on first run.
# ------------------------------------------------------------
DEFAULT_STATE = {
    "left_panel": {
        "current_path": "",
        "history": [],
        "column_visibility": {
            "name": True,
            "size": True,
            "type": True,
            "date_modified": True,
        },
        "filter_mode": "contains",
        "filter_kind": "all",
        "filter_text": "",
        "filter_exclude_text": "",
        "filter_extensions": "",
        "filter_words_combine_and": True,
        "filter_include_subfolders": False,
        "filter_advanced": {},
    },
    "right_panel": {
        "current_path": "",
        "history": [],
        "column_visibility": {
            "name": True,
            "size": True,
            "type": True,
            "date_modified": True,
        },
        "filter_mode": "contains",
        "filter_kind": "all",
        "filter_text": "",
        "filter_exclude_text": "",
        "filter_extensions": "",
        "filter_words_combine_and": True,
        "filter_include_subfolders": False,
        "filter_advanced": {},
    },
    "bookmarks": [],
    "recent_paths": [],
    "libraries": [],
    "folder_tags": {},
    "saved_library_filters": [],
    "saved_file_filters": [],
    "sidebar_state": {
        "current_tab": "bookmarks",
    },
}


# ------------------------------------------------------------
# Class: SettingsManager
# Purpose: Provides a unified interface for reading and writing
#          application settings and panel state from/to JSON.
#          Handles file I/O, defaults, and first-run creation.
# ------------------------------------------------------------
class SettingsManager:

    SETTINGS_FILENAME = "settings.json"
    STATE_FILENAME = "state.json"
    BOOKMARKS_FILENAME = BOOKMARKS_FILENAME
    MAX_RECENT_PATHS = 30

    # --------------------------------------------------------
    # Method: __init__
    # Purpose: Initializes the manager, resolves file paths,
    #          and loads (or creates) both JSON config files.
    # Input:  base_path (str) - Directory where config files live.
    #         project_root (str|None) - Git/project root for updates.
    # --------------------------------------------------------
    def __init__(self, base_path, project_root=None, enable_backup=True):
        self._base_path = base_path
        self._project_root = project_root or base_path
        self._settings_path = os.path.join(base_path, self.SETTINGS_FILENAME)
        self._state_path = os.path.join(base_path, self.STATE_FILENAME)
        self._bookmarks_path = os.path.join(base_path, self.BOOKMARKS_FILENAME)
        self._last_good_bookmarks_path = os.path.join(
            base_path, LAST_GOOD_BOOKMARKS_FILENAME
        )
        self._backup_enabled = enable_backup
        # True only after this process changes the bookmark list.
        self._bookmarks_dirty = False
        # True after the user removes every bookmark in this process.
        self._bookmarks_explicit_clear = False
        self._bookmark_recovery_notice = ""

        self._settings = self._loadOrCreate(self._settings_path, DEFAULT_SETTINGS)
        self._state = self._loadState()

    # --------------------------------------------------------
    # Method: _loadOrCreate
    # Purpose: Loads a JSON file if it exists, otherwise creates
    #          it with the supplied defaults and returns them.
    # Input:  path (str) - Full path to the JSON file.
    #         defaults (dict) - Default values to write if missing.
    # Output: dict - The loaded or default configuration data.
    # --------------------------------------------------------
    def _loadOrCreate(self, path, defaults):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise json.JSONDecodeError("Expected a JSON object", "", 0)
                merged = self._deepMerge(defaults, data)
                return merged
            except (json.JSONDecodeError, IOError, OSError, ValueError):
                return copy.deepcopy(defaults)
        else:
            data = copy.deepcopy(defaults)
            self._writeJson(path, data)
            return data

    # --------------------------------------------------------
    # Method: _loadState
    # Purpose: Load state.json for panel layout, then load the
    #          bookmark list from bookmarks.json. An older list
    #          still stored in state.json is moved across once.
    # --------------------------------------------------------
    def _loadState(self):
        data = self._readStateDocument()
        self._resolveBookmarkStore(data)
        return data

    # --------------------------------------------------------
    # Method: _readStateDocument
    # Purpose: Load state.json, or replace an unreadable file
    #          with defaults. Bookmark recovery is separate.
    # --------------------------------------------------------
    def _readStateDocument(self):
        path = self._state_path
        if not os.path.exists(path):
            data = copy.deepcopy(DEFAULT_STATE)
            self._writeJson(path, data)
            return data
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise json.JSONDecodeError("Expected a JSON object", "", 0)
            return self._deepMerge(DEFAULT_STATE, raw)
        except (json.JSONDecodeError, IOError, OSError, ValueError):
            self._quarantineCorruptState(path)
            data = copy.deepcopy(DEFAULT_STATE)
            self._writeJson(path, data)
            return data

    # --------------------------------------------------------
    # Method: _resolveBookmarkStore
    # Purpose: bookmarks.json is the bookmark list. If that file
    #          is missing, copy bookmarks out of state.json once.
    #          If it is empty or unreadable, use the last good copy
    #          unless the user deleted every bookmark on purpose.
    # --------------------------------------------------------
    def _resolveBookmarkStore(self, data):
        document = self._readBookmarkDocument(self._bookmarks_path)
        from_corrupt = False
        if document is not None and document.get("corrupt"):
            self._quarantineCorruptState(self._bookmarks_path)
            document = None
            from_corrupt = True

        if document is not None:
            data["bookmarks"] = document["bookmarks"]
            if document.get("explicit_empty"):
                self._bookmarks_explicit_clear = True
            if (
                self._countBookmarks(data.get("bookmarks", [])) == 0
                and not document.get("explicit_empty")
                and self._restoreBookmarksIfNeeded(data, from_corrupt=False)
            ):
                self._writeBookmarkStore(data.get("bookmarks", []))
            self._seedLastGoodIfMissing(data)
            return

        legacy = data.get("bookmarks", [])
        if from_corrupt:
            # state.json can be rewritten by a window that did not edit bookmarks.
            # After a damaged bookmark file, prefer the last good copy.
            data["bookmarks"] = []
            if not self._restoreBookmarksIfNeeded(data, from_corrupt=True):
                if self._countBookmarks(legacy) > 0:
                    data["bookmarks"] = legacy
        elif self._countBookmarks(legacy) == 0:
            self._restoreBookmarksIfNeeded(data, from_corrupt=False)
        self._writeBookmarkStore(data.get("bookmarks", []))
        self._seedLastGoodIfMissing(data)

    # --------------------------------------------------------
    # Method: _deepMerge
    # Purpose: Recursively merges loaded data onto defaults so
    #          that any new keys added in future versions are
    #          present while preserving existing user values.
    # Input:  defaults (dict), override (dict)
    # Output: dict - Merged result.
    # --------------------------------------------------------
    def _deepMerge(self, defaults, override):
        result = copy.deepcopy(defaults)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deepMerge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    # --------------------------------------------------------
    # Method: _writeJson
    # Purpose: Writes a dictionary to a JSON file with pretty
    #          formatting for human readability.
    # --------------------------------------------------------
    def _writeJson(self, path, data):
        parent = os.path.dirname(path)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as e:
                print(f"[SettingsManager] Error creating {parent}: {e}")
                return False
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
            return True
        except (IOError, OSError, TypeError, ValueError) as e:
            print(f"[SettingsManager] Error writing {path}: {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False

    # --------------------------------------------------------
    # Settings Accessors
    # --------------------------------------------------------
    def getSetting(self, key, default=None):
        return self._settings.get(key, default)

    def setSetting(self, key, value):
        self._settings[key] = value

    def getSettings(self):
        return self._settings

    # --------------------------------------------------------
    # State Accessors
    # --------------------------------------------------------
    def getState(self, key, default=None):
        return self._state.get(key, default)

    def setState(self, key, value):
        self._state[key] = value

    def getFullState(self):
        return self._state

    # --------------------------------------------------------
    # Panel State Helpers
    # --------------------------------------------------------
    def getPanelState(self, panel_side):
        key = f"{panel_side}_panel"
        return self._state.get(key, DEFAULT_STATE.get(key, {}))

    def setPanelState(self, panel_side, data):
        key = f"{panel_side}_panel"
        self._state[key] = data

    # --------------------------------------------------------
    # Bookmarks (structure: list of nodes; node = bookmark or group)
    # --------------------------------------------------------
    def getBookmarksStructure(self):
        raw = self._state.get("bookmarks", [])
        if not raw:
            return []
        if isinstance(raw[0], dict) and "type" in raw[0]:
            return raw
        for bm in raw:
            if not isinstance(bm, dict) or "path" not in bm:
                return raw
        return [{"type": "bookmark", "name": b.get("name", ""), "path": b.get("path", "")} for b in raw]

    # --------------------------------------------------------
    # Method: setBookmarksStructure
    # Purpose: Replace the in-memory bookmark tree. user_edit
    #          writes it immediately and records an intentional
    #          clear when the new tree has no bookmarks.
    # --------------------------------------------------------
    def setBookmarksStructure(self, structure, user_edit=False):
        self._state["bookmarks"] = structure if isinstance(structure, list) else []
        if user_edit:
            self._bookmarks_dirty = True
            self._bookmarks_explicit_clear = self._countBookmarks(self._state["bookmarks"]) == 0
            self.saveState()

    def addBookmark(self, name, path):
        structure = self.getBookmarksStructure()
        if self._findBookmarkByPath(structure, path) is not None:
            return
        structure.append({"type": "bookmark", "name": name, "path": path})
        self.setBookmarksStructure(structure, user_edit=True)

    def _findBookmarkByPath(self, structure, path):
        for node in structure:
            if node.get("type") == "bookmark" and node.get("path") == path:
                return node
            if node.get("type") == "group":
                found = self._findBookmarkByPath(node.get("children", []), path)
                if found is not None:
                    return found
        return None

    def _removeBookmarkFromList(self, nodes, path):
        for i, node in enumerate(nodes):
            if node.get("type") == "bookmark" and node.get("path") == path:
                nodes.pop(i)
                return True
            if node.get("type") == "group":
                if self._removeBookmarkFromList(node.get("children", []), path):
                    return True
        return False

    def removeBookmark(self, path):
        structure = self.getBookmarksStructure()
        if not self._removeBookmarkFromList(structure, path):
            return
        self.setBookmarksStructure(structure, user_edit=True)

    def getBookmarks(self):
        out = []

        def walk(nodes):
            for node in nodes or []:
                if not isinstance(node, dict):
                    continue
                if node.get("type") == "group":
                    walk(node.get("children", []))
                elif node.get("type") == "bookmark" or "path" in node:
                    out.append({"name": node.get("name", ""), "path": node.get("path", "")})

        walk(self.getBookmarksStructure())
        return out

    # --------------------------------------------------------
    # Method: applyBookmarkTreeSnapshot
    # Purpose: On shutdown, keep a non-empty list when the sidebar
    #          tree is empty or this process never edited bookmarks.
    # --------------------------------------------------------
    def applyBookmarkTreeSnapshot(self, structure):
        structure = structure if isinstance(structure, list) else []
        if self._countBookmarks(structure) == 0:
            if self._countBookmarks(self.getBookmarksStructure()) > 0 and not self._bookmarks_explicit_clear:
                return
            if not self._bookmarks_dirty:
                return
        if not self._bookmarks_dirty:
            return
        self.setBookmarksStructure(structure, user_edit=True)

    # --------------------------------------------------------
    # Method: consumeBookmarkRecoveryNotice
    # Purpose: Return a one-time status message when bookmarks
    #          were restored from the last good copy.
    # --------------------------------------------------------
    def consumeBookmarkRecoveryNotice(self):
        notice = self._bookmark_recovery_notice
        self._bookmark_recovery_notice = ""
        return notice

    # --------------------------------------------------------
    # Method: exportBookmarks
    # Purpose: Write the bookmark tree to a portable JSON file.
    # --------------------------------------------------------
    def exportBookmarks(self, path):
        payload = {
            "format": BOOKMARKS_FORMAT,
            "format_version": BOOKMARKS_FORMAT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION,
            "bookmarks": copy.deepcopy(self.getBookmarksStructure()),
        }
        if not self._writeJson(path, payload):
            raise OSError(f"Could not write bookmarks to {path}")
        return path

    # --------------------------------------------------------
    # Method: importBookmarks
    # Purpose: Replace the list or merge imported paths into it,
    #          then save immediately.
    # Input:  mode - "replace" or "merge"
    # Output: dict {count, mode}
    # --------------------------------------------------------
    def importBookmarks(self, path, mode="replace"):
        imported = self._normalizeBookmarkNodes(self._loadBookmarkFile(path))
        if mode == "merge":
            structure = self._mergeBookmarkStructures(self.getBookmarksStructure(), imported)
        elif mode == "replace":
            structure = imported
        else:
            raise ValueError("Bookmark import mode must be 'replace' or 'merge'.")
        self.setBookmarksStructure(structure, user_edit=True)
        return {
            "count": self._countBookmarks(self.getBookmarksStructure()),
            "mode": mode,
        }

    # --------------------------------------------------------
    # Libraries / Tags
    # --------------------------------------------------------
    def getLibraries(self):
        return self._state.get("libraries", [])

    def setLibraries(self, libraries):
        self._state["libraries"] = libraries or []

    def getFolderTags(self):
        return self._state.get("folder_tags", {})

    def setFolderTags(self, folder_tags):
        self._state["folder_tags"] = folder_tags or {}

    def getSavedLibraryFilters(self):
        return self._state.get("saved_library_filters", [])

    def setSavedLibraryFilters(self, filters):
        self._state["saved_library_filters"] = filters or []

    def getSavedFileFilters(self):
        return self._state.get("saved_file_filters", [])

    def setSavedFileFilters(self, filters):
        self._state["saved_file_filters"] = filters or []

    def getSidebarState(self):
        return self._state.get("sidebar_state", DEFAULT_STATE.get("sidebar_state", {}))

    def setSidebarState(self, sidebar_state):
        self._state["sidebar_state"] = self._deepMerge(
            DEFAULT_STATE.get("sidebar_state", {}),
            sidebar_state or {},
        )

    # --------------------------------------------------------
    # Recent Paths
    # --------------------------------------------------------
    def addRecentPath(self, path):
        recent = self._state.get("recent_paths", [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._state["recent_paths"] = recent[:self.MAX_RECENT_PATHS]

    def getRecentPaths(self):
        return self._state.get("recent_paths", [])

    # --------------------------------------------------------
    # Persistence
    # --------------------------------------------------------
    def saveSettings(self):
        update_bookmarks = self._prepareBookmarksForPersist()
        self._finishBookmarkPersist(update_bookmarks)
        self._writeJson(self._settings_path, self._settings)
        self._backupConfigLocal()

    def saveState(self):
        update_bookmarks = self._prepareBookmarksForPersist()
        self._finishBookmarkPersist(update_bookmarks)
        self._writeJson(self._state_path, self._state)
        self._backupConfigLocal()

    def saveAll(self):
        update_bookmarks = self._prepareBookmarksForPersist()
        self._finishBookmarkPersist(update_bookmarks)
        self._writeJson(self._settings_path, self._settings)
        self._writeJson(self._state_path, self._state)
        self._backupConfigLocal()

    # --------------------------------------------------------
    # Method: buildProfileBundle
    # Purpose: Build a single-file dict with settings + bookmarks,
    #          libraries, panel state, filters, etc.
    # Input:  settings_override (dict|None) - optional settings
    #         snapshot (e.g. unsaved dialog values).
    # --------------------------------------------------------
    def buildProfileBundle(self, settings_override=None):
        settings = dict(self._settings)
        if settings_override:
            settings.update(settings_override)
        state = {}
        for key in PROFILE_STATE_KEYS:
            if key in self._state:
                state[key] = self._state[key]
        return {
            "format": PROFILE_FORMAT,
            "format_version": PROFILE_FORMAT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION,
            "settings": settings,
            "state": state,
        }

    # --------------------------------------------------------
    # Method: exportProfile
    # Purpose: Write a portable profile JSON (settings + state).
    # --------------------------------------------------------
    def exportProfile(self, path, settings_override=None):
        bundle = self.buildProfileBundle(settings_override=settings_override)
        self._writeJson(path, bundle)
        return path

    # --------------------------------------------------------
    # Method: importProfile
    # Purpose: Load a profile JSON and apply settings + state keys.
    # Output: dict summary {settings_count, state_keys}
    # --------------------------------------------------------
    def importProfile(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Profile file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Profile file must be a JSON object.")

        settings = data.get("settings")
        state = data.get("state")

        # Accept loose layouts: top-level settings-like keys, or our backup split files merged by user.
        if settings is None and state is None:
            if any(k in data for k in ("theme_mode", "font_size", "show_hidden_files")):
                settings = {
                    k: v
                    for k, v in data.items()
                    if k not in ("format", "format_version", "exported_at", "app_version", "state", "bookmarks", "libraries")
                }
            if "bookmarks" in data or "libraries" in data:
                state = {
                    k: data[k]
                    for k in PROFILE_STATE_KEYS
                    if k in data
                }

        if not isinstance(settings, dict) and not isinstance(state, dict):
            raise ValueError(
                "Unrecognized profile file. Expected a Total Commander Clone "
                "export with 'settings' and/or 'state'."
            )

        applied_settings = 0
        if isinstance(settings, dict):
            self._settings = self._deepMerge(DEFAULT_SETTINGS, settings)
            applied_settings = len(settings)

        applied_state_keys = []
        if isinstance(state, dict):
            for key in PROFILE_STATE_KEYS:
                if key not in state:
                    continue
                value = state[key]
                if key in ("left_panel", "right_panel", "sidebar_state", "folder_tags") and isinstance(value, dict):
                    defaults = DEFAULT_STATE.get(key, {})
                    self._state[key] = self._deepMerge(defaults, value) if isinstance(defaults, dict) else value
                else:
                    self._state[key] = value
                if key == "bookmarks":
                    self._bookmarks_dirty = True
                    self._bookmarks_explicit_clear = self._countBookmarks(value) == 0
                applied_state_keys.append(key)

        self.saveAll()
        return {
            "settings_count": applied_settings,
            "state_keys": applied_state_keys,
        }

    # --------------------------------------------------------
    # Method: _backupConfigLocal
    # Purpose: Write latest per-computer backups under the local
    #          user-data directory. Does not invoke Git.
    # --------------------------------------------------------
    def _backupConfigLocal(self):
        if not self._backup_enabled:
            return
        try:
            backupConfig(
                self._settings,
                self._state,
                allow_empty_bookmarks=self._bookmarks_explicit_clear,
            )
        except Exception as e:
            print(f"[SettingsManager] Config backup failed: {e}")

    # --------------------------------------------------------
    # Bookmark durability helpers
    # --------------------------------------------------------
    def _countBookmarks(self, structure):
        count = 0

        def walk(nodes):
            nonlocal count
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if node.get("type") == "group":
                    walk(node.get("children", []))
                elif node.get("type") == "bookmark" or "path" in node:
                    count += 1

        walk(structure)
        return count

    def _readBookmarksFromDisk(self):
        document = self._readBookmarkDocument(self._bookmarks_path)
        if document is not None:
            if document.get("corrupt"):
                return None
            return document["bookmarks"]
        return self._readLegacyStateBookmarks()

    def _readLegacyStateBookmarks(self):
        if not os.path.isfile(self._state_path):
            return None
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("bookmarks", [])
        if not isinstance(raw, list):
            return []
        return raw

    def _readBookmarkDocument(self, path):
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError, ValueError):
            return {"corrupt": True, "bookmarks": [], "explicit_empty": False}
        if isinstance(data, list):
            return {"bookmarks": data, "explicit_empty": False}
        if not isinstance(data, dict) or not isinstance(data.get("bookmarks"), list):
            return {"corrupt": True, "bookmarks": [], "explicit_empty": False}
        return {
            "bookmarks": data["bookmarks"],
            "explicit_empty": bool(data.get("explicit_empty", False)),
        }

    def _writeBookmarkStore(self, structure):
        structure = structure if isinstance(structure, list) else []
        payload = {
            "format": BOOKMARKS_FORMAT,
            "format_version": BOOKMARKS_FORMAT_VERSION,
            "explicit_empty": (
                self._bookmarks_explicit_clear and self._countBookmarks(structure) == 0
            ),
            "bookmarks": structure,
        }
        return self._writeJson(self._bookmarks_path, payload)

    def _finishBookmarkPersist(self, update_bookmarks):
        """Write bookmarks.json before state.json so a failed state save cannot drop the list."""
        if not update_bookmarks:
            return
        if self._writeBookmarkStore(self._state.get("bookmarks", [])):
            self._writeLastGood(self._state.get("bookmarks", []))
            self._bookmarks_dirty = False

    def _prepareBookmarksForPersist(self):
        """Keep on-disk bookmarks when this process did not edit them.

        Returns True when a user edit should refresh the last-good file.
        """
        disk = self._readBookmarksFromDisk()
        if not self._bookmarks_dirty:
            if disk is not None:
                self._state["bookmarks"] = disk
                if self._countBookmarks(disk) > 0:
                    self._bookmarks_explicit_clear = False
            return False
        memory_count = self._countBookmarks(self._state.get("bookmarks", []))
        disk_count = self._countBookmarks(disk) if isinstance(disk, list) else 0
        if memory_count == 0 and disk_count > 0 and not self._bookmarks_explicit_clear:
            self._state["bookmarks"] = disk
            self._bookmarks_dirty = False
            return False
        return True

    def _seedLastGoodIfMissing(self, data):
        """Remember a non-empty list once so a later empty file can be restored."""
        if os.path.isfile(self._last_good_bookmarks_path):
            return
        bookmarks = data.get("bookmarks", [])
        if self._countBookmarks(bookmarks) == 0:
            return
        self._writeLastGood(bookmarks)

    def _writeLastGood(self, structure):
        payload = {
            "bookmarks": structure if isinstance(structure, list) else [],
            "explicit_empty": (
                self._bookmarks_explicit_clear and self._countBookmarks(structure) == 0
            ),
        }
        self._writeJson(self._last_good_bookmarks_path, payload)

    def _readLastGood(self):
        path = self._last_good_bookmarks_path
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        if isinstance(data, list):
            return {"bookmarks": data, "explicit_empty": False}
        if not isinstance(data, dict):
            return None
        bookmarks = data.get("bookmarks", [])
        if not isinstance(bookmarks, list):
            bookmarks = []
        return {
            "bookmarks": bookmarks,
            "explicit_empty": bool(data.get("explicit_empty", False)),
        }

    def _restoreBookmarksIfNeeded(self, data, from_corrupt):
        if self._countBookmarks(data.get("bookmarks", [])) > 0:
            return False
        last = self._readLastGood()
        if not last or last.get("explicit_empty"):
            return False
        if self._countBookmarks(last.get("bookmarks", [])) == 0:
            return False
        data["bookmarks"] = last["bookmarks"]
        if from_corrupt:
            self._bookmark_recovery_notice = (
                "Bookmarks were restored from the last good copy "
                "because the bookmark file was unreadable."
            )
        else:
            self._bookmark_recovery_notice = (
                "Bookmarks were restored from the last good copy "
                "because the saved list was empty."
            )
        return True

    def _quarantineCorruptState(self, path):
        dest = path + ".corrupt"
        if os.path.exists(dest):
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            dest = f"{path}.corrupt.{stamp}"
        try:
            os.replace(path, dest)
        except OSError as e:
            print(f"[SettingsManager] Could not quarantine {path}: {e}")

    def _loadBookmarkFile(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Bookmark file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._coerceBookmarkList(data)

    def _normalizeBookmarkNodes(self, nodes):
        out = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            is_group = node.get("type") == "group" or (
                "children" in node and node.get("type") != "bookmark" and "path" not in node
            )
            if is_group:
                out.append({
                    "type": "group",
                    "name": node.get("name", ""),
                    "expanded": node.get("expanded", True),
                    "children": self._normalizeBookmarkNodes(node.get("children", [])),
                })
                continue
            if node.get("type") == "bookmark" or "path" in node:
                item = {
                    "type": "bookmark",
                    "name": node.get("name", ""),
                    "path": node.get("path", ""),
                }
                if node.get("kind"):
                    item["kind"] = node.get("kind")
                out.append(item)
        return out

    def _coerceBookmarkList(self, data):
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            raise ValueError("Bookmark file must be a JSON list or object.")
        if isinstance(data.get("bookmarks"), list):
            return data["bookmarks"]
        state = data.get("state")
        if isinstance(state, dict) and isinstance(state.get("bookmarks"), list):
            return state["bookmarks"]
        raise ValueError(
            "Unrecognized bookmark file. Expected a bookmark export with a 'bookmarks' list."
        )

    def _mergeBookmarkStructures(self, existing, imported):
        result = copy.deepcopy(existing or [])
        seen = set()

        def collect(nodes):
            for node in nodes or []:
                if not isinstance(node, dict):
                    continue
                if node.get("type") == "group":
                    collect(node.get("children", []))
                elif node.get("type") == "bookmark" or "path" in node:
                    seen.add(node.get("path", ""))

        def filter_new(nodes):
            out = []
            for node in nodes or []:
                if not isinstance(node, dict):
                    continue
                if node.get("type") == "group":
                    children = filter_new(node.get("children", []))
                    if children:
                        out.append({
                            "type": "group",
                            "name": node.get("name", ""),
                            "expanded": node.get("expanded", True),
                            "children": children,
                        })
                elif node.get("type") == "bookmark" or "path" in node:
                    path = node.get("path", "")
                    if path in seen:
                        continue
                    seen.add(path)
                    out.append(copy.deepcopy(node))
            return out

        collect(result)
        result.extend(filter_new(imported))
        return result

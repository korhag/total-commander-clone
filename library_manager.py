"""
Total Commander Clone - Library and Tag Manager
Handles library roots, portable marker files, folder tags,
and simple drive-aware root discovery for removable media.
"""

import ctypes
import json
import os
import string
import uuid


# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
LIBRARY_MARKER_FILENAME = ".tcc_library_root.json"
LIBRARY_MARKER_VERSION = 1


# ------------------------------------------------------------
# Helper: parse a tag into (category, value) pair.
# Tags using "category:value" format are split; plain tags
# return an empty category string.
# ------------------------------------------------------------
def parseTagCategory(tag):
    if ":" in tag:
        category, _, value = tag.partition(":")
        return (category.strip(), value.strip())
    return ("", tag.strip())


# ------------------------------------------------------------
# Helper: normalize a filesystem path for comparisons
# ------------------------------------------------------------
def normalizePath(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


# ------------------------------------------------------------
# Helper: safe common-path containment check
# ------------------------------------------------------------
def isPathInsideRoot(path, root_path):
    norm_path = normalizePath(path)
    norm_root = normalizePath(root_path)
    if not norm_path or not norm_root:
        return False
    try:
        return os.path.commonpath([norm_path, norm_root]) == norm_root
    except ValueError:
        return False


# ------------------------------------------------------------
# Helper: stable folder key inside a library root
# ------------------------------------------------------------
def buildFolderKey(library_id, root_id, relative_path):
    rel = relative_path.replace("\\", "/").strip("./")
    return f"{library_id}:{root_id}:{rel}"


# ------------------------------------------------------------
# Helper: set hidden attribute on Windows marker files
# ------------------------------------------------------------
def setHiddenFile(path):
    if os.name != "nt" or not path:
        return
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
    except Exception:
        pass


# ------------------------------------------------------------
# Helper: read a marker file from a candidate root folder
# ------------------------------------------------------------
def readLibraryMarker(root_path):
    marker_path = os.path.join(root_path, LIBRARY_MARKER_FILENAME)
    if not os.path.isfile(marker_path):
        return None
    try:
        with open(marker_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (IOError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


# ------------------------------------------------------------
# Helper: breadth-first directory scan for marker files
# ------------------------------------------------------------
def findMarkerDirectories(base_path, max_depth=2, max_directories=250):
    if not base_path or not os.path.isdir(base_path):
        return []

    results = []
    queue = [(base_path, 0)]
    seen = set()

    while queue and len(seen) < max_directories:
        current_path, depth = queue.pop(0)
        norm_current = normalizePath(current_path)
        if norm_current in seen:
            continue
        seen.add(norm_current)

        marker = readLibraryMarker(current_path)
        if marker:
            results.append((current_path, marker))

        if depth >= max_depth:
            continue

        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    name = entry.name
                    if name.startswith("$RECYCLE") or name in ("System Volume Information",):
                        continue
                    queue.append((entry.path, depth + 1))
        except OSError:
            continue

    return results


# ------------------------------------------------------------
# Class: LibraryManager
# Purpose: Encapsulates library persistence-friendly logic and
#          portable root discovery so UI code stays lightweight.
# ------------------------------------------------------------
class LibraryManager:

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, settings_manager):
        self._settings = settings_manager

    # --------------------------------------------------------
    # Method: getLibraries
    # --------------------------------------------------------
    def getLibraries(self):
        return self._settings.getLibraries()

    # --------------------------------------------------------
    # Method: getFolderTags
    # --------------------------------------------------------
    def getFolderTags(self):
        return self._settings.getFolderTags()

    # --------------------------------------------------------
    # Method: getSavedFilters
    # --------------------------------------------------------
    def getSavedFilters(self):
        return self._settings.getSavedLibraryFilters()

    # --------------------------------------------------------
    # Method: _saveLibraries / _saveFolderTags
    # Purpose: Store and write state.json right away so library
    #          and tag edits survive a crash before a clean exit.
    # --------------------------------------------------------
    def _saveLibraries(self, libraries):
        self._settings.setLibraries(libraries)
        self._settings.saveState()

    def _saveFolderTags(self, folder_tags):
        self._settings.setFolderTags(folder_tags)
        self._settings.saveState()

    # --------------------------------------------------------
    # Method: registerLibraryRoot
    # Purpose: Create or extend a library with a root folder and
    #          write the hidden marker used for drive discovery.
    # --------------------------------------------------------
    def registerLibraryRoot(self, library_name, root_path, root_name="", description=""):
        library_name = (library_name or "").strip()
        root_path = normalizePath(root_path)
        root_name = (root_name or "").strip()

        if not library_name or not root_path or not os.path.isdir(root_path):
            return None

        libraries = self.getLibraries()
        library = None
        for candidate in libraries:
            if candidate.get("name", "").strip().lower() == library_name.lower():
                library = candidate
                break

        if library is None:
            library = {
                "id": str(uuid.uuid4()),
                "name": library_name,
                "description": description or "",
                "roots": [],
            }
            libraries.append(library)
        elif description and not library.get("description"):
            library["description"] = description

        for existing_root in library.get("roots", []):
            existing_path = normalizePath(existing_root.get("path", ""))
            if existing_path == root_path:
                existing_root["is_available"] = True
                existing_root["last_seen_path"] = root_path
                self._saveLibraries(libraries)
                self._writeMarker(root_path, library, existing_root)
                return {
                    "library": library,
                    "root": existing_root,
                }

        root = {
            "id": str(uuid.uuid4()),
            "name": root_name or os.path.basename(root_path) or library_name,
            "path": root_path,
            "last_seen_path": root_path,
            "is_available": True,
        }
        library.setdefault("roots", []).append(root)
        self._saveLibraries(libraries)
        self._writeMarker(root_path, library, root)
        return {
            "library": library,
            "root": root,
        }

    # --------------------------------------------------------
    # Method: refreshLibraries
    # Purpose: Reconnect saved roots, update availability, and
    #          repair paths when marker files are rediscovered.
    # --------------------------------------------------------
    def refreshLibraries(self):
        libraries = self.getLibraries()
        discovered = self._discoverMarkers(libraries)

        for library in libraries:
            for root in library.get("roots", []):
                key = (library.get("id", ""), root.get("id", ""))
                resolved_path = discovered.get(key, "")
                root["is_available"] = bool(resolved_path and os.path.isdir(resolved_path))
                if resolved_path:
                    root["path"] = resolved_path
                    root["last_seen_path"] = resolved_path

        self._saveLibraries(libraries)
        self._refreshResolvedFolderPaths()
        return libraries

    # --------------------------------------------------------
    # Method: assignTagsToFolder
    # Purpose: Save library-aware tags for a folder path.
    # --------------------------------------------------------
    def assignTagsToFolder(self, folder_path, tags, note=""):
        context = self.resolveFolderContext(folder_path)
        if context is None:
            return None

        cleaned_tags = []
        seen = set()
        for tag in tags:
            value = (tag or "").strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned_tags.append(value)

        key = context["folder_key"]
        folder_tags = self.getFolderTags()
        if not cleaned_tags and not (note or "").strip():
            folder_tags.pop(key, None)
            self._saveFolderTags(folder_tags)
            return None

        folder_tags[key] = {
            "library_id": context["library"]["id"],
            "root_id": context["root"]["id"],
            "relative_path": context["relative_path"],
            "resolved_path": normalizePath(folder_path),
            "tags": cleaned_tags,
            "note": (note or "").strip(),
        }
        self._saveFolderTags(folder_tags)
        return folder_tags[key]

    # --------------------------------------------------------
    # Method: getFolderRecordForPath
    # --------------------------------------------------------
    def getFolderRecordForPath(self, folder_path):
        context = self.resolveFolderContext(folder_path)
        if context is None:
            return None
        return self.getFolderTags().get(context["folder_key"])

    # --------------------------------------------------------
    # Method: resolveFolderContext
    # Purpose: Find the best matching library root for a folder.
    # --------------------------------------------------------
    def resolveFolderContext(self, folder_path):
        folder_path = normalizePath(folder_path)
        if not folder_path or not os.path.isdir(folder_path):
            return None

        best_match = None
        for library in self.getLibraries():
            for root in library.get("roots", []):
                root_path = normalizePath(root.get("path", ""))
                if not root_path or not os.path.isdir(root_path):
                    continue
                if not isPathInsideRoot(folder_path, root_path):
                    continue

                rel_path = os.path.relpath(folder_path, root_path)
                if rel_path == ".":
                    rel_path = ""

                candidate = {
                    "library": library,
                    "root": root,
                    "relative_path": rel_path,
                    "folder_key": buildFolderKey(library["id"], root["id"], rel_path),
                    "matched_root_length": len(root_path),
                }
                if best_match is None or candidate["matched_root_length"] > best_match["matched_root_length"]:
                    best_match = candidate

        return best_match

    # --------------------------------------------------------
    # Method: getAvailableTags
    # --------------------------------------------------------
    def getAvailableTags(self, library_id=""):
        tags = set()
        for record in self.getFolderTags().values():
            if library_id and record.get("library_id") != library_id:
                continue
            for tag in record.get("tags", []):
                if tag:
                    tags.add(tag)
        return sorted(tags, key=lambda value: value.lower())

    # --------------------------------------------------------
    # Method: getTaggedFolders
    # Purpose: Return library-aware tagged folder records that
    #          the Libraries UI can filter and display.
    # --------------------------------------------------------
    def getTaggedFolders(self, library_id="", selected_tags=None):
        selected_tags = selected_tags or []
        selected = {tag.lower() for tag in selected_tags if tag}
        libraries_by_id = {lib.get("id", ""): lib for lib in self.getLibraries()}
        roots_by_key = {}
        for library in self.getLibraries():
            for root in library.get("roots", []):
                roots_by_key[(library.get("id", ""), root.get("id", ""))] = root

        results = []
        for record in self.getFolderTags().values():
            if library_id and record.get("library_id") != library_id:
                continue

            record_tags = [tag for tag in record.get("tags", []) if tag]
            lowered_tags = {tag.lower() for tag in record_tags}
            if selected and not selected.issubset(lowered_tags):
                continue

            library = libraries_by_id.get(record.get("library_id", ""))
            root = roots_by_key.get((record.get("library_id", ""), record.get("root_id", "")))
            if not library or not root:
                continue

            root_path = normalizePath(root.get("path", ""))
            rel_path = record.get("relative_path", "")
            resolved_path = root_path
            if rel_path:
                resolved_path = normalizePath(os.path.join(root_path, rel_path))

            display_name = os.path.basename(resolved_path) or library.get("name", "Folder")
            results.append({
                "display_name": display_name,
                "library_id": library.get("id", ""),
                "library_name": library.get("name", ""),
                "root_id": root.get("id", ""),
                "root_name": root.get("name", ""),
                "relative_path": rel_path,
                "resolved_path": resolved_path,
                "is_available": bool(root.get("is_available")) and os.path.isdir(resolved_path),
                "tags": record_tags,
                "note": record.get("note", ""),
            })

        results.sort(key=lambda item: (item["library_name"].lower(), item["display_name"].lower()))
        return results

    # --------------------------------------------------------
    # Method: findFirstAvailableRootPath
    # --------------------------------------------------------
    def findFirstAvailableRootPath(self, library_id):
        for library in self.getLibraries():
            if library.get("id") != library_id:
                continue
            for root in library.get("roots", []):
                root_path = normalizePath(root.get("path", ""))
                if root_path and os.path.isdir(root_path):
                    return root_path
        return ""

    # --------------------------------------------------------
    # Internal: write marker file to a root
    # --------------------------------------------------------
    def _writeMarker(self, root_path, library, root):
        marker_path = os.path.join(root_path, LIBRARY_MARKER_FILENAME)
        data = {
            "version": LIBRARY_MARKER_VERSION,
            "library_id": library.get("id", ""),
            "library_name": library.get("name", ""),
            "root_id": root.get("id", ""),
            "root_name": root.get("name", ""),
        }
        try:
            with open(marker_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4, ensure_ascii=False)
            setHiddenFile(marker_path)
        except IOError:
            return False
        return True

    # --------------------------------------------------------
    # Internal: reconcile tagged folder paths after root changes
    # --------------------------------------------------------
    def _refreshResolvedFolderPaths(self):
        folder_tags = self.getFolderTags()
        libraries = self.getLibraries()
        roots_by_key = {}
        for library in libraries:
            for root in library.get("roots", []):
                roots_by_key[(library.get("id", ""), root.get("id", ""))] = root

        for key, record in folder_tags.items():
            root = roots_by_key.get((record.get("library_id", ""), record.get("root_id", "")))
            if root is None:
                continue
            root_path = normalizePath(root.get("path", ""))
            rel_path = record.get("relative_path", "")
            resolved_path = root_path
            if rel_path:
                resolved_path = normalizePath(os.path.join(root_path, rel_path))
            record["resolved_path"] = resolved_path

        self._saveFolderTags(folder_tags)

    # --------------------------------------------------------
    # Internal: discover roots by saved path and marker scans
    # --------------------------------------------------------
    def _discoverMarkers(self, libraries):
        discovered = {}
        missing_keys = set()

        for library in libraries:
            for root in library.get("roots", []):
                key = (library.get("id", ""), root.get("id", ""))
                root_path = normalizePath(root.get("path", ""))
                marker = readLibraryMarker(root_path) if root_path and os.path.isdir(root_path) else None
                if marker and marker.get("library_id") == key[0] and marker.get("root_id") == key[1]:
                    discovered[key] = root_path
                else:
                    missing_keys.add(key)

        if not missing_keys:
            return discovered

        for base_path in self._candidateScanBases():
            for candidate_path, marker in findMarkerDirectories(base_path):
                key = (marker.get("library_id", ""), marker.get("root_id", ""))
                if key in missing_keys:
                    discovered[key] = normalizePath(candidate_path)
                    missing_keys.remove(key)
                if not missing_keys:
                    return discovered

        return discovered

    # --------------------------------------------------------
    # Internal: candidate roots for removable-drive scans
    # --------------------------------------------------------
    def _candidateScanBases(self):
        bases = []
        if os.name == "nt":
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.isdir(drive):
                    bases.append(drive)
        else:
            for candidate in ("/Volumes", "/media", "/mnt", "/"):
                if os.path.isdir(candidate):
                    bases.append(candidate)
        return bases

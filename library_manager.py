"""
Total Commander Clone - Library Manager
Handles libraries, their roots, named fields, and the folder values
used to filter the active library. A hidden marker in each root lets
the same folder be found again when a drive letter or mount point changes.
"""

import json
import os
import string
import unicodedata
import uuid
from datetime import datetime, timezone

from app_version import APP_VERSION


# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
LIBRARY_MARKER_FILENAME = ".tcc_library_root.json"
LIBRARY_MARKER_VERSION = 1
LIBRARY_FILE_FORMAT = "tcc-library"
LIBRARY_FILE_VERSION = 1


# ------------------------------------------------------------
# Function: foldText
# Purpose: Compare and search text so Turkish letters match.
#          "İstanbul" matches "istanbul", and "IŞIK" matches "ışık".
#          The stored spelling is never changed.
# ------------------------------------------------------------
def foldText(text):
    if text is None:
        return ""
    folded = unicodedata.normalize("NFC", str(text))
    folded = folded.replace("İ", "i").replace("I", "i").replace("ı", "i")
    return folded.casefold()


# ------------------------------------------------------------
# Function: normalizePath
# Purpose: One comparable form of a filesystem path.
# ------------------------------------------------------------
def normalizePath(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


# ------------------------------------------------------------
# Function: isPathInsideRoot
# Purpose: True when path is the root or a folder inside it.
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
# Function: storeRelativePath
# Purpose: Store a folder's place inside a root with "/" so a
#          library file works on Windows and Linux.
# ------------------------------------------------------------
def storeRelativePath(relative_path):
    rel = (relative_path or "").replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.strip("/")
    if rel == ".":
        return ""
    return rel


# ------------------------------------------------------------
# Function: buildFolderKey
# Purpose: Stable key for one folder inside one library root.
# ------------------------------------------------------------
def buildFolderKey(library_id, root_id, relative_path):
    return f"{library_id}:{root_id}:{storeRelativePath(relative_path)}"


# ------------------------------------------------------------
# Function: joinRoot
# Purpose: Build an absolute folder path from a root and a
#          stored relative path.
# ------------------------------------------------------------
def joinRoot(root_path, relative_path):
    rel = storeRelativePath(relative_path)
    if not root_path:
        return ""
    if not rel:
        return normalizePath(root_path)
    return normalizePath(os.path.join(root_path, *rel.split("/")))


# ------------------------------------------------------------
# Function: matchesFolderFilters
# Purpose: Several terms in one field match when any term is
#          found inside any value. Several fields match only
#          when every field matches.
# ------------------------------------------------------------
def matchesFolderFilters(field_map, filters):
    for field_id, terms in (filters or {}).items():
        usable = [term for term in (terms or []) if str(term).strip()]
        if not usable:
            continue
        values = (field_map or {}).get(field_id, [])
        if not any(_termMatchesAny(term, values) for term in usable):
            return False
    return True


# ------------------------------------------------------------
# Function: _termMatchesAny
# Purpose: True when the folded term is part of any value.
# ------------------------------------------------------------
def _termMatchesAny(term, values):
    needle = foldText(term)
    if not needle:
        return False
    return any(needle in foldText(value) for value in values)


# ------------------------------------------------------------
# Function: _cleanValues
# Purpose: Trim values, drop blanks, and keep the first spelling
#          when two values match under foldText.
# ------------------------------------------------------------
def _cleanValues(values):
    cleaned = []
    seen = set()
    for raw in values or []:
        value = str(raw).strip()
        if not value:
            continue
        key = foldText(value)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


# ------------------------------------------------------------
# Function: setHiddenFile
# Purpose: Mark a marker file hidden on Windows.
# ------------------------------------------------------------
def setHiddenFile(path):
    if os.name != "nt" or not path:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
    except Exception:
        pass


# ------------------------------------------------------------
# Function: readLibraryMarker
# Purpose: Read the marker file from a candidate root folder.
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
# Function: findMarkerDirectories
# Purpose: Breadth-first search for marker files under a base path.
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
# Purpose: Save libraries, roots, fields, and folder values, and
#          find roots again from their marker files.
# ------------------------------------------------------------
class LibraryManager:

    # --------------------------------------------------------
    # Method: __init__
    # Purpose: Keep a settings store and turn old tags into fields.
    # --------------------------------------------------------
    def __init__(self, settings_manager):
        self._settings = settings_manager
        self._migrateLegacyTags()

    # --------------------------------------------------------
    # Method: getLibraries
    # --------------------------------------------------------
    def getLibraries(self):
        return self._settings.getLibraries()

    # --------------------------------------------------------
    # Method: getFolderTags
    # Purpose: Folder records still live under this settings key.
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
    #          edits survive a crash before a clean exit.
    # --------------------------------------------------------
    def _saveLibraries(self, libraries):
        self._settings.setLibraries(libraries)
        self._settings.saveState()

    def _saveFolderTags(self, folder_tags):
        self._settings.setFolderTags(folder_tags)
        self._settings.saveState()

    # --------------------------------------------------------
    # Method: createLibrary
    # Purpose: Add an empty library. Roots and fields come later.
    # --------------------------------------------------------
    def createLibrary(self, name, description=""):
        name = (name or "").strip()
        if not name:
            return None
        libraries = self.getLibraries()
        library = {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": description or "",
            "roots": [],
            "fields": [],
        }
        libraries.append(library)
        self._saveLibraries(libraries)
        return library

    # --------------------------------------------------------
    # Method: renameLibrary
    # --------------------------------------------------------
    def renameLibrary(self, library_id, name):
        name = (name or "").strip()
        if not library_id or not name:
            return None
        library = self._findLibrary(library_id)
        if library is None:
            return None
        library["name"] = name
        self._saveLibraries(self.getLibraries())
        self._rewriteMarkers(library)
        return library

    # --------------------------------------------------------
    # Method: deleteLibrary
    # Purpose: Remove the library and every folder value in it.
    #          Marker files stay, so an imported copy can find
    #          the same roots.
    # --------------------------------------------------------
    def deleteLibrary(self, library_id):
        libraries = self.getLibraries()
        kept = [library for library in libraries if library.get("id") != library_id]
        if len(kept) == len(libraries):
            return False
        self._saveLibraries(kept)
        folder_tags = self.getFolderTags()
        removed = False
        for key, record in list(folder_tags.items()):
            if isinstance(record, dict) and record.get("library_id") == library_id:
                folder_tags.pop(key, None)
                removed = True
        if removed:
            self._saveFolderTags(folder_tags)
        return True

    # --------------------------------------------------------
    # Method: addRoot
    # Purpose: Attach a folder to an existing library and write
    #          the marker used to find it later.
    # --------------------------------------------------------
    def addRoot(self, library_id, root_path, root_name=""):
        root_path = normalizePath(root_path)
        if not library_id or not root_path or not os.path.isdir(root_path):
            return None
        library = self._findLibrary(library_id)
        if library is None:
            return None

        root_name = (root_name or "").strip()
        for existing in library.get("roots", []):
            if normalizePath(existing.get("path", "")) == root_path:
                existing["is_available"] = True
                existing["last_seen_path"] = root_path
                if root_name:
                    existing["name"] = root_name
                self._saveLibraries(self.getLibraries())
                self._writeMarker(root_path, library, existing)
                return {"library": library, "root": existing}

        root = {
            "id": str(uuid.uuid4()),
            "name": root_name or os.path.basename(root_path) or library.get("name", "Root"),
            "path": root_path,
            "last_seen_path": root_path,
            "is_available": True,
        }
        library.setdefault("roots", []).append(root)
        self._saveLibraries(self.getLibraries())
        self._writeMarker(root_path, library, root)
        return {"library": library, "root": root}

    # --------------------------------------------------------
    # Method: registerLibraryRoot
    # Purpose: Create the named library when it is missing, then
    #          add the root. Kept for callers that still pass a name.
    # --------------------------------------------------------
    def registerLibraryRoot(self, library_name, root_path, root_name="", description=""):
        library_name = (library_name or "").strip()
        root_path = normalizePath(root_path)
        if not library_name or not root_path or not os.path.isdir(root_path):
            return None

        folded = foldText(library_name)
        library = None
        for candidate in self.getLibraries():
            if foldText(candidate.get("name", "")) == folded:
                library = candidate
                break
        if library is None:
            library = self.createLibrary(library_name, description=description)
        elif description and not library.get("description"):
            library["description"] = description
            self._saveLibraries(self.getLibraries())
        if library is None:
            return None
        library.setdefault("fields", [])
        return self.addRoot(library.get("id", ""), root_path, root_name=root_name)

    # --------------------------------------------------------
    # Method: renameRoot
    # --------------------------------------------------------
    def renameRoot(self, library_id, root_id, name):
        name = (name or "").strip()
        if not name:
            return None
        library = self._findLibrary(library_id)
        root = self._findRoot(library, root_id)
        if root is None:
            return None
        root["name"] = name
        self._saveLibraries(self.getLibraries())
        if root.get("path") and os.path.isdir(root.get("path", "")):
            self._writeMarker(root["path"], library, root)
        return root

    # --------------------------------------------------------
    # Method: removeRoot
    # Purpose: Drop the root and its folder values. The folder
    #          on disk is left alone, including its marker.
    # --------------------------------------------------------
    def removeRoot(self, library_id, root_id):
        library = self._findLibrary(library_id)
        if library is None:
            return False
        roots = library.get("roots", [])
        kept = [root for root in roots if root.get("id") != root_id]
        if len(kept) == len(roots):
            return False
        library["roots"] = kept
        self._saveLibraries(self.getLibraries())
        folder_tags = self.getFolderTags()
        removed = False
        for key, record in list(folder_tags.items()):
            if not isinstance(record, dict):
                continue
            if record.get("library_id") == library_id and record.get("root_id") == root_id:
                folder_tags.pop(key, None)
                removed = True
        if removed:
            self._saveFolderTags(folder_tags)
        return True

    # --------------------------------------------------------
    # Method: locateRoot
    # Purpose: Point an offline root at a folder on this computer
    #          and rewrite its marker there.
    # --------------------------------------------------------
    def locateRoot(self, library_id, root_id, new_path):
        new_path = normalizePath(new_path)
        if not new_path or not os.path.isdir(new_path):
            return None
        library = self._findLibrary(library_id)
        root = self._findRoot(library, root_id)
        if root is None:
            return None
        for other in library.get("roots", []):
            if other.get("id") != root_id and normalizePath(other.get("path", "")) == new_path:
                return None

        old_path = normalizePath(root.get("path", ""))
        if old_path and old_path != new_path:
            self._removeMarkerIfMatch(old_path, library_id, root_id)
        root["path"] = new_path
        root["last_seen_path"] = new_path
        root["is_available"] = True
        self._saveLibraries(self.getLibraries())
        self._writeMarker(new_path, library, root)
        self._refreshResolvedFolderPaths()
        return root

    # --------------------------------------------------------
    # Method: getFields
    # --------------------------------------------------------
    def getFields(self, library_id):
        library = self._findLibrary(library_id)
        if library is None:
            return []
        return [dict(field) for field in library.get("fields", []) if field.get("id")]

    # --------------------------------------------------------
    # Method: createField
    # Purpose: Add a field, or return the one that already has
    #          this name under Turkish-aware comparison.
    # --------------------------------------------------------
    def createField(self, library_id, name):
        name = (name or "").strip()
        if not library_id or not name:
            return None
        library = self._findLibrary(library_id)
        if library is None:
            return None
        field = self._ensureField(library, name)
        self._saveLibraries(self.getLibraries())
        return dict(field)

    # --------------------------------------------------------
    # Method: renameField
    # Purpose: Rename a field. Returns None when another field
    #          in the library already uses that name.
    # --------------------------------------------------------
    def renameField(self, library_id, field_id, name):
        name = (name or "").strip()
        if not name:
            return None
        library = self._findLibrary(library_id)
        if library is None:
            return None
        folded = foldText(name)
        target = None
        for field in library.get("fields", []):
            if field.get("id") == field_id:
                target = field
                continue
            if foldText(field.get("name", "")) == folded:
                return None
        if target is None:
            return None
        target["name"] = name
        self._saveLibraries(self.getLibraries())
        return dict(target)

    # --------------------------------------------------------
    # Method: deleteField
    # Purpose: Remove the field from the library and from every
    #          folder that used it.
    # --------------------------------------------------------
    def deleteField(self, library_id, field_id):
        library = self._findLibrary(library_id)
        if library is None or not field_id:
            return False
        fields = library.get("fields", [])
        kept = [field for field in fields if field.get("id") != field_id]
        if len(kept) == len(fields):
            return False
        library["fields"] = kept
        self._saveLibraries(self.getLibraries())

        folder_tags = self.getFolderTags()
        changed = False
        for key, record in list(folder_tags.items()):
            if not isinstance(record, dict) or record.get("library_id") != library_id:
                continue
            values = record.get("fields") or {}
            if field_id in values:
                values.pop(field_id, None)
                record["fields"] = values
                changed = True
            if not self._recordHasValues(record):
                folder_tags.pop(key, None)
                changed = True
        if changed:
            self._saveFolderTags(folder_tags)
        return True

    # --------------------------------------------------------
    # Method: getFieldValues
    # Purpose: Distinct values already used for one field, in
    #          their stored spelling.
    # --------------------------------------------------------
    def getFieldValues(self, library_id, field_id):
        seen = {}
        for record in self.getFolderTags().values():
            if not isinstance(record, dict) or record.get("library_id") != library_id:
                continue
            for value in (record.get("fields") or {}).get(field_id, []):
                key = foldText(value)
                if key and key not in seen:
                    seen[key] = value
        return sorted(seen.values(), key=foldText)

    # --------------------------------------------------------
    # Method: setFolderFields
    # Purpose: Save field values for a folder inside the given
    #          library. An empty set removes the folder record.
    # --------------------------------------------------------
    def setFolderFields(self, folder_path, library_id, fields, note=None):
        context = self.resolveFolderContext(folder_path, library_id)
        if context is None:
            return None

        allowed = {field.get("id") for field in context["library"].get("fields", [])}
        cleaned = {}
        for field_id, values in (fields or {}).items():
            if field_id not in allowed:
                continue
            kept = _cleanValues(values)
            if kept:
                cleaned[field_id] = kept

        key = context["folder_key"]
        folder_tags = self.getFolderTags()
        existing = folder_tags.get(key) if isinstance(folder_tags.get(key), dict) else {}
        kept_note = existing.get("note", "") if note is None else (note or "").strip()
        if not cleaned and not kept_note:
            if key in folder_tags:
                folder_tags.pop(key, None)
                self._saveFolderTags(folder_tags)
            return None

        folder_tags[key] = {
            "library_id": context["library"]["id"],
            "root_id": context["root"]["id"],
            "relative_path": storeRelativePath(context["relative_path"]),
            "resolved_path": normalizePath(folder_path),
            "fields": cleaned,
            "note": kept_note,
        }
        self._saveFolderTags(folder_tags)
        return folder_tags[key]

    # --------------------------------------------------------
    # Method: getFolderRecordForPath
    # --------------------------------------------------------
    def getFolderRecordForPath(self, folder_path, library_id=""):
        context = self.resolveFolderContext(folder_path, library_id)
        if context is None:
            return None
        record = self.getFolderTags().get(context["folder_key"])
        if not isinstance(record, dict):
            return None
        return record

    # --------------------------------------------------------
    # Method: resolveFolderContext
    # Purpose: Find the library root that contains this folder.
    #          When a library id is given, only that library matches.
    # --------------------------------------------------------
    def resolveFolderContext(self, folder_path, library_id=""):
        folder_path = normalizePath(folder_path)
        if not folder_path or not os.path.isdir(folder_path):
            return None

        matches = []
        for library in self.getLibraries():
            if library_id and library.get("id") != library_id:
                continue
            for root in library.get("roots", []):
                root_path = normalizePath(root.get("path", ""))
                if not root_path or not os.path.isdir(root_path):
                    continue
                if not isPathInsideRoot(folder_path, root_path):
                    continue
                rel_path = storeRelativePath(os.path.relpath(folder_path, root_path))
                matches.append({
                    "library": library,
                    "root": root,
                    "relative_path": rel_path,
                    "folder_key": buildFolderKey(library.get("id", ""), root.get("id", ""), rel_path),
                    "matched_root_length": len(root_path),
                })

        if not matches:
            return None
        return max(matches, key=lambda item: item["matched_root_length"])

    # --------------------------------------------------------
    # Method: findFolders
    # Purpose: Folders in one library that match the field filters.
    #          No filters returns every folder that has values.
    # --------------------------------------------------------
    def findFolders(self, library_id="", filters=None):
        active = {}
        for field_id, terms in (filters or {}).items():
            usable = [term for term in (terms or []) if str(term).strip()]
            if usable:
                active[field_id] = usable

        libraries_by_id = {library.get("id", ""): library for library in self.getLibraries()}
        roots_by_key = {}
        for library in self.getLibraries():
            for root in library.get("roots", []):
                roots_by_key[(library.get("id", ""), root.get("id", ""))] = root

        results = []
        for record in self.getFolderTags().values():
            if not isinstance(record, dict):
                continue
            if library_id and record.get("library_id") != library_id:
                continue
            field_map = record.get("fields") or {}
            if not isinstance(field_map, dict):
                field_map = {}
            if not matchesFolderFilters(field_map, active):
                continue

            library = libraries_by_id.get(record.get("library_id", ""))
            root = roots_by_key.get((record.get("library_id", ""), record.get("root_id", "")))
            if not library or not root:
                continue

            rel_path = storeRelativePath(record.get("relative_path", ""))
            root_path = normalizePath(root.get("path", "")) if root.get("is_available") else ""
            resolved_path = joinRoot(root_path, rel_path) if root_path else ""
            available = bool(root_path) and os.path.isdir(resolved_path or root_path)
            display_name = os.path.basename(resolved_path or rel_path) or library.get("name", "Folder")

            field_defs = {field.get("id"): field for field in library.get("fields", [])}
            field_rows = []
            for field_id, values in field_map.items():
                field = field_defs.get(field_id)
                if not field:
                    continue
                field_rows.append({
                    "id": field_id,
                    "name": field.get("name", ""),
                    "values": list(values),
                })
            field_rows.sort(key=lambda row: foldText(row["name"]))

            results.append({
                "display_name": display_name,
                "library_id": library.get("id", ""),
                "library_name": library.get("name", ""),
                "root_id": root.get("id", ""),
                "root_name": root.get("name", ""),
                "relative_path": rel_path,
                "resolved_path": resolved_path,
                "is_available": available,
                "fields": field_rows,
                "field_map": {field_id: list(values) for field_id, values in field_map.items()},
                "note": record.get("note", ""),
            })

        results.sort(key=lambda item: (
            foldText(item["root_name"]),
            foldText(item["display_name"]),
            foldText(item["relative_path"]),
        ))
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
    # Method: exportLibrary
    # Purpose: Write one library file. Roots keep a hint path,
    #          and folder places are stored relative to the root.
    # --------------------------------------------------------
    def exportLibrary(self, library_id, path):
        library = self._findLibrary(library_id)
        if library is None or not path:
            return False
        folders = []
        for record in self.getFolderTags().values():
            if not isinstance(record, dict) or record.get("library_id") != library_id:
                continue
            folders.append({
                "root_id": record.get("root_id", ""),
                "relative_path": storeRelativePath(record.get("relative_path", "")),
                "fields": record.get("fields") or {},
                "note": record.get("note", ""),
            })
        payload = {
            "format": LIBRARY_FILE_FORMAT,
            "format_version": LIBRARY_FILE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION,
            "library": {
                "id": library.get("id", ""),
                "name": library.get("name", ""),
                "description": library.get("description", ""),
                "fields": [
                    {"id": field.get("id", ""), "name": field.get("name", "")}
                    for field in library.get("fields", [])
                ],
                "roots": [
                    {
                        "id": root.get("id", ""),
                        "name": root.get("name", ""),
                        "hint_path": root.get("last_seen_path") or root.get("path") or "",
                    }
                    for root in library.get("roots", [])
                ],
            },
            "folders": folders,
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=4, ensure_ascii=False)
        except OSError:
            return False
        return True

    # --------------------------------------------------------
    # Method: importLibrary
    # Purpose: Add a library from a file. When the same library
    #          is already stored, replace must be True or the
    #          call reports a conflict and changes nothing.
    #          After a successful import, roots are scanned.
    # --------------------------------------------------------
    def importLibrary(self, path, replace=False):
        data = self._readLibraryExport(path)
        if data is None:
            return None
        incoming = data["library"]
        library_id = incoming.get("id") or ""
        name = (incoming.get("name") or "").strip()
        if not library_id or not name:
            return None

        exists = self._findLibrary(library_id) is not None
        if exists and not replace:
            return {
                "conflict": True,
                "library_id": library_id,
                "name": name,
            }

        libraries = [library for library in self.getLibraries() if library.get("id") != library_id]
        folder_tags = self.getFolderTags()
        if exists:
            for key, record in list(folder_tags.items()):
                if isinstance(record, dict) and record.get("library_id") == library_id:
                    folder_tags.pop(key, None)

        roots = []
        for root in incoming.get("roots") or []:
            root_id = root.get("id") or str(uuid.uuid4())
            hint = root.get("hint_path") or ""
            hint_norm = normalizePath(hint) if hint else ""
            available = False
            path_now = ""
            if hint_norm and os.path.isdir(hint_norm):
                marker = readLibraryMarker(hint_norm)
                if (
                    marker
                    and marker.get("library_id") == library_id
                    and marker.get("root_id") == root_id
                ):
                    available = True
                    path_now = hint_norm
            roots.append({
                "id": root_id,
                "name": (root.get("name") or "").strip() or "Root",
                "path": path_now,
                "last_seen_path": hint_norm,
                "is_available": available,
            })

        fields = []
        seen_names = set()
        for field in incoming.get("fields") or []:
            field_name = (field.get("name") or "").strip()
            if not field_name:
                continue
            folded = foldText(field_name)
            if folded in seen_names:
                continue
            seen_names.add(folded)
            fields.append({
                "id": field.get("id") or str(uuid.uuid4()),
                "name": field_name,
            })

        library = {
            "id": library_id,
            "name": name,
            "description": incoming.get("description") or "",
            "fields": fields,
            "roots": roots,
        }
        libraries.append(library)
        self._saveLibraries(libraries)

        allowed = {field["id"] for field in fields}
        root_ids = {root["id"] for root in roots}
        roots_by_id = {root["id"]: root for root in roots}
        for folder in data.get("folders") or []:
            if not isinstance(folder, dict):
                continue
            root_id = folder.get("root_id", "")
            if root_id not in root_ids:
                continue
            cleaned = {}
            for field_id, values in (folder.get("fields") or {}).items():
                if field_id not in allowed:
                    continue
                kept = _cleanValues(values if isinstance(values, list) else [])
                if kept:
                    cleaned[field_id] = kept
            rel = storeRelativePath(folder.get("relative_path", ""))
            note = (folder.get("note") or "").strip()
            if not cleaned and not note:
                continue
            root = roots_by_id[root_id]
            resolved = ""
            if root.get("is_available") and root.get("path"):
                resolved = joinRoot(root["path"], rel)
            folder_tags[buildFolderKey(library_id, root_id, rel)] = {
                "library_id": library_id,
                "root_id": root_id,
                "relative_path": rel,
                "resolved_path": resolved,
                "fields": cleaned,
                "note": note,
            }
        self._saveFolderTags(folder_tags)
        self.refreshLibraries()
        restored = self._findLibrary(library_id)
        return {
            "conflict": False,
            "library": restored or library,
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
    # Internal: find a library or root in the saved list
    # --------------------------------------------------------
    def _findLibrary(self, library_id):
        if not library_id:
            return None
        for library in self.getLibraries():
            if library.get("id") == library_id:
                return library
        return None

    def _findRoot(self, library, root_id):
        if library is None or not root_id:
            return None
        for root in library.get("roots", []):
            if root.get("id") == root_id:
                return root
        return None

    # --------------------------------------------------------
    # Internal: add a field or return the one with the same name
    # --------------------------------------------------------
    def _ensureField(self, library, name):
        name = (name or "").strip()
        folded = foldText(name)
        fields = library.setdefault("fields", [])
        for field in fields:
            if foldText(field.get("name", "")) == folded:
                return field
        field = {"id": str(uuid.uuid4()), "name": name}
        fields.append(field)
        return field

    def _recordHasValues(self, record):
        for values in (record.get("fields") or {}).values():
            if _cleanValues(values if isinstance(values, list) else []):
                return True
        return bool((record.get("note") or "").strip())

    # --------------------------------------------------------
    # Internal: turn "category:value" tags into fields once
    # --------------------------------------------------------
    def _migrateLegacyTags(self):
        libraries = self.getLibraries()
        folder_tags = self.getFolderTags()
        libraries_by_id = {}
        libraries_changed = False
        for library in libraries:
            if not isinstance(library, dict):
                continue
            libraries_by_id[library.get("id", "")] = library
            if not isinstance(library.get("fields"), list):
                library["fields"] = []
                libraries_changed = True
            if not isinstance(library.get("roots"), list):
                library["roots"] = []
                libraries_changed = True

        migrated = {}
        tags_changed = False
        for key, record in folder_tags.items():
            if not isinstance(record, dict):
                migrated[key] = record
                continue
            rel = storeRelativePath(record.get("relative_path", ""))
            if record.get("relative_path", "") != rel:
                record["relative_path"] = rel
                tags_changed = True

            tags = record.get("tags")
            if isinstance(tags, list):
                library = libraries_by_id.get(record.get("library_id", ""))
                field_map = record.get("fields") if isinstance(record.get("fields"), dict) else {}
                if library is not None:
                    for tag in tags:
                        text = (tag or "").strip()
                        if not text:
                            continue
                        if ":" in text:
                            field_name, _, value = text.partition(":")
                            field_name = field_name.strip() or "Tag"
                            value = value.strip()
                        else:
                            field_name, value = "Tag", text
                        if not value:
                            continue
                        field = self._ensureField(library, field_name)
                        libraries_changed = True
                        values = field_map.setdefault(field["id"], [])
                        if foldText(value) not in {foldText(item) for item in values}:
                            values.append(value)
                    record["fields"] = field_map
                    record.pop("tags", None)
                    tags_changed = True
            elif not isinstance(record.get("fields"), dict):
                record["fields"] = {}
                tags_changed = True

            new_key = buildFolderKey(
                record.get("library_id", ""),
                record.get("root_id", ""),
                record.get("relative_path", ""),
            )
            if new_key != key:
                tags_changed = True
            migrated[new_key] = record

        if libraries_changed:
            self._saveLibraries(libraries)
        if tags_changed or migrated.keys() != folder_tags.keys():
            self._saveFolderTags(migrated)

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
        except OSError:
            return False
        return True

    def _rewriteMarkers(self, library):
        for root in library.get("roots", []):
            root_path = root.get("path", "")
            if root_path and os.path.isdir(root_path):
                self._writeMarker(root_path, library, root)

    def _removeMarkerIfMatch(self, root_path, library_id, root_id):
        if not root_path or not os.path.isdir(root_path):
            return
        marker = readLibraryMarker(root_path)
        if not marker:
            return
        if marker.get("library_id") != library_id or marker.get("root_id") != root_id:
            return
        try:
            os.remove(os.path.join(root_path, LIBRARY_MARKER_FILENAME))
        except OSError:
            pass

    # --------------------------------------------------------
    # Internal: reconcile folder paths after a root moves
    # --------------------------------------------------------
    def _refreshResolvedFolderPaths(self):
        folder_tags = self.getFolderTags()
        roots_by_key = {}
        for library in self.getLibraries():
            for root in library.get("roots", []):
                roots_by_key[(library.get("id", ""), root.get("id", ""))] = root

        for record in folder_tags.values():
            if not isinstance(record, dict):
                continue
            root = roots_by_key.get((record.get("library_id", ""), record.get("root_id", "")))
            if root is None:
                continue
            record["relative_path"] = storeRelativePath(record.get("relative_path", ""))
            if root.get("is_available") and root.get("path"):
                record["resolved_path"] = joinRoot(root.get("path", ""), record["relative_path"])
            else:
                record["resolved_path"] = ""

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
    # Internal: folders worth scanning for a moved root
    # --------------------------------------------------------
    def _candidateScanBases(self):
        bases = []
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            bases.append(home)
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

    # --------------------------------------------------------
    # Internal: read and check a library export file
    # --------------------------------------------------------
    def _readLibraryExport(self, path):
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("format") != LIBRARY_FILE_FORMAT:
            return None
        if data.get("format_version") != LIBRARY_FILE_VERSION:
            return None
        library = data.get("library")
        folders = data.get("folders")
        if not isinstance(library, dict) or not isinstance(folders, list):
            return None
        return data

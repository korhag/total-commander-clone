# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Placeholder for upcoming changes. When you ship, add a dated section below and bump `APP_VERSION` in `app_version.py`.

## [0.4.69] - 2026-10-01

### Changed

- **Clearer bookmark drag-and-drop**: The line or highlight on a row is the action that will happen when you release. The top and bottom of a row reorder, the middle of a bookmark creates a group, and the middle of a group moves the item inside. A short hint under the list says which of those you are about to do. Hovering a collapsed group opens it. A group cannot be dropped inside itself, and a group stays expanded or collapsed after you move it.

## [0.4.68] - 2026-09-29

### Changed

- **Bookmarks have their own file**: The bookmark list is stored in `bookmarks.json` next to `state.json` (`%APPDATA%\TotalCommanderClone` for the built app). Panel layout and filters no longer share that file. An existing list inside `state.json` is copied over on the next launch.

## [0.4.67] - 2026-09-29

### Added

- **Bookmark import and export**: The Bookmarks menu and the bookmarks sidebar can save the list to a JSON file, or load one by replacing the list or merging paths that are not already present.

### Fixed

- **Bookmarks stay saved**: Adding, editing, reordering, or deleting a bookmark writes it immediately. A second window that did not change bookmarks keeps the newer list on disk. An empty sidebar or a damaged `state.json` cannot replace a saved list. If the saved list is empty or unreadable, the app restores the last good copy, unless every bookmark was deleted on purpose. Nested bookmarks appear in the Bookmarks menu.

## [0.4.66] - 2026-08-28

### Changed

- **Settings backups stay local**: Per-computer settings, bookmarks, and libraries are written to `%APPDATA%\TotalCommanderClone\backups\<computer-name>\` (or `~/.config/TotalCommanderClone/backups/` on other platforms). Saving settings no longer commits or pushes to Git. Use Settings export/import to copy a profile between machines.

### Removed

- Generated packaged builds (`dist_build/`), machine-specific `__copycodebase.json`, debug logs, and the old `backup/settings/` copies from Git. Push and pull now sync source, resources, and documentation only.

## [0.4.65] - 2026-08-10

### Changed

- **Conflict dialog robustness**: Source/destination lookup uses normalized and Windows long-path forms; missing sides show **Not found** with a clear reason instead of a blank “Missing”.

### Added

- **Overwrite all matching size+files** / **Skip all matching size+files**: When total size and file count match, apply that action and auto-resolve later matching conflicts (non-matching conflicts still prompt).

## [0.4.64] - 2026-08-10

### Removed

- Selection details strip above the file list (full path / Copy path / Compare / folder stats). Compare remains available from the context menu and SPECIAL menu.

## [0.4.63] - 2026-08-10

### Changed

- **Copy/move conflict dialog**: Side-by-side Source vs Destination comparison with full paths, type, size, modified time, and async folder tree stats. New **Skip** leaves the existing item and continues the batch; **Cancel** still aborts the whole transfer. “Do this for all remaining conflicts” applies Overwrite / Keep both / Skip to later conflicts.

## [0.4.62] - 2026-08-10

### Added

- **Selection details strip**: Selecting one item shows full path (and relative path in Subfolders mode), plus async folder tree size/file/subfolder counts. **Copy path** and **Compare…** buttons on the strip.
- **Compare with other panel**: Context menu and SPECIAL menu open a side-by-side compare (path, exists, type, modified, tree size/counts) using the same relative path under the other panel’s root when possible.
- Richer row tooltips: full path, relative path, parent folder (no deep scan on hover).

## [0.4.61] - 2026-08-10

### Added

- **Recursive search cache**: Subfolders listings are kept in memory and optionally on disk so returning to the same folder is fast. After copy/move/delete, the list is updated in place instead of re-walking the whole tree. Filter banner **Refresh** / F5 still force a full scan. Settings → **Cache recursive folder scans**.

## [0.4.60] - 2026-08-10

### Added

- **SPECIAL center button**: Copy/Move **keeping structure** relative to the active panel’s current folder (search root), so recursive filter hits like `Archive\Alexa\…\output` land under `Duplicates\Alexa\…\output` instead of flattening. Also **Copy relative paths** / **Copy full paths**. Same structure actions in the file context menu. Normal F6/F7 stay flat.

## [0.4.59] - 2026-08-10

### Added

- **Help → Publish Version to GitHub…**: When local `APP_VERSION` is newer than GitHub, commit (if the tree is dirty) and push with a normal (non-force) push. Prompts for remote URL, username, and PAT when needed; can save to `.git-account.*`.
- **Check for Updates**: If your version is ahead of GitHub, offers **Publish to GitHub…** (startup checks stay quiet when local is ahead).

### Safety

- Publish never force-pushes. Rejected non-fast-forward pushes ask you to pull/merge first. Credentials are not stored in `settings.json`.

## [0.4.58] - 2026-08-10

### Added

- **Filter banner Refresh**: When a filter is active, the banner includes a **Refresh** button that reloads the folder (and re-scans subfolders when that option is on), then re-applies all filter rules.

### Changed

- **Subfolders** is no longer a toolbar toggle; enable recursive search from **Settings** → Search scope (Include subfolders).
- **Filter Settings** is a labeled toolbar button (with border and hover) instead of a small flat gear icon.

## [0.4.57] - 2026-07-22

### Added

- **`scripts\build-user.bat`**: Plain rebuild of the current sources with **no Git sync** (no account, push, or pull). Calls `build.bat skip-git`.
- **Updates without Git installed**: If Git is missing, `update-and-rebuild.bat` downloads the public GitHub branch as a zip (`download-public-update.ps1`), merges sources (preserving `dist`, `.venv`, `.git`, backups), then builds with `build-user.bat`. Version checks already used anonymous HTTPS.

### Changed

- **`scripts\build.bat`**: Documented as the developer build (Git BuildSync first). Users should prefer `build-user.bat`.

## [0.4.56] - 2026-07-22

### Added

- **Folder Properties → Size**: The General tab shows total folder size (human-readable and bytes), plus file/subfolder counts from a background tree walk. Shows “Calculating…” until the scan finishes.

## [0.4.55] - 2026-07-22

### Changed

- **Public update source**: Update checks use the public repo `https://github.com/derya-kromeka/total-commander-clone` (anonymous raw GitHub version first; no username/PAT). If `origin` is missing, it is added automatically for pull/rebuild.

## [0.4.54] - 2026-07-22

### Added

- **Update from Git on startup**: After the window opens, the app compares its `APP_VERSION` to the remote branch’s `app_version.py` (hidden `git fetch`). If Git is newer, a dialog offers **Update now**, **Later**, or **Skip this version**. Update now closes the app and runs `scripts\update-and-rebuild.bat` (pull → `build.bat skip-git` → relaunch the new exe). Also available from **Help → Check for Updates…**. Toggle in **Settings → Check for updates from Git when the app starts**.

## [0.4.53] - 2026-07-22

### Fixed

- **No more flashing Git cmd windows**: Background config backup (`git add` / `commit` / `push` and PAT decrypt via PowerShell) now runs with a hidden console on Windows (`CREATE_NO_WINDOW`), so starting the app or saving settings no longer opens stacks of `git.exe` console windows.

## [0.4.52] - 2026-07-22

### Changed

- **Font size scales layout**: Raising **Font size** in Settings no longer only enlarges text. Row height, file-list icons, nav buttons, padding, and related spacing scale from a **10 pt = 100%** baseline (with Interface density still applied on top), so the file list stays readable instead of cramped.

## [0.4.51] - 2026-07-22

### Added

- **Bookmarks context menu**: Right-click a bookmark for **Edit bookmark…** (name and path dialog with folder/file browse) and **Update with current panel** (repoint the bookmark to the active pane’s path). Rename and Delete remain available.

## [0.4.50] - 2026-07-22

### Fixed

- **Build promote failsafe**: If `dist\TotalCommanderClone` cannot be deleted because some files are locked (e.g. `VCRUNTIME*.dll` held by another process), `scripts\build.bat` merges the new build over `dist\` instead of failing. The taskbar shortcut path keeps working; locked files that cannot be overwritten are left in place when the new exe is present.

## [0.4.49] - 2026-07-22

### Changed

- **Filter visibility**: When any panel filter is active, the filter field gets a red border, a red **✕ Clear** button appears beside it, and a red banner above the file list explains what is filtered and how many items are hidden (e.g. “files only — 2 item(s) hidden”). The status bar also warns when rows are hidden. Click either **Clear** control to reset all filters for that panel.

## [0.4.48] - 2026-07-22

### Added

- **Context menu: Open / Explorer / Terminal**: Right-click a file or folder (including Subfolders search results) for **Open File** (or **Open** for folders), **Open in File Explorer** (reveals/selects the item), and **Open Folder in Terminal** (Command Prompt or Windows Terminal in the item’s folder). Right-click also selects the row under the cursor when needed.

## [0.4.47] - 2026-07-22

### Added

- **Clear active filter (red X)**: When any panel filter is active (name text, files/folders only, exclude/extensions, size/date, or Subfolders), a red **X** appears in the filter field. Click it to reset all search/filter options for that panel. The status bar also shows how many items remain visible when a filter hides rows (e.g. `0 shown · 0 file(s), 2 folder(s)`).

## [0.4.46] - 2026-07-22

### Added

- **Settings Import / Export**: In **Edit → Settings**, export or import a single JSON profile that includes preferences plus bookmarks, libraries, folder tags, saved filters, and panel state. Import applies immediately and refreshes the UI.

## [0.4.45] - 2026-07-22

### Added

- **Per-computer settings backup**: On every settings/state save, the app writes the latest `settings.json`, `bookmarks.json`, `libraries.json`, and related state under `backup/settings/<computer-name>/` (overwrites previous files for that PC). It then best-effort commits and pushes those files to the Git remote (uses a saved PAT from `scripts\git-config-account.cmd` when available).

## [0.4.44] - 2026-07-22

### Added

- **Search filter enhancements**: Filter options (gear) now support **exclude** terms, **AND/OR** matching for multiple include words, and **file extension** filters (e.g. `txt, pdf, docx`). Folders are not filtered by extension; exclude removes matches when any exclude word appears in the name.

## [0.4.43] - 2026-07-22

### Added

- **Build Git sync**: `scripts\build.bat` compares local `APP_VERSION` in `app_version.py` to the remote branch before building. If the local version is ahead it pushes first; if behind it pulls first. Uses saved GitHub credentials when available, or prompts for username and PAT. Pass `skip-git` to build without syncing (e.g. `scripts\build.bat skip-git`).

## [0.4.42] - 2026-06-18

### Fixed

- **In-place rename**: File name text no longer overlaps the rename field; the cell label is hidden while editing and the inline editor uses an opaque background aligned with the table row.

## [0.4.41] - 2026-06-08

### Added

- **Background file transfers**: Copy, move, and delete run in a non-blocking FIFO queue so the main window stays usable. A compact transfers row above the F-key bar shows active progress with Cancel; click the row to open a modeless details popup (safe to close — transfers continue). Multiple operations can be queued; cut/paste clears the clipboard only after a successful move.

## [0.4.40] - 2026-06-08

### Changed

- **Filter nav bar**: Removed the separate **Clear** button; filter text is cleared with the built-in × inside the filter field. **Subfolders** is now a compact toggle button (highlighted when active) instead of a checkbox. Filter clear and subfolder toggle styling updated for the dark theme.

## [0.4.39] - 2026-06-08

### Added

- **Date Modified format**: Right-click the **Date Modified** column header for a **Date format** submenu (YYYY/MM/DD, YY/MM/DD, with optional time, plus DD/MM/YYYY and MM/DD/YYYY variants). The current choice is checkmarked and saved in `settings.json` as `date_modified_format`.
- **Open With**: File context menu **Open With...** launches the Windows **Open with** dialog via `rundll32 shell32.dll,OpenAs_RunDLL` (first selected file when multiple files are selected).

## [0.4.38] - 2026-06-03

### Fixed

- **Frozen (.exe) invisible window / blink**: saved panel paths and library drive scans no longer run synchronously before the first `show()`. The window opens on local home folders immediately; `%APPDATA%` state restore and library marker scans run on the next event-loop tick so slow or offline network paths (e.g. Google Drive) cannot block startup. Off-screen or minimized saved geometry is corrected on first show. Unhandled exceptions and startup steps are logged to `%APPDATA%\TotalCommanderClone\crash.log` and `startup.log`. PyInstaller builds also prepend bundled `Qt5\bin` to `PATH` for platform DLL loading.

### Added

- **Debug build**: `TotalCommanderClone-debug.spec` and `scripts\build.bat debug` produce a console `.exe` at `dist_build\TotalCommanderClone-debug\` for one-shot diagnosis.

## [0.4.37] - 2026-06-02

### Fixed

- **Copy/move progress**: Progress dialog now updates during large file transfers using byte-level chunked copy (1 MiB chunks) instead of staying at 0% until each top-level item finishes. Shows combined item count and transferred/total size; folder trees report per-file progress within the overall byte total. Cross-volume moves use the same byte progress; same-volume renames stay instant.

## [0.4.36] - 2026-06-02

### Fixed

- **File list column resize**: Manual column widths (especially **Name**) no longer bounce back after drag; viewport normalization runs only on first layout or **Distribute columns evenly**, not on every header resize or panel resize.
- **Horizontal scroll**: When total column width exceeds the file table viewport, a horizontal scrollbar appears instead of forcing all columns to fit the window.
- **Column width persistence**: All four columns are saved to panel state when you finish resizing a header (debounced); restored widths are applied without shrinking to the viewport.

## [0.4.35] - 2026-06-02

### Fixed

- **Nav bar drive combo and filter field**: Tighter nav-specific padding and explicit heights so text is not clipped at 70–100% density; drive inner editor no longer draws a nested border; filter field reserves right inset for the clear (×) control so it does not overlap the border.

## [0.4.34] - 2026-06-02

### Added

- **Interface density** presets **Extra compact (70%)** and **Very compact (75%)** below Compact (85%). **Ctrl+mouse wheel** and **Edit → Settings** step through all five levels (70 → 75 → 85 → 100 → 115). Layout metrics use minimum floors so path bar, table rows, and sidebar tabs stay readable at 70%.

## [0.4.33] - 2026-06-02

### Fixed

- **File list columns**: Size, Type, and Date Modified headers no longer clip to fragments like “iz”/“yp”; each column has a header-aware minimum width, extra space goes to **Name** (Date Modified is capped), and long names use middle elision.
- **Path bar**: Reduced vertical padding and explicit min-height so address text is not clipped at the top.
- **Sidebar tabs**: Bookmarks/Libraries tabs show full labels (no elide, min tab width, wider default sidebar).
- **Bookmarks toolbar**: Shorter **Collapse** / **Expand** button labels fit narrow sidebars.
- **F-key bar**: Buttons size to their labels instead of stretching across the window.
- **Typography**: Slightly stronger default font weight at small sizes for clearer text.

## [0.4.32] - 2026-06-02

### Added

- **Ctrl+mouse wheel** adjusts **Interface density** in place: wheel up steps toward **Comfortable (115%)**, wheel down toward **Compact (85%)**, using the same 85/100/115 presets as **Edit → Settings**. The choice is saved to `settings.json` and the status bar briefly shows the new density label.

## [0.4.31] - 2026-06-02

### Added

- **Interface density** in **Edit → Settings** (also **View → Settings**, toolbar **⚙ Settings**, **Ctrl+,**): choose **Compact (85%)**, **Normal (100%)**, or **Comfortable (115%)**. Scales row heights, toolbar and F-key bar buttons, center copy/move column, tree/list padding, and related QSS spacing. Persisted as `ui_scale` in `settings.json`.

### Changed

- **Default layout** is tighter at Normal density: smaller table row padding, toolbar/F-key/center-panel controls, and sidebar tree item spacing.

### Fixed

- **Name column** no longer collapses to icons-only when `%APPDATA%` panel state has hidden Name, tiny widths, or over-locked columns; saved visibility/widths are sanitized on restore and Name gets a larger minimum share of the viewport.

## [0.4.30] - 2026-06-02

### Fixed

- **Frozen (.exe) startup**: saved `window_geometry` in `%APPDATA%` is validated against connected screens; off-screen positions (e.g. after unplugging a monitor) are recentered instead of opening an invisible window. Locked column widths below 48 px in panel state are ignored so corrupt `%APPDATA%` state cannot collapse the file lists. PyInstaller builds set `QT_PLUGIN_PATH` for bundled Qt platform plugins.

## [0.4.29] - 2026-06-02

### Fixed

- **Startup layout**: panel state no longer restores column widths below 48 px (corrupt values from saving before the window was laid out). After the first show, the main splitter and both file lists re-layout so columns and the sidebar use usable sizes again.

## [0.4.28] - 2026-04-13

### Fixed

- **Sidebar splitter rewrite**: removed sidebar host wrapper widget, `showEvent` geometry sync, `setStretchFactor`, `setOpaqueResize`, and `setHandleWidth` overrides that accumulated and interfered with each other. The sidebar is now a plain `QTabWidget` directly inside a `QSplitter` with only `setCollapsible(0, False)` and a `minimumWidth` of 140 px. Saved widths are clamped to 140–600 px on restore. Splitter handle width is controlled only by the theme stylesheet (4 px).

## [0.4.27] - 2026-04-13

### Fixed

- **Sidebar resize jank with locked columns**: `_onColumnSectionResized` now uses the same debounced path as viewport resize instead of calling `_normalizeColumnWidthsForViewport` immediately—this broke the debounce and caused a re-entrant feedback loop (`setColumnWidth` -> `sectionResized` -> normalize -> `setColumnWidth` -> …). All stretch-behavior and locked-width bookkeeping now runs inside the `blockSignals` / `_column_width_clamping` guard so no stray signals re-trigger layout during the update.

## [0.4.26] - 2026-04-13

### Fixed

- **Bookmarks / Libraries sidebar splitter**: sidebar lives in a dedicated host widget with size policy, the splitter uses **opaque resize**, **stretch** (sidebar fixed weight, file area grows), **wider handle**, and a **one-shot geometry sync** after the first show so saved widths match the real window. Initial saved widths below ~180 px are bumped when restoring proportions. **File panels**: column width normalization is **coalesced (~33 ms)** on viewport resize to reduce jank while dragging the main splitter.

## [0.4.25] - 2026-04-13

### Fixed

- **Main splitter**: only the **sidebar** pane is non-collapsible (`setCollapsible(0, false)`). Applying non-collapsible to **both** panes (or `setChildrenCollapsible(false)`) combined badly with the file area’s minimum size and made dragging the splitter feel stuck or unusable.
- **File panels**: column width normalization on viewport resize is **immediate** again (removed the debounce timer), so lists track splitter and window resizes without lag.

## [0.4.24] - 2026-04-13

### Fixed

- **Main splitter**: `setChildrenCollapsible(False)` and `setCollapsible` now run **after** panes are added so Qt does not leave new panes collapsible (which still reported as collapsible in diagnostics and could allow odd resize behavior).

## [0.4.23] - 2026-04-13

### Fixed

- **Main sidebar splitter**: children are no longer collapsible (prevents the sidebar from snapping to zero width and fighting `minimumWidth`), the sidebar no longer uses a hard `maximumWidth` that conflicted with splitter sizing during drags, and the splitter handle is slightly wider for easier dragging.

## [0.4.22] - 2026-04-13

### Fixed

- **Sidebar / splitter resize**: resizing the bookmarks (or Libraries) sidebar no longer fights column layout on every pixel; column widths are normalized shortly after the table viewport stops changing, so dragging the splitter stays smooth even with locked columns.

### Changed

- **Lock column width**: you can no longer lock every visible column—locking the last unlocked column shows a message, because at least one column must stay flexible when the window or sidebar resizes.

## [0.4.21] - 2026-04-07

### Added

- **Lock column width**: right-click a column header and toggle **Lock column width** so that column keeps its size when you resize other columns or the panel. Locked widths are saved in panel state. **Distribute columns evenly** only resizes unlocked columns.

## [0.4.20] - 2026-04-07

### Fixed

- **Panel column widths**: visible columns are **clamped** so their total width never exceeds the table viewport (no horizontal overflow hiding **Date** / **Type**). Each visible column keeps at least **5%** of the viewport width (or an equal split when the pane is too narrow). Applies on resize, restore, column visibility, and **Distribute columns evenly**.

## [0.4.19] - 2026-04-07

### Fixed

- **Panel columns**: the **rightmost visible** file-list column now stretches to the panel edge, instead of relying on Qt's global "last section" behavior. This removes blank space on the right and keeps hidden-column layouts, restored widths, and manual column toggles aligned with the panel width.

## [0.4.18] - 2026-04-07

### Fixed

- **Font size (and theme) on startup**: Saved **Font size** from Settings now applies as soon as the app opens. The dark theme stylesheet used fixed pixel sizes that overrode `QApplication`’s font until Settings was opened; theme text sizes are now derived from the same base size, and `applyTheme()` sets the application font for all theme modes.

## [0.4.17] - 2026-04-07

### Added

- **Settings → Mirror (Ctrl+Shift+M)**: choose whether **Mirror** makes the **inactive panel** follow the **active** panel’s folder (default), or the **active panel** follow the **inactive** panel’s folder. View menu and toolbar tooltips update to match.

## [0.4.16] - 2026-04-07

### Added

- **Paste from system file manager**: **Ctrl+V** / **Edit → Paste** pastes files or folders copied or cut in **File Explorer** (and other apps that put local file URLs on the clipboard), into the **active panel’s current folder**. Windows **Cut** in Explorer is honored as a **move** via the shell “Preferred DropEffect” format.

## [0.4.15] - 2026-04-07

### Changed

- **`scripts/git-hub-menu.sh`** aligned with **`scripts/git-hub-menu.bat`**: asterisk-framed **GIT** / **THIS REPO** context (origin, identity, HTTPS token file), **MENU** block and option wording, **SUCCESS** / **FAILED** banners on pull / commit+push / force-push / first-time wizard, option **6** continues after setting **origin** via **3** (`GIT_MENU_FROM_COMMIT`), first-time flow matches the Windows script (`.gitkeep`, `commit --allow-empty`, fetch + push hints), and clearer messages (e.g. “nothing to commit” + no commits yet).

## [0.4.14] - 2026-04-07

### Added

- **Developer scripts**: `scripts/install.bat` creates `.venv` and installs `requirements.txt` on Windows (Command Prompt). `scripts/run.bat` runs `main.py` with `.venv\Scripts\python.exe` after install.
- **macOS**: `scripts/RUN.command` in the repo (re-written by `bash scripts/install.sh` on Apple systems) — double-click in Finder to launch via `run.sh` after a successful install. If Terminal says permission denied, run `chmod +x scripts/RUN.command`.

### Changed

- **`scripts/run.sh`**: Invokes `.venv/bin/python` or `.venv/Scripts/python.exe` directly so macOS/Linux never pick a wrong `python` on PATH; error text points to `install.sh` / `install.bat`.

## [0.4.13] - 2026-04-07

### Changed

- **Subfolders** search no longer blocks the UI: recursive listing runs on a **background thread** with a **progress dialog** (item count + current path) and **Cancel**. First-time enable shows an explanation with optional “Don’t show again” (stored in settings). Status line shows **Subfolders scan** when active; the Subfolders checkbox uses a stronger style when checked (dark theme).

## [0.4.12] - 2026-04-07

### Added

- **Filter options dialog** (gear next to the filter field): match mode, files/folders, subfolders, **size** and **modified date** ranges with **AND/OR** between size and date blocks, **saved presets** (stored in app state), **Clear** in the dialog and a **Clear** button on the toolbar. Advanced rules are **AND**ed with the name filter. State persists in `state.json` per panel (`filter_advanced`).

## [0.4.11] - 2026-04-07

### Changed

- **Settings** moved from **File** to **Edit** (**Edit → Settings…**).

## [0.4.10] - 2026-04-07

### Changed

- **Windows `git-hub-menu.bat`**: Main screen uses asterisk-framed sections for the title block, **GIT**, **THIS REPO**, and **MENU** (options list closed with a matching line) for easier scanning.

## [0.4.9] - 2026-04-07

### Changed

- **Windows `git-hub-menu.bat`**: Main menu shows a short **repo summary** (origin URL, commit name/email, HTTPS token file). **Option 6** (save/commit/push), **4** (pull), **8** (first-time wizard), and **10** (force push) end with **SUCCESS** or **FAILED** asterisk banners. Clearer text when there is nothing to commit; first-time wizard uses a reliable `.gitkeep` and can fall back to `git commit --allow-empty` instead of the vague “add project files” message.

## [0.4.8] - 2026-04-07

### Added

- **Windows Git helper**: `scripts/save-github-token.ps1` — guided GitHub HTTPS Personal Access Token setup (opens token pages on request, saves repo-local credentials, tests with `git ls-remote`, SUCCESS/FAILED banners). Used from `git-hub-menu.bat` option 11.

## [0.4.7] - 2026-04-07

### Added

- **Settings** dialog (**File → Settings…**), aligned with the [denizko-gh/total-commander-clone-1](https://github.com/denizko-gh/total-commander-clone-1) fork: theme (dark / light / same as system), font size, show hidden files, confirm before delete, default left/right paths. **`theme.applyTheme`** in `theme.py` applies the custom dark stylesheet or Fusion light / native system look; `main.py` stores the initial style and palette for the “system” option.

## [0.4.6] - 2026-04-07

### Added

- **Folder tooltips**: **Size** line sums **only files directly in that folder** (one `scandir`, no subfolder recursion) so hover stays fast; footer clarifies that subfolders are not included.

## [0.4.5] - 2026-04-07

### Added

- **Column header menu**: **Distribute columns evenly** splits the panel width equally across all visible columns (turns off “stretch last column” so widths stay equal).

## [0.4.4] - 2026-04-07

### Added

- **Properties** (right-click): Tabbed dialog with **General** (name, type, location, full path, size or folder item count, created / modified / accessed, attributes), **Details** (MIME type, extension, symlink target, permissions, inode, device, owner/group on Unix, drive), and **Checksums** (MD5, SHA-1, SHA-256) for files.

## [0.4.3] - 2026-04-07

### Added

- **Tooltips**: Title plus short description on main menus, toolbar, center pane buttons, bottom F-key bar, sidebar tabs, bookmarks/libraries panels, library browser controls, and file context menu items. File list rows keep **summary card** HTML tooltips (path, size, dates, MIME, “Opens with” on Windows) from the file panel model; the file table enables mouse tracking so hover tips behave reliably.

## [0.4.2] - 2026-04-07

### Changed

- **File panel toolbar**: **New folder** sits immediately to the **right of Home** and to the **left of the drive** dropdown (before the filter row).

## [0.4.1] - 2026-04-07

### Added

- **Filter — subfolders**: Checkbox **Subfolders** next to the filter field lists and searches **recursively** under the current folder (names show as `subdir\\file`). The same filter modes (contains / wildcard / regex) and **Files only** / **Folders only** apply to that full tree. State is saved per pane. Large directories may take longer to scan.

## [0.4.0] - 2026-04-07

### Added

- **File panel columns**: Right-click the column header row to show a menu with checkboxes for **Name**, **Size**, **Type**, and **Date Modified** (at least one column must stay visible). Visibility is saved per pane in `state.json`.
- **Filter options**: A **gear-style** button next to the filter field opens a menu: **Match name** — contains text, wildcard (`*`, `?`), or regular expression; **Show** — all items, folders only, or files only. The filter box placeholder summarizes the active mode; filter text and options persist per pane.

## [0.3.12] - 2026-04-07

### Changed

- **Active panel**: The file list (`QTableView`) uses the same thin **orange** focus ring as the path field when that pane is active; inactive panes keep a neutral border on both.

## [0.3.11] - 2026-04-07

### Changed

- **File panels**: The **Date Modified** column stretches to the right edge of the pane (`stretchLastSection`), so the file list usually shows all four columns without a horizontal scrollbar. Saved column widths apply only to **Name**, **Size**, and **Type**.

## [0.3.10] - 2026-04-07

### Changed

- **Git helper scripts** (`scripts/git-hub-menu.bat`, `scripts/git-hub-menu.sh`): option **6 — Save to GitHub** keeps the safer flow (no `origin` → offer to set remote; identity check; **Proceed?**; optional `git ls-remote` warning and **Try push anyway?**; `git commit -F` message file, UTF-8 on Windows; push stderr tail + tips). **After setting `origin` from option 6**, the scripts now **continue** into add/commit/push instead of always returning to the menu.

## [0.3.9] - 2026-04-07

### Changed

- **Active panel**: The address bar (`QLineEdit` showing the current path) shows a thin orange border when that panel is active; inactive panels keep a neutral border. The file panel’s outer frame uses the same border for both states so focus reads on the path field.

## [0.3.8] - 2026-04-07

### Added

- **New folder** button on each file panel’s navigation bar (folder-with-plus style icon): creates a subfolder in that panel’s current directory; **F8** still uses the same logic for whichever panel is active.

## [0.3.7] - 2026-04-07

### Changed

- **Drive list**: Removed the separate refresh button; the drive list is re-scanned when you open the drive dropdown (Windows), so USB and external disks stay current without an extra click.

## [0.3.6] - 2026-04-02

### Changed

- **Drive picker**: left-click on the drive letter / combo field opens the drive list (same as the ▼ control), not only the separate arrow button.

## [0.3.5] - 2026-04-02

### Changed

- **Git helper scripts** (`scripts/git-hub-menu.bat`, `scripts/git-hub-menu.sh`): option **6 — Save to GitHub** now checks for `origin` and user identity first, asks **Proceed?** before `git add`, optionally warns when `git ls-remote` fails (offline/auth), commits via **`-F`** message file (UTF-8 on Windows), skips **push** after a failed commit, and shows only the **last lines** of push errors plus tips (options 4, 11, 12).

## [0.3.4] - 2026-04-02

### Fixed

- **Crash when opening some folders** (e.g. CAD paths with names starting with digits): natural name sorting used mixed `int` and `str` list elements, which raised `TypeError` during sort. Segments are now tagged `(numeric)` vs `(text)` so ordering is always comparable.

## [0.3.3] - 2026-04-02

### Fixed

- **Name column** sorting uses **natural order**: numeric runs in file names are compared as numbers, so e.g. `KT-167` sorts before `KT-1665` and `KT-173`, matching typical file manager expectations.

## [0.3.2] - 2026-04-02

### Changed

- Path bar **Open folder** button (folder icon) now opens **that panel’s** current directory in the system file manager (Windows Explorer / Finder / etc.) instead of showing a folder picker dialog.
- Inactive file panel: thin **gray** border (`overlay0`). Active file panel: thin **orange** border (`panel_focus_ring`).

## [0.3.1] - 2026-04-02

### Fixed

- File list scroll position resets to the top when navigating into a folder (e.g. double-click), so the new directory listing always starts from the first row.

## [0.3.0] - 2026-04-02

### Added

- **Library Browser Panel**: full panel-sized library browser that can replace either file panel, with library selector dropdown, categorized tag tree, and folder results list with action buttons.
- **Tag categories**: tags using `category:value` format are now grouped by category in the Library Browser. The Tag Assignment dialog shows known categories as hints and provides autocomplete for existing tags.
- **Mirror button**: new center column button to open the active panel's current folder in the other panel (Ctrl+Shift+M).
- **Panel toggle**: View menu actions and Ctrl+Shift+L shortcut to toggle any panel between file browser and library browser mode.
- QSS styling for library browser components and list widgets.

### Changed

- Home button icon replaced with a recognizable house emoji instead of the generic `SP_DirHomeIcon` which looked like a folder on Windows.

## [0.2.2] - 2026-04-01

### Changed

- `scripts/install.sh`: expanded macOS support — Homebrew on Apple Silicon (`/opt/homebrew`) and Intel (`/usr/local`), MacPorts (`python312` + `port select`), discovery of python.org Framework installs when not on `PATH`, and clearer manual install hints.

## [0.2.1] - 2026-04-01

### Added

- `scripts/install.sh`: detects OS and CPU architecture, installs Python when needed, creates `.venv`, installs `requirements.txt`, and generates `scripts/run.sh` to launch the app from the venv.

## [0.2.0] - 2026-03-30

### Added

- Application version in window title and About dialog (`app_version.py`).
- Libraries and folder tags (registry, marker file `.tcc_library_root.json`, Libraries sidebar tab, tag assignment).
- This changelog and versioning workflow for the project.

"""
Filter Options dialog: name match mode, files/folders, subfolders, size/date
constraints with AND/OR, saved presets, clear/apply/ok.
"""

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QDialogButtonBox,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QPushButton,
    QLabel,
    QSpinBox,
    QDateTimeEdit,
    QMessageBox,
    QInputDialog,
)
from PyQt5.QtCore import QDateTime

from filter_spec import FilterSpec


def _dt_to_ts(qdt):
    if hasattr(qdt, "toSecsSinceEpoch"):
        return int(qdt.toSecsSinceEpoch())
    return int(qdt.toTime_t())


def _ts_to_qdt(ts):
    if ts is None:
        return None
    if hasattr(QDateTime, "fromSecsSinceEpoch"):
        return QDateTime.fromSecsSinceEpoch(int(ts))
    return QDateTime.fromTime_t(int(ts))


def _mb_to_bytes(mb):
    if mb is None or mb <= 0:
        return None
    return int(mb * 1024 * 1024)


def _bytes_to_mb(b):
    if b is None or b <= 0:
        return 0
    return max(0, int(round(b / (1024 * 1024))))


class FilterOptionsDialog(QDialog):
    def __init__(self, file_panel, settings_manager, parent=None):
        super().__init__(parent)
        self._file_panel = file_panel
        self._settings = settings_manager
        self.setWindowTitle("Filter options")
        self.setModal(True)
        self.resize(560, 640)

        root = QVBoxLayout(self)

        # --- Name filter (toolbar mirror) ---
        name_box = QGroupBox("Name filter (toolbar)", self)
        name_form = QFormLayout()
        self._filter_text = QLineEdit(self)
        self._filter_text.setPlaceholderText(
            "Words to find in file or folder name (separate with spaces or commas)…"
        )
        name_form.addRow("Include", self._filter_text)

        words_row = QHBoxLayout()
        self._bg_words = QButtonGroup(self)
        self._rb_words_and = QRadioButton("Match all words (AND)")
        self._rb_words_or = QRadioButton("Match any word (OR)")
        self._bg_words.addButton(self._rb_words_and)
        self._bg_words.addButton(self._rb_words_or)
        words_row.addWidget(self._rb_words_and)
        words_row.addWidget(self._rb_words_or)
        words_row.addStretch()
        name_form.addRow("Multiple words", words_row)

        self._filter_exclude = QLineEdit(self)
        self._filter_exclude.setPlaceholderText(
            "Exclude names containing any of these words…"
        )
        name_form.addRow("Exclude", self._filter_exclude)

        self._filter_extensions = QLineEdit(self)
        self._filter_extensions.setPlaceholderText(
            "File types only, e.g. txt, pdf, docx (folders are not filtered by extension)"
        )
        name_form.addRow("Extensions", self._filter_extensions)

        match_row = QHBoxLayout()
        self._bg_match = QButtonGroup(self)
        self._rb_contains = QRadioButton("Contains text")
        self._rb_wildcard = QRadioButton("Wildcard (* ?)")
        self._rb_regex = QRadioButton("Regular expression")
        for rb in (self._rb_contains, self._rb_wildcard, self._rb_regex):
            self._bg_match.addButton(rb)
            match_row.addWidget(rb)
        match_row.addStretch()
        name_form.addRow("Match mode", match_row)

        kind_row = QHBoxLayout()
        self._bg_kind = QButtonGroup(self)
        self._rb_kind_all = QRadioButton("All items")
        self._rb_kind_dirs = QRadioButton("Folders only")
        self._rb_kind_files = QRadioButton("Files only")
        for rb in (self._rb_kind_all, self._rb_kind_dirs, self._rb_kind_files):
            self._bg_kind.addButton(rb)
            kind_row.addWidget(rb)
        kind_row.addStretch()
        name_form.addRow("Show", kind_row)

        self._chk_subfolders = QCheckBox(
            "Include subfolders when listing (recursive search)", self
        )
        self._chk_subfolders.setToolTip(
            "When enabled, the file list includes every item under the current folder. "
            "Large trees can take a while; a progress window with Cancel appears while scanning."
        )
        name_form.addRow("Search scope", self._chk_subfolders)
        name_box.setLayout(name_form)
        root.addWidget(name_box)

        # --- Advanced: size + date ---
        adv_box = QGroupBox("Size and date (advanced)", self)
        adv_layout = QVBoxLayout()

        self._chk_size = QCheckBox("Filter by file size (folders are not excluded by size)", self)
        adv_layout.addWidget(self._chk_size)
        sz_form = QFormLayout()
        self._spin_min_mb = QSpinBox(self)
        self._spin_min_mb.setRange(0, 2_000_000)
        self._spin_min_mb.setSpecialValueText("—")
        self._spin_min_mb.setValue(0)
        self._spin_max_mb = QSpinBox(self)
        self._spin_max_mb.setRange(0, 2_000_000)
        self._spin_max_mb.setSpecialValueText("—")
        self._spin_max_mb.setValue(0)
        sz_form.addRow("Minimum size (MB)", self._spin_min_mb)
        sz_form.addRow("Maximum size (MB)", self._spin_max_mb)
        for sp in (self._spin_min_mb, self._spin_max_mb):
            sp.setMinimum(0)
            sp.setSpecialValueText("—")
        adv_layout.addLayout(sz_form)

        self._chk_date = QCheckBox("Filter by modification date", self)
        adv_layout.addWidget(self._chk_date)
        dt_form = QFormLayout()
        self._dt_after = QDateTimeEdit(self)
        self._dt_after.setCalendarPopup(True)
        self._dt_after.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._dt_before = QDateTimeEdit(self)
        self._dt_before.setCalendarPopup(True)
        self._dt_before.setDisplayFormat("yyyy-MM-dd HH:mm")
        dt_form.addRow("Modified on or after", self._dt_after)
        dt_form.addRow("Modified on or before", self._dt_before)
        adv_layout.addLayout(dt_form)

        combine_row = QHBoxLayout()
        self._bg_combine = QButtonGroup(self)
        self._rb_and = QRadioButton("Require both size and date (AND)")
        self._rb_or = QRadioButton("Match either size or date (OR)")
        self._bg_combine.addButton(self._rb_and)
        self._bg_combine.addButton(self._rb_or)
        combine_row.addWidget(self._rb_and)
        combine_row.addWidget(self._rb_or)
        combine_row.addStretch()
        adv_layout.addLayout(combine_row)
        adv_box.setLayout(adv_layout)
        root.addWidget(adv_box)

        root.addWidget(QLabel(
            "Include, exclude, and extension rules apply together with the advanced "
            "size/date block (name AND advanced). Exclude removes matches even when "
            "include terms match.",
            self,
        ))

        # --- Saved filters ---
        preset_box = QGroupBox("Saved filters", self)
        preset_layout = QHBoxLayout()
        self._preset_combo = QComboBox(self)
        self._preset_combo.setMinimumWidth(200)
        preset_layout.addWidget(self._preset_combo, 1)
        self._btn_preset_load = QPushButton("Load", self)
        self._btn_preset_save = QPushButton("Save as…", self)
        self._btn_preset_delete = QPushButton("Delete", self)
        preset_layout.addWidget(self._btn_preset_load)
        preset_layout.addWidget(self._btn_preset_save)
        preset_layout.addWidget(self._btn_preset_delete)
        preset_box.setLayout(preset_layout)
        root.addWidget(preset_box)

        self._btn_preset_load.clicked.connect(self._onPresetLoad)
        self._btn_preset_save.clicked.connect(self._onPresetSave)
        self._btn_preset_delete.clicked.connect(self._onPresetDelete)

        # Buttons
        bbox = QHBoxLayout()
        self._btn_clear = QPushButton("Clear filter", self)
        self._btn_clear.setToolTip(
            "Reset name, match mode, show, subfolders, and size/date to defaults."
        )
        bbox.addWidget(self._btn_clear)
        bbox.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._onApply)
        buttons.accepted.connect(self._onOk)
        buttons.rejected.connect(self.reject)
        bbox.addWidget(buttons)
        root.addLayout(bbox)

        self._btn_clear.clicked.connect(self._onClearClicked)

        self._reloadPresetCombo()
        self._load_from_panel()

    def _reloadPresetCombo(self):
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        presets = []
        if self._settings is not None:
            presets = self._settings.getSavedFileFilters()
        for p in presets:
            name = p.get("name", "")
            if name:
                self._preset_combo.addItem(name, p)
        self._preset_combo.blockSignals(False)

    def _load_from_panel(self):
        self._applyFilterState(self._file_panel.getFilterState())

    # --------------------------------------------------------
    # Method: _applyFilterState
    # Purpose: Fill every widget from a saved filter state (panel
    #          or preset). Missing values reset to defaults so no
    #          control keeps a stale value from a previous load.
    # --------------------------------------------------------
    def _applyFilterState(self, st):
        self._filter_text.setText(st.get("filter_text") or "")
        self._filter_exclude.setText(st.get("filter_exclude_text") or "")
        self._filter_extensions.setText(st.get("filter_extensions") or "")
        self._rb_words_and.setChecked(bool(st.get("filter_words_combine_and", True)))
        self._rb_words_or.setChecked(not bool(st.get("filter_words_combine_and", True)))
        mode = st.get("filter_mode", "contains")
        self._rb_contains.setChecked(mode == "contains")
        self._rb_wildcard.setChecked(mode == "wildcard")
        self._rb_regex.setChecked(mode == "regex")
        kind = st.get("filter_kind", "all")
        self._rb_kind_all.setChecked(kind == "all")
        self._rb_kind_dirs.setChecked(kind == "dirs")
        self._rb_kind_files.setChecked(kind == "files")
        self._chk_subfolders.setChecked(bool(st.get("filter_include_subfolders")))

        spec = FilterSpec.from_dict(st.get("filter_advanced"))
        self._chk_size.setChecked(spec.size_enabled)
        self._spin_min_mb.setValue(_bytes_to_mb(spec.size_min))
        self._spin_max_mb.setValue(_bytes_to_mb(spec.size_max))
        self._chk_date.setChecked(spec.date_enabled)
        dta = _ts_to_qdt(spec.date_after)
        if dta is None:
            dta = QDateTime.currentDateTime().addYears(-10)
        self._dt_after.setDateTime(dta)
        dtb = _ts_to_qdt(spec.date_before)
        if dtb is None:
            dtb = QDateTime.currentDateTime().addYears(10)
        self._dt_before.setDateTime(dtb)
        self._rb_and.setChecked(spec.combine_and)
        self._rb_or.setChecked(not spec.combine_and)

    def _gather_spec(self):
        spec = FilterSpec()
        spec.size_enabled = self._chk_size.isChecked()
        spec.size_min = _mb_to_bytes(self._spin_min_mb.value()) if spec.size_enabled else None
        spec.size_max = _mb_to_bytes(self._spin_max_mb.value()) if spec.size_enabled else None
        spec.date_enabled = self._chk_date.isChecked()
        if spec.date_enabled:
            spec.date_after = _dt_to_ts(self._dt_after.dateTime())
            spec.date_before = _dt_to_ts(self._dt_before.dateTime())
        else:
            spec.date_after = None
            spec.date_before = None
        spec.combine_and = self._rb_and.isChecked()
        return spec

    def _validate(self):
        spec = self._gather_spec()
        if self._chk_size.isChecked():
            lo = self._spin_min_mb.value()
            hi = self._spin_max_mb.value()
            if lo > 0 and hi > 0 and lo > hi:
                QMessageBox.warning(
                    self,
                    "Filter",
                    "Minimum size cannot be greater than maximum size.",
                )
                return False
        if self._chk_date.isChecked():
            if self._dt_after.dateTime() > self._dt_before.dateTime():
                QMessageBox.warning(
                    self,
                    "Filter",
                    "'Modified after' must be before or equal to 'Modified before'.",
                )
                return False
        return True

    def _state_dict(self):
        mode = "contains"
        if self._rb_wildcard.isChecked():
            mode = "wildcard"
        elif self._rb_regex.isChecked():
            mode = "regex"
        kind = "all"
        if self._rb_kind_dirs.isChecked():
            kind = "dirs"
        elif self._rb_kind_files.isChecked():
            kind = "files"
        return {
            "filter_text": self._filter_text.text(),
            "filter_exclude_text": self._filter_exclude.text(),
            "filter_extensions": self._filter_extensions.text(),
            "filter_words_combine_and": self._rb_words_and.isChecked(),
            "filter_mode": mode,
            "filter_kind": kind,
            "filter_include_subfolders": self._chk_subfolders.isChecked(),
            "filter_advanced": self._gather_spec().to_dict(),
        }

    def _onApply(self):
        if not self._validate():
            return
        self._file_panel.applyFilterState(self._state_dict())
        self._load_from_panel()

    def _onOk(self):
        if not self._validate():
            return
        self._file_panel.applyFilterState(self._state_dict())
        self.accept()

    def _onClearClicked(self):
        self._file_panel.clearFilter()
        self._load_from_panel()

    def _onPresetLoad(self):
        idx = self._preset_combo.currentIndex()
        if idx < 0:
            return
        payload = self._preset_combo.currentData()
        if not payload or not isinstance(payload, dict):
            return
        pl = payload.get("payload")
        if not isinstance(pl, dict):
            return
        self._applyFilterState(pl)

    def _onPresetSave(self):
        name, ok = QInputDialog.getText(self, "Save filter", "Preset name:")
        if not ok or not name.strip():
            return
        if not self._validate():
            return
        entry = {"name": name.strip(), "payload": self._state_dict()}
        presets = []
        if self._settings is not None:
            presets = list(self._settings.getSavedFileFilters())
        replaced = False
        for i, p in enumerate(presets):
            if p.get("name") == entry["name"]:
                presets[i] = entry
                replaced = True
                break
        if not replaced:
            presets.append(entry)
        if self._settings is not None:
            self._settings.setSavedFileFilters(presets)
            self._settings.saveState()
        self._reloadPresetCombo()
        idx = self._preset_combo.findText(entry["name"])
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _onPresetDelete(self):
        idx = self._preset_combo.currentIndex()
        if idx < 0:
            return
        name = self._preset_combo.currentText()
        if QMessageBox.question(
            self,
            "Delete preset",
            f"Remove saved filter “{name}”?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        presets = []
        if self._settings is not None:
            presets = [
                p
                for p in self._settings.getSavedFileFilters()
                if p.get("name") != name
            ]
            self._settings.setSavedFileFilters(presets)
            self._settings.saveState()
        self._reloadPresetCombo()

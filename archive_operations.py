"""
Total Commander Clone - Archive extract and compress workers

Both run on the file-operation queue. Extract pulls members out
with 7-Zip into a hidden staging folder, then moves them with the
same conflict dialog copy and move already use. Compress builds a
new archive next to the selection or in the other panel.
"""

import os
import shutil
import subprocess
import threading
import uuid

from archive_backend import (
    COMPRESSION_LEVELS,
    PIPED_COMPRESS_TYPES,
    ArchiveToolError,
    _killProcess,
    _popenKwargs,
    _short7zError,
    buildCompressArgs,
    buildExtractArgs,
    find7zExecutable,
    parseProgressPercent,
    readProcess,
    stream7z,
)
from file_operations import FileOperationWorker, UserAbortError


# ------------------------------------------------------------
# Class: ArchiveExtractWorker
# Purpose: Extract an archive, or selected members, into a folder.
#          members is None for the whole archive. Each member is
#          a path inside the archive using "/".
# ------------------------------------------------------------
class ArchiveExtractWorker(FileOperationWorker):

    OPERATION_EXTRACT = "extract"

    def __init__(self, archive_path, members, destination, password="", parent=None):
        listed = list(members) if members else [archive_path]
        super().__init__(self.OPERATION_EXTRACT, listed, destination, parent)
        self._archive_path = archive_path
        self._members = list(members) if members else None
        self._password = password or ""

    def run(self):
        destination = self._destination
        if not destination:
            self.operationFinished.emit(False, "No destination folder.")
            return
        staging = os.path.join(
            destination, f".tcc-extract-{uuid.uuid4().hex[:10]}"
        )
        try:
            os.makedirs(destination, exist_ok=True)
            os.makedirs(staging, exist_ok=True)
            self._extractToStaging(staging)
            items = self._stagedItems(staging)
            total = max(1, len(items))
            for index, source in enumerate(items):
                if self._cancelled:
                    raise UserAbortError()
                self._moveItem(source, destination, index, total)
            self.progressChanged.emit(100, "", "Done")
            count = len(items)
            self.operationFinished.emit(True, f"Extracted {count} item(s).")
        except UserAbortError:
            self.operationFinished.emit(False, "Operation cancelled.")
        except ArchiveToolError as exc:
            self.operationFinished.emit(False, str(exc))
        except Exception as exc:
            self.operationFinished.emit(False, str(exc))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _extractToStaging(self, staging):
        name = os.path.basename(self._archive_path) or "archive"

        def _onLine(line):
            percent = parseProgressPercent(line)
            if percent is None:
                return
            self.progressChanged.emit(percent, name, "Extracting...")

        code, output, cancelled = stream7z(
            buildExtractArgs(
                self._archive_path,
                staging,
                members=self._members,
                password=self._password,
            ),
            on_line=_onLine,
            cancel_check=lambda: self._cancelled,
        )
        if cancelled:
            raise UserAbortError()
        if code is None:
            raise ArchiveToolError(output or "7-Zip is not available.")
        if code != 0:
            message = _short7zError(output) or f"7-Zip failed (exit {code})."
            raise OSError(message)

    def _stagedItems(self, staging):
        """Top-level items to move into the destination."""
        if not self._members:
            try:
                names = sorted(os.listdir(staging))
            except OSError as exc:
                raise OSError(exc.strerror or str(exc)) from exc
            return [os.path.join(staging, name) for name in names]

        items = []
        for member in self._members:
            rel = member.replace("/", os.sep).replace("\\", os.sep).strip(os.sep)
            if not rel or ".." in rel.split(os.sep):
                raise OSError(f"Invalid archive path: {member}")
            path = os.path.join(staging, rel)
            if not os.path.lexists(path):
                raise OSError(f"7-Zip did not extract:\n{member}")
            items.append(path)
        return items


# ------------------------------------------------------------
# Class: ArchiveCompressWorker
# Purpose: Create one archive from the selected files.
#          Paths stored in the archive are relative to base_dir,
#          which is the folder the panel was showing.
# ------------------------------------------------------------
class ArchiveCompressWorker(FileOperationWorker):

    OPERATION_COMPRESS = "compress"

    def __init__(
        self,
        sources,
        archive_out,
        fmt,
        level,
        password="",
        base_dir="",
        parent=None,
    ):
        super().__init__(self.OPERATION_COMPRESS, list(sources), archive_out, parent)
        self._fmt = fmt or "zip"
        self._level = level or "normal"
        self._password = password or ""
        self._base_dir = base_dir or ""

    def run(self):
        archive_out = self._destination
        if not archive_out or not self._file_paths:
            self.operationFinished.emit(False, "Nothing to compress.")
            return
        existed = os.path.lexists(archive_out)
        try:
            parent = os.path.dirname(archive_out)
            if parent:
                os.makedirs(parent, exist_ok=True)
            names = self._relativeNames()
            if self._fmt in PIPED_COMPRESS_TYPES:
                self._compressPiped(names)
            else:
                self._compressDirect(names)
            self.progressChanged.emit(100, os.path.basename(archive_out), "Done")
            self.operationFinished.emit(
                True, f"Compressed {len(names)} item(s)."
            )
        except UserAbortError:
            self._removeNewOutput(existed)
            self.operationFinished.emit(False, "Operation cancelled.")
        except ArchiveToolError as exc:
            self._removeNewOutput(existed)
            self.operationFinished.emit(False, str(exc))
        except Exception as exc:
            self._removeNewOutput(existed)
            self.operationFinished.emit(False, str(exc))

    def _relativeNames(self):
        base = self._base_dir or os.path.dirname(self._file_paths[0])
        names = []
        for source in self._file_paths:
            try:
                rel = os.path.relpath(source, base)
            except ValueError as exc:
                raise OSError(str(exc)) from exc
            parts = rel.split(os.sep)
            if not parts or ".." in parts or rel in (".", ""):
                raise OSError(f"Path is outside the folder being compressed:\n{source}")
            names.append(rel)
        return names

    def _onLine(self, line):
        percent = parseProgressPercent(line)
        if percent is None:
            return
        name = os.path.basename(self._destination) or "archive"
        self.progressChanged.emit(percent, name, "Compressing...")

    def _compressDirect(self, names):
        code, output, cancelled = stream7z(
            buildCompressArgs(
                self._destination,
                names,
                self._fmt,
                self._level,
                password=self._password,
            ),
            cwd=self._base_dir or None,
            on_line=self._onLine,
            cancel_check=lambda: self._cancelled,
        )
        self._checkResult(code, output, cancelled)

    def _compressPiped(self, names):
        """tar on stdout, then gzip or xz. Used for .tar.gz and .tar.xz.

        stderr of the tar process stays off the pipe so messages are
        not stored as archive bytes.
        """
        second_type = PIPED_COMPRESS_TYPES[self._fmt]
        level = (COMPRESSION_LEVELS.get(self._level) or COMPRESSION_LEVELS["normal"])["mx"]
        exe = find7zExecutable()
        if not exe:
            raise ArchiveToolError("7-Zip is not available.")
        first = None
        second = None
        try:
            # "archive.tar" is the name of the stream. -so writes it to
            # stdout, so that file is not created on disk. Without a name,
            # 7-Zip treats the first real file as the archive.
            first = subprocess.Popen(
                [exe, "a", "-ttar", "-so", "-y", "-bso0", "-bsp0", "archive.tar", "--", *names],
                cwd=self._base_dir or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_popenKwargs(),
            )
            second = subprocess.Popen(
                [
                    exe, "a", f"-t{second_type}", "-si", "-y", "-bsp1",
                    "-sccUTF-8", f"-mx={level}", "--", self._destination,
                ],
                stdin=first.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **_popenKwargs(),
            )
        except OSError as exc:
            _killProcess(first)
            raise ArchiveToolError(str(exc)) from exc
        if first.stdout is not None:
            first.stdout.close()

        first_errors = []

        def _drain():
            try:
                first_errors.append(first.stderr.read())
            except OSError:
                pass

        drainer = threading.Thread(target=_drain, daemon=True)
        drainer.start()

        def _cancel():
            if self._cancelled:
                _killProcess(second)
                _killProcess(first)
                return True
            return False

        code, output, cancelled = readProcess(
            second, on_line=self._onLine, cancel_check=_cancel
        )
        if cancelled:
            _killProcess(first)
            raise UserAbortError()
        try:
            first_code = first.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _killProcess(first)
            first_code = first.poll()
        drainer.join(timeout=2)
        if first.stderr is not None:
            try:
                first.stderr.close()
            except OSError:
                pass
        if first_code not in (0, None):
            err = b"".join(first_errors).decode("utf-8", errors="replace")
            raise OSError(_short7zError(err) or f"7-Zip failed (exit {first_code}).")
        self._checkResult(code, output, False)

    def _checkResult(self, code, output, cancelled):
        if cancelled:
            raise UserAbortError()
        if code is None:
            raise ArchiveToolError(output or "7-Zip is not available.")
        if code != 0:
            raise OSError(_short7zError(output) or f"7-Zip failed (exit {code}).")

    def _removeNewOutput(self, existed):
        if existed or not self._destination:
            return
        try:
            if os.path.isfile(self._destination):
                os.remove(self._destination)
            elif os.path.isdir(self._destination):
                shutil.rmtree(self._destination, ignore_errors=True)
        except OSError:
            pass

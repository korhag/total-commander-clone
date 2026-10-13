"""
Windows shell clipboard helpers for Explorer-compatible file copy/cut.
"""

import os


if os.name == "nt":
    import ctypes
    import time
    from ctypes import wintypes


    # ------------------------------------------------------------
    # Win32 constants and structures used to publish a CF_HDROP
    # payload plus the Preferred DropEffect for Explorer paste.
    # ------------------------------------------------------------
    CF_HDROP = 15
    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040
    DROPEFFECT_COPY = 0x00000001
    DROPEFFECT_MOVE = 0x00000002

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = ()
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = ()
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = (wintypes.UINT,)
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = (wintypes.LPCWSTR,)
    user32.RegisterClipboardFormatW.restype = wintypes.UINT


    class POINT(ctypes.Structure):
        _fields_ = [
            ("x", wintypes.LONG),
            ("y", wintypes.LONG),
        ]


    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", wintypes.DWORD),
            ("pt", POINT),
            ("fNC", wintypes.BOOL),
            ("fWide", wintypes.BOOL),
        ]


    # ------------------------------------------------------------
    # Helper: Try to open the clipboard a few times because
    # another application can briefly hold a clipboard lock.
    # ------------------------------------------------------------
    def _openClipboardWithRetry(retries=10, delay_seconds=0.02):
        for _ in range(retries):
            if user32.OpenClipboard(None):
                return True
            time.sleep(delay_seconds)
        return False


    # ------------------------------------------------------------
    # Helper: Allocate movable global memory and copy bytes into
    # it. Ownership is transferred to the clipboard on success.
    # ------------------------------------------------------------
    def _createGlobalMemory(payload):
        size = len(payload)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            ctypes.memmove(pointer, payload, size)
        finally:
            kernel32.GlobalUnlock(handle)

        return handle


    # ------------------------------------------------------------
    # Helper: Build the UTF-16 DROPFILES payload for CF_HDROP.
    # ------------------------------------------------------------
    def _buildDropFilesPayload(paths):
        normalized_paths = [os.path.normpath(path) for path in paths]
        files_blob = ("\0".join(normalized_paths) + "\0\0").encode("utf-16le")

        dropfiles = DROPFILES()
        dropfiles.pFiles = ctypes.sizeof(DROPFILES)
        dropfiles.pt = POINT(0, 0)
        dropfiles.fNC = False
        dropfiles.fWide = True

        header = ctypes.string_at(ctypes.byref(dropfiles), ctypes.sizeof(dropfiles))
        return header + files_blob


    # ------------------------------------------------------------
    # Function: setFileClipboard
    # Purpose: Publish a file list to the Windows clipboard in a
    # format that File Explorer can paste as copy or move.
    # ------------------------------------------------------------
    def setFileClipboard(paths, mode="copy"):
        existing_paths = [path for path in paths if path and os.path.exists(path)]
        if not existing_paths:
            return False

        preferred_effect = DROPEFFECT_MOVE if mode == "cut" else DROPEFFECT_COPY
        effect_format = user32.RegisterClipboardFormatW("Preferred DropEffect")

        drop_handle = None
        effect_handle = None
        clipboard_open = False

        try:
            drop_handle = _createGlobalMemory(_buildDropFilesPayload(existing_paths))
            effect_handle = _createGlobalMemory(preferred_effect.to_bytes(4, "little"))

            if not _openClipboardWithRetry():
                return False
            clipboard_open = True

            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())

            if not user32.SetClipboardData(CF_HDROP, drop_handle):
                raise ctypes.WinError(ctypes.get_last_error())
            drop_handle = None

            effect_set = bool(effect_format) and bool(
                user32.SetClipboardData(effect_format, effect_handle)
            )
            if effect_set:
                effect_handle = None
            elif mode == "cut":
                # Without the move effect a paste would copy instead of move.
                user32.EmptyClipboard()
                return False

            return True
        finally:
            if drop_handle:
                kernel32.GlobalFree(drop_handle)
            if effect_handle:
                kernel32.GlobalFree(effect_handle)
            if clipboard_open:
                user32.CloseClipboard()


    # ------------------------------------------------------------
    # Function: getClipboardDropEffect
    # Purpose: Read Explorer "Preferred DropEffect" (copy vs cut/move)
    #          from the clipboard. Returns "copy", "move", or None.
    # ------------------------------------------------------------
    def getClipboardDropEffect():
        effect_format = user32.RegisterClipboardFormatW("Preferred DropEffect")
        if not effect_format:
            return None
        if not _openClipboardWithRetry():
            return None
        try:
            handle = user32.GetClipboardData(effect_format)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                val = int.from_bytes(ctypes.string_at(ptr, 4), "little")
            finally:
                kernel32.GlobalUnlock(handle)
            if val & DROPEFFECT_MOVE:
                return "move"
            if val & DROPEFFECT_COPY:
                return "copy"
            return None
        finally:
            user32.CloseClipboard()


else:
    # ------------------------------------------------------------
    # Non-Windows fallback keeps the rest of the app logic
    # working without trying to publish shell clipboard data.
    # ------------------------------------------------------------
    def setFileClipboard(paths, mode="copy"):
        return False

    def getClipboardDropEffect():
        return None

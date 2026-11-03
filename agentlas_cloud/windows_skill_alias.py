"""Create one Windows skill alias while holding no-reparse ancestor handles.

No replacement or cleanup of an existing alias is attempted. A denied sharing
mode, missing symlink privilege, or unsupported API leaves an explicit conflict.
"""
from __future__ import annotations



class _WindowsAPI:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.library = ctypes.WinDLL('kernel32', use_last_error=True)
        self.library.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.library.CreateFileW.restype = wintypes.HANDLE
        self.library.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
            ctypes.c_void_p, wintypes.DWORD]
        self.library.GetFileInformationByHandleEx.restype = wintypes.BOOL
        self.library.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
        self.library.CreateDirectoryW.restype = wintypes.BOOL
        self.library.CreateSymbolicLinkW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        self.library.CreateSymbolicLinkW.restype = ctypes.c_ubyte
        self.library.CloseHandle.argtypes = [wintypes.HANDLE]
        self.library.CloseHandle.restype = wintypes.BOOL

    def _raise(self):
        raise self.ctypes.WinError(self.ctypes.get_last_error())

    def open_directory(self, path):
        # FILE_READ_ATTRIBUTES, FILE_SHARE_READ only, OPEN_EXISTING,
        # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT.
        # Omitting SHARE_WRITE/DELETE prevents replacement or reparse mutation
        # while descendants are opened and the final link is created.
        handle = self.library.CreateFileW(str(path), 0x80, 1, None, 3, 0x02200000, None)
        if handle == self.ctypes.c_void_p(-1).value:
            self._raise()
        try:
            attributes = (self.ctypes.c_uint32 * 2)()
            if not self.library.GetFileInformationByHandleEx(handle, 9,
                    self.ctypes.byref(attributes), self.ctypes.sizeof(attributes)):
                self._raise()
            if attributes[0] & 0x400 or not attributes[0] & 0x10:
                from .host_core import Conflict
                raise Conflict('codex_windows_parent_reparse_or_not_directory')
            return handle
        except BaseException:
            self.close(handle)
            raise

    def mkdir(self, path):
        if not self.library.CreateDirectoryW(str(path), None):
            if self.ctypes.get_last_error() != 183:
                self._raise()

    def symlink(self, alias, target):
        # Unprivileged creation requires Developer Mode. On older Windows,
        # retry only an unsupported flag; ordinary privilege errors stay errors.
        if self.library.CreateSymbolicLinkW(str(alias), str(target), 3):
            return
        if self.ctypes.get_last_error() == 87:
            if self.library.CreateSymbolicLinkW(str(alias), str(target), 1):
                return
        self._raise()

    def close(self, handle):
        if not self.library.CloseHandle(handle):
            self._raise()


def publish(alias, target, *, api=None):
    from .host_core import Conflict
    handles = []
    try:
        api = api or _WindowsAPI()
        for directory in reversed((alias.parent, *alias.parent.parents)):
            try:
                handle = api.open_directory(directory)
            except OSError as exc:
                if getattr(exc, 'winerror', None) not in (2, 3):
                    raise
                # The existing parent is already locked. Concurrent creation
                # is accepted only after opening and checking that exact child.
                if not handles:
                    raise
                api.mkdir(directory)
                handle = api.open_directory(directory)
            handles.append(handle)
        api.symlink(alias, target)
        if not alias.is_symlink() or alias.resolve(strict=True) != target:
            raise Conflict('codex_skill_alias_changed')
    except OSError as exc:
        code = getattr(exc, 'winerror', None)
        if code in (80, 183):
            raise Conflict('codex_skill_alias_concurrent_collision')
        if code == 1314:
            raise Conflict('codex_windows_symlink_privilege_required')
        raise Conflict('codex_windows_skill_alias_create_failed:' + str(code or exc.errno))
    except AttributeError:
        raise Conflict('codex_windows_skill_alias_api_unavailable')
    finally:
        # Attempt every close, including after a failure partway down the path.
        close_error = None
        for handle in reversed(handles):
            try:
                api.close(handle)
            except OSError as exc:
                close_error = exc
        if close_error is not None:
            raise Conflict('codex_windows_directory_handle_close_failed')

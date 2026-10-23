"""Inspect only a scoped per-user TechScout backend before Windows maintenance.

No process is stopped here. Native process data establishes the executable,
command line and actual working directory; a matching port alone proves nothing.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import ntpath
import os
from pathlib import Path
import sys


def canonical(path: str) -> str:
    if path.startswith("\\\\?\\"):
        path = path[4:]
    return ntpath.normcase(ntpath.normpath(path))


def classify_process(argv: list[str], executable: str, cwd: str, app: str, *, base_executable=None, parent=None) -> dict:
    module = any(argv[index:index + 2] == ["-m", "alerters.techscout"] for index in range(len(argv) - 1))
    candidate = module and "--serve" in argv
    result = {"recognized": False, "is_techscout": candidate,
              "app_scope": canonical(cwd) == canonical(app)}
    if not candidate or not result["app_scope"]:
        return result

    def option(name):
        values = []
        for index, value in enumerate(argv):
            if value == name and index + 1 < len(argv):
                values.append(argv[index + 1])
            elif value.startswith(name + "="):
                values.append(value.partition("=")[2])
        return values[0] if len(values) == 1 else None

    settings, output = option("--settings"), option("--output")
    if not settings or not output or not ntpath.isabs(settings) or not ntpath.isabs(output):
        return result
    local = ntpath.dirname(settings)
    wrappers = {canonical(ntpath.join(local, "venv", "Scripts", name)) for name in ("python.exe", "pythonw.exe")}
    direct = canonical(executable) in wrappers
    child = bool(base_executable and canonical(executable) == canonical(base_executable)
                 and parent and parent.get("recognized")
                 and canonical(parent.get("data_directory", "")) == canonical(local)
                 and canonical(parent.get("executable", "")) in wrappers)
    if (canonical(ntpath.basename(settings)) != "settings.json"
            or canonical(output) != canonical(ntpath.join(local, "reports"))
            or not (direct or child)):
        return result
    return {**result, "recognized": True, "data_directory": local,
            "executable": executable, "app": app,
            **({"venv_wrapper_pid": parent["pid"]} if child else {})}


def native_process(pid: int) -> tuple[list[str], str, str, int]:
    """Read a same-architecture Windows process without executing its code."""
    from ctypes import wintypes

    if os.name != "nt":
        raise OSError("Windows process inspection is required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel.ReadProcessMemory.restype = wintypes.BOOL
    kernel.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x0410, False, pid)  # query information + VM read
    if not handle:
        raise OSError("Process could not be inspected")
    try:
        target_wow, current_wow = wintypes.BOOL(), wintypes.BOOL()
        if (not kernel.IsWow64Process(handle, ctypes.byref(target_wow))
                or not kernel.IsWow64Process(kernel.GetCurrentProcess(), ctypes.byref(current_wow))
                or target_wow.value != current_wow.value):
            raise OSError("Process architecture cannot be inspected safely")

        class BasicInfo(ctypes.Structure):
            _fields_ = [("reserved", ctypes.c_void_p), ("peb", ctypes.c_void_p),
                        ("reserved2", ctypes.c_void_p * 2), ("pid", ctypes.c_void_p),
                        ("reserved3", ctypes.c_void_p)]

        class UnicodeString(ctypes.Structure):
            _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT),
                        ("buffer", ctypes.c_void_p)]

        def read(address, count):
            buffer = ctypes.create_string_buffer(count)
            received = ctypes.c_size_t()
            if not kernel.ReadProcessMemory(handle, address, buffer, count, ctypes.byref(received)) or received.value != count:
                raise OSError("Process memory could not be inspected")
            return buffer.raw

        info = BasicInfo()
        status = ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None)
        if status != 0 or not info.peb:
            raise OSError("Process parameters are unavailable")
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        parameters_offset, cwd_offset, command_offset = ((0x20, 0x38, 0x70) if pointer_size == 8 else (0x10, 0x24, 0x40))
        parameters = int.from_bytes(read(info.peb + parameters_offset, pointer_size), "little")

        def string(offset):
            value = UnicodeString.from_buffer_copy(read(parameters + offset, ctypes.sizeof(UnicodeString)))
            if not value.buffer or value.length > 32768 or value.length % 2:
                raise OSError("Invalid process string")
            return read(value.buffer, value.length).decode("utf-16-le")

        cwd, command = string(cwd_offset), string(command_offset)
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise OSError("Process executable is unavailable")
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        argc = ctypes.c_int()
        args = shell.CommandLineToArgvW(command, ctypes.byref(argc))
        if not args:
            raise OSError("Process command line cannot be parsed")
        try:
            argv = [args[index] for index in range(argc.value)]
        finally:
            kernel.LocalFree(args)
        return argv, image.value, cwd, int(info.reserved3 or 0)
    finally:
        kernel.CloseHandle(handle)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--app", required=True)
    args = parser.parse_args(argv)
    try:
        command, executable, cwd, parent_pid = native_process(args.pid)
        result = classify_process(command, executable, cwd, args.app)
        if result.get("is_techscout") and result.get("app_scope") and not result["recognized"] and parent_pid:
            parent_command, parent_exe, parent_cwd, _ = native_process(parent_pid)
            parent = {**classify_process(parent_command, parent_exe, parent_cwd, args.app), "pid": parent_pid}
            if parent["recognized"]:
                cfg = Path(parent["data_directory"]) / "venv" / "pyvenv.cfg"
                values = dict(line.strip().split(" = ", 1) for line in cfg.read_text(encoding="utf-8").splitlines() if " = " in line)
                base = ntpath.join(values.get("home", ""), ntpath.basename(executable))
                result = classify_process(command, executable, cwd, args.app, base_executable=base, parent=parent)
        print(json.dumps({**result, "pid": args.pid}))
        return 0
    except (OSError, ValueError, UnicodeError):
        # Never print another process's raw command line or memory.
        print(json.dumps({"recognized": False, "pid": args.pid, "inspection_error": True}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

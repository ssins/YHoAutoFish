import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath


APP_NAME = "YHoAutoFish"
PROTECTED_NAMES = {
    "config.json",
    "records.json",
    "records.db",
    "records - 副本.json",
}
PROTECTED_DIRS = {
    "logs",
    "screenshots",
    "captures",
}
PROTECTED_PREFIXES = (
    ".records.",
    "debug_",
)


def log(app_dir, message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    try:
        logs_dir = Path(app_dir) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with open(logs_dir / "update.log", "a", encoding="utf-8") as file:
            file.write(line)
    except OSError:
        pass


def wait_for_process_exit(pid, timeout=60):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 0 or os.name != "nt":
        time.sleep(1.5)
        return

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    user_timeout_ms = int(max(1, timeout) * 1000)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    wait_for_single_object.restype = ctypes.c_uint32
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    handle = open_process(synchronize, False, pid)
    if not handle:
        time.sleep(1.5)
        return
    try:
        result = wait_for_single_object(handle, user_timeout_ms)
        if result == wait_timeout:
            raise TimeoutError("主程序退出等待超时")
    finally:
        close_handle(handle)


def safe_member_path(extract_root, member_name):
    member_path = PurePosixPath(member_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise RuntimeError(f"更新包包含非法路径: {member_name}")
    target = (extract_root / Path(*member_path.parts)).resolve()
    root = extract_root.resolve()
    if target != root and root not in target.parents:
        raise RuntimeError(f"更新包路径越界: {member_name}")
    return target


def extract_zip_safely(zip_path, extract_root):
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            target = safe_member_path(extract_root, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as destination:
                shutil.copyfileobj(source, destination)


def find_payload_root(extract_root, exe_name):
    direct = extract_root / exe_name
    if direct.exists():
        return extract_root
    children = [path for path in extract_root.iterdir() if path.is_dir()]
    for child in children:
        if (child / exe_name).exists():
            return child
    if len(children) == 1:
        return children[0]
    raise RuntimeError(f"更新包内未找到 {exe_name}")


def is_protected(relative_path):
    parts = relative_path.parts
    if not parts:
        return True
    first = parts[0].lower()
    name = relative_path.name.lower()
    if first in PROTECTED_DIRS:
        return True
    if name in PROTECTED_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def copy_with_retries(source, target, attempts=8):
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for _ in range(attempts):
        try:
            shutil.copy2(source, target)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.5)
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)
    raise last_error or RuntimeError(f"复制失败: {source} -> {target}")


def apply_payload(payload_root, app_dir):
    copied = 0
    skipped = 0
    for source in payload_root.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(payload_root)
        if is_protected(relative):
            skipped += 1
            continue
        copy_with_retries(source, app_dir / relative)
        copied += 1
    return copied, skipped


def restart_app(app_dir, exe_name):
    exe_path = app_dir / exe_name
    if exe_path.exists():
        subprocess.Popen([str(exe_path)], cwd=str(app_dir), close_fds=True)


def remove_if_temp(path):
    try:
        temp_root = Path(tempfile.gettempdir()).resolve()
        resolved = Path(path).resolve()
        if resolved != temp_root and temp_root in resolved.parents and resolved.exists():
            resolved.unlink()
    except OSError:
        pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="YHo AutoFish external updater")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--exe", default=f"{APP_NAME}.exe")
    parser.add_argument("--wait-timeout", type=int, default=90)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app_dir = Path(args.app_dir).resolve()
    package = Path(args.package).resolve()
    extract_root = Path(tempfile.gettempdir()) / APP_NAME / "apply" / str(os.getpid())

    try:
        log(app_dir, "更新器已启动，等待主程序退出")
        wait_for_process_exit(args.pid, timeout=args.wait_timeout)
        log(app_dir, "开始解压更新包")
        extract_zip_safely(package, extract_root)
        payload_root = find_payload_root(extract_root, args.exe)
        copied, skipped = apply_payload(payload_root, app_dir)
        log(app_dir, f"文件覆盖完成，复制 {copied} 个文件，跳过用户数据 {skipped} 个文件")
        restart_app(app_dir, args.exe)
        log(app_dir, "新版主程序已启动")
        remove_if_temp(package)
        return 0
    except Exception as exc:
        log(app_dir, f"更新失败: {exc}")
        return 1
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

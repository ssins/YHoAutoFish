import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.paths import app_base_dir
from core.version import APP_NAME, APP_REPOSITORY_URL, APP_VERSION


LATEST_RELEASE_API = "https://api.github.com/repos/FADEDTUMI/YHoAutoFish/releases/latest"
LATEST_MANIFEST_URL = f"{APP_REPOSITORY_URL}/releases/latest/download/latest.json"
ENABLE_GITHUB_API_FALLBACK = False
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
MIRROR_PREFIXES = (
    "https://gh.llkk.cc/",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
)


class UpdateError(RuntimeError):
    pass


class NoPublishedRelease(UpdateError):
    pass


class ManifestUnavailable(UpdateError):
    pass


@dataclass
class UpdateInfo:
    version: str
    tag_name: str
    release_name: str
    body: str
    asset_name: str
    download_url: str
    html_url: str
    digest: str = ""

    @property
    def sha256(self):
        prefix = "sha256:"
        value = (self.digest or "").strip()
        if value.lower().startswith(prefix):
            return value[len(prefix):].strip().lower()
        if re.fullmatch(r"[a-fA-F0-9]{64}", value):
            return value.lower()
        return ""


def parse_version(version_text):
    parts = re.findall(r"\d+", str(version_text or ""))
    normalized = [int(part) for part in parts[:4]]
    while len(normalized) < 4:
        normalized.append(0)
    return tuple(normalized)


def is_newer_version(remote_version, current_version=APP_VERSION):
    return parse_version(remote_version) > parse_version(current_version)


def _request(url, timeout=8, api=False):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": USER_AGENT,
    }
    if api:
        headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _load_json(url, timeout=8, label="GitHub Release 信息", api=False):
    try:
        with _request(url, timeout=timeout, api=api) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            text = response.read().decode(charset, errors="replace").lstrip("\ufeff")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        message = _format_http_error(exc)
        if exc.code == 404:
            if label == "更新清单":
                raise ManifestUnavailable(message) from exc
            raise NoPublishedRelease(message) from exc
        raise UpdateError(message) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"无法连接 GitHub: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        if label == "更新清单" and _looks_like_html(text):
            raise ManifestUnavailable("更新清单尚未发布，或当前网络返回了网页而不是 JSON") from exc
        raise UpdateError(f"{label}不是有效 JSON") from exc


def _looks_like_html(text):
    sample = str(text or "").lstrip()[:256].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<html" in sample


def _format_http_error(exc):
    detail = ""
    try:
        charset = exc.headers.get_content_charset() or "utf-8"
        raw_body = exc.read().decode(charset, errors="replace")
        payload = json.loads(raw_body) if raw_body else {}
        detail = str(payload.get("message") or "").strip()
    except Exception:
        detail = ""

    if exc.code == 404:
        return "当前仓库还没有可用于自动更新的正式 GitHub Release"

    if exc.code == 403:
        remaining = (exc.headers.get("X-RateLimit-Remaining") or "").strip()
        reset_at = _format_rate_limit_reset(exc.headers.get("X-RateLimit-Reset"))
        retry_after = (exc.headers.get("Retry-After") or "").strip()
        if remaining == "0":
            suffix = f"，预计 {reset_at} 后恢复" if reset_at else ""
            return f"GitHub API 请求已达到未登录限额{suffix}"
        if retry_after:
            return f"GitHub API 暂时拒绝频繁请求，建议 {retry_after} 秒后再试"
        if detail:
            return f"GitHub API 访问被拒绝: {detail}"
        return "GitHub API 访问被拒绝，可能是网络代理、限流或仓库权限导致"

    if detail:
        return f"GitHub 返回 HTTP {exc.code}: {detail}"
    return f"GitHub 返回 HTTP {exc.code}"


def _format_rate_limit_reset(value):
    try:
        reset_ts = int(value)
    except (TypeError, ValueError):
        return ""
    if reset_ts <= 0:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(reset_ts))


def _version_from_tag(tag_name):
    return str(tag_name or "").strip().lstrip("vV")


def _expected_asset_name(version):
    return f"{APP_NAME}-v{version}-windows.zip"


def _latest_asset_download_url(asset_name):
    return f"{APP_REPOSITORY_URL}/releases/latest/download/{asset_name}"


def _is_repo_release_download_url(url):
    return str(url or "").startswith(f"{APP_REPOSITORY_URL}/releases/download/")


def _select_release_asset(release, version):
    assets = release.get("assets") or []
    expected = _expected_asset_name(version).lower()
    fallback = None
    for asset in assets:
        name = str(asset.get("name") or "")
        lower_name = name.lower()
        if lower_name == expected:
            return asset
        if (
            fallback is None
            and lower_name.endswith(".zip")
            and APP_NAME.lower() in lower_name
            and "windows" in lower_name
        ):
            fallback = asset
    return fallback


def _latest_manifest_candidates():
    urls = [LATEST_MANIFEST_URL]
    urls.extend(mirrored_url(LATEST_MANIFEST_URL, prefix) for prefix in MIRROR_PREFIXES)
    return urls


def _load_latest_manifest(timeout=8):
    errors = []
    for url in _latest_manifest_candidates():
        try:
            return _load_json(url, timeout=timeout, label="更新清单", api=False)
        except NoPublishedRelease:
            return None
        except ManifestUnavailable:
            continue
        except UpdateError as exc:
            errors.append(str(exc))
    if errors:
        raise UpdateError("无法获取更新清单：" + "；".join(errors[-3:]))
    return None


def _manifest_to_update_info(manifest, current_version=APP_VERSION):
    if not isinstance(manifest, dict):
        raise UpdateError("更新清单格式错误：根节点不是 JSON 对象")

    version = _version_from_tag(manifest.get("version") or manifest.get("tag") or manifest.get("tag_name"))
    if not version:
        raise UpdateError("更新清单缺少 version")
    if not is_newer_version(version, current_version):
        return None

    tag_name = str(manifest.get("tag") or manifest.get("tag_name") or f"v{version}").strip()
    asset_name = str(manifest.get("asset_name") or _expected_asset_name(version)).strip()
    if not asset_name:
        raise UpdateError("更新清单缺少 asset_name")

    download_url = str(manifest.get("download_url") or "").strip()
    if not download_url or _is_repo_release_download_url(download_url):
        download_url = _latest_asset_download_url(asset_name)

    return UpdateInfo(
        version=version,
        tag_name=tag_name,
        release_name=str(manifest.get("release_name") or tag_name),
        body=str(manifest.get("notes") or manifest.get("body") or ""),
        asset_name=asset_name,
        download_url=download_url,
        html_url=str(manifest.get("html_url") or f"{APP_REPOSITORY_URL}/releases/latest"),
        digest=str(manifest.get("digest") or manifest.get("sha256") or ""),
    )


def check_for_update(current_version=APP_VERSION, timeout=8):
    manifest = _load_latest_manifest(timeout=timeout)
    if manifest is not None:
        return _manifest_to_update_info(manifest, current_version=current_version)
    if not ENABLE_GITHUB_API_FALLBACK:
        return None

    try:
        release = _load_json(LATEST_RELEASE_API, timeout=timeout, api=True)
    except NoPublishedRelease:
        return None
    tag_name = str(release.get("tag_name") or "")
    remote_version = _version_from_tag(tag_name)
    if not remote_version or not is_newer_version(remote_version, current_version):
        return None

    asset = _select_release_asset(release, remote_version)
    if not asset:
        raise UpdateError(f"最新版本 v{remote_version} 未找到 Windows zip 发布包")

    download_url = asset.get("browser_download_url")
    if not download_url:
        raise UpdateError("最新版本发布包缺少下载地址")

    return UpdateInfo(
        version=remote_version,
        tag_name=tag_name,
        release_name=str(release.get("name") or tag_name),
        body=str(release.get("body") or ""),
        asset_name=str(asset.get("name") or _expected_asset_name(remote_version)),
        download_url=str(download_url),
        html_url=str(release.get("html_url") or APP_REPOSITORY_URL),
        digest=str(asset.get("digest") or ""),
    )


def mirrored_url(url, prefix):
    prefix = (prefix or "").strip()
    if not prefix:
        return url
    return f"{prefix.rstrip('/')}/{url}"


def _download_once(url, target_path, progress_callback=None, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as file:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                file.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    percent = int(downloaded * 100 / total) if total else 0
                    progress_callback(max(0, min(100, percent)), downloaded, total)
    if progress_callback:
        progress_callback(100, target_path.stat().st_size, target_path.stat().st_size)


def _verify_sha256(path, expected_sha256):
    expected = (expected_sha256 or "").strip().lower()
    if not expected:
        return
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected:
        raise UpdateError("更新包 SHA256 校验失败，已拒绝安装")


def download_update(update_info, progress_callback=None, timeout=25):
    if update_info is None:
        raise UpdateError("没有可下载的更新信息")

    temp_root = Path(tempfile.gettempdir()) / APP_NAME / "downloads"
    temp_root.mkdir(parents=True, exist_ok=True)
    target_path = temp_root / update_info.asset_name
    expected_sha256 = update_info.sha256

    errors = []
    candidates = []
    for url in (update_info.download_url, _latest_asset_download_url(update_info.asset_name)):
        if url and url not in candidates:
            candidates.append(url)
    if expected_sha256:
        for base_url in list(candidates):
            for prefix in MIRROR_PREFIXES:
                mirror = mirrored_url(base_url, prefix)
                if mirror not in candidates:
                    candidates.append(mirror)

    for index, url in enumerate(candidates):
        try:
            if target_path.exists():
                target_path.unlink()
            _download_once(url, target_path, progress_callback=progress_callback, timeout=timeout)
            _verify_sha256(target_path, expected_sha256)
            return str(target_path)
        except Exception as exc:
            errors.append(str(exc))
            try:
                if target_path.exists():
                    target_path.unlink()
            except OSError:
                pass
            if index == 0 and progress_callback:
                progress_callback(0, 0, 0)

    raise UpdateError("更新包下载失败：" + "；".join(errors[-3:]))


def cleanup_old_update_runners(max_age_seconds=86400):
    root = Path(tempfile.gettempdir()) / APP_NAME / "runners"
    if not root.exists():
        return
    now = time.time()
    for child in root.iterdir():
        try:
            if not child.is_dir():
                continue
            if now - child.stat().st_mtime >= max_age_seconds:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def prepare_updater_runner(app_dir=None):
    app_dir = Path(app_dir or app_base_dir()).resolve()
    updater = app_dir / "YHoUpdater.exe"
    if not updater.exists():
        raise UpdateError("未找到 YHoUpdater.exe，当前版本不支持全自动更新")

    cleanup_old_update_runners()
    runner_dir = Path(tempfile.gettempdir()) / APP_NAME / "runners" / str(os.getpid())
    runner_dir.mkdir(parents=True, exist_ok=True)
    runner_path = runner_dir / updater.name
    shutil.copy2(updater, runner_path)
    return runner_path


def start_external_update(package_path, app_dir=None, main_pid=None):
    app_dir = Path(app_dir or app_base_dir()).resolve()
    package_path = Path(package_path).resolve()
    if not package_path.exists():
        raise UpdateError("更新包不存在，无法启动更新器")

    runner_path = prepare_updater_runner(app_dir)
    args = [
        str(runner_path),
        "--pid",
        str(int(main_pid or os.getpid())),
        "--package",
        str(package_path),
        "--app-dir",
        str(app_dir),
        "--exe",
        f"{APP_NAME}.exe",
    ]
    subprocess.Popen(args, cwd=str(app_dir), close_fds=True)
    return True

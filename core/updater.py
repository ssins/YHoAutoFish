import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.paths import app_base_dir
from core.version import APP_NAME, APP_REPOSITORY_URL, APP_VERSION

try:
    from core.version import APP_GITEE_REPOSITORY_URL
except ImportError:
    APP_GITEE_REPOSITORY_URL = ""


LATEST_RELEASE_API = "https://api.github.com/repos/FADEDTUMI/YHoAutoFish/releases/latest"
LATEST_MANIFEST_URL = f"{APP_REPOSITORY_URL}/releases/latest/download/latest.json"
ENABLE_GITHUB_API_FALLBACK = False
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
DEFAULT_MIRROR_PREFIXES = (
    "https://gh.llkk.cc/",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
)
MIRROR_PREFIXES = DEFAULT_MIRROR_PREFIXES
UPDATE_CONFIG_NAME = "config.json"
UPDATE_SOURCE_GITHUB = "github"
UPDATE_SOURCE_GITEE = "gitee"
UPDATE_SOURCE_AUTO = "auto"
UPDATE_WORK_DIR_NAME = ".updates"
UPDATE_DOWNLOAD_DIR_NAME = "downloads"
UPDATE_RUNNER_DIR_NAME = "runners"


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
    download_urls: tuple = ()
    github_download_urls: tuple = ()
    gitee_download_urls: tuple = ()
    source: str = UPDATE_SOURCE_GITHUB

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
    service_name = "Gitee" if _is_gitee_url(url) else "GitHub"
    try:
        with _request(url, timeout=timeout, api=api) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            text = response.read().decode(charset, errors="replace").lstrip("\ufeff")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        message = _format_http_error(exc, service_name=service_name)
        if exc.code == 404:
            if label == "更新清单":
                raise ManifestUnavailable(message) from exc
            raise NoPublishedRelease(message) from exc
        raise UpdateError(message) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"无法连接 {service_name}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        if label == "更新清单" and _looks_like_html(text):
            raise ManifestUnavailable("更新清单尚未发布，或当前网络返回了网页而不是 JSON") from exc
        raise UpdateError(f"{label}不是有效 JSON") from exc


def _looks_like_html(text):
    sample = str(text or "").lstrip()[:256].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<html" in sample


def _format_http_error(exc, service_name="GitHub"):
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
            return f"{service_name} API 请求已达到未登录限额{suffix}"
        if retry_after:
            return f"{service_name} API 暂时拒绝频繁请求，建议 {retry_after} 秒后再试"
        if detail:
            return f"{service_name} API 访问被拒绝: {detail}"
        return f"{service_name} API 访问被拒绝，可能是网络代理、限流或仓库权限导致"

    if detail:
        return f"{service_name} 返回 HTTP {exc.code}: {detail}"
    return f"{service_name} 返回 HTTP {exc.code}"


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


def _is_github_url(url):
    normalized = str(url or "").lower()
    return normalized.startswith("https://github.com/") or normalized.startswith("https://api.github.com/")


def _is_gitee_url(url):
    normalized = str(url or "").lower()
    return normalized.startswith("https://gitee.com/") or normalized.startswith("https://api.gitee.com/")


def _coerce_url_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[\r\n,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return []
    urls = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in urls:
            urls.append(text)
    return urls


def _read_update_config():
    config_path = Path(app_base_dir()) / UPDATE_CONFIG_NAME
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def update_work_dir(app_dir=None):
    root = Path(app_dir or app_base_dir()).resolve() / UPDATE_WORK_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _update_subdir(name, app_dir=None):
    root = update_work_dir(app_dir) / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_old_children(root, max_age_seconds=86400):
    root = Path(root)
    if not root.exists():
        return
    now = time.time()
    for child in root.iterdir():
        try:
            if now - child.stat().st_mtime < max_age_seconds:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            continue


def _gitee_repository_url():
    config = _read_update_config()
    configured = str(
        config.get("gitee_repository_url")
        or config.get("update_gitee_repository_url")
        or os.environ.get("YHO_GITEE_REPOSITORY_URL")
        or APP_GITEE_REPOSITORY_URL
        or ""
    ).strip()
    return configured.rstrip("/")


def _gitee_owner_repo():
    repo_url = _gitee_repository_url()
    match = re.match(r"https?://gitee\.com/([^/]+)/([^/#?]+)", repo_url, re.IGNORECASE)
    if not match:
        return "", ""
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _env_url_list(name):
    return _coerce_url_list(os.environ.get(name))


def _config_url_list(config, *keys):
    urls = []
    for key in keys:
        for url in _coerce_url_list(config.get(key)):
            if url not in urls:
                urls.append(url)
    return urls


def _merge_urls(*groups):
    urls = []
    for group in groups:
        for url in _coerce_url_list(group):
            if url not in urls:
                urls.append(url)
    return urls


def _mirror_prefixes(manifest=None):
    config = _read_update_config()
    manifest_prefixes = []
    if isinstance(manifest, dict):
        manifest_prefixes = _coerce_url_list(manifest.get("mirror_prefixes") or manifest.get("github_mirror_prefixes"))
    return tuple(
        _merge_urls(
            _config_url_list(config, "update_mirror_prefixes", "github_mirror_prefixes"),
            _env_url_list("YHO_UPDATE_MIRROR_PREFIXES"),
            manifest_prefixes,
            DEFAULT_MIRROR_PREFIXES,
        )
    )


def _format_url_template(url, version="", tag_name="", asset_name=""):
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        return text.format(version=version, tag=tag_name, tag_name=tag_name, asset=asset_name, asset_name=asset_name)
    except Exception:
        return text


def _source_label(source):
    normalized = str(source or "").strip().lower()
    if normalized == UPDATE_SOURCE_GITEE:
        return "Gitee 国内源"
    if normalized == UPDATE_SOURCE_GITHUB:
        return "GitHub 官方源"
    return "自动源"


def _gitee_latest_release_api_url():
    owner, repo = _gitee_owner_repo()
    if not owner or not repo:
        return ""
    return f"https://gitee.com/api/v5/repos/{owner}/{repo}/releases/latest"


def _gitee_manifest_url_for_tag(tag_name):
    repo_url = _gitee_repository_url()
    tag_name = str(tag_name or "").strip()
    if not repo_url or not tag_name:
        return ""
    return f"{repo_url}/releases/download/{tag_name}/latest.json"


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


def _github_manifest_candidates():
    config = _read_update_config()
    configured_urls = _merge_urls(
        _config_url_list(config, "update_github_manifest_urls", "github_manifest_urls", "github_manifest_url"),
        _env_url_list("YHO_GITHUB_MANIFEST_URLS"),
    )
    urls = _merge_urls([LATEST_MANIFEST_URL])
    urls.extend(
        mirrored_url(LATEST_MANIFEST_URL, prefix)
        for prefix in _mirror_prefixes()
    )
    return _merge_urls(urls, configured_urls)


def _general_manifest_candidates():
    config = _read_update_config()
    return _merge_urls(
        _config_url_list(config, "update_manifest_urls", "update_manifest_url"),
        _env_url_list("YHO_UPDATE_MANIFEST_URLS"),
    )


def _gitee_manifest_candidates():
    config = _read_update_config()
    return _merge_urls(
        _config_url_list(config, "update_gitee_manifest_urls", "gitee_manifest_urls", "gitee_manifest_url"),
        _env_url_list("YHO_GITEE_MANIFEST_URLS"),
    )


def _latest_manifest_candidates():
    urls = _merge_urls(_github_manifest_candidates(), _general_manifest_candidates(), _gitee_manifest_candidates())
    api_url = _gitee_latest_release_api_url()
    if api_url:
        urls.append(api_url)
    return _merge_urls(urls)


def _load_manifest_from_urls(urls, timeout=8, source=UPDATE_SOURCE_GITHUB):
    errors = []
    for url in urls:
        try:
            manifest = _load_json(url, timeout=timeout, label="更新清单", api=False)
            if isinstance(manifest, dict):
                manifest.setdefault("source", source)
            return manifest
        except NoPublishedRelease:
            return None
        except ManifestUnavailable:
            continue
        except UpdateError as exc:
            errors.append(str(exc))
    if errors:
        raise UpdateError("无法获取更新清单：" + "；".join(errors[-3:]))
    return None


def _load_github_latest_manifest(timeout=8):
    return _load_manifest_from_urls(
        _merge_urls(_github_manifest_candidates(), _general_manifest_candidates()),
        timeout=timeout,
        source=UPDATE_SOURCE_GITHUB,
    )


def _asset_url_from_release_asset(asset):
    if not isinstance(asset, dict):
        return ""
    for key in ("browser_download_url", "download_url", "url"):
        value = str(asset.get(key) or "").strip()
        if value and value.startswith("http"):
            return value
    return ""


def _extract_release_assets(release):
    if not isinstance(release, dict):
        return []
    assets = []
    for key in ("assets", "attach_files", "attachments"):
        raw = release.get(key)
        if isinstance(raw, list):
            assets.extend(item for item in raw if isinstance(item, dict))
    return assets


def _find_release_asset_url(release, filename):
    expected = str(filename or "").strip().lower()
    for asset in _extract_release_assets(release):
        name = str(asset.get("name") or asset.get("filename") or asset.get("file_name") or "").strip().lower()
        if name == expected:
            return _asset_url_from_release_asset(asset)
    return ""


def _load_gitee_manifest_from_latest_release(timeout=8):
    api_url = _gitee_latest_release_api_url()
    if not api_url:
        return None
    release = _load_json(api_url, timeout=timeout, label="Gitee Release 信息", api=False)
    if not isinstance(release, dict):
        return None
    tag_name = str(release.get("tag_name") or release.get("tag") or "").strip()
    if not tag_name:
        tag = release.get("tag")
        if isinstance(tag, dict):
            tag_name = str(tag.get("name") or "").strip()
    if not tag_name:
        tag_name = str(release.get("name") or "").strip()
    manifest_urls = _merge_urls(
        [_find_release_asset_url(release, "latest.json")],
        [_gitee_manifest_url_for_tag(tag_name)],
    )
    manifest = _load_manifest_from_urls(manifest_urls, timeout=timeout, source=UPDATE_SOURCE_GITEE)
    if isinstance(manifest, dict):
        manifest.setdefault("tag", tag_name)
        manifest.setdefault("tag_name", tag_name)
        manifest.setdefault("html_url", str(release.get("html_url") or _gitee_repository_url()))
    return manifest


def _load_gitee_latest_manifest(timeout=8):
    configured = _load_manifest_from_urls(_gitee_manifest_candidates(), timeout=timeout, source=UPDATE_SOURCE_GITEE)
    if configured is not None:
        return configured
    return _load_gitee_manifest_from_latest_release(timeout=timeout)


def _manifest_to_update_info(manifest, current_version=APP_VERSION, source=None):
    if not isinstance(manifest, dict):
        raise UpdateError("更新清单格式错误：根节点不是 JSON 对象")
    manifest_source = str(source or manifest.get("source") or UPDATE_SOURCE_GITHUB).strip().lower()
    if manifest_source not in {UPDATE_SOURCE_GITHUB, UPDATE_SOURCE_GITEE, UPDATE_SOURCE_AUTO}:
        manifest_source = UPDATE_SOURCE_GITHUB

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
    download_urls = []
    for item in _coerce_url_list(manifest.get("download_urls") or manifest.get("asset_urls")):
        formatted = _format_url_template(item, version=version, tag_name=tag_name, asset_name=asset_name)
        if formatted and formatted not in download_urls:
            download_urls.append(formatted)
    if download_url not in download_urls:
        download_urls.append(download_url)
    github_download_urls = []
    for item in _coerce_url_list(manifest.get("github_download_urls") or manifest.get("github_asset_urls")):
        formatted = _format_url_template(item, version=version, tag_name=tag_name, asset_name=asset_name)
        if formatted and formatted not in github_download_urls:
            github_download_urls.append(formatted)
    gitee_download_urls = []
    for item in _coerce_url_list(manifest.get("gitee_download_urls") or manifest.get("gitee_asset_urls")):
        formatted = _format_url_template(item, version=version, tag_name=tag_name, asset_name=asset_name)
        if formatted and formatted not in gitee_download_urls:
            gitee_download_urls.append(formatted)

    return UpdateInfo(
        version=version,
        tag_name=tag_name,
        release_name=str(manifest.get("release_name") or tag_name),
        body=str(manifest.get("notes") or manifest.get("body") or ""),
        asset_name=asset_name,
        download_url=download_url,
        html_url=str(manifest.get("html_url") or f"{APP_REPOSITORY_URL}/releases/latest"),
        digest=str(manifest.get("digest") or manifest.get("sha256") or ""),
        download_urls=tuple(download_urls),
        github_download_urls=tuple(github_download_urls),
        gitee_download_urls=tuple(gitee_download_urls),
        source=manifest_source,
    )


def check_for_update(current_version=APP_VERSION, timeout=8):
    errors = []
    github_manifest_loaded = False
    gitee_manifest_loaded = False
    try:
        manifest = _load_github_latest_manifest(timeout=timeout)
        github_manifest_loaded = manifest is not None
        if manifest is not None:
            update_info = _manifest_to_update_info(
                manifest,
                current_version=current_version,
                source=UPDATE_SOURCE_GITHUB,
            )
            if update_info is not None:
                return update_info
    except UpdateError as exc:
        errors.append(str(exc))

    try:
        manifest = _load_gitee_latest_manifest(timeout=timeout)
        gitee_manifest_loaded = manifest is not None
        if manifest is not None:
            update_info = _manifest_to_update_info(
                manifest,
                current_version=current_version,
                source=UPDATE_SOURCE_GITEE,
            )
            if update_info is not None:
                return update_info
    except UpdateError as exc:
        errors.append(str(exc))

    if errors and not (github_manifest_loaded or gitee_manifest_loaded):
        raise UpdateError("；".join(errors[-3:]))

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


def _configured_download_urls(update_info):
    config = _read_update_config()
    urls = _merge_urls(
        _config_url_list(config, "update_download_urls", "update_download_url"),
        _env_url_list("YHO_UPDATE_DOWNLOAD_URLS"),
    )
    return [
        _format_url_template(url, version=update_info.version, tag_name=update_info.tag_name, asset_name=update_info.asset_name)
        for url in urls
    ]


def _configured_source_download_urls(update_info, source):
    config = _read_update_config()
    if source == UPDATE_SOURCE_GITEE:
        urls = _merge_urls(
            _config_url_list(config, "update_gitee_download_urls", "gitee_download_urls", "gitee_download_url"),
            _env_url_list("YHO_GITEE_DOWNLOAD_URLS"),
        )
    elif source == UPDATE_SOURCE_GITHUB:
        urls = _merge_urls(
            _config_url_list(config, "update_github_download_urls", "github_download_urls", "github_download_url"),
            _env_url_list("YHO_GITHUB_DOWNLOAD_URLS"),
        )
    else:
        urls = []
    return [
        _format_url_template(url, version=update_info.version, tag_name=update_info.tag_name, asset_name=update_info.asset_name)
        for url in urls
    ]


def _gitee_asset_download_url(update_info):
    repo_url = _gitee_repository_url()
    if not repo_url:
        return ""
    tag_name = str(update_info.tag_name or f"v{update_info.version}").strip()
    return f"{repo_url}/releases/download/{tag_name}/{update_info.asset_name}"


def get_download_candidates(update_info, source=UPDATE_SOURCE_GITHUB):
    source = str(source or UPDATE_SOURCE_GITHUB).strip().lower()
    if source not in {UPDATE_SOURCE_GITHUB, UPDATE_SOURCE_GITEE, UPDATE_SOURCE_AUTO}:
        source = UPDATE_SOURCE_GITHUB

    if source == UPDATE_SOURCE_GITEE:
        generic_non_github = [
            url for url in _merge_urls(_configured_download_urls(update_info), getattr(update_info, "download_urls", ()))
            if not _is_github_url(url)
        ]
        candidates = _merge_urls(
            _configured_source_download_urls(update_info, UPDATE_SOURCE_GITEE),
            getattr(update_info, "gitee_download_urls", ()),
            [_gitee_asset_download_url(update_info)],
            generic_non_github,
        )
        return tuple(url for url in candidates if url)

    if source == UPDATE_SOURCE_AUTO:
        candidates = _merge_urls(
            _configured_download_urls(update_info),
            _configured_source_download_urls(update_info, UPDATE_SOURCE_GITHUB),
            getattr(update_info, "github_download_urls", ()),
            getattr(update_info, "download_urls", ()),
            [update_info.download_url, _latest_asset_download_url(update_info.asset_name)],
            _configured_source_download_urls(update_info, UPDATE_SOURCE_GITEE),
            getattr(update_info, "gitee_download_urls", ()),
            [_gitee_asset_download_url(update_info)],
        )
        return tuple(url for url in candidates if url)

    candidates = _merge_urls(
        _configured_source_download_urls(update_info, UPDATE_SOURCE_GITHUB),
        getattr(update_info, "github_download_urls", ()),
        [update_info.download_url, _latest_asset_download_url(update_info.asset_name)],
        _configured_download_urls(update_info),
        getattr(update_info, "download_urls", ()),
    )
    return tuple(url for url in candidates if url)


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


def download_update(update_info, progress_callback=None, timeout=25, source=UPDATE_SOURCE_GITHUB):
    if update_info is None:
        raise UpdateError("没有可下载的更新信息")

    download_root = _update_subdir(UPDATE_DOWNLOAD_DIR_NAME)
    _cleanup_old_children(download_root, max_age_seconds=86400)
    target_path = download_root / update_info.asset_name
    expected_sha256 = update_info.sha256

    errors = []
    candidates = list(get_download_candidates(update_info, source=source))
    if not candidates:
        raise UpdateError(f"{_source_label(source)}没有可用下载地址")
    if expected_sha256:
        for base_url in list(candidates):
            if not _is_github_url(base_url):
                continue
            for prefix in _mirror_prefixes():
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

    raise UpdateError(f"{_source_label(source)}更新包下载失败：" + "；".join(errors[-3:]))


def cleanup_old_update_runners(app_dir=None, max_age_seconds=86400):
    _cleanup_old_children(_update_subdir(UPDATE_RUNNER_DIR_NAME, app_dir=app_dir), max_age_seconds=max_age_seconds)


def prepare_updater_runner(app_dir=None):
    app_dir = Path(app_dir or app_base_dir()).resolve()
    updater = app_dir / "YHoUpdater.exe"
    if not updater.exists():
        raise UpdateError("未找到 YHoUpdater.exe，当前版本不支持全自动更新")

    cleanup_old_update_runners(app_dir=app_dir)
    runner_dir = _update_subdir(UPDATE_RUNNER_DIR_NAME, app_dir=app_dir) / str(os.getpid())
    runner_dir.mkdir(parents=True, exist_ok=True)
    runner_path = runner_dir / updater.name
    shutil.copy2(updater, runner_path)
    return runner_path


def start_external_update(package_path, app_dir=None, main_pid=None, version=None):
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
    if version:
        args.extend(["--version", str(version)])
    subprocess.Popen(args, cwd=str(app_dir), close_fds=True)
    return True

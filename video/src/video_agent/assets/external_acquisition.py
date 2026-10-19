from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "Mozilla/5.0 (compatible; CorbittTRPG-AssetEvidence/1.0)"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, *, opener: urllib.request.OpenerDirector | None = None, data: bytes | None = None,
          referer: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    if data is not None:
        headers["X-Requested-With"] = "XMLHttpRequest"
    request = urllib.request.Request(url, data=data, headers=headers)
    return (opener or urllib.request.build_opener()).open(request, timeout=180).read()


def write_new_or_verify(path: Path, content: bytes) -> str:
    """Never overwrite acquisition evidence or media."""
    digest = sha256_bytes(content)
    if path.exists():
        if sha256_file(path) != digest:
            raise FileExistsError(f"refusing to overwrite changed acquisition file: {path}")
        return digest
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return digest


def external_tree_manifest(root: Path) -> dict[str, Any]:
    files = []
    aggregate = hashlib.sha256()
    if root.exists():
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().casefold()):
            relative = path.relative_to(root).as_posix()
            digest = sha256_file(path)
            files.append({"path": relative, "size": path.stat().st_size, "sha256": digest})
            aggregate.update(relative.encode("utf-8")); aggregate.update(b"\0"); aggregate.update(digest.encode("ascii")); aggregate.update(b"\n")
    return {"root": str(root), "file_count": len(files), "aggregate_sha256": aggregate.hexdigest(), "files": files}


@dataclass(frozen=True)
class DirectAsset:
    category: str
    filename: str
    media_url: str
    source_url: str
    source_site: str
    creator: str
    title: str
    license_name: str
    license_url: str
    commercial_use: bool
    video_use: bool
    modification_allowed: bool
    attribution_required: bool
    redistribution_allowed: bool
    terms_summary: str
    credit_text: str | None = None
    generation_origin: str = "UNKNOWN"
    official_preview_derivative: bool = False


DIRECT_ASSETS = [
    DirectAsset("backgrounds/basement/AIPICT", "aipict_basement_concrete01.png",
                "https://aipict.com/wp-content/uploads/basement_concrete01.png", "https://aipict.com/en/general-en/basement-en/",
                "AIPICT", "AIPICT", "Basement Concrete 01", "AIPICT Terms of Use", "https://aipict.com/en/terms-of-use-en/",
                True, True, True, False, False, "Commercial and video use and editing are permitted; credit is optional; redistribution or sale as material is prohibited.", generation_origin="AI_GENERATED"),
    DirectAsset("backgrounds/basement/AIPICT", "aipict_basement_concrete04.png",
                "https://aipict.com/wp-content/uploads/basement_concrete04.png", "https://aipict.com/en/general-en/basement-en/",
                "AIPICT", "AIPICT", "Basement Concrete 04", "AIPICT Terms of Use", "https://aipict.com/en/terms-of-use-en/",
                True, True, True, False, False, "Commercial and video use and editing are permitted; credit is optional; redistribution or sale as material is prohibited.", generation_origin="AI_GENERATED"),
    DirectAsset("backgrounds/basement/AIPICT", "aipict_basement_ruins01.png",
                "https://aipict.com/wp-content/uploads/basement_ruins01.png", "https://aipict.com/en/general-en/basement-en/",
                "AIPICT", "AIPICT", "Basement Ruins 01", "AIPICT Terms of Use", "https://aipict.com/en/terms-of-use-en/",
                True, True, True, False, False, "Commercial and video use and editing are permitted; credit is optional; redistribution or sale as material is prohibited.", generation_origin="AI_GENERATED"),
    DirectAsset("sfx/wood_creak/Freesound_Rudmer_Rotteveel", "freesound_502505_wood_creak_single_v1_hq_preview.mp3",
                "https://cdn.freesound.org/previews/502/502505_4921277-hq.mp3", "https://freesound.org/people/Rudmer_Rotteveel/sounds/502505/",
                "Freesound", "Rudmer_Rotteveel", "Wood Creak Single V1", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                True, True, True, False, True, "Individual sound page identifies this work as CC0. This file is Freesound's official HQ MP3 preview derivative of the original WAV.", official_preview_derivative=True),
    DirectAsset("sfx/wood_creak/Freesound_Rudmer_Rotteveel", "freesound_502511_wood_creak_single_v3_hq_preview.mp3",
                "https://cdn.freesound.org/previews/502/502511_4921277-hq.mp3", "https://freesound.org/people/Rudmer_Rotteveel/sounds/502511/",
                "Freesound", "Rudmer_Rotteveel", "Wood Creak Single V3", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                True, True, True, False, True, "Individual sound page identifies this work as CC0. This file is Freesound's official HQ MP3 preview derivative of the original WAV.", official_preview_derivative=True),
    DirectAsset("sfx/wood_creak/Freesound_Rudmer_Rotteveel", "freesound_506660_wood_creak_single_v5_hq_preview.mp3",
                "https://cdn.freesound.org/previews/506/506660_4921277-hq.mp3", "https://freesound.org/people/Rudmer_Rotteveel/sounds/506660/",
                "Freesound", "Rudmer_Rotteveel", "Wood Creak Single V5", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                True, True, True, False, True, "Individual sound page identifies this work as CC0. This file is Freesound's official HQ MP3 preview derivative of the original WAV.", official_preview_derivative=True),
    DirectAsset("sfx/wood_break/Freesound", "freesound_387014_wood_break_hq_preview.mp3",
                "https://cdn.freesound.org/previews/387/387014_2984479-hq.mp3", "https://freesound.org/people/mlodydebus/sounds/387014/",
                "Freesound", "mlodydebus", "Wood Break", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                True, True, True, False, True, "Individual sound page identifies this work as CC0. This file is Freesound's official HQ MP3 preview derivative of the original WAV.", official_preview_derivative=True),
    DirectAsset("sfx/wood_break/Freesound", "freesound_766406_branch_break_hq_preview.mp3",
                "https://cdn.freesound.org/previews/766/766406_15764407-hq.mp3", "https://freesound.org/people/DariusOW/sounds/766406/",
                "Freesound", "DariusOW", "Branch Break", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                True, True, True, False, True, "Individual sound page identifies this work as CC0. This file is Freesound's official HQ MP3 preview derivative of the original WAV.", official_preview_derivative=True),
    DirectAsset("sfx/wood_break/Freesound", "freesound_452109_branch_break_snap_crunch_hq_preview.mp3",
                "https://cdn.freesound.org/previews/452/452109_612689-hq.mp3", "https://freesound.org/people/kyles/sounds/452109/",
                "Freesound", "kyles", "branch break snap crunch nice.wav", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                True, True, True, False, True, "Individual sound page identifies this work as CC0. This file is Freesound's official HQ MP3 preview derivative of the original WAV.", official_preview_derivative=True),
]


ITCH_PACKS = [
    {
        "source_url": "https://mumusi-c21.itch.io/snaps-in-the-dark", "slug": "snaps-in-the-dark", "upload_id": "14976584",
        "source_site": "itch.io", "creator": "mumusi_c21", "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/", "credit_text": "Music by mumusi_c21 – https://mumusi-c21.itch.io",
        "members": {"SnapsInTheDark_bgm_mumusi/Snaps In The Dark_loop.wav": "itch_mumusi_snaps_in_the_dark_tension_loop.wav"},
    },
    {
        "source_url": "https://seciden.itch.io/music-pack-6", "slug": "music-pack-6", "upload_id": "13442698",
        "source_site": "itch.io", "creator": "Arkeia / Seciden", "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "credit_text": "Contains music ©2026 Arkeia (https://arkeiamusic.itch.io/)\nLicensed under Creative Commons Attribution 4.0 International",
        "members": {"as-the-light-fades.ogg": "itch_arkeia_tension_as_the_light_fades.ogg",
                    "eyes-piercing-shadow.ogg": "itch_arkeia_tension_eyes_piercing_shadow.ogg",
                    "monster.ogg": "itch_arkeia_tension_monster.ogg"},
    },
]


def _metadata(asset: DirectAsset, downloaded_at: str, original_filename: str, digest: str) -> dict[str, Any]:
    recommendation = "RECOMMEND_APPROVE" if asset.license_name.startswith("CC0") else "RECOMMEND_APPROVE_WITH_ATTRIBUTION"
    return {
        "source_url": asset.source_url, "media_url": asset.media_url, "source_site": asset.source_site,
        "creator": asset.creator, "asset_title": asset.title, "downloaded_at": downloaded_at,
        "original_filename": original_filename, "sha256": digest, "license_name": asset.license_name,
        "license_url": asset.license_url, "commercial_use": asset.commercial_use, "video_use": asset.video_use,
        "modification_allowed": asset.modification_allowed, "attribution_required": asset.attribution_required,
        "redistribution_allowed": asset.redistribution_allowed, "credit_text": asset.credit_text,
        "terms_summary": asset.terms_summary, "generation_origin": asset.generation_origin,
        "official_preview_derivative": asset.official_preview_derivative,
        "license_status": "LICENSE_REVIEW_REQUIRED", "approval_status": "NOT_APPROVED", "auto_use": False,
        "license_review_recommendation": recommendation,
    }


def _license_text(metadata: dict[str, Any]) -> str:
    keys = ["asset_title", "creator", "source_url", "license_name", "license_url", "downloaded_at", "terms_summary",
            "commercial_use", "video_use", "modification_allowed", "attribution_required", "redistribution_allowed", "credit_text"]
    return "\n".join(f"{key}: {metadata.get(key)}" for key in keys) + "\n\nSTATUS: LICENSE_REVIEW_REQUIRED / NOT_APPROVED / auto_use=false\n"


def _download_itch_pack(pack: dict[str, Any]) -> tuple[bytes, bytes, bytes]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    source = fetch(pack["source_url"], opener=opener)
    source_text = source.decode("utf-8", "replace")
    csrf = re.search(r'name="csrf_token" value="([^"]+)', source_text)
    if csrf is None:
        raise RuntimeError(f"itch csrf token missing: {pack['source_url']}")
    payload = urllib.parse.urlencode({"csrf_token": csrf.group(1)}).encode()
    response = json.loads(fetch(pack["source_url"] + "/download_url", opener=opener, data=payload, referer=pack["source_url"]))
    download_page_url = response["url"]
    download_page = fetch(download_page_url, opener=opener)
    page_text = download_page.decode("utf-8", "replace")
    csrf2 = re.search(r'name="csrf_token" value="([^"]+)', page_text)
    if csrf2 is None:
        raise RuntimeError(f"itch download csrf token missing: {pack['source_url']}")
    file_endpoint = f"{pack['source_url']}/file/{pack['upload_id']}?source=game_download"
    payload2 = urllib.parse.urlencode({"csrf_token": csrf2.group(1)}).encode()
    file_response = json.loads(fetch(file_endpoint, opener=opener, data=payload2, referer=download_page_url))
    archive = fetch(file_response["url"], opener=opener)
    return source, download_page, archive


def acquire(root: Path) -> dict[str, Any]:
    root = root.resolve()
    downloaded_at = datetime.now(timezone.utc).isoformat()
    cache: dict[str, bytes] = {}
    records = []
    for asset in DIRECT_ASSETS:
        media = fetch(asset.media_url)
        source_html = cache.setdefault(asset.source_url, fetch(asset.source_url))
        license_html = cache.setdefault(asset.license_url, fetch(asset.license_url))
        target = root / asset.category / asset.filename
        digest = write_new_or_verify(target, media)
        metadata = _metadata(asset, downloaded_at, Path(urllib.parse.urlsplit(asset.media_url).path).name, digest)
        write_new_or_verify(target.with_name(target.name + ".source.json"), (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        write_new_or_verify(target.with_name(target.name + ".license.txt"), _license_text(metadata).encode("utf-8"))
        write_new_or_verify(target.with_name(target.name + ".source.html"), source_html)
        write_new_or_verify(target.with_name(target.name + ".license.html"), license_html)
        records.append({"path": str(target), **metadata})

    for pack in ITCH_PACKS:
        source_html, download_html, archive = _download_itch_pack(pack)
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "pack.zip"
            archive_path.write_bytes(archive)
            with zipfile.ZipFile(archive_path) as zipped:
                for member, filename in pack["members"].items():
                    media = zipped.read(member)
                    target = root / "bgm/tension/itch.io" / filename
                    digest = write_new_or_verify(target, media)
                    metadata = {
                        "source_url": pack["source_url"], "media_url": "ITCH_FREE_DOWNLOAD_PACKAGE",
                        "source_site": pack["source_site"], "creator": pack["creator"],
                        "asset_title": Path(member).stem, "downloaded_at": downloaded_at, "original_filename": member,
                        "package_sha256": sha256_bytes(archive), "sha256": digest, "license_name": pack["license_name"],
                        "license_url": pack["license_url"], "commercial_use": True, "video_use": True,
                        "modification_allowed": True, "attribution_required": True, "redistribution_allowed": False,
                        "credit_text": pack["credit_text"],
                        "terms_summary": "CC BY 4.0 permits commercial/video use and adaptation with attribution; standalone asset redistribution is not an approved use here.",
                        "generation_origin": "HUMAN_CREATED_NO_GENERATIVE_AI_DECLARED",
                        "license_status": "LICENSE_REVIEW_REQUIRED", "approval_status": "NOT_APPROVED", "auto_use": False,
                        "license_review_recommendation": "RECOMMEND_APPROVE_WITH_ATTRIBUTION",
                    }
                    license_html = cache.setdefault(pack["license_url"], fetch(pack["license_url"]))
                    write_new_or_verify(target.with_name(target.name + ".source.json"), (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                    write_new_or_verify(target.with_name(target.name + ".license.txt"), _license_text(metadata).encode("utf-8"))
                    write_new_or_verify(target.with_name(target.name + ".source.html"), source_html)
                    write_new_or_verify(target.with_name(target.name + ".license.html"), license_html)
                    write_new_or_verify(target.with_name(target.name + ".download_page.html"), download_html)
                    records.append({"path": str(target), **metadata})
    manifest = external_tree_manifest(root)
    return {"schema_version": "1.0", "acquisition_id": "EXTERNAL_ASSET_ACQUISITION_V1",
            "downloaded_at": downloaded_at, "asset_count": len(records), "assets": records,
            "external_root_manifest": manifest}


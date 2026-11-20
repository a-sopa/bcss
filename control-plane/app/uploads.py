"""Turn uploaded files (a folder or a single .zip) into a source directory, safely."""

import io
import shutil
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from . import config


class UploadError(ValueError):
    pass


def safe_relative(name: str) -> PurePosixPath:
    """A relative POSIX path that cannot escape its directory."""
    if not isinstance(name, str) or not 0 < len(name) <= 300 or any(ord(c) < 32 or c == "\x7f" for c in name):
        raise UploadError("Invalid file path")
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts) or ":" in path.parts[0]:
        raise UploadError(f"Invalid file path: {name!r}")
    if len(path.parts) > 32 or any(len(part) > 255 for part in path.parts):
        raise UploadError("File path is too deep or too long")
    return path


def _strip_common_root(paths: list[PurePosixPath]) -> list[PurePosixPath]:
    """Uploading a folder prefixes every path with the folder name; drop it."""
    roots = {p.parts[0] for p in paths}
    if len(roots) == 1 and all(len(p.parts) > 1 for p in paths):
        return [PurePosixPath(*p.parts[1:]) for p in paths]
    return paths


def write_sources(files: list[tuple[str, bytes]], destination: Path) -> int:
    """Write uploaded (name, content) pairs into destination. Returns the number of files."""
    if len(files) == 1 and files[0][0].lower().endswith(".zip"):
        files = _unzip(files[0][1])
    if not files:
        raise UploadError("No files were uploaded")
    if len(files) > config.MAX_UPLOAD_FILES:
        raise UploadError(f"At most {config.MAX_UPLOAD_FILES} files can be uploaded")
    if sum(len(content) for _, content in files) > config.MAX_UPLOAD_BYTES:
        raise UploadError("Uploads are limited to 50 MB")

    paths = _strip_common_root([safe_relative(name) for name, _ in files])
    if len(set(paths)) != len(paths):
        raise UploadError("Duplicate file paths in the upload")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    try:
        for path, (_, content) in zip(paths, files):
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    except OSError as exc:  # e.g. a file and a folder with the same name
        shutil.rmtree(destination, ignore_errors=True)
        raise UploadError("The upload contains conflicting file paths") from exc
    return len(files)


def _unzip(data: bytes) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UploadError("The .zip file is not valid") from exc
    entries = [info for info in archive.infolist() if not info.is_dir() and not info.filename.startswith("__MACOSX/")]
    if len(entries) > config.MAX_UPLOAD_FILES:
        raise UploadError(f"At most {config.MAX_UPLOAD_FILES} files can be uploaded")
    # zipfile stops reading each entry at its declared size, so this bounds decompression (zip bombs).
    if sum(info.file_size for info in entries) > config.MAX_UPLOAD_BYTES:
        raise UploadError("The extracted archive exceeds 50 MB")
    try:
        return [(info.filename, archive.read(info)) for info in entries]
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError) as exc:
        raise UploadError("The .zip file could not be extracted") from exc

"""Guardado de fotos en disco. Se re-codifican a JPEG (valida que sea imagen y borra el EXIF/GPS)."""
import io
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings


def save_photo(upload: UploadFile) -> str:
    limit = settings.max_photo_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"supera {settings.max_photo_mb} MB")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("no es una imagen válida") from None
    img.thumbnail((1600, 1600))
    name = f"{uuid4().hex}.jpg"
    img.save(settings.upload_dir / name, "JPEG", quality=85)
    return name


def save_uploads(files: list[UploadFile] | None, already: int) -> tuple[list[str], list[str]]:
    """Devuelve (nombres_guardados, errores). Si hay error no deja archivos huérfanos."""
    files = [f for f in (files or []) if f.filename]
    if already + len(files) > settings.max_photos_per_space:
        return [], [f"Máximo {settings.max_photos_per_space} fotos por espacio."]
    names: list[str] = []
    errors: list[str] = []
    for f in files:
        try:
            names.append(save_photo(f))
        except ValueError as e:
            errors.append(f"Foto «{f.filename}»: {e}.")
    if errors:
        delete_photos(names)
        return [], errors
    return names, []


def delete_photos(names: list[str]) -> None:
    for n in names:
        (settings.upload_dir / Path(n).name).unlink(missing_ok=True)

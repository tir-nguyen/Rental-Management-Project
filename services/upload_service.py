"""Lưu file người dùng tải lên (ảnh thẻ SV, ảnh listing, ảnh bằng chứng check-in/out)."""
import os
import uuid
from pathlib import Path

from flask import abort, current_app, send_from_directory
from werkzeug.utils import secure_filename


class UploadError(ValueError):
    pass


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
EVIDENCE_EXTENSIONS = IMAGE_EXTENSIONS | {"mp4", "mov", "webm"}


def save_upload(file_storage, upload_folder, allowed_extensions=None):
    """Lưu file và trả về logical key tương thích với dữ liệu hiện có."""
    if not file_storage or file_storage.filename == "":
        return None
    filename = secure_filename(file_storage.filename)
    if not filename or "." not in filename:
        raise UploadError("Tệp tải lên không hợp lệ.")
    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in (allowed_extensions or IMAGE_EXTENSIONS):
        raise UploadError("Định dạng tệp không được hỗ trợ.")
    unique_name = f"{uuid.uuid4().hex}.{extension}"
    os.makedirs(upload_folder, exist_ok=True)
    path = os.path.join(upload_folder, unique_name)
    file_storage.save(path)
    return f"uploads/{unique_name}"


def send_private_upload(storage_key):
    """Serve a private logical key only through an already-authorized route."""
    prefix = "uploads/"
    if not isinstance(storage_key, str) or not storage_key.startswith(prefix):
        abort(404)

    filename = storage_key[len(prefix):]
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or secure_filename(filename) != filename
        or "." not in filename
        or filename.rsplit(".", 1)[1].lower() not in EVIDENCE_EXTENSIONS
    ):
        abort(404)

    folders = (
        current_app.config["PRIVATE_UPLOAD_FOLDER"],
        current_app.config["UPLOAD_FOLDER"],
    )
    for folder in folders:
        if (Path(folder) / filename).is_file():
            response = send_from_directory(folder, filename)
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            return response
    abort(404)

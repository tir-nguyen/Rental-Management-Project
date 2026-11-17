"""Lưu file người dùng tải lên (ảnh thẻ SV, ảnh listing, ảnh bằng chứng check-in/out)."""
import os
import re
import uuid
import cloudinary
import cloudinary.exceptions
import cloudinary.uploader
from pathlib import Path
from urllib.parse import urlsplit

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


def save_listing_image(file_storage):
    """Upload ảnh bài đăng lên Cloudinary và trả về URL công khai."""
    if not file_storage or file_storage.filename == "":
        return None

    filename = secure_filename(file_storage.filename)

    if not filename or "." not in filename:
        raise UploadError("Tệp tải lên không hợp lệ.")

    extension = filename.rsplit(".", 1)[1].lower()

    if extension not in IMAGE_EXTENSIONS:
        raise UploadError("Định dạng ảnh không được hỗ trợ.")

    if not os.environ.get("CLOUDINARY_URL"):
        raise UploadError("Chưa cấu hình Cloudinary.")
    cloudinary.config()
    

    try:
        result = cloudinary.uploader.upload(
            file_storage.stream,
            folder="rental-management/listings",
            resource_type="image",
            allowed_formats=sorted(IMAGE_EXTENSIONS),
            use_filename=False,
            unique_filename=True,
            overwrite=False,
        )

        image_url = result.get("secure_url")

        if not image_url:
            raise UploadError("Không nhận được đường dẫn ảnh từ Cloudinary.")

        if len(image_url) > 255:
            raise UploadError("Đường dẫn ảnh vượt quá giới hạn lưu trữ.")

        return image_url

    except UploadError:
        raise
    except Exception as exc:
        current_app.logger.exception("Cloudinary upload failed")
        raise UploadError(
            "Không thể tải ảnh lên Cloudinary. Vui lòng thử lại."
        ) from exc


def delete_listing_image(image_url):
    """Delete an owned listing image from local storage or Cloudinary."""
    if not isinstance(image_url, str):
        current_app.logger.error("Listing image has an invalid storage key")
        return False

    if image_url.startswith("uploads/"):
        filename = image_url[len("uploads/"):]
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or secure_filename(filename) != filename
            or "." not in filename
            or filename.rsplit(".", 1)[1].lower() not in IMAGE_EXTENSIONS
        ):
            current_app.logger.error("Listing image has an unsafe local storage key")
            return False

        root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        path = (root / filename).resolve()
        if path.parent != root:
            current_app.logger.error("Listing image resolves outside upload storage")
            return False
        if not path.is_file():
            return True
        try:
            path.unlink()
        except OSError:
            current_app.logger.exception("Could not remove local listing image")
            return False
        return True

    parsed_url = urlsplit(image_url)
    if parsed_url.scheme not in ("http", "https") or parsed_url.hostname != "res.cloudinary.com":
        return True

    segments = [segment for segment in parsed_url.path.split("/") if segment]
    try:
        upload_index = segments.index("upload")
    except ValueError:
        current_app.logger.error("Cloudinary listing image URL has no upload segment")
        return False
    asset_segments = segments[upload_index + 1:]
    if asset_segments and re.fullmatch(r"v\d+", asset_segments[0]):
        asset_segments = asset_segments[1:]
    asset_path = "/".join(asset_segments)
    if not asset_path.startswith("rental-management/listings/"):
        return True

    suffix = Path(asset_path).suffix
    public_id = asset_path[:-len(suffix)] if suffix else asset_path
    if not public_id:
        current_app.logger.error("Cloudinary listing image URL has an invalid public ID")
        return False

    try:
        cloudinary.config()
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type="image",
            type="upload",
            invalidate=True,
        )
    except cloudinary.exceptions.Error:
        current_app.logger.exception("Could not remove Cloudinary listing image")
        return False

    if result.get("result") not in ("ok", "not found"):
        current_app.logger.error("Cloudinary did not confirm listing image deletion")
        return False
    return True


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

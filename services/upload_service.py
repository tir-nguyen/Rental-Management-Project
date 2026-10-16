"""Lưu file người dùng tải lên (ảnh thẻ SV, ảnh listing, ảnh bằng chứng check-in/out)."""
import os
import uuid
from werkzeug.utils import secure_filename


class UploadError(ValueError):
    pass


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
EVIDENCE_EXTENSIONS = IMAGE_EXTENSIONS | {"mp4", "mov", "webm"}


def save_upload(file_storage, upload_folder, allowed_extensions=None):
    """Lưu 1 file vào upload_folder, trả về đường dẫn tương đối (dùng với url_for('static', filename=...))."""
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

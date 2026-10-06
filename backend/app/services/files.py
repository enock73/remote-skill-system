import os, uuid
from flask import current_app

MAGIC = (("png", b"\x89PNG\r\n\x1a\n"), ("jpg", b"\xff\xd8\xff"), ("webp", b"RIFF"))


def sniff(head):
    """Return png/jpg/webp if the bytes really are that image type, else None (the file extension is not trusted)."""
    for ext, sig in MAGIC:
        if head.startswith(sig) and (ext != "webp" or head[8:12] == b"WEBP"):
            return ext
    return None


def save_private_image(file):
    """Save a photo into the private folder (not web-accessible). Returns (filename, error)."""
    if not file or not file.filename:
        return None, "Choose a photo."
    ext = sniff(file.stream.read(16)); file.stream.seek(0)
    if not ext:
        return None, "Upload a real photo (JPG, PNG or WebP)."
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(current_app.config["PRIVATE_FOLDER"], name))
    return name, None


def save_public_image(file):
    """Same check, saved into the public uploads folder (work photos)."""
    if not file or not file.filename:
        return None, "Choose a photo."
    ext = sniff(file.stream.read(16)); file.stream.seek(0)
    if not ext:
        return None, "Upload a real photo (JPG, PNG or WebP)."
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return name, None


def delete_file(folder_key, name):
    try:
        if name: os.remove(os.path.join(current_app.config[folder_key], os.path.basename(name)))
    except OSError:
        pass

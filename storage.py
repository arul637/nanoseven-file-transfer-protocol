import os
import secrets
import shutil

from werkzeug.utils import secure_filename

from config import Config
from crypto import encrypt_data, decrypt_data


def share_dir(token):
    return os.path.join(Config.UPLOAD_DIR, f'{token:06d}')


def sanitize_filename(name):
    base = os.path.basename(name)
    safe = secure_filename(base)
    return safe or 'file'


def save_uploaded_files(token, file_storage_list, key=None):
    directory = share_dir(token)
    os.makedirs(directory, exist_ok=True)

    saved = []
    for f in file_storage_list:
        if not f or not f.filename:
            continue
        original = f.filename
        stored = f'{secrets.token_hex(8)}_{sanitize_filename(original)}'
        path = os.path.join(directory, stored)

        data = f.read()
        original_size = len(data)
        encrypted = False
        if key is not None:
            data = encrypt_data(data, key)
            encrypted = True

        with open(path, 'wb') as out:
            out.write(data)

        saved.append({
            'original_filename': original,
            'stored_filename': stored,
            'size': original_size,
            'encrypted': encrypted,
        })
    return saved


def file_path(share, shared_file):
    return os.path.join(share_dir(share.token), shared_file.stored_filename)


def read_file_bytes(shared_file, key=None):
    path = file_path(shared_file.share, shared_file)
    with open(path, 'rb') as fh:
        data = fh.read()
    if shared_file.encrypted:
        if key is None:
            raise ValueError('File is encrypted but no key was provided')
        data = decrypt_data(data, key)
    return data


def delete_share_files(share):
    directory = share_dir(share.token)
    if os.path.isdir(directory):
        shutil.rmtree(directory, ignore_errors=True)


def ensure_dirs():
    os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

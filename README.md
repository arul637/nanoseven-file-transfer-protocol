# NanoShare

Share files anywhere, anytime, using just a **6-digit token**. No accounts, no login, no third-party services.

A professor or student uploads a file, gets a token (and an optional password), and shares those credentials. Anyone can download the file by entering the token. When the download limit is reached or the share expires, the file is **deleted automatically**.

Built with Python Flask and SQLite — modular, simple, and easy to debug.

---

## Features

- **Token-based sharing** — 6-digit token, sequential and reused efficiently (000001, 000002, ...).
- **Optional password / encryption** — set a password and files are **encrypted at rest** with the password as the key (PBKDF2 + HMAC). Leave it empty for a plain, token-only share.
- **Download limits**
  - Unlimited downloads (until expiry)
  - 1 download only
  - 5 downloads only
- **Auto-delete** — when the limit is reached or the share expires, the file and metadata are removed and the token is freed for reuse.
- **Drag & drop upload** — files and folders can be mixed in a single upload, with separate "Select files" / "Select folder" buttons.
- **No file type restrictions** — any file, any extension.
- **Expiry control** — set days / hours / minutes with number inputs (default 1 day, max 1 day).
- **No user accounts** — upload and download without signing in.

---

## Architecture

```
User uploads files
        |
        v
  /upload (POST)
        |
        v
  SQLite metadata  +  files stored in uploads/<token>/
        |
        v
  Token (000001) + optional password returned
        |
        v
Recipient visits /download/<token>, enters password (if set), downloads
        |
        v
  download count incremented
        |
        +--> limit reached or expired? --> auto-delete + token reused
```

**Modules**

| File          | Responsibility                                    |
|---------------|---------------------------------------------------|
| `app.py`      | Flask app, routes, download/token logic           |
| `config.py`   | Configuration (env-driven)                        |
| `models.py`   | SQLAlchemy models (`Share`, `SharedFile`)         |
| `storage.py`  | Filesystem operations (save, delete, encrypt)     |
| `crypto.py`   | Stdlib-only encryption (PBKDF2 + HMAC stream)     |
| `templates/`  | Jinja2 templates (`base`, `index`, `download`)    |
| `static/`     | CSS (`root.css`, `main.css`) and JS (`app.js`)    |

---

## Token management

Tokens are integers `1` to `999999`, always displayed as 6 digits (`000001`).

- The **smallest free token** is always assigned on upload.
- When a share is deleted (limit reached / expired), its token becomes free and is **reused** by the next upload.

Example:

1. Person A uploads → gets `000001`.
2. Person B uploads → gets `000002`.
3. Person A's share expires → token `000001` is freed.
4. Person C uploads → gets `000001` (reused).

---

## Installation

```bash
pip install -r requirements.txt
```

## Running locally

```bash
python app.py
```

Then open http://localhost:5000

The SQLite database is created automatically at `instance/nanoshare.db` on first run.

## Environment variables

All configuration lives in `.env` (copy from `.env.example`). Everything has a sensible default.

| Variable              | Default                          | Description                        |
|-----------------------|----------------------------------|------------------------------------|
| `SECRET_KEY`          | `dev-secret-key-change-me`       | Flask session secret. Set in prod. |
| `DATABASE_URL`        | `sqlite:///nanoshare.db`         | SQLAlchemy database URI            |
| `UPLOAD_DIR`          | `uploads/`                       | Folder where uploaded files live   |
| `MAX_CONTENT_LENGTH`  | `209715200` (200 MB)             | Max upload size in bytes           |

---

## Project structure

```
nanoshare/
    app.py
    config.py
    models.py
    storage.py
    crypto.py
    requirements.txt
    README.md
    .env.example
    templates/
        base.html
        index.html
        download.html
    static/
        css/
            root.css
            main.css
        js/
            app.js
    uploads/           # uploaded files, one folder per token
    instance/          # SQLite database
```

---

## How downloads work

1. From the home page, choose **Download** and enter the token (password optional).
2. If the share is password protected, the password is required once (remembered for the session).
3. Single-file shares download that file directly. Multi-file shares offer per-file download plus a **"Download all as ZIP"** button.
4. Every download increments the count. When the count reaches the limit (1 or 5), or when the expiry passes, the files and database record are deleted and the token is reused.

---

## Security notes

- Passwords are hashed with Werkzeug (never stored in plain text).
- **Encryption** (`crypto.py`): when a password is set, each file is encrypted at rest with a key derived from the password via PBKDF2-HMAC-SHA256 plus a per-share random salt, with an HMAC integrity tag. Files uploaded without a password are stored as-is (plain text). Decryption happens in memory at download time only if the correct password was supplied.
- Filenames are sanitized (`secure_filename`) to prevent path traversal.
- CSRF protection on all POST forms.
- SQLAlchemy (parameterized queries) prevents SQL injection.
- No authentication is required to *download* by design — the token + optional password is the access control, which is exactly the intended use case.

> For production: set a strong `SECRET_KEY`, run behind HTTPS (e.g. gunicorn + nginx), and set `MAX_CONTENT_LENGTH` to your desired cap.

---

## License

MIT

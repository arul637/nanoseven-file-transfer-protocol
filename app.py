import base64
import io
import os
import secrets
import zipfile
from datetime import datetime, timedelta

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template,
    request, send_file, session, url_for,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from config import Config
from crypto import derive_key, generate_salt
from models import Share, SharedFile, db
from storage import (
    delete_share_files, ensure_dirs, read_file_bytes, save_uploaded_files,
)

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

MAX_EXPIRY_MINUTES = 24 * 60  # 1 day
DEFAULT_EXPIRY = timedelta(minutes=1440)

LIMIT_VALUES = {
    'unlimited': None,
    '1': 1,
    '5': 5,
}


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(16)
    return session['_csrf']


app.jinja_env.globals['csrf_token'] = csrf_token


def csrf_protect():
    if request.method == 'POST':
        token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or token != session.get('_csrf'):
            abort(403)


def cleanup_expired():
    now = datetime.now()
    expired = Share.query.filter(Share.expires_at <= now).all()
    for share in expired:
        delete_share_files(share)
        db.session.delete(share)
    if expired:
        db.session.commit()


@app.before_request
def before_request():
    csrf_protect()
    cleanup_expired()


def next_available_token():
    used = {t for (t,) in db.session.query(Share.token).all()}
    token = 1
    while token in used and token <= Config.TOKEN_MAX:
        token += 1
    if token > Config.TOKEN_MAX:
        raise RuntimeError('No tokens available')
    return token


def get_share(token_str):
    try:
        token = int(token_str)
    except (TypeError, ValueError):
        return None
    return Share.query.filter_by(token=token).first()


def parse_expiry(form):
    def num(field):
        try:
            return max(0, int(form.get(field, 0) or 0))
        except (TypeError, ValueError):
            return 0

    days = num('days')
    hours = num('hours')
    minutes = num('minutes')
    total = min(MAX_EXPIRY_MINUTES, max(1, days * 1440 + hours * 60 + minutes))
    return timedelta(minutes=total)


def count_download(share):
    share.downloads += 1
    if share.limit_reached:
        delete_share_files(share)
        db.session.delete(share)
    db.session.commit()


def session_key(share):
    b64 = session.get(f'key_{share.token}')
    if b64:
        try:
            return base64.b64decode(b64)
        except Exception:
            return None
    return None


def serve_file(share, shared_file, key=None):
    try:
        data = read_file_bytes(shared_file, key)
    except ValueError:
        flash('Unable to decrypt file', 'error')
        return redirect(url_for('download', token=share.token_str))
    count_download(share)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=os.path.basename(shared_file.original_filename),
        mimetype='application/octet-stream',
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        return jsonify({'success': False, 'error': 'No files selected'}), 400

    limit = LIMIT_VALUES.get(request.form.get('limit', 'unlimited'), None)
    expiry = parse_expiry(request.form)
    password = request.form.get('password', '').strip()

    for _ in range(5):
        try:
            token = next_available_token()
            share = Share(
                token=token, # type: ignore
                download_limit=limit, # type: ignore
                expires_at=datetime.now() + expiry, # type: ignore
            )
            share.set_password(password)
            if password:
                share.salt = generate_salt()
            db.session.add(share)
            db.session.flush()
            break
        except IntegrityError:
            db.session.rollback()
    else:
        return jsonify({'success': False, 'error': 'Could not allocate a token'}), 500

    key = derive_key(password, share.salt) if password else None
    saved = save_uploaded_files(token, files, key=key)
    for item in saved:
        db.session.add(SharedFile(share_id=share.id, **item)) # type: ignore
    db.session.commit()

    return jsonify({
        'success': True,
        'token': share.token_str,
        'has_password': bool(password),
        'expires_at': share.expires_at.strftime('%Y-%m-%d %H:%M %Z'),
        'file_count': len(saved),
    })


@app.route('/download', methods=['POST'])
def download_via_modal():
    token_str = request.form.get('token', '').strip()
    password = request.form.get('password', '')

    share = get_share(token_str)
    if share is None:
        flash('Invalid token', 'error')
        return redirect(url_for('index'))
    if not share.usable:
        return redirect(url_for('download', token=share.token_str))

    if share.protected:
        if not share.check_password(password):
            flash('Invalid password', 'error')
            return redirect(url_for('index'))
        session[f'key_{share.token}'] = base64.b64encode(
            derive_key(password, share.salt)).decode()

    return redirect(url_for('download', token=share.token_str))


@app.route('/download/<token>', methods=['GET', 'POST'])
def download(token):
    share = get_share(token)
    if share is None:
        abort(404)

    if not share.usable:
        return render_template('download.html', share=share, available=False)

    authed = share.password_hash is None or session_key(share) is not None

    if request.method == 'POST':
        if share.protected:
            if not share.check_password(request.form.get('password', '')):
                flash('Invalid password', 'error')
                return render_template(
                    'download.html', share=share, available=True, need_auth=True)
            session[f'key_{share.token}'] = base64.b64encode(
                derive_key(request.form.get('password', ''), share.salt)).decode()
            authed = True

        if authed:
            if share.files.count() == 1:
                return serve_file(share, share.files.first(), session_key(share))
            return redirect(url_for('download', token=share.token_str))

    return render_template(
        'download.html', share=share, available=True, need_auth=not authed)


@app.route('/download/<token>/file/<int:file_id>')
def download_file(token, file_id):
    share = get_share(token)
    if share is None or not share.usable:
        abort(404)

    key = session_key(share)
    if share.password_hash is not None and key is None:
        return redirect(url_for('download', token=share.token_str))

    shared_file = SharedFile.query.get_or_404(file_id)
    if shared_file.share_id != share.id:
        abort(404)

    return serve_file(share, shared_file, key)


@app.route('/download/<token>/zip')
def download_zip(token):
    share = get_share(token)
    if share is None or not share.usable:
        abort(404)

    key = session_key(share)
    if share.password_hash is not None and key is None:
        return redirect(url_for('download', token=share.token_str))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for shared_file in share.files:
            try:
                data = read_file_bytes(shared_file, key)
            except ValueError:
                continue
            zf.writestr(shared_file.original_filename, data)
    buffer.seek(0)

    count_download(share)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'nanoshare-{share.token_str}.zip',
        mimetype='application/zip',
    )


@app.errorhandler(404)
def not_found(e):
    return render_template('base.html', error_code=404, error_message='Page not found'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('base.html', error_code=403, error_message='Forbidden'), 403


@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large'}), 413


def ensure_schema():
    """Add columns introduced after the original schema without wiping data."""
    migs = [
        ('shares', 'salt', 'VARCHAR(64)'),
        ('shared_files', 'encrypted', 'BOOLEAN'),
    ]
    inspector = sa_inspect(db.engine)
    for table, column, ddl in migs:
        existing = {c['name'] for c in inspector.get_columns(table)}
        if column not in existing:
            try:
                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
                app.logger.info('Migration: added %s.%s', table, column)
            except OperationalError:
                pass


with app.app_context():
    db.create_all()
    ensure_schema()
    ensure_dirs()


if __name__ == '__main__':
    HOST = Config.HOST
    PORT = Config.PORT
    app.run(host=HOST, port=PORT, debug=True)

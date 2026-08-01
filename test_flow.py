import io
import os
import shutil
import sys
from datetime import datetime, timedelta

os.environ['UPLOAD_DIR'] = '/tmp/nanoshare_test_uploads'

import app as appmod
import storage

app = appmod.app
app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

TOKEN_MAX = appmod.Config.TOKEN_MAX

results = []


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def check(name, cond, extra=''):
    status = 'PASS' if cond else 'FAIL'
    results.append((name, status, extra))
    print(f'[{status}] {name}' + (f' :: {extra}' if extra else ''))


with app.app_context():
    appmod.db.drop_all()
    appmod.db.create_all()
    shutil.rmtree(appmod.Config.UPLOAD_DIR, ignore_errors=True)
    appmod.ensure_dirs()

    client = app.test_client()

    # CSRF token: since before_request aborts POSTs without csrf, we must
    # fetch a page to establish the session csrf.
    def get_csrf():
        with client.session_transaction() as sess:
            sess['_csrf'] = 'testcsrf'
        return 'testcsrf'

    def upload(files, limit='unlimited', days='0', hours='0', minutes='0', password=''):
        data = {
            '_csrf_token': get_csrf(),
            'limit': limit,
            'days': days,
            'hours': hours,
            'minutes': minutes,
            'password': password,
            'files': [(io.BytesIO(content), fname) for fname, content in files],
        }
        return client.post('/upload', data=data, content_type='multipart/form-data')

    # --- Test 1: crypto roundtrip ---
    from crypto import derive_key, encrypt_data, decrypt_data, generate_salt
    salt = generate_salt()
    key = derive_key('secret123', salt)
    data = b'hello world' * 1000
    blob = encrypt_data(data, key)
    check('crypto roundtrip', decrypt_data(blob, key) == data)
    check('crypto wrong key fails', _raises(lambda: decrypt_data(blob, derive_key('nope', salt))))
    check('crypto blob not plaintext', b'hello' not in blob)

    # --- Test 2: plaintext upload, sequential tokens ---
    r = upload([('a.txt', b'AAA')])
    check('upload plaintext 200', r.status_code == 200, r.data[:200].decode())
    j = r.get_json()
    check('token 000001', j['token'] == '000001', str(j['token']))
    check('has_password False', j['has_password'] is False)

    r = upload([('b.txt', b'BBB')])
    j = r.get_json()
    check('token 000002', j['token'] == '000002')

    # --- Test 3: encrypted upload ---
    r = upload([('secret.txt', b'TOP SECRET DATA')], password='pw123')
    check('encrypted upload 200', r.status_code == 200)
    j = r.get_json()
    check('token 000003', j['token'] == '000003', str(j['token']))
    check('has_password True', j['has_password'] is True)

    # verify file on disk is encrypted (does not contain plaintext)
    from models import Share
    share3 = Share.query.filter_by(token=3).first()
    sf = share3.files.first()
    path = storage.file_path(share3, sf)
    with open(path, 'rb') as fh:
        disk = fh.read()
    check('file encrypted on disk', b'TOP SECRET' not in disk, f'{len(disk)} bytes')

    # --- Test 4: download via modal (POST /download) with wrong then right password ---
    r = client.post('/download', data={
        '_csrf_token': get_csrf(), 'token': '000003', 'password': 'wrong'})
    check('wrong pw redirects home with error', r.status_code == 302 and '/download/000003' not in r.headers['Location'], r.headers.get('Location', ''))

    r = client.post('/download', data={
        '_csrf_token': get_csrf(), 'token': '000003', 'password': 'pw123'})
    check('right pw redirects to share page', r.status_code == 302 and r.headers['Location'].endswith('/download/000003'), r.headers.get('Location', ''))

    r = client.get('/download/000003')
    check('share page renders', r.status_code == 200 and b'secret.txt' in r.data)

    # --- Test 5: single encrypted file download ---
    from models import SharedFile
    sf = share3.files.first()
    r = client.get(f'/download/000003/file/{sf.id}')
    check('encrypted download content', r.status_code == 200 and r.data == b'TOP SECRET DATA', r.data[:100])

    # --- Test 6: limit 1 auto-delete ---
    r = upload([('one.txt', b'ONLY ONCE')], limit='1')
    j = r.get_json()
    tok = j['token']
    share = Share.query.filter_by(token=int(tok)).first()
    sf = share.files.first()
    r = client.get(f'/download/{tok}/file/{sf.id}')
    check('limit1 first download ok', r.status_code == 200 and r.data == b'ONLY ONCE')
    r = client.get(f'/download/{tok}')
    check('limit1 share deleted after 1', r.status_code == 404)

    # --- Test 7: 5-limit exact ---
    r = upload([('five.txt', b'FIVE')], limit='5')
    j = r.get_json()
    tok = j['token']
    share = Share.query.filter_by(token=int(tok)).first()
    sf = share.files.first()
    ok = 0
    for i in range(5):
        rr = client.get(f'/download/{tok}/file/{sf.id}')
        if rr.status_code == 200 and rr.data == b'FIVE':
            ok += 1
    r = client.get(f'/download/{tok}')
    check('limit5: 5 downloads then deleted', ok == 5 and r.status_code == 404)

    # --- Test 8: token reuse ---
    r = upload([('reuse.txt', b'REUSE')])
    j = r.get_json()
    check('smallest free token assigned (000004)', j['token'] == '000004', str(j['token']))

    # --- Test 9: expiry via days/hours/minutes, clamp to 1 day ---
    r = upload([('x.txt', b'X')], days='1', hours='10', minutes='30')
    j = r.get_json()
    share = Share.query.filter_by(token=int(j['token'])).first()
    delta = share.expires_at - datetime.utcnow()
    check('expiry capped at 1 day', delta <= timedelta(days=1), str(delta))
    r = upload([('y.txt', b'Y')], minutes='90')
    j = r.get_json()
    share = Share.query.filter_by(token=int(j['token'])).first()
    delta = share.expires_at - datetime.utcnow()
    check('90 min -> 90 min', timedelta(minutes=89) < delta < timedelta(minutes=91), str(delta))

    # --- Test 10: folder-style filenames preserved ---
    r = upload([('folder/sub/note.txt', b'NOTE')])
    j = r.get_json()
    tok = j['token']
    share = Share.query.filter_by(token=int(tok)).first()
    sf = share.files.first()
    check('folder path stored', sf.original_filename == 'folder/sub/note.txt', sf.original_filename)
    r = client.get(f'/download/{tok}/file/{sf.id}')
    check('folder file download', r.status_code == 200 and r.data == b'NOTE')

    # --- Test 11: multi-file zip (mixed encrypted share) ---
    r = upload([('z1.txt', b'Z1'), ('z2.txt', b'Z2')], password='zip-pass')
    j = r.get_json()
    tok = j['token']
    client.post('/download', data={'_csrf_token': get_csrf(), 'token': tok, 'password': 'zip-pass'})
    r = client.get(f'/download/{tok}/zip')
    import zipfile
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = sorted(zf.namelist())
    check('zip contains files', names == ['z1.txt', 'z2.txt'], str(names))
    check('zip decrypts content', zf.read('z1.txt') == b'Z1')

    # --- Test 12: expiry cleanup + smallest free token ---
    share = Share.query.filter_by(token=int(j['token'])).first()
    share.expires_at = datetime.utcnow() - timedelta(seconds=1)
    appmod.db.session.commit()
    client.get('/')  # triggers cleanup
    check('expired share cleaned', Share.query.filter_by(token=share.token).first() is None)
    r = upload([('after.txt', b'AFTER')])
    j = r.get_json()
    check('smallest free token after cleanup', j['token'] == '000008', str(j['token']))

    # --- Test 12b: single-use share delivers all files as one ZIP, no per-file buttons ---
    r = upload([('u1.txt', b'U1'), ('u2.txt', b'U2')], limit='1', password='onepw')
    j = r.get_json()
    tok = j['token']
    client.post('/download', data={'_csrf_token': get_csrf(), 'token': tok, 'password': 'onepw'})
    r = client.get(f'/download/{tok}')
    body = r.data.decode()
    check('single-use page shows one ZIP action', r.status_code == 200 and 'Download all files as ZIP' in body)
    check('single-use page hides per-file buttons', '/file/' not in body, '')
    zf = zipfile.ZipFile(io.BytesIO(client.get(f'/download/{tok}/zip').data))
    check('single-use ZIP has all files', sorted(zf.namelist()) == ['u1.txt', 'u2.txt'])
    r = client.get(f'/download/{tok}')
    check('single-use share deleted after one download', r.status_code == 404)

    # --- Test 13: plaintext file does not need password ---
    r = upload([('open.txt', b'OPEN')])
    j = r.get_json()
    tok = j['token']
    r = client.post('/download', data={'_csrf_token': get_csrf(), 'token': tok, 'password': ''})
    check('open share no pw needed', r.status_code == 302 and r.headers['Location'].endswith(f'/download/{tok}'))

    # --- Test 14: CSRF protection ---
    r = client.post('/upload', data={'limit': 'unlimited'}, content_type='multipart/form-data')
    check('POST without csrf blocked (403)', r.status_code == 403)

    # --- Test 15: smoke home + 404 ---
    r = client.get('/')
    check('GET / renders', r.status_code == 200 and b'Upload' in r.data and b'Download' in r.data)
    r = client.get('/download/999999')
    check('unknown token -> 404', r.status_code == 404)


print()
passed = sum(1 for _, s, _ in results if s == 'PASS')
failed = sum(1 for _, s, _ in results if s == 'FAIL')
print(f'{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)

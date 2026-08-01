(function () {
    'use strict';

    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrf = () => (csrfMeta ? csrfMeta.getAttribute('content') : '');

    function qs(sel) { return document.querySelector(sel); }

    // ---------- Toast ----------
    function toast(message, type) {
        const box = qs('#toast-container');
        if (!box) return;
        const el = document.createElement('div');
        el.className = 'toast toast-' + type;
        el.textContent = message;
        box.appendChild(el);
        setTimeout(() => {
            el.style.transition = 'all 0.3s ease';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 320);
        }, 3000);
    }

    // ---------- Copy ----------
    function copyText(text, okMsg) {
        const done = () => toast(okMsg || 'Copied to clipboard', 'success');
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
        } else {
            fallbackCopy(text, done);
        }
    }

    function fallbackCopy(text, done) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); }
        catch (e) { toast('Could not copy', 'error'); }
        document.body.removeChild(ta);
    }

    // ---------- Landing choice ----------
    const uploadModule = qs('#upload-module');
    const landingActions = qs('.landing-actions');

    const gotoUpload = qs('#goto-upload');
    const gotoDownload = qs('#goto-download');
    const uploadBack = qs('#upload-back');

    if (gotoUpload) {
        gotoUpload.addEventListener('click', () => {
            landingActions.classList.add('hidden');
            uploadModule.classList.remove('hidden');
            uploadModule.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }
    if (uploadBack) {
        uploadBack.addEventListener('click', () => {
            uploadModule.classList.add('hidden');
            landingActions.classList.remove('hidden');
            landingActions.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }
    if (gotoDownload) {
        gotoDownload.addEventListener('click', () => openModal(qs('#download-modal')));
    }

    // ---------- Modal helpers ----------
    function openModal(overlay) {
        if (!overlay) return;
        overlay.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        const input = overlay.querySelector('input[autofocus]');
        if (input) setTimeout(() => input.focus(), 60);
    }

    function closeModal(overlay) {
        if (!overlay) return;
        overlay.classList.add('hidden');
        document.body.style.overflow = '';
    }

    document.querySelectorAll('.modal-overlay').forEach((overlay) => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal(overlay);
        });
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(closeModal);
        }
    });

    const downloadCancel = qs('#download-cancel');
    if (downloadCancel) {
        downloadCancel.addEventListener('click', () => closeModal(qs('#download-modal')));
    }

    const copyToken = qs('#copy-token');
    if (copyToken) {
        copyToken.addEventListener('click', () => {
            const token = qs('#result-token').textContent.trim();
            if (token) copyText(token, 'Token copied');
        });
    }

    const resultDone = qs('#result-done');
    if (resultDone) {
        resultDone.addEventListener('click', () => closeModal(qs('#result-modal')));
    }

    // ---------- Expiry defaults ----------
    const expDays = qs('#exp-days');
    const expHours = qs('#exp-hours');
    const expMinutes = qs('#exp-minutes');

    if (expDays && expHours && expMinutes) {
        expDays.value = '1';
        expHours.value = '0';
        expMinutes.value = '0';

        const MAX_MINUTES = 24 * 60;

        function numValue(el) {
            if (el.value === '') return 0;
            const v = parseInt(el.value, 10);
            return isNaN(v) ? 0 : v;
        }

        function clampField(el, max) {
            if (el.value === '') { el.value = '0'; return; }
            const v = Math.max(0, Math.min(numValue(el), max));
            el.value = String(v);
        }

        expDays.addEventListener('blur', () => clampField(expDays, 1));
        expHours.addEventListener('blur', () => clampField(expHours, 23));
        expMinutes.addEventListener('blur', () => clampField(expMinutes, 59));

        function totalMinutes() {
            return numValue(expDays) * 1440 + numValue(expHours) * 60 + numValue(expMinutes);
        }

        function fmt(total) {
            if (total >= 1440) return '1 day';
            if (total >= 60) {
                const h = Math.floor(total / 60);
                const m = total % 60;
                return m ? h + 'h ' + m + 'm' : h + 'h';
            }
            return total + 'm';
        }

        function updateExpirySummary() {
            const total = totalMinutes();
            const el = qs('#expiry-summary');
            if (!el) return;
            if (total === 0) {
                el.textContent = 'Will not expire (0 minutes)';
                el.classList.remove('warn');
            } else if (total > MAX_MINUTES) {
                el.textContent = 'Capped at 1 day (you entered ' + fmt(total) + ')';
                el.classList.add('warn');
            } else {
                el.textContent = 'Expires in ' + fmt(total);
                el.classList.remove('warn');
            }
        }

        expDays.addEventListener('input', updateExpirySummary);
        expHours.addEventListener('input', updateExpirySummary);
        expMinutes.addEventListener('input', updateExpirySummary);
        updateExpirySummary();
    }

    // ---------- Upload (index page) ----------
    const dropZone = qs('#drop-zone');
    const fileInput = qs('#file-input');
    const folderInput = qs('#folder-input');
    const fileListEl = qs('#file-list');
    const uploadForm = qs('#upload-form');
    const uploadBtn = qs('#upload-btn');
    const progressWrap = qs('#progress-wrap');
    const progressFill = qs('#progress-fill');
    const progressPercent = qs('#progress-percent');
    const progressStatus = qs('#progress-status');
    const resultModal = qs('#result-modal');
    const resultToken = qs('#result-token');

    const pendingFiles = [];

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
        return (bytes / 1073741824).toFixed(2) + ' GB';
    }

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function addPending(file, path) {
        pendingFiles.push({ file: file, path: path });
    }

    function renderList() {
        if (!fileListEl) return;
        if (pendingFiles.length === 0) {
            fileListEl.innerHTML = '';
            return;
        }
        let html = '';
        pendingFiles.forEach((item, i) => {
            html += '<div class="file-item">';
            html += '<i class="fa-solid fa-file c-blue"></i>';
            html += '<span class="fname">' + escapeHtml(item.path) + '</span>';
            html += '<span class="fsize">' + formatSize(item.file.size) + '</span>';
            html += '<span class="frm" data-i="' + i + '">&times;</span>';
            html += '</div>';
        });
        fileListEl.innerHTML = html;
        fileListEl.querySelectorAll('.frm').forEach((el) => {
            el.addEventListener('click', () => {
                pendingFiles.splice(parseInt(el.getAttribute('data-i'), 10), 1);
                renderList();
            });
        });
    }

    // Recursively walk dropped items (files + folders).
    function walkEntry(entry, base, acc) {
        return new Promise((resolve) => {
            if (entry.isFile) {
                entry.file((file) => {
                    acc.push({ file: file, path: base ? base + '/' + file.name : file.name });
                    resolve();
                }, () => resolve());
            } else if (entry.isDirectory) {
                const reader = entry.createReader();
                const readAll = () => {
                    reader.readEntries((entries) => {
                        if (!entries.length) { resolve(); return; }
                        Promise.all(entries.map((e) => walkEntry(e, base ? base + '/' + entry.name : entry.name, acc)))
                            .then(readAll);
                    }, () => resolve());
                };
                readAll();
            } else {
                resolve();
            }
        });
    }

    function handleDrop(e) {
        e.preventDefault();
        if (!dropZone) return;
        dropZone.classList.remove('dragover');

        const items = e.dataTransfer.items;
        if (items && items.length) {
            const acc = [];
            const promises = [];
            for (const item of items) {
                const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
                if (entry) {
                    promises.push(walkEntry(entry, '', acc));
                } else if (item.getAsFile) {
                    const f = item.getAsFile();
                    if (f) acc.push({ file: f, path: f.name });
                }
            }
            Promise.all(promises).then(() => {
                acc.forEach((x) => addPending(x.file, x.path));
                renderList();
            });
        } else {
            const files = e.dataTransfer.files;
            for (const f of files) addPending(f, f.name);
            renderList();
        }
    }

    if (dropZone) {
        dropZone.addEventListener('click', () => fileInput && fileInput.click());

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', handleDrop);
    }

    const pickFiles = qs('#pick-files');
    if (pickFiles) {
        pickFiles.addEventListener('click', (e) => {
            e.preventDefault();
            fileInput && fileInput.click();
        });
    }

    const pickFolder = qs('#pick-folder');
    if (pickFolder) {
        pickFolder.addEventListener('click', (e) => {
            e.preventDefault();
            folderInput && folderInput.click();
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', () => {
            for (const f of fileInput.files) {
                addPending(f, f.name);
            }
            renderList();
            fileInput.value = '';
        });
    }

    if (folderInput) {
        folderInput.addEventListener('change', () => {
            for (const f of folderInput.files) {
                const rel = f.webkitRelativePath || f.name;
                addPending(f, rel);
            }
            renderList();
            folderInput.value = '';
        });
    }

    if (uploadForm) {
        uploadForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (pendingFiles.length === 0) {
                toast('Please select at least one file or folder', 'error');
                return;
            }

            uploadBtn.disabled = true;
            uploadBtn.textContent = 'Uploading...';
            progressWrap.classList.remove('hidden');
            progressFill.style.width = '0%';
            progressPercent.textContent = '0%';
            progressStatus.textContent = 'Preparing...';

            const fd = new FormData();
            for (const item of pendingFiles) {
                fd.append('files', item.file, item.path);
            }
            fd.append('limit', qs('#limit').value);
            fd.append('days', qs('#exp-days').value || '0');
            fd.append('hours', qs('#exp-hours').value || '0');
            fd.append('minutes', qs('#exp-minutes').value || '0');
            fd.append('password', qs('#password').value.trim());
            fd.append('_csrf_token', csrf());

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/upload', true);

            xhr.upload.onprogress = (ev) => {
                if (ev.lengthComputable) {
                    const pct = Math.round((ev.loaded / ev.total) * 100);
                    progressFill.style.width = pct + '%';
                    progressPercent.textContent = pct + '%';
                    progressStatus.textContent = 'Uploading...';
                }
            };

            xhr.onload = () => {
                uploadBtn.disabled = false;
                uploadBtn.textContent = 'Upload';
                let data = null;
                try { data = JSON.parse(xhr.responseText); } catch (err) { /* ignore */ }

                if (xhr.status >= 200 && xhr.status < 300 && data && data.success) {
                    progressFill.style.width = '100%';
                    progressPercent.textContent = '100%';
                    progressStatus.textContent = 'Done';
                    showResult(data);
                    pendingFiles.length = 0;
                    renderList();
                } else {
                    progressWrap.classList.add('hidden');
                    toast((data && data.error) || 'Upload failed', 'error');
                }
            };

            xhr.onerror = () => {
                uploadBtn.disabled = false;
                uploadBtn.textContent = 'Upload';
                progressWrap.classList.add('hidden');
                toast('Network error during upload', 'error');
            };

            xhr.send(fd);
        });
    }

    function showResult(data) {
        if (!resultToken) return;
        resultToken.textContent = data.token;
        openModal(resultModal);
    }
})();

/* ui/static/ui/js/scripts.js */

/* ============================================
   Theme toggle
   ============================================ */
function initThemeToggle() {
    const toggle = document.getElementById('themeToggle');
    if (!toggle) return;

    function updateIcon() {
        const theme = document.documentElement.getAttribute('data-bs-theme');
        const icon = toggle.querySelector('i');
        if (icon) {
            icon.className = theme === 'dark' ? 'bi bi-moon' : 'bi bi-sun';
        }
    }

    updateIcon();

    toggle.addEventListener('click', function () {
        const current = document.documentElement.getAttribute('data-bs-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-bs-theme', next);
        localStorage.setItem('theme', next);
        updateIcon();
    });
}

/* ============================================
   Folder state persistence
   ============================================ */
function getFolderTargetId(header) {
    const attr = header.getAttribute('data-bs-target') || header.getAttribute('href') || '';
    return attr.replace('#', '');
}

function initFolderStates() {
    const folderHeaders = document.querySelectorAll('.folder-header');

    folderHeaders.forEach(header => {
        const targetId = getFolderTargetId(header);
        if (!targetId) return;
        const target = document.getElementById(targetId);
        const saved = localStorage.getItem(`folder-${targetId}`);

        if (saved === 'collapsed') {
            header.setAttribute('aria-expanded', 'false');
            if (target) target.classList.remove('show');
        } else if (saved === 'expanded') {
            header.setAttribute('aria-expanded', 'true');
            if (target) target.classList.add('show');
        }
    });

    folderHeaders.forEach(header => {
        header.addEventListener('click', function () {
            const targetId = getFolderTargetId(this);
            if (!targetId) return;
            const isExpanded = this.getAttribute('aria-expanded') === 'true';
            localStorage.setItem(`folder-${targetId}`, isExpanded ? 'collapsed' : 'expanded');
        });
    });
}

/* ============================================
   Copy to clipboard
   ============================================ */
function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    } else {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        return new Promise((resolve, reject) => {
            try {
                const success = document.execCommand('copy');
                document.body.removeChild(textArea);
                if (success) {
                    resolve();
                } else {
                    reject('Copy command failed');
                }
            } catch (err) {
                document.body.removeChild(textArea);
                reject(err);
            }
        });
    }
}

function initCopyButtons() {
    document.querySelectorAll('.copy-pull-btn').forEach(button => {
        button.addEventListener('click', function () {
            const command = this.getAttribute('data-command');
            if (command) {
                copyToClipboard(command)
                    .then(() => {
                        const originalHTML = this.innerHTML;
                        this.innerHTML = '<i class="bi bi-check"></i>';
                        this.classList.add('copy-success');
                        setTimeout(() => {
                            this.innerHTML = originalHTML;
                            this.classList.remove('copy-success');
                        }, 1500);
                    })
                    .catch(err => console.error('Copy failed:', err));
            }
        });
    });
}

/* ============================================
   Async tag detail loading
   ============================================ */
function initTagDetails() {
    const table = document.querySelector('table[data-repository]');
    if (!table) return;

    const repository = table.getAttribute('data-repository');
    const tbody = table.querySelector('tbody');

    fetch(`/ui/repositories/${encodeURI(repository)}/tag-details/`)
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(data => {
            tbody.querySelectorAll('tr[data-tag-name]').forEach(row => {
                const tag = row.getAttribute('data-tag-name');
                const detail = data[tag];
                if (!detail) return;

                row.setAttribute('data-created', detail.created || '');

                const createdCell = row.querySelector('.tag-created');
                if (createdCell) createdCell.textContent = detail.age;

                const sizeCell = row.querySelector('.tag-size');
                if (sizeCell) sizeCell.textContent = detail.size;

                const archCell = row.querySelector('.tag-arch');
                if (archCell) {
                    archCell.innerHTML = detail.architectures.map(arch =>
                        `<div class="mb-1"><span class="badge rounded-pill arch-badge arch-${arch.toLowerCase()}">${arch}</span></div>`
                    ).join('');
                }
            });

            const rows = Array.from(tbody.querySelectorAll('tr[data-tag-name]'));
            rows.sort((a, b) => {
                const dateA = a.getAttribute('data-created') || '';
                const dateB = b.getAttribute('data-created') || '';
                return dateB.localeCompare(dateA);
            });
            rows.forEach(row => tbody.appendChild(row));
        })
        .catch(error => {
            console.error('Error fetching tag details:', error);
            tbody.querySelectorAll('tr[data-tag-name]').forEach(row => {
                const createdCell = row.querySelector('.tag-created');
                const sizeCell = row.querySelector('.tag-size');
                const archCell = row.querySelector('.tag-arch');
                if (createdCell) createdCell.textContent = 'Error';
                if (sizeCell) sizeCell.textContent = 'Error';
                if (archCell) archCell.textContent = 'Error';
            });
        });
}

/* ============================================
   Admin delete logic
   ============================================ */
function getCsrfToken() {
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

function initAdminDelete() {
    let pendingDeleteTag = null;
    let pendingDeleteRepo = null;

    // Delete tag (detail page)
    document.querySelectorAll('.delete-tag-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            pendingDeleteTag = this.getAttribute('data-tag');
            const nameEl = document.getElementById('deleteTagName');
            if (nameEl) nameEl.textContent = pendingDeleteTag;
            const modal = new bootstrap.Modal(document.getElementById('deleteTagModal'));
            modal.show();
        });
    });

    const confirmDeleteTag = document.getElementById('confirmDeleteTag');
    if (confirmDeleteTag) {
        confirmDeleteTag.addEventListener('click', function () {
            if (!pendingDeleteTag) return;
            const table = document.querySelector('table[data-repository]');
            const repository = table ? table.getAttribute('data-repository') : '';

            fetch(`/ui/repositories/${encodeURI(repository)}/delete-tag/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `tag=${encodeURIComponent(pendingDeleteTag)}`,
            })
                .then(resp => resp.json().then(data => ({status: resp.status, data})))
                .then(({status, data}) => {
                    bootstrap.Modal.getInstance(document.getElementById('deleteTagModal')).hide();
                    if (data.success) {
                        const row = document.querySelector(`tr[data-tag-name="${pendingDeleteTag}"]`);
                        if (row) row.remove();
                        const badge = document.querySelector('.badge.bg-info');
                        if (badge) {
                            const current = parseInt(badge.textContent) || 0;
                            badge.textContent = Math.max(0, current - 1);
                        }
                    } else {
                        alert('Error: ' + (data.error || 'Unknown error'));
                    }
                    pendingDeleteTag = null;
                })
                .catch(err => {
                    bootstrap.Modal.getInstance(document.getElementById('deleteTagModal')).hide();
                    alert('Error deleting tag: ' + err);
                    pendingDeleteTag = null;
                });
        });
    }

    // Delete repo (detail page, "Delete All Tags")
    const confirmDeleteRepo = document.getElementById('confirmDeleteRepo');
    if (confirmDeleteRepo) {
        confirmDeleteRepo.addEventListener('click', function () {
            const table = document.querySelector('table[data-repository]');
            const repository = table ? table.getAttribute('data-repository') : '';
            const btn = this;
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Deleting...';
            btn.disabled = true;

            fetch(`/ui/repositories/${encodeURI(repository)}/delete/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
            })
                .then(resp => resp.json().then(data => ({status: resp.status, data})))
                .then(({status, data}) => {
                    bootstrap.Modal.getInstance(document.getElementById('deleteRepoModal')).hide();
                    if (data.success || data.deleted.length > 0) {
                        window.location.href = '/ui/repositories/';
                    } else {
                        btn.innerHTML = originalText;
                        btn.disabled = false;
                        alert('Error: ' + (data.errors.map(e => e.tag + ': ' + e.error).join('\n') || 'Unknown error'));
                    }
                })
                .catch(err => {
                    bootstrap.Modal.getInstance(document.getElementById('deleteRepoModal')).hide();
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                    alert('Error deleting repository: ' + err);
                });
        });
    }

    // Delete repo (list page)
    document.querySelectorAll('.delete-repo-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            pendingDeleteRepo = this.getAttribute('data-repository');
            const nameEl = document.getElementById('deleteRepoListName');
            if (nameEl) nameEl.textContent = pendingDeleteRepo;
        });
    });

    const confirmDeleteRepoList = document.getElementById('confirmDeleteRepoList');
    if (confirmDeleteRepoList) {
        confirmDeleteRepoList.addEventListener('click', function () {
            if (!pendingDeleteRepo) return;
            const btn = this;
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Deleting...';
            btn.disabled = true;

            fetch(`/ui/repositories/${encodeURI(pendingDeleteRepo)}/delete/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
            })
                .then(resp => resp.json().then(data => ({status: resp.status, data})))
                .then(({status, data}) => {
                    bootstrap.Modal.getInstance(document.getElementById('deleteRepoListModal')).hide();
                    if (data.success || data.deleted.length > 0) {
                        window.location.reload();
                    } else {
                        btn.innerHTML = originalText;
                        btn.disabled = false;
                        alert('Error: ' + (data.errors.map(e => e.tag + ': ' + e.error).join('\n') || 'Unknown error'));
                    }
                })
                .catch(err => {
                    bootstrap.Modal.getInstance(document.getElementById('deleteRepoListModal')).hide();
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                    alert('Error deleting repository: ' + err);
                    pendingDeleteRepo = null;
                });
        });
    }
}

/* ============================================
   Async tag count loading (list page) — batch sequential
   ============================================ */
function initTagCounts() {
    const tagElements = document.querySelectorAll('[data-repo-name]');
    if (tagElements.length === 0) return;

    // Collect unique repo names preserving order
    const seen = new Set();
    const allRepos = [];
    tagElements.forEach(el => {
        const name = el.getAttribute('data-repo-name');
        if (name && !seen.has(name)) {
            seen.add(name);
            allRepos.push(name);
        }
    });

    // Split into batches of 10
    const BATCH_SIZE = 10;
    const batches = [];
    for (let i = 0; i < allRepos.length; i += BATCH_SIZE) {
        batches.push(allRepos.slice(i, i + BATCH_SIZE));
    }

    function applyTagCounts(data) {
        tagElements.forEach(el => {
            const repoName = el.getAttribute('data-repo-name');
            if (!(repoName in data)) return;
            const tagCount = data[repoName] || 0;

            if (tagCount > 0) {
                el.textContent = `${tagCount} tag${tagCount !== 1 ? 's' : ''}`;
                el.classList.add('tag-count-loaded');
            } else {
                el.textContent = '0 tags';
                el.classList.add('tag-count-zero');
            }
        });
    }

    function markError(repoNames) {
        tagElements.forEach(el => {
            const repoName = el.getAttribute('data-repo-name');
            if (repoNames.includes(repoName)) {
                el.textContent = 'Error';
                el.classList.add('tag-count-error');
            }
        });
    }

    async function fetchBatches() {
        for (const batch of batches) {
            try {
                const params = new URLSearchParams({ repos: batch.join(',') });
                const response = await fetch(`/ui/tag-counts/?${params}`);
                if (!response.ok) throw new Error('Network response was not ok');
                const data = await response.json();
                applyTagCounts(data);
            } catch (error) {
                console.error('Error fetching tag counts batch:', error);
                markError(batch);
            }
        }
    }

    fetchBatches();
}

/* ============================================
   Admin stats page — progressive loader
   ============================================ */
function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    let i = 0;
    let v = bytes;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i++;
    }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 2)} ${units[i]}`;
}

function initAdminStats() {
    const root = document.getElementById('adminStats');
    if (!root) return;

    const els = {
        repos: document.getElementById('kpiRepos'),
        tags: document.getElementById('kpiTags'),
        size: document.getElementById('kpiSize'),
        empty: document.getElementById('kpiEmpty'),
        progressBar: document.getElementById('statsProgressBar'),
        progressLabel: document.getElementById('statsProgressLabel'),
        progressCounter: document.getElementById('statsProgressCounter'),
        emptyCard: document.getElementById('emptyReposCard'),
        emptyList: document.getElementById('emptyReposList'),
        topSize: document.getElementById('topBySizeBody'),
        topTags: document.getElementById('topByTagsBody'),
        errorBox: document.getElementById('statsError'),
        errorMessage: document.getElementById('statsErrorMessage'),
        errorsCard: document.getElementById('statsErrorsCard'),
        errorsList: document.getElementById('statsErrorsList'),
        refreshBtn: document.getElementById('statsRefreshBtn'),
    };

    const TOP_N = 10;
    const CONCURRENCY = 4;

    let state = null;

    function showError(msg) {
        els.errorMessage.textContent = msg;
        els.errorBox.classList.remove('d-none');
    }

    function clearError() {
        els.errorBox.classList.add('d-none');
    }

    function renderEmptyRepos(empty) {
        if (!empty.length) {
            els.emptyCard.classList.add('d-none');
            return;
        }
        els.emptyCard.classList.remove('d-none');
        els.emptyList.innerHTML = empty
            .map(repo => `
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-box me-2 text-muted"></i>${repo}</span>
                    <span class="badge bg-secondary">0 tags</span>
                </li>`)
            .join('');
    }

    function renderTopBySize() {
        const top = state.perRepo
            .filter(r => r.size > 0)
            .sort((a, b) => b.size - a.size)
            .slice(0, TOP_N);

        if (!top.length) {
            els.topSize.innerHTML = '<tr><td colspan="3" class="text-muted text-center">No data yet…</td></tr>';
            return;
        }
        els.topSize.innerHTML = top
            .map(r => `
                <tr>
                    <td><a href="/ui/repositories/${encodeURI(r.repository)}/">${r.repository}</a></td>
                    <td class="text-right">${r.tags}</td>
                    <td class="text-right">${formatBytes(r.size)}</td>
                </tr>`)
            .join('');
    }

    function renderTopByTags() {
        const top = Object.entries(state.tagCounts)
            .filter(([, n]) => n > 0)
            .sort((a, b) => b[1] - a[1])
            .slice(0, TOP_N);

        if (!top.length) {
            els.topTags.innerHTML = '<tr><td colspan="2" class="text-muted text-center">No data</td></tr>';
            return;
        }
        els.topTags.innerHTML = top
            .map(([repo, count]) => `
                <tr>
                    <td><a href="/ui/repositories/${encodeURI(repo)}/">${repo}</a></td>
                    <td class="text-right">${count}</td>
                </tr>`)
            .join('');
    }

    function pushError(repo, msg) {
        state.errors.push({ repository: repo, error: msg });
        els.errorsCard.classList.remove('d-none');
        const li = document.createElement('li');
        li.className = 'list-group-item';
        li.innerHTML = `<code>${repo}</code> — <span class="text-muted"></span>`;
        li.querySelector('span').textContent = msg;
        els.errorsList.appendChild(li);
    }

    function updateProgress() {
        const total = state.reposToProcess.length;
        const done = state.processed;
        const pct = total > 0 ? (done / total) * 100 : 100;
        els.progressBar.style.width = `${pct}%`;
        els.progressCounter.textContent = `${done} / ${total}`;
        if (done === total) {
            els.progressLabel.textContent = total === 0 ? 'No repositories to scan.' : 'Done.';
        } else {
            els.progressLabel.textContent = 'Scanning repositories…';
        }
    }

    async function fetchRepoStats(repo) {
        const url = `/ui/stats/repo/${encodeURI(repo)}/${state.force ? '?refresh=true' : ''}`;
        try {
            const resp = await fetch(url);
            if (!resp.ok) {
                const body = await resp.json().catch(() => ({}));
                throw new Error(body.error || `HTTP ${resp.status}`);
            }
            const data = await resp.json();
            state.perRepo.push({
                repository: data.repository,
                tags: data.tags,
                size: data.size,
            });
            state.totalSize += data.size || 0;
            els.size.textContent = formatBytes(state.totalSize);
            renderTopBySize();
            (data.errors || []).forEach(e => pushError(`${repo}:${e.tag}`, e.error));
        } catch (err) {
            pushError(repo, err.message || String(err));
        } finally {
            state.processed += 1;
            updateProgress();
        }
    }

    async function runWorkers() {
        const queue = state.reposToProcess.slice();
        const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
            while (queue.length) {
                const repo = queue.shift();
                await fetchRepoStats(repo);
            }
        });
        await Promise.all(workers);
    }

    async function load(force) {
        clearError();
        state = {
            force: !!force,
            perRepo: [],
            tagCounts: {},
            reposToProcess: [],
            processed: 0,
            totalSize: 0,
            errors: [],
        };
        els.errorsCard.classList.add('d-none');
        els.errorsList.innerHTML = '';
        els.size.textContent = '—';
        els.topSize.innerHTML = '<tr><td colspan="3" class="text-muted text-center">Waiting for data…</td></tr>';
        els.topTags.innerHTML = '<tr><td colspan="2" class="text-muted text-center">Waiting for data…</td></tr>';
        els.progressBar.style.width = '0%';
        els.progressCounter.textContent = '';
        els.progressLabel.textContent = 'Loading summary…';
        els.refreshBtn.disabled = true;

        try {
            const resp = await fetch(`/ui/stats/summary/${force ? '?refresh=true' : ''}`);
            if (!resp.ok) {
                const body = await resp.json().catch(() => ({}));
                throw new Error(body.error || `HTTP ${resp.status}`);
            }
            const summary = await resp.json();

            els.repos.textContent = summary.total_repositories;
            els.tags.textContent = summary.total_tags;
            els.empty.textContent = summary.empty_repositories.length;
            state.tagCounts = summary.tag_counts || {};
            renderTopByTags();
            renderEmptyRepos(summary.empty_repositories || []);

            state.reposToProcess = (summary.repositories || []).filter(
                r => (summary.tag_counts[r] || 0) > 0
            );
            updateProgress();

            await runWorkers();
        } catch (err) {
            showError(err.message || String(err));
        } finally {
            els.refreshBtn.disabled = false;
        }
    }

    els.refreshBtn.addEventListener('click', () => load(true));
    load(false);
}

/* ============================================
   Initialize everything on DOMContentLoaded
   ============================================ */
document.addEventListener('DOMContentLoaded', function () {
    initThemeToggle();
    initFolderStates();
    initCopyButtons();
    initTagDetails();
    initAdminDelete();
    initTagCounts();
    initAdminStats();
});

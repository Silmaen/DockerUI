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
   Initialize everything on DOMContentLoaded
   ============================================ */
document.addEventListener('DOMContentLoaded', function () {
    initThemeToggle();
    initFolderStates();
    initCopyButtons();
    initTagDetails();
    initAdminDelete();
    initTagCounts();
});

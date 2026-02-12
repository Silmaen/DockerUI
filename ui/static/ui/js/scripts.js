/* ui/static/ui/js/scripts.js */
document.addEventListener('DOMContentLoaded', function () {
    // Get all folder headers
    const folderHeaders = document.querySelectorAll('.folder-header');

    // Load saved states
    folderHeaders.forEach(header => {
        const targetId = header.getAttribute('data-bs-target').replace('#', '');
        const target = document.getElementById(targetId);
        const isCollapsed = localStorage.getItem(`folder-${targetId}`) === 'collapsed';

        if (isCollapsed) {
            header.setAttribute('aria-expanded', 'false');
            if (target) target.classList.remove('show');
        } else if (localStorage.getItem(`folder-${targetId}`) === 'expanded') {
            header.setAttribute('aria-expanded', 'true');
            if (target) target.classList.add('show');
        }
    });

    // Save state on click
    folderHeaders.forEach(header => {
        header.addEventListener('click', function () {
            const targetId = this.getAttribute('data-bs-target').replace('#', '');
            const isExpanded = this.getAttribute('aria-expanded') === 'true';
            localStorage.setItem(`folder-${targetId}`, isExpanded ? 'collapsed' : 'expanded');
        });
    });
});

// Copy docker pull command
function copyToClipboard(text) {
    // Method 1: Try modern clipboard API (works in HTTPS)
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    } else {
        // Method 2: Fallback for HTTP using document.execCommand
        const textArea = document.createElement('textarea');
        textArea.value = text;

        // Make it invisible but keep it functional
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

// Replace your existing click handler with this
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.copy-pull-btn').forEach(button => {
        button.addEventListener('click', function () {
            const command = this.getAttribute('data-command');
            if (command) {
                copyToClipboard(command)
                    .then(() => {
                        // Visual feedback
                        const originalHTML = this.innerHTML;
                        this.innerHTML = '<i class="bi bi-check"></i>';
                        this.classList.add('btn-success');
                        this.classList.remove('btn-outline-secondary');

                        setTimeout(() => {
                            this.innerHTML = originalHTML;
                            this.classList.remove('btn-success');
                            this.classList.add('btn-outline-secondary');
                        }, 1500);
                    })
                    .catch(err => console.error('Copy failed:', err));
            }
        });
    });
});

// Async tag detail loading for repository detail page
document.addEventListener('DOMContentLoaded', function () {
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
            // Update each row with details
            tbody.querySelectorAll('tr[data-tag-name]').forEach(row => {
                const tag = row.getAttribute('data-tag-name');
                const detail = data[tag];
                if (!detail) return;

                // Set created date for sorting
                row.setAttribute('data-created', detail.created || '');

                // Update Created cell
                const createdCell = row.querySelector('.tag-created');
                if (createdCell) createdCell.textContent = detail.age;

                // Update Size cell
                const sizeCell = row.querySelector('.tag-size');
                if (sizeCell) sizeCell.textContent = detail.size;

                // Update Architecture cell with badges
                const archCell = row.querySelector('.tag-arch');
                if (archCell) {
                    archCell.innerHTML = detail.architectures.map(arch =>
                        `<div class="mb-1"><span class="badge rounded-pill arch-badge arch-${arch.toLowerCase()}">${arch}</span></div>`
                    ).join('');
                }
            });

            // Sort rows by created date descending (ISO dates sort lexicographically)
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
});

// --- Admin delete logic ---
function getCsrfToken() {
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

document.addEventListener('DOMContentLoaded', function () {
    let pendingDeleteTag = null;
    let pendingDeleteRepo = null;

    // --- Delete tag (detail page) ---
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
                        // Decrement badge count
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

    // --- Delete repo (detail page, "Delete All Tags") ---
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

    // --- Delete repo (list page) ---
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
});

document.addEventListener('DOMContentLoaded', function () {
    // Get all tag count elements
    const tagElements = document.querySelectorAll('[data-repo-name]');

    // Only proceed if there are elements to update
    if (tagElements.length > 0) {
        // Show loading indicators
        tagElements.forEach(el => {
            el.innerHTML = '<small><i class="bi bi-hourglass-split loading-spin"></i></small>';
            el.classList.add('bg-dark', 'text-white');
        });

        // Fetch tag counts
        fetch('/ui/tag-counts/')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                tagElements.forEach(element => {
                    const repoName = element.getAttribute('data-repo-name');
                    const tagCount = data[repoName] || 0;

                    if (tagCount > 0) {
                        element.textContent = `${tagCount} tag${tagCount !== 1 ? 's' : ''}`;
                        element.classList.remove('bg-dark');
                        element.classList.add('bg-primary');
                    } else {
                        element.textContent = '0 tags';
                        element.classList.remove('bg-dark');
                        element.classList.add('bg-secondary');
                    }
                });
            })
            .catch(error => {
                console.error('Error fetching tag counts:', error);
                tagElements.forEach(element => {
                    element.textContent = 'Error';
                    element.classList.remove('bg-dark');
                    element.classList.add('bg-danger');
                });
            });
    }
});

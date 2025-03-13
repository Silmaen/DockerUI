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
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.copy-pull-btn').forEach(button => {
        button.addEventListener('click', function () {
            const command = this.getAttribute('data-command');
            navigator.clipboard.writeText(command)
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
        });
    });
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

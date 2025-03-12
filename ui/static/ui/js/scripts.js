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
document.querySelectorAll('.copy-pull-btn').forEach(button => {
    button.addEventListener('click', function () {
        // Get repository and tag from data attributes
        const registry = this.getAttribute('data-registry') || '';
        const repo = this.getAttribute('data-repo');
        const tag = this.getAttribute('data-tag');

        // Properly format the pull command with the registry
        let pullCommand = '';
        if (registry && registry.trim() !== '') {
            pullCommand = `docker pull ${registry}/${repo}:${tag}`;
        } else {
            pullCommand = `docker pull ${repo}:${tag}`;
        }

        // Create a textarea element (works better than input for clipboard operations)
        const textarea = document.createElement('textarea');
        textarea.value = pullCommand;

        // Make it part of the document but visually hidden
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);

        // Select the text and copy to clipboard
        textarea.focus();
        textarea.select();

        try {
            // Execute the copy command
            const successful = document.execCommand('copy');

            // Visual feedback
            const icon = this.querySelector('i');
            if (successful) {
                const originalClass = icon.className;
                icon.className = 'far fa-check-circle';
                setTimeout(() => {
                    icon.className = originalClass;
                }, 2000);
            }
        } catch (err) {
            console.error('Failed to copy text: ', err);
        }

        // Remove the textarea
        document.body.removeChild(textarea);
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

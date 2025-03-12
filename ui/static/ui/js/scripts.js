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

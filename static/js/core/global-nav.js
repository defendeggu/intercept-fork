(() => {
    const dropdowns = Array.from(document.querySelectorAll('.mode-nav-dropdown'));
    if (!dropdowns.length) return;

    const closeAll = () => {
        dropdowns.forEach((dropdown) => dropdown.classList.remove('open'));
    };

    const openDropdown = (dropdown) => {
        if (!dropdown.classList.contains('open')) {
            closeAll();
            dropdown.classList.add('open');
        }
    };

    document.addEventListener('click', (event) => {
        const menuLink = event.target.closest('.mode-nav-dropdown-menu a');
        if (menuLink) {
            event.preventDefault();
            event.stopPropagation();
            window.location.href = menuLink.href;
            return;
        }

        const button = event.target.closest('.mode-nav-dropdown-btn');
        if (button) {
            event.preventDefault();
            const dropdown = button.closest('.mode-nav-dropdown');
            if (!dropdown) return;
            if (dropdown.classList.contains('open')) {
                dropdown.classList.remove('open');
            } else {
                openDropdown(dropdown);
            }
            return;
        }

        if (!event.target.closest('.mode-nav-dropdown')) {
            closeAll();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeAll();
        }
    });
})();

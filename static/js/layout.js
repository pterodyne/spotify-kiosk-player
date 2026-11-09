/* Presentation only: retain the existing panes, listeners and playback state. */
(() => {
    const container = document.querySelector('.container');
    const toggle = document.querySelector('.library-tracks-toggle');
    if (!container || !toggle) return;

    function selectPane(pane) {
        container.dataset.activePane = pane;
        toggle.querySelectorAll('button[data-pane]').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.pane === pane));
        });
    }

    toggle.addEventListener('click', event => {
        const button = event.target.closest('button[data-pane]');
        if (button) selectPane(button.dataset.pane);
    });
    document.querySelector('#playlists-container')?.addEventListener('click', event => {
        if (window.matchMedia('(max-width: 900px)').matches &&
            event.target.closest('.playlist-item, .artist-item')) {
            selectPane('tracks');
            // The selected library button is now hidden; keep keyboard focus usable.
            toggle.querySelector('[data-pane="tracks"]').focus({ preventScroll: true });
        }
    });
    selectPane('library');
})();

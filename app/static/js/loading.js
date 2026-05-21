(function() {
    function createLoadingOverlay() {
        let overlay = document.getElementById("globalLoadingOverlay");

        if (overlay) {
            return overlay;
        }

        overlay = document.createElement("div");
        overlay.id = "globalLoadingOverlay";
        overlay.className = "loading-overlay";
        overlay.setAttribute("aria-hidden", "true");

        overlay.innerHTML = `
            <div class="loading-box" role="status" aria-live="polite">
                <div class="loading-spinner" aria-hidden="true">
                    <span></span>
                    <span></span>
                    <span></span>
                    <span></span>
                    <span></span>
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                <div id="globalLoadingText"></div>
            </div>
        `;

        document.body.appendChild(overlay);
        return overlay;
    }

    window.showLoading = function () {
        const overlay = createLoadingOverlay();
        const text = document.getElementById("globalLoadingText");

        overlay.classList.add("show");
        overlay.setAttribute("aria-hidden", "false");
        document.body.classList.add("loading-active");
    };

    window.hideLoading = function () {
        const overlay = document.getElementById("globalLoadingOverlay");

        if (!overlay) {
            return
        }

        overlay.classList.remove("show");
        overlay.setAttribute("aria-hidden", "true");
        document.body.classList.remove("loading-active");
    };

    window.withLoading = async function (callback) {
        try {
            window.showLoading(message);
            return await callback();
        } finally {
            window.hideLoading();
        }
    };
})();
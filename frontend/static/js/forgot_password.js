document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("forgotPasswordForm");

    if (!form) {
        return;
    }

    form.addEventListener("submit", () => {
        const submitButton = form.querySelector("button[type='submit']");

        if (window.showLoading) {
            window.showLoading();
        }

        if (submitButton) {
            submitButton.classList.add("is-loading");
            submitButton.disabled = true;
            submitButton.dataset.originalText = submitButton.textContent.trim()
        }
    });
});
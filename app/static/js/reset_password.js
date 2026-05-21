document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("resetPasswordForm");

    if (!form) {
        return;
    }

    form.addEventListener("submit", (event) => {
        const password = document.getElementById("password")?.value || "";
        const confirmPassword = document.getElementById("confirm_password")?.value || "";
        const submitButton = form.querySelector("button[type='submit']");

        if (password.length < 8) {
            event.preventDefault();
            alert("Password must be at least 8 characters.");
            return;
        }

        if (password != confirmPassword) {
            event.preventDefault();
            alert("Password do not match.");
            return;
        }

        if (window.showLoading) {
            window.showLoading();
        }

        if (submitButton) {
            submitButton.classList.add("is-loading");
            submitButton.disabled = true;
            submitButton.dataset.originalText = submitButton.textContent.trim();
        }
    });
});
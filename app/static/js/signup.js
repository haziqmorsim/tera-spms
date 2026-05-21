document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("signUpForm");

    if (!form) {
        return;
    }

    form.addEventListener("submit", (event) => {
        const password = document.getElementById("password")?.value || "";
        const confirmPassword = document.getElementById("confirmPassword")?.value || "";
        const submitButton = document.querySelector("button[type='submit']");

        if (password != confirmPassword) {
            event.preventDefault();

            if (window.hideLoading) {
                window.hideLoading();
            }

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
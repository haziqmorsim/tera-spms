document.addEventListener("DOMContentLoaded", async () => {
  await redirectIfAuthenticated();

  const form = document.getElementById("resetPasswordForm");
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") || "";

  if (!token) {
    showPageAlert("authAlert", "Reset token is missing.");
    return;
  }

  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const password = document.getElementById("password").value;
    const confirmPassword = document.getElementById("confirm_password").value;
    const submitButton = form.querySelector("button[type='submit']");

    if (password.length < 8) {
      showPageAlert("authAlert", "Password must be at least 8 characters.");
      return;
    }

    if (password !== confirmPassword) {
      showPageAlert("authAlert", "Passwords do not match.");
      return;
    }

    try {
      if (window.showLoading) window.showLoading();

      if (submitButton) {
        submitButton.disabled = true;
        submitButton.classList.add("is-loading");
      }

      await apiFetch("/api/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({
          token,
          password,
          confirm_password: confirmPassword,
        }),
      });

      window.location.href = "/signin.html?reset=success";
    } catch (error) {
      showPageAlert("authAlert", error.message || "Failed to reset password.");
    } finally {
      if (window.hideLoading) window.hideLoading();

      if (submitButton) {
        submitButton.disabled = false;
        submitButton.classList.remove("is-loading");
      }
    }
  });
});
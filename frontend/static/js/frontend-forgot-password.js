document.addEventListener("DOMContentLoaded", async () => {
  await redirectIfAuthenticated();

  const form = document.getElementById("forgotPasswordForm");

  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const submitButton = form.querySelector("button[type='submit']");

    try {
      if (window.showLoading) window.showLoading();

      if (submitButton) {
        submitButton.disabled = true;
        submitButton.classList.add("is-loading");
      }

      const data = await apiFetch("/api/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({
          email: document.getElementById("email").value,
        }),
      });

      showPageAlert(
        "authAlert",
        data.message || "If that account exists, a reset link has been sent.",
        "success"
      );
    } catch (error) {
      showPageAlert("authAlert", error.message || "Failed to process request.");
    } finally {
      if (window.hideLoading) window.hideLoading();

      if (submitButton) {
        submitButton.disabled = false;
        submitButton.classList.remove("is-loading");
      }
    }
  });
});
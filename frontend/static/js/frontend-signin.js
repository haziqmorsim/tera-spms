document.addEventListener("DOMContentLoaded", async () => {
  await redirectIfAuthenticated();

  const form = document.getElementById("signInForm");

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

      await apiFetch("/api/auth/signin", {
        method: "POST",
        body: JSON.stringify({
          email: document.getElementById("email").value,
          password: document.getElementById("password").value,
        }),
      });

      window.location.href = "/";
    } catch (error) {
      showPageAlert("authAlert", error.message || "Failed to sign in.");
    } finally {
      if (window.hideLoading) window.hideLoading();

      if (submitButton) {
        submitButton.disabled = false;
        submitButton.classList.remove("is-loading");
      }
    }
  });
});
// Shared progressive enhancement for confirmation forms.
document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
  }
});

document.addEventListener("error", (event) => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement) || !image.dataset.fallbackSrc) return;
  if (image.getAttribute("src") !== image.dataset.fallbackSrc) {
    image.src = image.dataset.fallbackSrc;
  }
}, true);

document.addEventListener("click", (event) => {
  const notificationToggle = event.target.closest("[data-notification-toggle]");
  const notificationMenu = document.querySelector("[data-notification-menu]");
  if (notificationToggle && notificationMenu) {
    const isOpen = notificationToggle.getAttribute("aria-expanded") === "true";
    notificationToggle.setAttribute("aria-expanded", String(!isOpen));
    notificationMenu.hidden = isOpen;
    return;
  }

  if (notificationMenu && !notificationMenu.hidden && !event.target.closest(".notification-menu-wrap")) {
    notificationMenu.hidden = true;
    document.querySelector("[data-notification-toggle]")?.setAttribute("aria-expanded", "false");
  }

  const previewButton = event.target.closest("[data-image-preview]");
  if (previewButton) {
    const dialog = document.getElementById("admin-image-dialog");
    const previewImage = document.getElementById("admin-image-dialog-img");
    if (dialog && previewImage && !dialog.open) {
      previewImage.src = previewButton.dataset.imagePreview;
      previewImage.alt = previewButton.dataset.imageAlt || "";
      dialog.showModal();
    }
    return;
  }

  const imageDialog = document.getElementById("admin-image-dialog");
  if (imageDialog && event.target === imageDialog) {
    imageDialog.close();
    return;
  }

  const button = event.target.closest("[data-password-toggle]");
  if (!button) return;

  const input = document.getElementById(button.dataset.passwordToggle);
  if (!input) return;

  const showPassword = input.type === "password";
  input.type = showPassword ? "text" : "password";
  button.textContent = showPassword ? "Ẩn" : "Hiện";
  button.setAttribute("aria-label", `${showPassword ? "Ẩn" : "Hiện"} mật khẩu`);
  button.setAttribute("aria-pressed", String(showPassword));
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const notificationMenu = document.querySelector("[data-notification-menu]");
  const notificationToggle = document.querySelector("[data-notification-toggle]");
  if (notificationMenu && !notificationMenu.hidden) {
    notificationMenu.hidden = true;
    notificationToggle?.setAttribute("aria-expanded", "false");
    notificationToggle?.focus();
  }
});

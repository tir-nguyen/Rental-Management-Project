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

const listingImageInput = document.querySelector("[data-listing-image-input]");
const listingImagePreview = document.querySelector("[data-listing-image-preview]");
const listingDropzone = document.querySelector("[data-listing-dropzone]");

if (listingImageInput && listingImagePreview && listingDropzone) {
  let selectedImages = [];
  let objectUrls = [];
  const status = listingDropzone.querySelector("[data-dropzone-status]");

  const syncSelectedFiles = () => {
    const transfer = new DataTransfer();
    selectedImages.forEach((file) => transfer.items.add(file));
    listingImageInput.files = transfer.files;
  };

  const renderSelectedImages = () => {
    objectUrls.forEach((url) => URL.revokeObjectURL(url));
    objectUrls = [];
    listingImagePreview.querySelectorAll("[data-new-image-preview]").forEach((item) => item.remove());

    selectedImages.forEach((file, index) => {
      const figure = document.createElement("figure");
      figure.className = "listing-image-preview-item";
      figure.dataset.newImagePreview = "";

      const image = document.createElement("img");
      const imageUrl = URL.createObjectURL(file);
      objectUrls.push(imageUrl);
      image.src = imageUrl;
      image.alt = `Ảnh xem trước: ${file.name}`;

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "listing-image-remove";
      removeButton.dataset.removeSelectedImage = String(index);
      removeButton.setAttribute("aria-label", `Xóa ảnh ${file.name}`);
      removeButton.title = "Xóa ảnh";
      removeButton.textContent = "×";

      const caption = document.createElement("figcaption");
      caption.textContent = file.name;
      figure.append(image, removeButton, caption);
      listingImagePreview.append(figure);
    });

    if (status) {
      status.textContent = selectedImages.length
        ? `Đã chọn ${selectedImages.length} ảnh mới.`
        : "";
    }
  };

  const addSelectedImages = (files) => {
    const rejected = [];
    for (const file of files) {
      if (!/\.(jpe?g|png|webp|gif)$/i.test(file.name)) {
        rejected.push(file.name);
        continue;
      }
      const duplicate = selectedImages.some(
        (selected) =>
          selected.name === file.name &&
          selected.size === file.size &&
          selected.lastModified === file.lastModified
      );
      if (!duplicate) selectedImages.push(file);
    }

    syncSelectedFiles();
    renderSelectedImages();
    if (rejected.length && status) {
      status.textContent = "Một số tệp không được thêm. Chỉ hỗ trợ JPG, PNG, WEBP hoặc GIF.";
    }
  };

  listingImageInput.addEventListener("change", () => {
    addSelectedImages(Array.from(listingImageInput.files || []));
  });

  listingImagePreview.addEventListener("click", (event) => {
    const existingButton = event.target.closest("[data-toggle-image-removal]");
    if (existingButton) {
      const figure = existingButton.closest("[data-existing-image-preview]");
      const removeInput = figure?.querySelector('input[name="remove_image_ids"]');
      const removalLabel = figure?.querySelector("[data-image-removal-label]");
      if (!figure || !removeInput) return;

      const removePending = figure.dataset.removePending !== "true";
      figure.dataset.removePending = String(removePending);
      removeInput.disabled = !removePending;
      existingButton.textContent = removePending ? "↶" : "×";
      existingButton.setAttribute(
        "aria-label",
        removePending ? "Hoàn tác xóa ảnh" : "Đánh dấu xóa ảnh"
      );
      if (removalLabel) removalLabel.hidden = !removePending;
      return;
    }

    const selectedButton = event.target.closest("[data-remove-selected-image]");
    if (!selectedButton) return;
    selectedImages.splice(Number(selectedButton.dataset.removeSelectedImage), 1);
    syncSelectedFiles();
    renderSelectedImages();
  });

  listingDropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    listingDropzone.classList.add("is-dragover");
  });
  listingDropzone.addEventListener("dragleave", (event) => {
    if (!listingDropzone.contains(event.relatedTarget)) {
      listingDropzone.classList.remove("is-dragover");
    }
  });
  listingDropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    listingDropzone.classList.remove("is-dragover");
    addSelectedImages(Array.from(event.dataTransfer?.files || []));
  });
}

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
    const dialog = document.getElementById("image-viewer-dialog");
    const previewImage = document.getElementById("image-viewer-dialog-img");
    if (dialog && previewImage && !dialog.open) {
      previewImage.src = previewButton.dataset.imagePreview;
      previewImage.alt = previewButton.dataset.imageAlt || "";
      dialog.showModal();
      event.preventDefault();
    }
    return;
  }

  const imageDialog = document.getElementById("image-viewer-dialog");
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

const chatMessages = document.querySelector("[data-chat-messages]");
if (chatMessages) {
  let lastMessageId = Number.parseInt(chatMessages.dataset.lastMessageId || "0", 10);
  let requestInFlight = false;

  const refreshChat = async () => {
    if (requestInFlight || document.hidden) return;
    requestInFlight = true;
    try {
      const url = new URL(chatMessages.dataset.messagesUrl, window.location.origin);
      url.searchParams.set("after_id", String(lastMessageId));
      const response = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      if (!response.ok) {
        throw new Error(`Chat refresh failed with status ${response.status}`);
      }

      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        throw new Error("Chat refresh returned a non-JSON response");
      }

      const payload = await response.json();
      if (!Array.isArray(payload.messages) || payload.messages.length === 0) return;

      const wasNearBottom =
        chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 48;
      chatMessages.querySelector(".chat-empty")?.remove();

      for (const message of payload.messages) {
        if (!Number.isSafeInteger(message.id) || typeof message.content !== "string") continue;
        const bubble = document.createElement("div");
        bubble.className = `msg ${
          String(message.sender_id) === chatMessages.dataset.currentUserId ? "mine" : "theirs"
        }`;
        bubble.dataset.messageId = String(message.id);
        bubble.textContent = message.content;
        chatMessages.append(bubble);
        lastMessageId = Math.max(lastMessageId, message.id);
      }

      if (wasNearBottom) chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (error) {
      console.warn("Could not refresh chat messages.", error);
    } finally {
      requestInFlight = false;
    }
  };

  chatMessages.scrollTop = chatMessages.scrollHeight;
  refreshChat();
  window.setInterval(refreshChat, 2500);
  window.addEventListener("focus", refreshChat);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshChat();
  });
}

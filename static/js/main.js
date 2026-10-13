(function () {
  const form = document.getElementById("assess-form");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("image");
  const previewWrap = document.getElementById("preview-wrap");
  const preview = document.getElementById("preview");
  const placeholder = document.getElementById("drop-placeholder");
  const submitBtn = document.getElementById("submit-btn");

  if (!form || !fileInput) {
    return;
  }

  function showPreview(file) {
    if (!file || !file.type.startsWith("image/")) {
      return;
    }
    const url = URL.createObjectURL(file);
    preview.src = url;
    previewWrap.classList.add("is-visible");
    placeholder.hidden = true;
  }

  fileInput.addEventListener("change", function () {
    const file = fileInput.files && fileInput.files[0];
    showPreview(file);
  });

  ["dragenter", "dragover"].forEach(function (eventName) {
    dropzone.addEventListener(eventName, function (event) {
      event.preventDefault();
      dropzone.classList.add("is-dragover");
    });
  });

  ["dragleave", "drop"].forEach(function (eventName) {
    dropzone.addEventListener(eventName, function (event) {
      event.preventDefault();
      dropzone.classList.remove("is-dragover");
    });
  });

  dropzone.addEventListener("drop", function (event) {
    const files = event.dataTransfer && event.dataTransfer.files;
    if (!files || !files.length) {
      return;
    }
    fileInput.files = files;
    showPreview(files[0]);
  });

  form.addEventListener("submit", function (event) {
    if (!fileInput.files || !fileInput.files.length) {
      event.preventDefault();
      alert("Please add a skin photo first.");
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "Looking at your photo…";
  });
})();

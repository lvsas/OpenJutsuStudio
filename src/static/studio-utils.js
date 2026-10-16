window.OpenGenjutsuStudio = {
  showToast(region, message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    region.append(toast);
    window.setTimeout(() => toast.remove(), 4200);
  },
  replaceObjectUrl(current, file) {
    if (current) URL.revokeObjectURL(current);
    return URL.createObjectURL(file);
  },
  formatDuration(seconds) {
    if (!Number.isFinite(seconds)) return '';
    return `${Math.floor(seconds / 60)}:${Math.round(seconds % 60).toString().padStart(2, '0')}`;
  },
  bindFileDropTargets(onError) {
    document.querySelectorAll('[data-drop-kind]').forEach((picker) => {
      const input = document.getElementById(picker.htmlFor);
      if (!input) return;
      const setDragging = (active) => picker.classList.toggle('is-dragging', active);
      picker.addEventListener('dragenter', (event) => { event.preventDefault(); if (!input.disabled) setDragging(true); });
      picker.addEventListener('dragover', (event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; });
      picker.addEventListener('dragleave', (event) => { if (!picker.contains(event.relatedTarget)) setDragging(false); });
      picker.addEventListener('drop', (event) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files[0];
        if (!file || input.disabled) return;
        const extension = file.name.split('.').pop().toLowerCase();
        const fallbackExtensions = picker.dataset.dropKind === 'video'
          ? ['mp4', 'mov', 'mkv', 'webm']
          : ['png', 'jpg', 'jpeg', 'webp'];
        const allowed = input.accept.split(',').some((type) => file.type === type.trim()) || fallbackExtensions.includes(extension);
        if (!allowed) return onError(`Drop a supported ${picker.dataset.dropKind} file here.`);
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
  },
};

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
};

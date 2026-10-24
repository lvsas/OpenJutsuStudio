const studioResultLayouts=new WeakMap();
window.OpenGenjutsuStudio = {
  mountResultLayout(root=document) {
    if(!window.matchMedia||typeof MutationObserver!=='function')return ()=>{};
    const media=window.matchMedia('(max-width: 900px)'),cleanups=[];
    for(const grid of root.querySelectorAll('.studio-grid')) {
      if(studioResultLayouts.has(grid))continue;
      const panel=grid.querySelector('.recipe-panel'),stage=grid.querySelector('.studio-stage');
      const actions=stage?.querySelector('.result-actions'),title=panel?.querySelector('#recipe-title');
      if(!panel||!stage||!actions)continue;
      const originalTitle=title?.textContent;
      const sync=()=>{
        const saved=!actions.hidden;grid.classList.toggle('has-saved-result',saved);
        if(title)title.textContent=saved?'Create a new swap':originalTitle;
        const first=media.matches&&saved?stage:panel,second=first===stage?panel:stage;
        if(Array.from(grid.children).indexOf(first)>Array.from(grid.children).indexOf(second))grid.insertBefore(first,second);
      };
      const observer=new MutationObserver(sync);
      observer.observe(actions,{attributes:true,attributeFilter:['hidden']});
      media.addEventListener('change',sync);studioResultLayouts.set(grid,true);sync();
      cleanups.push(()=>{observer.disconnect();media.removeEventListener('change',sync);studioResultLayouts.delete(grid);});
    }
    if(!cleanups.length)return ()=>{};
    let disposed=false;
    const dispose=()=>{if(disposed)return;disposed=true;for(const cleanup of cleanups)cleanup();window.removeEventListener('pagehide',onLeave);};
    const onLeave=event=>{if(!event.persisted)dispose();};
    window.addEventListener('pagehide',onLeave);return dispose;
  },

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

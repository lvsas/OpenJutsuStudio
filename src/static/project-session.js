/* One navigation/session context over the existing project store. No compute. */
(() => {
  'use strict';
  const valid = id => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id);
  const remembered = 'opengenjutsu.workspace.project';
  const getStored = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const putStored = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  let project = null, assets = {characters: [], jobs: [], takes: []}, jobs = [];
  let projectId = null, blocked = null, epoch = 0, creating = null, bar = null;
  function context() {
    const params = new URLSearchParams(location.search);
    for (const key of ['project_id', 'job_id', 'character_id']) {
      const values = params.getAll(key);
      if (values.length > 1 || (values.length && !valid(values[0])))
        throw new Error('This workspace link is invalid. Open a workspace from navigation.');
    }
    return params;
  }
  try { projectId = context().get('project_id') || getStored(remembered); }
  catch (error) { blocked = error; }
  if (!valid(projectId)) projectId = null;
  async function api(path, options = {}) {
    const response = await fetch('/api/timeline' + path, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The project could not be opened.');
    return data;
  }
  function sync() {
    if (projectId) {
      const url = new URL(location.href);
      url.searchParams.set('project_id', projectId);
      history.replaceState(null, '', url.pathname + url.search + url.hash);
      putStored(remembered, projectId);
    }
    render();
    window.dispatchEvent(new CustomEvent('opengenjutsu:project-context'));
  }
  async function read(id, token) {
    const [next, contents] = await Promise.all([api('/projects/' + id), api('/projects/' + id + '/assets')]);
    if (token !== epoch) return;
    if (next.project_id !== id || contents.project_id !== id || !contents.assets || !Array.isArray(contents.jobs))
      throw new Error('The project response was invalid.');
    project = next; projectId = id; assets = contents.assets; jobs = contents.jobs;
    blocked = null; sync();
  }
  async function boot() {
    if (blocked) throw blocked;
    const token = ++epoch;
    try {
      if (projectId) await read(projectId, token);
      else {
        const data = await api('/draft');
        if (token !== epoch) return;
        if (data.project) {
          if (!valid(data.project.project_id)) throw new Error("The draft response was invalid.");
          await read(data.project.project_id, token);
        }
        else render(); // An empty visit does not create a draft or project.
      }
    } catch (error) { if (token === epoch) { blocked = error; render(); } throw error; }
  }
  const ready = boot();
  ready.catch(() => {}); // UI reports errors; there must be no unhandled rejection on an invalid URL.
  async function ensure() {
    await ready;
    if (blocked) throw blocked;
    if (projectId) return projectId;
    if (!creating) creating = (async () => {
      const token = epoch;
      const data = await api('/draft', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      if (token !== epoch) throw new Error('The project changed. Retry from the current workspace.');
      if (!valid(data.project?.project_id)) throw new Error('The draft response was invalid.');
      await read(data.project.project_id, token);
      return projectId;
    })().finally(() => { creating = null; });
    return creating;
  }
  async function associate(kind, id) {
    if (!valid(id) || !['character', 'job', 'take'].includes(kind)) throw new Error('Invalid project resource.');
    const owner = await ensure(), token = epoch;
    const current = await api('/projects/' + owner + '/assets');
    const result = await api('/projects/' + owner + '/assets', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({revision: current.revision, kind, asset_id: id})});
    if (token !== epoch || projectId !== owner) throw new Error('The project changed. The original association was preserved.');
    assets = result.assets; jobs = result.jobs; render();
    return result;
  }
  function recovery(engine) {
    const rows = jobs.filter(job => job.engine === engine);
    return rows.find(job => ['queued', 'running'].includes(job.status)) || rows.find(job => job.status === 'done') || null;
  }
  function acceptJob(id, owner, engine) {
    if (!valid(id) || owner !== projectId) throw new Error('The result belongs to another project. Reopen its original project.');
    const group = engine === 'flux3-klein-character' ? 'characters' : 'jobs';
    if (!assets[group].includes(id)) assets[group].push(id);
    for (const input of document.querySelectorAll('input[type=file]')) input.__submittedFiles = [...input.files];
  }
  function render() {
    if (!bar) return;
    const label = bar.querySelector('[data-project-label]');
    label.textContent = blocked ? blocked.message : project?.title || 'Draft · explore freely';
    bar.querySelector('[data-project-save]').hidden = Boolean(blocked);
    bar.querySelector('[data-project-save] summary').textContent = project && !project.is_draft ? 'Rename project' : 'Save project';
    bar.querySelector('[data-project-state]').textContent = blocked ? 'Project unavailable' : project?.is_draft || !project ? 'Draft' : 'Project';
    const selected = [...bar.querySelector('.project-actions select').options].find(option => option.value === projectId);
    if (selected && project) selected.textContent = project.title;
  }
  async function mount() {
    if (!document.querySelector('.site-header') || !document.createElement) return;
    bar = document.createElement('section'); bar.className = 'project-bar';
    bar.setAttribute('aria-label', 'Current creation');
    bar.innerHTML = '<span class="project-context-title"><small data-project-state>Draft</small><strong data-project-label>Draft · explore freely</strong></span>' +
      '<details class="project-actions"><summary>Open project</summary><div class="project-menu"><label>Saved projects<select aria-label="Open project"><option value="">Choose a project…</option></select></label><button type="button" data-project-draft>Back to draft</button></div></details>' +
      '<details data-project-library><summary>Creations</summary><div class="project-library"><label>Show<select data-creation-scope aria-label="Creation library scope"><option value="project">This project</option><option value="common">Common library</option></select></label><p class="microcopy">Characters and Swap results. Preview or reuse explicitly; originals stay unchanged. Native takes are in Sequence’s take library.</p><ul data-creation-list></ul></div></details>' +
      '<details data-project-save><summary>Save project</summary><form class="project-name-form"><label>Name this creation<input name="title" maxlength="160" required placeholder="My next creation"></label><button type="submit">Save</button></form></details><p class="project-error" role="status" hidden></p>';
    document.querySelector('.site-header').after(bar); render();
    const errorHost = bar.querySelector('.project-error');
    const fail = error => { errorHost.hidden = false; errorHost.textContent = error.message; };
    const go = async id => {
      try { await window.OpenGenjutsuProject.beforeNavigate?.(); } catch(error) { fail(error); return; }
      const url = new URL(location.href);
      for (const key of ['job_id', 'character_id']) url.searchParams.delete(key);
      if (id) url.searchParams.set('project_id', id); else url.searchParams.delete('project_id');
      location.assign(url.pathname + url.search);
    };
    const nameDetails = bar.querySelector('[data-project-save]');
    nameDetails.addEventListener('toggle', () => {
      if (nameDetails.open) nameDetails.querySelector('input').value = project && !project.is_draft ? project.title : '';
    });
    const creationDetails = bar.querySelector('[data-project-library]');
    const creationScope = bar.querySelector('[data-creation-scope]');
    const creationList = bar.querySelector('[data-creation-list]');
    let libraryEpoch = 0, libraryLimit = 24;
    async function showCreations() {
      const token = ++libraryEpoch, owner = projectId;
      creationList.replaceChildren();
      const state = document.createElement('li'); state.textContent = 'Loading creations…'; creationList.append(state);
      try {
        await ready;
        const common = creationScope.value === 'common';
        let records;
        if (common) {
          records = (await api('/library')).jobs;
        } else records = projectId ? (await api('/projects/'+projectId+'/assets')).jobs : [];
        if (token !== libraryEpoch || owner !== projectId) return;
        creationList.replaceChildren();
        const visible = records.filter(row => valid(row.job_id) && ['flux3-klein-character','ltx25-ripple','minimax-h3'].includes(row.engine)).sort((a,b)=>b.created-a.created);
        for (const row of visible.slice(0,libraryLimit)) {
          const item = document.createElement('li'), description = document.createElement('span');
          const type = {'flux3-klein-character':'Character','ltx25-ripple':'LTX swap','minimax-h3':'H3 swap'}[row.engine];
          description.textContent = type+' · '+row.status+' · '+new Date(row.created*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
          const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-secondary'; button.textContent = common ? 'Use in this project' : 'Open';
          if (row.status === 'done') {
            const media = document.createElement(row.engine === 'flux3-klein-character' ? 'img' : 'video');
            media.className = 'creation-thumb';
            if (row.engine === 'flux3-klein-character') { media.alt = ''; media.loading = 'lazy'; media.src = '/api/characters/jobs/'+row.job_id+'/image'; }
            else { media.muted = true; media.controls = true; media.playsInline = true; media.preload = 'none'; media.src = '/api/jobs/'+row.job_id+'/result'; }
            media.addEventListener('play', () => { for (const other of document.querySelectorAll('video')) if (other !== media) other.pause(); });
            media.addEventListener('error', () => { media.remove(); });
            item.append(media);
          }
          button.addEventListener('click', async () => {
            button.disabled = true;
            try {
              await window.OpenGenjutsuProject.beforeNavigate?.();
              if (common) await associate(row.engine === 'flux3-klein-character' ? 'character' : 'job', row.job_id);
              const path = {'flux3-klein-character':'/characters','ltx25-ripple':'/','minimax-h3':'/h3'}[row.engine];
              location.assign(path+'?project_id='+projectId+'&job_id='+row.job_id);
            } catch (error) { fail(error); button.disabled = false; }
          });
          item.append(description,button); creationList.append(item);
        }
        if (visible.length > libraryLimit) {
          const more = document.createElement('button'); more.type = 'button'; more.className = 'btn btn-ghost'; more.textContent = 'Show more creations';
          more.addEventListener('click', () => { libraryLimit += 24; showCreations(); }); creationList.append(more);
        }
        if (!creationList.children.length) {
          const empty = document.createElement('li'); empty.textContent = common ? 'No completed creations yet.' : 'No creations here yet. Explore, or reuse one from the common library.';
          creationList.append(empty);
        }
      } catch (error) { if (token === libraryEpoch) { creationList.replaceChildren(); fail(error); } }
    }
    creationDetails.addEventListener('toggle', () => { if (creationDetails.open) showCreations(); });
    creationScope.addEventListener('change', () => { libraryLimit = 24; showCreations(); });
    bar.querySelector('.project-actions select').addEventListener('change', event => {
      if (!valid(event.target.value)) return;
      go(event.target.value);
    });
    bar.querySelector('[data-project-draft]').addEventListener('click', async () => {
      try { await window.OpenGenjutsuProject.openDraft(); }
      catch (error) { fail(error); }
    });
    bar.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault();
      try {
        await window.OpenGenjutsuProject.beforeNavigate?.();
        const owner = await ensure();
        const current = await api('/projects/' + owner);
        const named = await api('/projects/' + owner + '/name', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({revision: current.revision, title: bar.querySelector('input').value.trim()})});
        if (owner !== projectId) throw new Error('The project changed. Reopen the saved creation.');
        project = named; await window.OpenGenjutsuProject.onRenamed?.(named); render(); bar.querySelectorAll('details').forEach(node => { node.open = false; });
      } catch (error) { fail(error); }
    });
    try {
      await ready.catch(fail);
      const data = await api('/projects');
      const select = bar.querySelector('.project-actions select');
      for (const item of data.projects) {
        const option = document.createElement('option'); option.value = item.project_id; option.textContent = item.title;
        select.append(option);
      }
      select.value = projectId || '';
    } catch (error) { fail(error); }
  }
  window.OpenGenjutsuProject = {
    ready, ensure, associate, recovery, acceptJob,
    async openDraft() {
      await ready.catch(() => {}); // This explicit action can recover an unavailable project.
      await window.OpenGenjutsuProject.beforeNavigate?.();
      const data = await api('/draft', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if (!valid(data.project?.project_id)) throw new Error('The draft response was invalid.');
      location.assign(location.pathname+'?project_id='+data.project.project_id);
    },
    id: () => projectId,
    storageKey: base => `${base}.project.${projectId || (blocked ? 'invalid' : 'draft')}`,
    containsJob: id => assets.jobs.includes(id) || assets.characters.includes(id),
    jobs: engine => jobs.filter(job => job.engine === engine),
    members: () => structuredClone(assets),
  };
  window.addEventListener('opengenjutsu:project-context', () => {
    try {
      const id = context().get('project_id');
      if (valid(id) && id !== projectId) {
        projectId = id; assets = {characters: [], jobs: [], takes: []}; jobs = [];
        read(id, ++epoch).catch(error => { blocked = error; render(); });
      }
    } catch (error) { blocked = error; render(); }
  });
  // Reuse is explicit: attach the chosen Character before navigating to its consumer.
  document.addEventListener('click', async event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !['/', '/h3', '/timeline'].includes(url.pathname) || !url.searchParams.has('character_id')) return;
    event.preventDefault();
    try {
      const id = url.searchParams.get('character_id');
      await associate('character', id);
      url.searchParams.set('project_id', projectId);
      location.assign(url.pathname + url.search);
    } catch (error) {
      const message = bar?.querySelector(".project-error");
      if (message) { message.hidden = false; message.textContent = error.message; }
    }
  });
  // A studio upload is not a server asset until submission; never silently drop it on navigation.
  window.addEventListener('beforeunload', event => {
    if ([...document.querySelectorAll('input[type=file]')].some(input => [...(input.files || [])].some(file =>
      file !== input.__recoverableReference && !input.__submittedFiles?.includes(file)))) {
      event.preventDefault(); event.returnValue = '';
    }
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();

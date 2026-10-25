/* Shared navigation is read-only; compute requests exist only on the Settings page. */
(() => {
  'use strict';
  function navigation() {
    const params = new URLSearchParams(location.search);
    const selected = window.OpenGenjutsuProject?.id?.();
    const id = selected || (params.getAll('project_id').length === 1 ? params.get('project_id') : null);
    if (!/^[a-f0-9]{32}$/.test(id || '')) return;
    for (const link of document.querySelectorAll('.site-header a[href]')) {
      const url = new URL(link.href, location.href);
      if (url.origin !== location.origin || !['/', '/h3', '/characters', '/timeline', '/settings'].includes(url.pathname)) continue;
      url.searchParams.set('project_id', id);
      link.href = url.pathname + url.search + url.hash;
    }
  }
  window.addEventListener('opengenjutsu:project-context', navigation);
  function mount() {
    navigation();
    const get = id => document.getElementById(id), form = get('settings-form');
    if (!form) return;
    const url = get('compute-url'), key = get('compute-key'), clear = get('clear-key');
    const test = get('test-connection'), save = get('save-settings');
    const status = get('settings-status'), testStatus = get('test-status'), results = get('test-results');
    const modelFields = get('model-fields'), modelsStatus = get('models-status'), inventoryStatus = get('model-inventory-status');
    const resetModels = get('reset-models');
    let revision = null, savedURL = '', configured = false, busy = false, epoch = 0, tested = false;
    let modelRoles = [], modelsSupported = false, modelsLoaded = false, modelURL = url.value.trim();
    const modelControls = new Map();
    function buttons() { test.disabled = save.disabled = busy || revision === null; }
    function bindings() {
      // Do not trim, case-fold or normalize separators: inventory names are literal.
      return Object.fromEntries(modelRoles.filter(role => modelControls.get(role.key).field.value !== role.default)
        .map(role => [role.key, modelControls.get(role.key).field.value]));
    }
    function inventory(data, secret = '') {
      const verified = data?.status === 'verified';
      for (const role of modelRoles) {
        const list = modelControls.get(role.key).list;
        list.replaceChildren();
        const choices = verified && Array.isArray(data.choices?.[role.key]) ? data.choices[role.key] : [];
        for (const filename of new Set(choices)) {
          // A diagnostic reply must never echo the submitted credential, even in a suggestion.
          if (typeof filename !== 'string' || !filename || (secret && filename.includes(secret))) continue;
          const option = document.createElement('option'); option.value = filename; option.textContent = filename; list.append(option);
        }
      }
      inventoryStatus.textContent = verified
        ? 'Inventory verified by the last explicit Test connection. Suggestions are filenames, not a compatibility guarantee.'
        : 'Inventory unknown. Test connection may provide suggestions; you can enter a compatible filename manually.';
    }
    function resetModelValues() {
      for (const role of modelRoles) modelControls.get(role.key).field.value = role.default;
    }
    function models(data, replace) {
      // Optional public metadata: older servers must remain usable without this extension.
      // Stale saves update the committed revision, never this newer draft or its controls.
      if (modelsLoaded && !replace) return;
      const previous = modelsLoaded ? bindings() : {};
      if (Array.isArray(data.model_roles)) {
        const valid = data.model_roles.every(role => role && ['key', 'label', 'engine', 'class_type', 'input', 'default']
          .every(name => typeof role[name] === 'string' && role[name].length > 0));
        modelsSupported = valid && new Set(data.model_roles.map(role => role.key)).size === data.model_roles.length;
        modelRoles = modelsSupported ? data.model_roles : [];
      }
      const overrides = replace && data.model_bindings && typeof data.model_bindings === 'object' && !Array.isArray(data.model_bindings)
        ? data.model_bindings : previous;
      modelFields.replaceChildren(); modelControls.clear();
      const group = role => ['ltx', 'h3'].includes(role.engine) ? role.engine : 'shared';
      for (const [engine, label] of [['ltx', 'LTX'], ['h3', 'H3'], ['shared', 'Shared']]) {
        const roles = modelRoles.filter(role => group(role) === engine);
        if (!roles.length) continue;
        const fieldset = document.createElement('fieldset'), legend = document.createElement('legend');
        fieldset.className = 'model-group'; legend.textContent = label; fieldset.append(legend);
        for (const role of roles) {
          const index = modelControls.size;
          const row = document.createElement('div'), name = document.createElement('label'), field = document.createElement('input');
          const hint = document.createElement('p'), list = document.createElement('datalist'), reset = document.createElement('button');
          row.className = 'model-role'; field.id = 'model-filename-' + index; hint.id = 'model-help-' + index; list.id = 'model-choices-' + index;
          name.className = 'field-label'; name.htmlFor = field.id; name.textContent = role.label;
          field.type = 'text'; field.className = 'text-input'; field.autocomplete = 'off'; field.spellcheck = false;
          field.setAttribute('autocapitalize', 'none'); field.setAttribute('list', list.id); field.setAttribute('data-model-role', role.key);
          field.setAttribute('aria-describedby', hint.id + ' models-help');
          field.value = Object.hasOwn(overrides, role.key) && typeof overrides[role.key] === 'string' ? overrides[role.key] : role.default;
          hint.className = 'settings-help'; hint.textContent = role.class_type + ' · ' + role.input + ' · Default: ' + role.default;
          reset.type = 'button'; reset.className = 'model-reset'; reset.textContent = 'Use default';
          reset.setAttribute('data-reset-role', role.key); reset.setAttribute('aria-label', 'Use default for ' + role.label);
          field.addEventListener('input', edit); field.addEventListener('change', edit);
          reset.addEventListener('click', () => { field.value = role.default; edit(); });
          row.append(name, field, hint, reset, list); fieldset.append(row);
          modelControls.set(role.key, {field, list});
        }
        modelFields.append(fieldset);
      }
      modelsLoaded = true; modelURL = url.value.trim(); resetModels.disabled = !modelsSupported || !modelRoles.length;
      modelsStatus.textContent = modelsSupported
        ? 'Fields show effective filenames: saved overrides or declared defaults. Changes are drafts until Save settings.'
        : 'Model filename configuration is not available from this server. Existing connection settings still work.';
      inventory();
    }
    function keyStatus() {
      get('key-status').textContent = configured
        ? (url.value.trim() === savedURL ? 'A key is configured. Leave blank to keep it, or enter a replacement.'
          : 'The saved key is not reused for a different URL. Enter a key if the new target requires one.')
        : 'No key is configured. Enter one only if your target requires authentication.';
    }
    function obsolete() {
      results.hidden = true;
      results.replaceChildren();
      testStatus.textContent = tested ? 'Test result obsolete. Test again for these settings.' : 'Not tested. Testing is explicit and does not save.';
    }
    function edit(event) {
      epoch++;
      if (url.value.trim() !== modelURL) {
        modelURL = url.value.trim(); resetModelValues(); inventory();
        if (modelsSupported) modelsStatus.textContent = 'Target URL changed: model overrides were cleared to avoid reusing filenames from a different target. Enter new names explicitly or keep the defaults.';
      } else if (event?.target === key || event?.target === clear) inventory();
      keyStatus(); obsolete();
      status.textContent = 'Unsaved changes. Save settings to activate them.';
    }
    resetModels.addEventListener('click', () => {
      if (!modelsSupported) return;
      resetModelValues(); edit();
      modelsStatus.textContent = 'All model overrides reset in this draft. Save settings to use declared defaults.';
    });
    for (const field of [url, key, clear]) {
      field.addEventListener('input', edit);
      field.addEventListener('change', edit);
    }
    function payload() {
      const data = {base_url: url.value.trim()};
      if (clear.checked) data.clear_api_key = true;
      else if (key.value) data.api_key = key.value;
      if (modelsSupported) data.model_bindings = bindings();
      return data;
    }
    async function request(path, method = 'GET', data) {
      const response = await fetch('/api/settings/compute' + path, {
        method, credentials: 'same-origin', cache: 'no-store',
        ...(data ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)} : {}),
      });
      if (!response.ok) {
        const messages = {
          409: 'Settings conflict or processing in progress. Your edits are kept. Wait for processing to finish; if settings changed elsewhere, reload before saving. Nothing was retried.',
          422: 'Invalid settings. Check the API v2 URL, key and model filenames, then try again. Your edits are kept.',
          403: 'This request was blocked. Open Settings from the same studio origin. Your edits are kept.',
        };
        const failure = new Error(messages[response.status] || 'The settings request failed. Your edits are kept. Try again when the service is available.');
        failure.settingsMessage = true;
        throw failure;
      }
      return response.json();
    }
    function accept(data, replace) {
      if (!Number.isInteger(data.revision) || typeof data.base_url !== 'string' || typeof data.api_key_configured !== 'boolean')
        throw new Error('The settings response was invalid. Reload before saving.');
      revision = data.revision; savedURL = data.base_url; configured = data.api_key_configured;
      if (replace) url.value = savedURL;
      models(data, replace);
      const source = {saved: 'Saved settings', environment: 'Environment configuration', default: 'Default configuration'}[data.source] || 'Configuration';
      get('settings-source').textContent = source + ' · ' + (typeof data.mode === 'string' ? data.mode : 'unknown mode');
      keyStatus();
    }
    function diagnostics(data, secret) {
      const text = value => {
        const valueText = typeof value === 'string' ? value : '';
        return secret ? valueText.split(secret).join('[redacted]') : valueText;
      };
      const row = (host, message) => {
        const item = document.createElement('li'); item.textContent = text(message); host.append(item);
      };
      const list = (host, values, prefix = '') => {
        if (Array.isArray(values)) for (const value of values) if (typeof value === 'string') row(host, prefix + value);
      };
      results.replaceChildren();
      const global = document.createElement('ul');
      list(global, data.issues, 'Issue: '); list(global, data.warnings, 'Warning: '); results.append(global);
      for (const name of ['ltx', 'h3']) {
        const engine = data.engines?.[name] || {};
        const state = ['ready', 'missing', 'unknown', 'unreachable'].includes(engine.status) ? engine.status : 'unknown';
        const section = document.createElement('section'), title = document.createElement('h3'), details = document.createElement('ul');
        title.textContent = name.toUpperCase() + ' · ' + state;
        list(details, engine.missing_nodes, 'Missing node: '); list(details, engine.missing_models, 'Missing model: ');
        list(details, engine.issues, 'Issue: '); list(details, engine.warnings, 'Warning: ');
        section.append(title, details); results.append(section);
      }
      const ready = data.connected === true && data.ready === true && ['ltx', 'h3'].every(name => data.engines?.[name]?.status === 'ready');
      testStatus.textContent = ready ? 'Ready · both engines passed this explicit check.'
        : data.connected === true ? 'Connected · setup incomplete or readiness unknown. Review the diagnostics.'
          : 'Not connected. Review the diagnostics and your API v2 setup.';
      results.hidden = false;
    }
    async function run(kind) {
      if (busy || revision === null) return;
      const token = epoch, data = payload();
      busy = true; buttons(); form.setAttribute('aria-busy', 'true');
      status.textContent = kind === 'test' ? 'Testing connection… Nothing is being saved or generated.' : 'Saving settings…';
      if (kind === 'test') { tested = true; obsolete(); inventory(); }
      try {
        if (kind === 'test') {
          const reply = await request('/test', 'POST', data);
          if (token !== epoch) { obsolete(); status.textContent = 'Test finished for older values. Your newer edits are kept.'; return; }
          diagnostics(reply, data.api_key || '');
          inventory(reply.model_inventory, data.api_key || '');
          status.textContent = 'Connection check finished. Settings were not saved.';
        } else {
          const reply = await request('', 'PUT', {revision, ...data});
          // Capture staleness before rebuilding controls: removing a focused
          // model input can synchronously emit change during accept().
          const current = token === epoch;
          accept(reply, current);
          if (!current) { status.textContent = 'Earlier settings saved. Your newer edits are not saved.'; return; }
          key.value = ''; clear.checked = false; epoch++; obsolete();
          status.textContent = 'Settings saved and activated. No restart needed. Saving does not test the target.';
        }
      } catch (error) {
        // Only locally authored errors may reach the UI; fetch/JSON failures can contain secrets.
        status.textContent = error.settingsMessage === true ? error.message : 'The settings service could not be reached or returned an invalid response. Your edits are kept.';
        if (kind === 'test') { results.hidden = true; testStatus.textContent = token === epoch ? 'Test failed. No readiness result is available.' : 'Test result obsolete. Test again for these settings.'; }
      } finally { busy = false; buttons(); form.setAttribute('aria-busy', 'false'); }
    }
    test.addEventListener('click', () => run('test'));
    form.addEventListener('submit', event => { event.preventDefault(); return run('save'); });
    buttons();
    const token = epoch;
    request('').then(data => {
      accept(data, token === epoch);
      if (token === epoch) status.textContent = 'Settings loaded. No connection test has run.';
    }).catch(() => { status.textContent = 'Settings could not be loaded. Reload this page before testing or saving.'; }).finally(buttons);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();

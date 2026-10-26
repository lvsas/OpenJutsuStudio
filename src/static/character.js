/* Viral Character Maker — instant local hooks, one independent job per request.
 *
 * The direction describes only the CHARACTER. Medium, framing, views and environment belong to the
 * output mode, which the server owns: mixing them produced a passport-photo brief with no hook.
 */
(() => {
  "use strict";

  // Believable weird adults: a distinctive physical hook, simple clothes, contrasting personality.
  // Complete tuples stay coherent and prop-free; rendering and framing belong to the server.
  const LOOKS = [
    {
      being: "man", role: "fastidious train announcer",
      build: "a broad-shouldered but realistically proportioned adult body",
      hair: "a jaw-length dense copper bob sculpted into a broad trapezoid, a completely flat top, straight heavy fringe and thick sides covering the ears and flaring outward at the jaw",
      face: "a long face with a bushy dark walrus moustache drooping over the upper lip",
      outfit: "a pale mint short-sleeved shirt buttoned to the collar, very high-waisted chocolate-brown trousers with sharp front creases and a slightly short hem, white socks and glossy black loafers",
      attitude: "standing with shy tucked-in elbows, raised eyebrows and a bashful closed-mouth smile",
    },
    {
      being: "woman", role: "unyielding boules referee",
      build: "a short sturdy adult build with powerful forearms and natural head proportions",
      hair: "natural grey hair with visible individual matte strands, cut into a low geometric crest with closely shaved temples",
      face: "an aquiline nose, straight emphatic eyebrows and tightly pursed lips",
      outfit: "a plum jumpsuit with an unusually broad collar and billowing legs gathered at the ankles, with simple black shoes",
      attitude: "feet firmly planted, chin forward and a defiant smirk",
    },
    {
      being: "woman", role: "ceremonious karaoke organiser",
      build: "a tall rounded adult build with narrow shoulders and ordinary limb lengths",
      hair: "two smooth horizontal black rolls above the ears and a short neat nape",
      face: "full cheeks, slightly spaced front teeth and an emphatic knowing smile",
      outfit: "a burnt-orange suit with a short square jacket, a long pleated skirt and low cream shoes",
      attitude: "chin raised, elbows poised and a triumphant closed-mouth smile",
    },
    {
      being: "woman", role: "dreamy lift technician",
      build: "a slender long-limbed adult build with long arms and a normal-sized head",
      hair: "pale blonde hair cut short at the front with a long wavy cascade down the back",
      face: "an angular face with heavy upper eyelids and a narrow softly crooked nose",
      outfit: "loose cobalt overalls over a lemon shirt with exaggerated balloon sleeves, and plain brown boots",
      attitude: "relaxed shoulders, a tilted head and a distracted gentle smile",
    },
    {
      being: "man", role: "reserved dance teacher",
      build: "a compact adult build with a round belly and strong natural-length legs",
      hair: "brown curls combed into three precise sculptural waves across the forehead",
      face: "a clean-shaven face with a short nose and deep smiling creases",
      outfit: "a rose satin blouse with bottle-green flared trousers and plain black dance shoes",
      attitude: "open hands, an earnest upright stance and a slightly worried expression",
    },
    {
      being: "non-binary person", role: "enthusiastic apartment-block coordinator",
      build: "a tall athletic adult build with broad shoulders and ordinary proportions",
      hair: "white hair shaped into an asymmetric sculptural fan sweeping to one side",
      face: "a wide angular jaw, a cleft chin and expressive arched eyebrows",
      outfit: "a very short lilac quilted jacket, red carrot-cut trousers and simple white shoes",
      attitude: "leaning slightly forward with a conspiratorial smile and an inviting open posture",
    },
  ];

  const AXES = [
    ["being", "Presentation", ["a woman", "a man", "an androgynous person", "a non-binary person"]],
    ["build", "Silhouette", LOOKS.map((look) => look.build)],
    ["skin_tone", "Skin tone", ["fair skin", "olive skin", "warm brown skin", "deep brown skin", "very dark brown skin"]],
    ["hair", "Signature hair", LOOKS.map((look) => look.hair)],
    ["face", "Face and expression", LOOKS.map((look) => look.face)],
    ["outfit", "Clothes", LOOKS.map((look) => look.outfit)],
    ["role", "Personality", LOOKS.map((look) => `a ${look.role}`)],
    ["era", "Era", ["present-day everyday clothing", "simple 1970s casual clothing", "simple 1990s casual clothing"]],
    ["attitude", "Posture and attitude", LOOKS.map((look) => look.attitude)],
  ];

  const REFINEMENTS = [
    ["identity", "Silhouette", ["build"], "From the idea"],
    ["appearance", "Signature hair and face", ["hair", "face"], "From the idea"],
    ["story", "Expression and personality", ["role", "attitude"], "From the idea"],
    ["style", "Clothes and style", ["outfit", "era"], "From the idea"],
  ];

  const MODE_HINTS = {
    portrait: "One shareable studio photograph.",
    turnaround: "Four photographs of the same person — front, three-quarter, profile, back.",
  };
  const LEGACY_KEY = "opengenjutsu.characters.jobs";
  const STORAGE_KEY = "opengenjutsu.characters.attempts";
  const ACTIVE_KEY = "opengenjutsu.characters.active";
  const MAX_STORED = 24;
  const validId = (id) => typeof id === "string" && /^[0-9a-f]{32}$/.test(id);
  const POLL_MS = 1500;

  const $ = (selector) => document.querySelector(selector);
  const form = $("#character-form");
  const directionField = $("#direction");
  const proposalSummary = $("#proposal-summary");
  const refineListHost = $("#refine-list");
  const refineOptionsHost = $("#refine-options");
  const clearAxesButton = $("#clear-axes");

  const errorHost = $("#form-error");
  const countHost = $("#job-count");

  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const randomSeed = () => {
    const buffer = new Uint32Array(2);
    crypto.getRandomValues(buffer);
    return ((buffer[0] * 4294967296) + buffer[1]) % 9007199254740991;
  };

  /* ---- progressive refinement: proposal first, named choices only when asked ---- */

  const axisValues = new Map();
  const axisByKey = new Map(AXES.map((axis) => [axis[0], axis]));
  const pickerHost = $("#axis-picker");
  const optionsHost = $("#axis-options");
  const pickerChips = new Map();
  let openAxis = null;
  let openRefinement = null;
  let directionOrigin = "generated";

  function selectedValues(axisKeys) {
    return axisKeys.map((key) => axisValues.get(key)).filter(Boolean);
  }

  function syncProposalSummary() {
    proposalSummary.textContent = axisValues.size
      ? `Overrides: ${[...axisValues.values()].join(" · ")}`
      : "Refinements are optional. Your idea leads.";
  }

  function renderChoices(axisKeys, host) {
    for (const key of axisKeys) {
      const [, label, choices] = axisByKey.get(key);
      const group = document.createElement("section");
      group.className = "refine-choice-group";
      const heading = document.createElement("p");
      heading.className = "field-label";
      heading.textContent = label;
      const row = document.createElement("div");
      row.className = "axis-chips";
      for (const choice of choices) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = choice;
        chip.setAttribute("aria-pressed", String(axisValues.get(key) === choice));
        chip.addEventListener("click", () => setAxis(key, axisValues.get(key) === choice ? "" : choice));
        row.append(chip);
      }
      const input = document.createElement("input");
      input.type = "text";
      input.className = "axis-input";
      input.maxLength = 300;
      input.placeholder = `or make the ${label.toLowerCase()} specific`;
      input.setAttribute("aria-label", `${label}: custom value`);
      const current = axisValues.get(key) || "";
      input.value = choices.includes(current) ? "" : current;
      input.addEventListener("change", () => setAxis(key, input.value.trim()));
      row.append(input);
      group.append(heading, row);
      host.append(group);
    }
  }

  function renderRefinements() {
    refineListHost.replaceChildren();
    for (const [key, label, axisKeys, fallback] of REFINEMENTS) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "refine-button";
      button.dataset.refinement = key;
      button.setAttribute("aria-expanded", String(openRefinement === key));
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = label;
      const summary = document.createElement("small");
      const values = selectedValues(axisKeys);
      summary.textContent = values.length ? values.join(" · ") : fallback;
      copy.append(title, summary);
      const arrow = document.createElement("span");
      arrow.className = "refine-arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "→";
      button.append(copy, arrow);
      button.addEventListener("click", () => {
        openRefinement = openRefinement === key ? null : key;
        renderRefinements();
        renderRefineOptions();
      });
      refineListHost.append(button);
    }
    clearAxesButton.hidden = axisValues.size === 0;
    syncProposalSummary();
  }

  function renderRefineOptions() {
    refineOptionsHost.replaceChildren();
    if (!openRefinement) return;
    const [, label, axisKeys] = REFINEMENTS.find(([key]) => key === openRefinement);
    const hint = document.createElement("p");
    hint.className = "microcopy";
    hint.textContent = `Refine ${label.toLowerCase()} — choose only what matters.`;
    refineOptionsHost.append(hint);
    renderChoices(axisKeys, refineOptionsHost);
  }

  for (const [key, label] of AXES) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "axis-name";
    chip.textContent = label;
    chip.setAttribute("aria-pressed", "false");
    chip.addEventListener("click", () => {
      openAxis = openAxis === key ? null : key;
      renderOptions();
    });
    pickerHost.append(chip);
    pickerChips.set(key, chip);
  }

  function renderOptions() {
    optionsHost.replaceChildren();
    for (const [key] of AXES) {
      pickerChips.get(key).setAttribute("aria-pressed", String(Boolean(axisValues.get(key))));
      pickerChips.get(key).dataset.open = String(openAxis === key);
    }
    if (!openAxis) return;
    const axisHost = document.createElement("div");
    axisHost.className = "advanced-axis-options";
    renderChoices([openAxis], axisHost);
    optionsHost.append(axisHost);
  }

  function setAxis(key, value) {
    if (value) axisValues.set(key, value);
    else axisValues.delete(key);
    renderRefinements();
    renderRefineOptions();
    renderOptions();
  }

  function clearAxes() {
    axisValues.clear();
    openAxis = null;
    openRefinement = null;
    renderRefinements();
    renderRefineOptions();
    renderOptions();
  }

  function selections() {
    const chosen = {};
    for (const [key] of AXES) {
      const value = axisValues.get(key);
      if (typeof value === "string" && value) chosen[key] = value;
    }
    return chosen;
  }

  /* ---- one legible hook per shuffle: five human signals, no object inventory ---- */

  function buildDirection() {
    const look = pick(LOOKS);
    const article = /^[aeiou]/i.test(look.role) ? "an" : "a";
    return `An original adult ${look.being}, ${article} ${look.role}: ${look.build}, ${look.hair}, ${look.face}, wearing ${look.outfit}, ${look.attitude}.`;
  }

  function shuffle() {
    directionOrigin = "generated";
    directionField.value = buildDirection();
    clearAxes();
    syncProposalSummary();
  }

  /* ---- one active canvas, ephemeral attempts, explicit server-owned library ---- */

  function storageNotice() {
    $("#storage-notice").hidden = false;
    $("#storage-notice").textContent = "Browser storage is unavailable. Recent attempts may not survive a refresh; saved characters stay in the server library.";
  }
  function readStorage(key) {
    key = globalThis.OpenGenjutsuProject?.storageKey(key) || key;
    try { return localStorage.getItem(key); } catch { storageNotice(); return null; }
  }
  function writeStorage(key, value) {
    key = globalThis.OpenGenjutsuProject?.storageKey(key) || key;
    try { localStorage.setItem(key, value); return true; } catch { storageNotice(); return false; }
  }
  function stored() {
    const current = readStorage(STORAGE_KEY);
    const legacy = current === null ? readStorage(LEGACY_KEY) : null;
    let ids = [];
    try {
      const parsed = JSON.parse(current || legacy || "[]");
      if (Array.isArray(parsed)) ids = [...new Set(parsed.filter(validId))].slice(0, MAX_STORED);
    } catch { /* An invalid browser cache is not library evidence. */ }
    if (legacy !== null && writeStorage(STORAGE_KEY, JSON.stringify(ids))) {
      try { localStorage.removeItem(LEGACY_KEY); } catch { storageNotice(); }
    }
    return ids;
  }
  const jobs = new Map();
  const watchers = new Map();
  let recent = stored();
  let cachedActive = readStorage(ACTIVE_KEY);
  let restoringSelection = validId(cachedActive);
  let activeId = null;
  let selectionEpoch = 0;
  let pendingExplicitEpoch = null;
  let libraryEpoch = 0;
  let library = new Map();
  let libraryLoaded = false;
  let libraryBusy = false;
  let renderedId = null;
  let sharedFile = null;

  function notice(text) { $("#workspace-notice").textContent = text; }
  function showError(message) { errorHost.textContent = message; errorHost.hidden = !message; }
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function action(label, callback) {
    const button = node("button", label, "btn btn-ghost btn-small");
    button.type = "button";
    button.addEventListener("click", callback);
    return button;
  }
  function persistAttempts() { writeStorage(STORAGE_KEY, JSON.stringify(recent)); }
  function remember(id) {
    recent = [id, ...recent.filter(existing => existing !== id)].slice(0, MAX_STORED);
    for (const oldId of watchers.keys()) if (!recent.includes(oldId)) watchers.delete(oldId);
    persistAttempts();
    renderShelves();
  }
  function removeAttempt(id) {
    recent = recent.filter(existing => existing !== id);
    watchers.delete(id); // Invalidates an in-flight response, not the server worker.
    if (cachedActive === id && activeId !== id) selectionEpoch++;
    if (activeId === id && !library.has(id)) {
      selectionEpoch++;
      activeId = null;
      writeStorage(ACTIVE_KEY, "");
    }
    persistAttempts();
    renderActive();
    renderShelves();
    notice("Attempt removed from this browser. Its job and durable assets are retained.");
  }

  function renderShelves() {
    const pending = recent.filter(id => !["done", "error", "unavailable"].includes(jobs.get(id)?.status)).length;
    countHost.textContent = pending ? `${pending} pending · ${recent.length} attempts` : `${recent.length} recent attempts`;
    $("#recent-count").textContent = `(${recent.length})`;
    const shelf = $("#recent-list");
    shelf.replaceChildren();
    for (const id of recent) {
      const job = jobs.get(id) || {status:"checking"};
      const row = node("article", undefined, "attempt-row");
      row.dataset.job = id;
      row.dataset.state = job.status;
      const title = job.direction || library.get(id)?.name || `Character ${id.slice(0, 8)}`;
      const copy = node("div");
      copy.append(node("p", title, "attempt-title"), node("p", `${job.status}${job.step ? ` · ${job.step}` : ""}`, "microcopy"));
      if (job.status === "error") copy.append(node("p", "Generation failed. The worker logs have the diagnostic details.", "form-error"));
      row.append(copy);
      if (job.status === "done") row.append(action(activeId === id ? "Selected" : "Choose", () => choose(id)));
      row.append(action("Discard", () => removeAttempt(id)));
      shelf.append(row);
    }
    const host = $("#library-list");
    host.replaceChildren();
    for (const [id, entry] of library) {
      const button = action("", () => choose(id));
      button.className = "library-item";
      button.dataset.job = id;
      button.setAttribute("aria-pressed", String(activeId === id));
      const image = node("img");
      image.alt = entry.name;
      image.loading = "lazy";
      image.src = `/api/characters/jobs/${id}/image`; // Never trust URLs supplied by the index.
      button.append(image, node("span", entry.name));
      host.append(button);
    }
  }

  async function prepareShare(id) {
    if (!navigator.canShare || !navigator.share || typeof File === "undefined") return;
    try {
      const response = await fetch(`/api/characters/jobs/${id}/image`);
      if (!response.ok) return;
      const blob = await response.blob();
      const bytes = new Uint8Array(await blob.slice(0, 8).arrayBuffer());
      if (blob.type !== "image/png" || ![137,80,78,71,13,10,26,10].every((value, index) => bytes[index] === value)) return;
      const file = new File([blob], `character-${id}.png`, {type:"image/png"});
      if (activeId !== id || !navigator.canShare({files:[file]})) return;
      sharedFile = {id, file};
      $("#share-character").hidden = false;
    } catch { /* Download is the always-available fallback. */ }
  }

  async function loadCaption(id) {
    try {
      const response = await fetch(`/api/characters/jobs/${id}/caption`);
      if (!response.ok) throw new Error();
      const text = await response.text();
      if (activeId === id) $("#active-caption").textContent = text;
    } catch {
      if (activeId === id) $("#active-caption").textContent = "Caption unavailable. The image can still be downloaded.";
    }
  }

  function renderActive() {
    $("#active-result").hidden = !activeId;
    $("#empty-result").hidden = Boolean(activeId);
    if (!activeId) { renderedId = null; sharedFile = null; return; }
    const saved = library.get(activeId);
    $("#active-title").textContent = saved?.name || "Original character";
    $("#saved-state").textContent = saved ? "Saved" : "Not saved";
    $("#keep-character").textContent = saved ? "Update name" : "Keep character";
    $("#keep-character").disabled = libraryBusy || !libraryLoaded;
    $("#remove-character").disabled = libraryBusy;
    $("#remove-character").hidden = !saved;
    $("#discard-character").hidden = !recent.includes(activeId);
    $("#use-character").hidden = !saved;
    $("#use-ltx").href = `/?character_id=${activeId}`;
    $("#use-h3").href = `/h3?character_id=${activeId}`;
    $("#use-timeline").href = `/timeline?character_id=${activeId}`;
    if (renderedId === activeId) return; // Status polling must not reset a useful canvas or a draft name.
    renderedId = activeId;
    sharedFile = null;
    $("#character-name").value = saved?.name || "";
    $("#share-character").hidden = true;
    $("#share-notice").textContent = "Download the PNG to share it. Native sharing appears on supported devices.";
    $("#more-details").open = false;
    $("#use-character").open = false;
    $("#image-state").textContent = "Loading image…";
    $("#active-image").src = `/api/characters/jobs/${activeId}/image`;
    $("#download-character").href = `/api/characters/jobs/${activeId}/image`;
    $("#download-character").download = `character-${activeId}.png`;
    $("#inspect-image").href = `/api/characters/jobs/${activeId}/image`;
    $("#inspect-caption").href = `/api/characters/jobs/${activeId}/caption`;
    $("#inspect-capsule").href = `/api/characters/jobs/${activeId}/capsule`;
    $("#active-caption").textContent = "Loading caption…";
    loadCaption(activeId);
    prepareShare(activeId);
  }

  async function choose(id, {automatic = false} = {}) {
    if (!validId(id) || (!recent.includes(id) && !library.has(id))) return;
    // An empty canvas can still have a user's selection in flight; completion is not intent.
    if (automatic && pendingExplicitEpoch === selectionEpoch) return;
    const epoch = ++selectionEpoch;
    if (!automatic) pendingExplicitEpoch = epoch;
    try {
      const response = await fetch(`/api/characters/jobs/${id}`);
      if (!response.ok) throw new Error();
      const job = await response.json();
      if (epoch !== selectionEpoch || (!recent.includes(id) && !library.has(id))) return;
      if (job.job_id !== id || job.status !== "done") {
        notice("This Character is not completed. Your current result is unchanged."); return;
      }
      jobs.set(id, {...jobs.get(id), ...job});
      activeId = id;
      writeStorage(ACTIVE_KEY, id);
      renderActive();
      renderShelves();
      notice("");
    } catch {
      if (epoch === selectionEpoch) notice("This Character is unavailable. Your current result is unchanged.");
    } finally {
      if (pendingExplicitEpoch === epoch) pendingExplicitEpoch = null;
    }
  }

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  async function watch(id) {
    if (!validId(id) || watchers.has(id) || !recent.includes(id)) return;
    const token = {};
    watchers.set(id, token);
    while (watchers.get(id) === token && recent.includes(id)) {
      try {
        const response = await fetch(`/api/characters/jobs/${id}`);
        if (watchers.get(id) !== token || !recent.includes(id)) return;
        if (!response.ok) {
          if (response.status === 404 || response.status === 409) {
            jobs.set(id, {...jobs.get(id), status:"unavailable", step:"Job record unavailable"});
            watchers.delete(id); renderShelves(); return;
          }
          throw new Error();
        }
        const job = await response.json();
        if (watchers.get(id) !== token || !recent.includes(id)) return;
        if (job.job_id !== id || !["queued", "running", "done", "error"].includes(job.status)) throw new Error();
        jobs.set(id, {...jobs.get(id), ...job});
        renderShelves();
        if (job.status === "done" || job.status === "error") {
          watchers.delete(id);
          if (job.status === "done" && !activeId && !restoringSelection) {
            // A cached selection takes priority over whichever pending request answers first.
            const restore = validId(cachedActive) && (recent.includes(cachedActive) || library.has(cachedActive)) && jobs.get(cachedActive)?.status !== "unavailable";
            if (!restore || cachedActive === id) await choose(id, {automatic:true});
          }
          return;
        }
      } catch {
        if (watchers.get(id) !== token || !recent.includes(id)) return;
        jobs.set(id, {...jobs.get(id), status:"offline", step:"Cannot reach the local app; retrying"});
        renderShelves();
      }
      await sleep(POLL_MS);
    }
  }

  async function refreshLibrary() {
    const epoch = ++libraryEpoch;
    try {
      const response = await fetch("/api/characters/library");
      if (!response.ok) throw new Error();
      const payload = await response.json();
      if (!Array.isArray(payload.characters) || payload.characters.some(entry => !validId(entry.job_id) || typeof entry.name !== "string")) throw new Error();
      if (epoch !== libraryEpoch) return false;
      library = new Map(payload.characters.map(entry => [entry.job_id, entry]));
      libraryLoaded = true;
      $("#library-state").textContent = library.size ? `${library.size} deliberately saved characters` : "No saved characters yet. Keep a result when it is worth returning to.";
      renderActive(); renderShelves();
      return true;
    } catch {
      if (epoch === libraryEpoch) {
        libraryLoaded = false;
        $("#library-state").textContent = "Library unavailable. Existing saves have not been changed. Retry with Refresh library.";
        renderActive();
      }
      return false;
    }
  }

  async function changeMembership(method) {
    const id = activeId;
    if (!id || libraryBusy || !libraryLoaded) return;
    const name = $("#character-name").value.trim();
    libraryBusy = true;
    libraryEpoch++; // An older initial/refetch response cannot undo a write's verification.
    renderActive();
    try {
      const response = await fetch(`/api/characters/library/${id}`, {
        method, headers:{"content-type":"application/json"},
        ...(method === "POST" ? {body:JSON.stringify(name ? {name} : {})} : {}),
      });
      if (!response.ok) {
        notice("The library change was refused. No success has been confirmed."); return;
      }
      if (!await refreshLibrary() || (method === "POST" ? !library.has(id) || (name && library.get(id).name !== name) : library.has(id))) {
        notice("Could not verify the library change. Refresh the library before trying again."); return;
      }
      notice(method === "POST" ? "Character saved in the server library." : "Removed from the library. Durable media, capsule and job are retained.");
      if (activeId === id && method === "POST") $("#character-name").value = library.get(id).name;
    } catch { notice("Could not verify the library change. Refresh the library before trying again."); }
    finally { libraryBusy = false; renderActive(); }
  }

  /* ---- submission never removes a useful active result ---- */
  async function submit(event) {
    event.preventDefault();
    showError("");
    const direction = directionField.value.trim();
    if (!direction) { showError("Describe the character first — or press Shuffle."); return; }
    if (/character sheet/i.test(direction)) {
      showError("Say “turnaround” instead: “character sheet” makes FLUX 3 draw an illustration."); return;
    }
    const button = $("#generate");
    button.disabled = true;
    const seed = randomSeed();
    try {
      const projectId = await globalThis.OpenGenjutsuProject?.ensure();
      const response = await fetch("/api/characters/jobs", {
        method:"POST", headers:{"content-type":"application/json"},
        body:JSON.stringify({project_id:projectId, direction, mode:$("#mode").value, trend_id:"original", selections:selections(),
          direction_origin:directionOrigin, sampler_seed:seed, upsampler_seed:randomSeed(), upsampler:$("#upsampler").value === "on"}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !validId(payload.job_id)) { showError("The local app could not queue this character. Check runtime readiness and try again."); return; }
      globalThis.OpenGenjutsuProject?.acceptJob(payload.job_id, payload.project_id, 'flux3-klein-character');
      remember(payload.job_id);
      jobs.set(payload.job_id, {status:"queued", direction});
      renderShelves();
      notice("Character queued. Your selected result stays here while it runs.");
      watch(payload.job_id);
    } catch { showError("Could not reach the local app. Your selected result is unchanged."); }
    finally { button.disabled = false; }
  }

  /* ---- boot ---- */
  $("#shuffle").addEventListener("click", shuffle);
  clearAxesButton.addEventListener("click", clearAxes);
  directionField.addEventListener("input", () => {
    directionOrigin = "user_authored";
    syncProposalSummary();
  });
  $("#clear-jobs").addEventListener("click", () => {
    selectionEpoch++;
    watchers.clear();
    recent = [];
    if (activeId && !library.has(activeId)) { activeId = null; writeStorage(ACTIVE_KEY, ""); }
    persistAttempts(); renderActive(); renderShelves();
    notice("Recent attempts cleared. Saved characters and durable assets are unchanged; running jobs continue.");
  });
  $("#discard-character").addEventListener("click", () => removeAttempt(activeId));
  $("#keep-character").addEventListener("click", () => changeMembership("POST"));
  $("#remove-character").addEventListener("click", () => changeMembership("DELETE"));
  $("#refresh-library").addEventListener("click", () => { if (!libraryBusy) refreshLibrary(); });
  $("#active-image").addEventListener("load", () => { $("#image-state").textContent = "Completed PNG · original result"; });
  $("#active-image").addEventListener("error", () => { $("#image-state").textContent = "Image unavailable. The saved entry has not been removed; refresh or inspect the job."; });
  $("#share-character").addEventListener("click", () => {
    if (!sharedFile || sharedFile.id !== activeId) return;
    // File is already prepared, so share() is invoked inside the user's activation, not after fetch().
    try {
      navigator.share({files:[sharedFile.file], title:"Original character"}).catch(error => {
        if (error.name !== "AbortError") $("#share-notice").textContent = "Native sharing failed. Use Download PNG instead.";
      });
    } catch { $("#share-notice").textContent = "Native sharing is unavailable. Use Download PNG instead."; }
  });
  $("#mode").addEventListener("change", event => { $("#mode-hint").textContent = MODE_HINTS[event.target.value]; });
  form.addEventListener("submit", submit);
  shuffle();
  renderActive(); renderShelves();
  fetch("/api/characters/readiness")
    .then(response => { if (!response.ok) throw new Error(); return response.json(); })
    .then(report => {
      const badge = $("#readiness");
      badge.textContent = report.ready ? "Local studio ready" : "Local studio not ready. Check the runtime configuration.";
      badge.dataset.state = report.ready ? "ok" : "blocked";
    })
    .catch(() => { $("#readiness").textContent = "Local studio unreachable"; $("#readiness").dataset.state = "blocked"; });
  const initialSelectionEpoch = selectionEpoch;
  (async () => {
    await globalThis.OpenGenjutsuProject?.ready;
    if (selectionEpoch !== initialSelectionEpoch) return;
    recent = [...new Set([...stored(), ...(globalThis.OpenGenjutsuProject?.jobs('flux3-klein-character') || []).map(job => job.job_id)])].slice(0, MAX_STORED);
    cachedActive = readStorage(ACTIVE_KEY);
    restoringSelection = validId(cachedActive);
    renderShelves();
    for (const id of recent) watch(id);
    await refreshLibrary();
    const explicit = typeof location !== 'undefined' ? new URLSearchParams(location.search).get('job_id') : null;
    if (validId(explicit) && globalThis.OpenGenjutsuProject?.containsJob(explicit)) {
      if (!recent.includes(explicit)) recent.unshift(explicit);
      await choose(explicit);
      restoringSelection = false;
      return;
    }
    let attemptedRestore = false;
    if (selectionEpoch === initialSelectionEpoch && validId(cachedActive) && (library.has(cachedActive) || recent.includes(cachedActive))) {
      attemptedRestore = true;
      await choose(cachedActive, {automatic:true});
    }
    restoringSelection = false;
    if (!activeId && selectionEpoch === initialSelectionEpoch + Number(attemptedRestore)) {
      const completed = recent.find(id => jobs.get(id)?.status === "done");
      if (completed) choose(completed, {automatic:true});
    }
  })().catch(error => showError(error.message));
})();

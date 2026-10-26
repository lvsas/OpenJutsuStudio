/* Viral Character Maker — instant local hooks, one independent job per request.
 *
 * The direction describes only the CHARACTER. Medium, framing, views and environment belong to the
 * output mode, which the server owns: mixing them produced a passport-photo brief with no hook.
 */
(() => {
  "use strict";

  // Coherent adults: a distinctive physical hook, deliberate styling, contrasting personality.
  // Complete tuples stay coherent and prop-free; rendering and framing belong to the server.
  const LOOKS = [
    {
      being: "man", role: "fastidious train announcer",
      build: "a heavy barrel-chested adult body with a prominent round belly, thick neck and substantial arms and legs",
      hair: "dense copper hair forming one continuous low horizontal sculptural mass, sweeping laterally outward from the temples to wider than both shoulders, with layered volume beside the cheeks and jaw rather than above the crown; visible strands flow from the scalp throughout the hair mass",
      face: "a long broad face with a substantial nose and a bushy dark walrus moustache drooping over the upper lip",
      outfit: "a mint-and-chocolate ribbed-velour jumpsuit with a giant pointed collar, diagonal colour-block panels, a high front zip, flared legs and cream platform loafers",
      attitude: "standing with shy tucked-in elbows, raised eyebrows and a bashful closed-mouth smile",
      primary_axis: "hair",
    },
    {
      being: "woman", role: "unyielding boules referee",
      build: "a broad powerful adult build with massive muscular shoulders, thick forearms and sturdy legs",
      hair: "natural grey hair with visible individual matte strands, rising from the scalp into a towering geometric crest as tall as the forehead, with closely shaved temples",
      face: "a strong square jaw, a prominent aquiline nose, straight emphatic eyebrows and tightly pursed lips",
      outfit: "a cropped plum velvet jacket with sharply squared shoulders, an acid-chartreuse satin shirt with spear-point lapels, plum pinstriped high-waisted flares and chunky black platform shoes",
      attitude: "feet firmly planted, chin forward and a defiant smirk",
      primary_axis: "build",
    },
    {
      being: "woman", role: "ceremonious karaoke organiser",
      build: "a tall pear-shaped adult body with narrow shoulders, a soft waist and very broad heavy hips and thighs",
      hair: "an enormous shoulder-wide halo of dense black curls, visible springy hair strands rooted at the scalp, with a short straight fringe",
      face: "full round cheeks, a broad nose, slightly spaced front teeth and an emphatic knowing smile",
      outfit: "a fitted burnt-orange brocade blazer with outsized cream lapels and enamel disc buttons, a violet high-waisted pleated A-line midi skirt and cream block-heel boots",
      attitude: "chin raised, elbows poised and a triumphant toothy smile",
      primary_axis: "face",
    },
    {
      being: "woman", role: "dreamy lift technician",
      build: "a very tall strikingly lean adult build with long arms and legs, high shoulders and large hands",
      hair: "a waist-length thick blonde cascade of crimped hair, spreading into a broad triangular silhouette behind the shoulders, visible fine strands and a short flat fringe",
      face: "an elongated angular face with a projecting chin, heavy upper eyelids and a long softly crooked nose",
      outfit: "a cropped cobalt quilted utility jacket with rounded cocoon sleeves and oversized white zips, a lemon ribbed turtleneck, cobalt high-waisted extra-wide carpenter trousers and chunky cream boots",
      attitude: "relaxed shoulders, a tilted head and a distracted gentle smile",
      primary_axis: "face",
    },
    {
      being: "man", role: "reserved dance teacher",
      build: "a top-heavy adult weightlifter build with an immense muscular chest, thick upper arms, a broad waist and solid legs",
      hair: "brown hair swept into three oversized sculptural waves rising high above the forehead, each wave made of visible combed strands connected to the scalp, with short sides",
      face: "a wide square jaw, a heavy cleft chin, a short nose and deep smiling creases on a clean-shaven face",
      outfit: "a fitted rose ribbed-knit polo with an absurdly oversized pointed collar and cream contrast piping, emerald high-waisted flares with sharp front pleats and a broad waistband, and oxblood heeled dance shoes",
      attitude: "open hands, an earnest upright stance and a slightly worried expression",
      primary_axis: "build",
    },
    {
      being: "non-binary person", role: "enthusiastic apartment-block coordinator",
      build: "a long-torsoed broad-hipped adult body with narrow sloping shoulders, a soft belly and long strong legs",
      hair: "white hair growing from the scalp into an enormous asymmetric sculptural fan sweeping a full head-width to one side, clearly visible wispy strands and closely cropped hair on the other side",
      face: "a wide angular jaw, a pronounced cleft chin, a broad nose and expressive arched eyebrows",
      outfit: "a cropped lilac mohair jacket with spherical sleeves and scarlet sculpted piping, a scarlet ribbed mock-neck top, scarlet high-waisted wide-leg trousers with chunky pleats, and white platform shoes",
      attitude: "leaning slightly forward with a conspiratorial smile and an inviting open posture",
      primary_axis: "hair",
    },
  ];

  const WARDROBES = [
    [
      {"label": "Neon mohair + checkerboard", "outfit": "an electric-lime shaggy mohair cropped cardigan with huge fuchsia cuffs, chocolate-and-cream checkerboard wide-leg trousers with a sky-high waist and fuchsia platform loafers"},
      {"label": "Cyber vinyl + cocoon trousers", "outfit": "a turquoise glossy-vinyl cropped biker jacket with an inflated round collar, violet high-waisted cocoon trousers with sculpted hip panels and acid-yellow cleated platform boots"},
      {"label": "Coral harlequin tailoring", "outfit": "a coral-and-cobalt harlequin-jacquard suit with enormous asymmetric lapels and extra-wide trouser legs, a lemon ribbed mock-neck and checkerboard platform brogues"},
    ],
    [
      {"label": "Chrome cocoon + acid cargos", "outfit": "a cropped mirror-silver quilted bomber with spherical sleeves and an enormous violet padded collar, acid-green high-waisted balloon cargo trousers and chunky plum platform boots"},
      {"label": "Pink leopard power suit", "outfit": "a hot-pink leopard-jacquard power suit with triangular shoulders, huge black rolled cuffs and sweeping flared trousers, a lime ribbed top and black-and-pink platform boots"},
      {"label": "Origami denim + lime pleats", "outfit": "a cobalt origami-folded denim cropped jacket with sculpted pointed shoulders, orange mesh over an opaque orange tank, asymmetric lime pleated cargo trousers and cobalt platform clogs"},
    ],
    [
      {"label": "Tulle + checkerboard taffeta", "outfit": "a violet ribbed fitted top with enormous orange tulle puff sleeves, a high-waisted circular skirt in clashing fuchsia-and-lime checkerboard taffeta and glossy orange platform boots"},
      {"label": "Holographic disco bolero", "outfit": "a sculpted cobalt holographic-brocade cropped bolero with giant fan-shaped lapels, a neon-coral pleated culotte skirt and violet knee-high platform boots"},
      {"label": "Pop patchwork + sculptural skirt", "outfit": "a hot-pink and turquoise patchwork denim peplum jacket with giant round enamel buttons, a lemon accordion-pleated midi skirt with a violet sculptural hem and two-tone platform Mary Janes"},
    ],
    [
      {"label": "Neoprene space-workwear", "outfit": "a sculptural white neoprene cropped jacket with banana-yellow tubular sleeves, cobalt extra-wide parachute carpenter trousers with oversized orange zip pockets and white platform moon boots"},
      {"label": "Electric denim + folded cuffs", "outfit": "an acid-orange quilted crop jacket with huge curved shoulders, a metallic-lilac ribbed turtleneck, cobalt patchwork denim trousers with giant folded cuffs and lime platform clogs"},
      {"label": "Optical knit + balloon sleeves", "outfit": "a lime-and-black optical-zigzag chunky-knit vest with a huge folded collar, a lilac balloon-sleeve blouse, copper satin extra-wide trousers and cobalt wedge boots"},
    ],
    [
      {"label": "Disco tiger + elephant legs", "outfit": "a fuchsia tiger-striped lurex cropped jacket with enormous pointed lapels, an orange ribbed mock-neck, emerald high-waisted elephant-leg trousers with side pleats and glossy fuchsia platform boots"},
      {"label": "Candy sculptural knit", "outfit": "a cobalt-and-lime chunky cable-knit cropped cardigan with enormous rounded sleeves and giant orange disc buttons, a scarlet fitted top, violet high-waisted balloon trousers and cream platform shoes"},
      {"label": "Holographic track couture", "outfit": "a violet holographic-taffeta cropped track jacket with an oversized orange funnel collar and lime piping, cobalt checkerboard pleated skater trousers and orange chunky platform sneakers"},
    ],
    [
      {"label": "Pop faux fur + tartan", "outfit": "a cropped scarlet shaggy faux-fur jacket with spherical lilac sleeves, an acid-yellow ribbed mock-neck, turquoise-and-fuchsia tartan wide-leg trousers with sculpted knee folds and white platform boots"},
      {"label": "Lavender origami + skirt layers", "outfit": "a lilac neoprene cropped jacket with huge fan-folded sleeves and red sculpted piping, a coral opaque top, an acid-green asymmetric layered skirt over lilac flared trousers and red platform clogs"},
      {"label": "Op-art puffer + racing trousers", "outfit": "a black-and-white optical-swirl satin cropped puffer with a giant orange padded collar, scarlet barrel-leg racing trousers with cobalt side panels and lime chunky platform sneakers"},
    ],
  ];

  const AXES = [
    ["being", "Presentation", ["a woman", "a man", "an androgynous person", "a non-binary person"]],
    ["build", "Silhouette", LOOKS.map((look) => look.build)],
    ["skin_tone", "Skin tone", ["fair skin", "olive skin", "warm brown skin", "deep brown skin", "very dark brown skin"]],
    ["hair", "Signature hair", LOOKS.map((look) => look.hair)],
    ["face", "Face and expression", LOOKS.map((look) => look.face)],
    ["outfit", "Clothes", [...WARDROBES.flat().map(entry => entry.outfit), ...LOOKS.map(look => look.outfit)]],
    ["role", "Personality", LOOKS.map((look) => `a ${look.role}`)],
    ["era", "Era", ["present-day everyday clothing", "simple 1970s casual clothing", "simple 1990s casual clothing"]],
    ["attitude", "Posture and attitude", LOOKS.map((look) => look.attitude)],
  ];

  // Human labels are presentation-only; the complete strings still form the frozen request.
  const CHOICE_LABELS = {
    being: ["Woman", "Man", "Androgynous", "Non-binary"],
    build: ["Barrel-chested", "Powerful shoulders", "Pear-shaped", "Tall and lean", "Weightlifter", "Broad hips"],
    hair: ["Low copper wings", "Grey geometric crest", "Black curl halo", "Blonde crimped cascade", "Three sculptural waves", "White asymmetric fan"],
    face: ["Walrus moustache", "Square jaw + defiant smirk", "Round cheeks + knowing smile", "Long angular face", "Cleft chin + smiling creases", "Angular jaw + arched brows"],
    outfit: [...WARDROBES.flat().map(entry => entry.label), "Retro mint jumpsuit", "Retro plum tailoring", "Retro orange + violet", "Retro cobalt workwear", "Retro rose + emerald", "Retro lilac + scarlet"],
    attitude: ["Shy and bashful", "Defiant", "Triumphant", "Dreamy", "Earnest and worried", "Conspiratorial"],
    role: ["Train announcer", "Boules referee", "Karaoke host", "Lift technician", "Dance teacher", "Block coordinator"],
    skin_tone: ["Fair", "Olive", "Warm brown", "Deep brown", "Very dark brown"],
    era: ["Contemporary", "1970s", "1990s"],
  };
  const REFINEMENTS = [
    ["identity", "Build", ["build"], ""],
    ["appearance", "Hair", ["hair"], ""],
    ["face", "Face", ["face"], ""],
    ["style", "Clothes", ["outfit"], ""],
    ["story", "Expression", ["attitude"], ""],
  ];
  const MODE_LABELS = {portrait:"Portrait", full_body:"Full body", turnaround:"Turnaround"};

  const MODE_HINTS = {
    portrait: "Waist-up portrait · face and hairstyle.",
    full_body: "Full figure · including both feet.",
    turnaround: "Four angles: front, three-quarter, profile, back.",
  };
  const LEGACY_KEY = "opengenjutsu.characters.jobs";
  const STORAGE_KEY = "opengenjutsu.characters.attempts";
  const ACTIVE_KEY = "opengenjutsu.characters.active";
  const HIDDEN_KEY = "opengenjutsu.characters.hidden";
  const PENDING_KEY = "opengenjutsu.characters.pending-result";
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
  const axisSelect = $("#axis-select");
  let draftEpoch = 0;
  let openAxis = null;
  let openRefinement = null;
  let directionOrigin = "generated";
  let directionFacts = null;

  function selectedValues(axisKeys) {
    return axisKeys.map((key) => axisValues.get(key)).filter(Boolean);
  }

  function shortChoice(key, value) {
    if (!value) return "";
    const index = axisByKey.get(key)?.[2].indexOf(value) ?? -1;
    const label = CHOICE_LABELS[key]?.[index] || value;
    return label.length > 48 ? label.slice(0, 45) + "…" : label;
  }
  function syncProposalSummary() {
    $("#idea-adjustments").hidden = !directionFacts;
    if (!directionFacts) {
      const text = directionField.value.trim();
      $("#idea-summary").textContent = text.length > 180 ? text.slice(0, 177) + "…" : text || "Write a character idea, or choose Another idea.";
      proposalSummary.textContent = "Your own idea. Another idea restores optional adjustments.";
      return;
    }
    const fact = key => axisValues.get(key) || directionFacts[key];
    const presentation = shortChoice("being", axisValues.get("being") || `a ${directionFacts.being}`);
    const role = shortChoice("role", axisValues.get("role") || `a ${directionFacts.role}`);
    const signature = directionFacts.primary_axis;
    $("#idea-summary").textContent = `${presentation} · ${role}. ${shortChoice(signature, fact(signature))} · ${shortChoice("outfit", fact("outfit"))}.`;
    proposalSummary.textContent = axisValues.size ? `Adjusted: ${[...axisValues.keys()].map(key => axisByKey.get(key)[1]).join(" · ")}` : "";
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
      const profile = directionFacts ? LOOKS.findIndex(look => look.role === directionFacts.role && look.build === directionFacts.build) : -1;
      const visibleChoices = key === "outfit" && profile >= 0
        ? [...WARDROBES[profile].map(entry => entry.outfit), LOOKS[profile].outfit]
        : choices;
      for (const choice of visibleChoices) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = shortChoice(key, choice);
        chip.title = choice;
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
    $("#proposal-refinements").hidden = !directionFacts;
    refineListHost.replaceChildren();
    clearAxesButton.hidden = axisValues.size === 0;
    syncProposalSummary();
    if (!directionFacts) return;
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
      summary.textContent = values.length ? axisKeys.map(key => shortChoice(key, axisValues.get(key))).filter(Boolean).join(" · ") : fallback;
      copy.append(title, summary);
      const arrow = document.createElement("span");
      arrow.className = "refine-arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "→";
      button.append(copy, arrow);
      button.addEventListener("click", () => {
        if (!directionFacts) return;
        openRefinement = openRefinement === key ? null : key;
        renderRefinements();
        renderRefineOptions();
      });
      refineListHost.append(button);
    }
  }

  function renderRefineOptions() {
    refineOptionsHost.replaceChildren();
    if (!directionFacts || !openRefinement) return;
    const [, label, axisKeys] = REFINEMENTS.find(([key]) => key === openRefinement);
    const hint = document.createElement("p");
    hint.className = "microcopy";
    hint.textContent = `Refine ${label.toLowerCase()} — choose only what matters.`;
    refineOptionsHost.append(hint);
    renderChoices(axisKeys, refineOptionsHost);
  }

  for (const [key, label] of AXES) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = label;
    axisSelect.append(option);
  }
  axisSelect.addEventListener("change", () => {
    if (!directionFacts) return;
    openAxis = axisByKey.has(axisSelect.value) ? axisSelect.value : null;
    renderOptions();
  });

  function renderOptions() {
    $("#fine-refinements").hidden = !directionFacts;
    axisSelect.disabled = !directionFacts;
    axisSelect.value = openAxis || "";
    optionsHost.replaceChildren();
    if (!directionFacts || !openAxis) return;
    renderChoices([openAxis], optionsHost);
  }

  function setAxis(key, value) {
    if (!directionFacts) return; // Detached controls cannot add refinements to authored prose.
    draftEpoch++;
    if (value) axisValues.set(key, value);
    else axisValues.delete(key);
    renderRefinements();
    renderRefineOptions();
    renderOptions();
  }

  function clearAxes() {
    draftEpoch++;
    axisValues.clear();
    openAxis = null;
    openRefinement = null;
    renderRefinements();
    renderRefineOptions();
    renderOptions();
  }

  function selections() {
    const chosen = {};
    if (!directionFacts) return chosen;
    for (const [key] of AXES) {
      const value = axisValues.get(key);
      if (typeof value === "string" && value) chosen[key] = value;
    }
    return chosen;
  }

  /* ---- one legible hook per shuffle: five human signals, no object inventory ---- */

  function buildDirection(look) {
    const article = /^[aeiou]/i.test(look.role) ? "an" : "a";
    return `An original adult ${look.being}, ${article} ${look.role}: ${look.build}, ${look.hair}, ${look.face}, wearing ${look.outfit}, ${look.attitude}.`;
  }

  const personaBag = [], wardrobeBags = LOOKS.map(() => []);
  let lastPersona = null;
  function drawWithoutReplacement(bag, values, avoid = null) {
    if (!bag.length) bag.push(...values);
    const alternatives = bag.filter(value => value !== avoid);
    const value = pick(alternatives.length ? alternatives : bag);
    bag.splice(bag.indexOf(value), 1);
    return value;
  }
  function shuffle() {
    directionOrigin = "generated";
    const index = drawWithoutReplacement(personaBag, LOOKS.map((_, i) => i), lastPersona);
    lastPersona = index;
    const look = LOOKS[index];
    const outfit = drawWithoutReplacement(wardrobeBags[index], WARDROBES[index]).outfit;
    directionFacts = Object.freeze({...look, outfit});
    directionField.value = buildDirection(directionFacts);
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
  function readHidden() {
    try {
      const ids = JSON.parse(readStorage(HIDDEN_KEY) || "[]");
      return new Set(Array.isArray(ids) ? ids.filter(validId) : []);
    } catch { return new Set(); }
  }
  function persistHidden() { return writeStorage(HIDDEN_KEY, JSON.stringify([...hiddenAttempts])); }
  const jobs = new Map();
  const watchers = new Map();
  let hiddenAttempts = readHidden();
  let recent = stored().filter(id => !hiddenAttempts.has(id));
  let latestGeneration = null;
  let submissionSerial = 0;
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
  let attemptsSignature = "", librarySignature = "";

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
    hiddenAttempts.delete(id);
    persistHidden();
    recent = [id, ...recent.filter(existing => existing !== id)].slice(0, MAX_STORED);
    for (const oldId of watchers.keys()) if (!recent.includes(oldId)) watchers.delete(oldId);
    persistAttempts();
    renderShelves();
  }
  function removeAttempt(id) {
    if (!validId(id)) return;
    hiddenAttempts.add(id);
    if (latestGeneration?.id === id) { latestGeneration = null; writeStorage(PENDING_KEY, ""); }
    updateSelectionQuery(null, id);
    const persisted = persistHidden();
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
    notice(persisted ? "Attempt hidden in this browser. Its job and media are retained." : "Attempt hidden for now. Browser storage is unavailable; it may return after refresh.");
  }

  function selectShelfTab(tab, focus = false) {
    for (const key of ["attempts", "saved"]) {
      const button = $(`#tab-${key}`);
      button.setAttribute("aria-selected", String(tab === key));
      button.setAttribute("tabindex", tab === key ? "0" : "-1");
      if (tab === key && focus) button.focus();
    }
    $("#recent-attempts").hidden = tab !== "attempts";
    $("#saved-characters").hidden = tab !== "saved";
  }
  function renderGenerationState() {
    const host = $("#generation-state");
    if (!latestGeneration) { host.hidden = true; return; }
    const job = jobs.get(latestGeneration.id);
    const label = MODE_LABELS[latestGeneration.mode || job?.mode] || "Character";
    host.hidden = job?.status === "done" && activeId === latestGeneration.id;
    host.textContent = job?.status === "done" ? `${label} ready — select it in Attempts.`
      : job?.status === "error" ? "Generation failed. Your previous result is preserved."
      : job?.status === "offline" ? "Connection lost. Checking the existing job; no resubmission."
      : job?.status === "running" ? `Generating ${label.toLowerCase()}… You can keep exploring.`
      : `${label} queued. You can keep exploring.`;
  }
  function renderShelves() {
    renderGenerationState();
    const pending = recent.filter(id => !["done", "error", "unavailable"].includes(jobs.get(id)?.status)).length;
    countHost.textContent = pending ? `${pending} pending · ${recent.length} attempts` : `${recent.length} attempts`;
    $("#recent-count").textContent = `(${recent.length})`;
    const shelf = $("#recent-list");
    const signature = JSON.stringify([activeId, recent.map(id => [id, jobs.get(id)?.status, jobs.get(id)?.mode, library.get(id)?.name])]);
    if (signature !== attemptsSignature) {
      attemptsSignature = signature;
    shelf.replaceChildren();
    for (const [index, id] of recent.entries()) {
      const job = jobs.get(id) || {status:"checking"};
      const row = node("article", undefined, "attempt-row");
      row.dataset.job = id;
      row.dataset.state = job.status;
      const title = library.get(id)?.name || `Attempt ${recent.length - index}`;
      const select = action("", () => { if (job.status === "done") choose(id); });
      select.className = "attempt-select";
      select.disabled = job.status !== "done";
      select.setAttribute("aria-pressed", String(activeId === id));
      select.setAttribute("aria-label", `${title}${job.status === "done" ? ": select result" : ": " + job.status}`);
      const thumb = node("span", undefined, "attempt-thumb");
      if (job.status === "done") {
        const image = node("img");
        image.alt = title;
        image.loading = "lazy";
        image.src = `/api/characters/jobs/${id}/image`;
        thumb.append(image);
      } else {
        thumb.textContent = ({checking:"Checking…",queued:"Queued",running:"Generating…",offline:"Reconnecting…",error:"Failed",unavailable:"Unavailable"})[job.status] || "Checking…";
      }
      const state = job.status === "done" ? (MODE_LABELS[job.mode] || "Ready") : (job.status === "error" ? "Generation failed" : thumb.textContent);
      select.append(thumb, node("span", title, "attempt-title"), node("p", state, "microcopy"));
      const hide = action("×", () => removeAttempt(id));
      hide.className = "attempt-hide";
      hide.title = `Hide ${title} in this browser`;
      hide.setAttribute("aria-label", hide.title);
      row.append(select, hide);
      shelf.append(row);
    }
    $("#attempts-empty").hidden = recent.length > 0;
    }
    const savedSignature = JSON.stringify([activeId, [...library].map(([id, entry]) => [id, entry.name])]);
    if (savedSignature === librarySignature) return;
    librarySignature = savedSignature;
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

  async function loadFacePrompt(id) {
    const refined = jobs.get(id)?.face_refine === true;
    $("#face-prompt-details").hidden = !refined;
    $("#caption-label").textContent = refined ? "Base image caption" : "Description used for this image";
    if (!refined) return;
    $("#face-caption").textContent = "Loading facial conditioning…";
    try {
      const response = await fetch(`/api/characters/jobs/${id}/capsule`);
      if (!response.ok) throw new Error();
      const capsule = await response.json();
      const recipe = capsule.recipe;
      if (activeId !== id) return;
      if (!recipe || recipe.face_refine !== true) throw new Error();
      $("#face-caption").textContent = recipe.face_refine_policy === 2 && typeof recipe.face_refine_prompt === "string"
        ? recipe.face_refine_prompt
        : "Legacy face pass: this existing image used the full base caption. Its frozen evidence is unchanged; new generations use face-only conditioning.";
    } catch {
      if (activeId === id) $("#face-caption").textContent = "Facial conditioning unavailable. Inspect the frozen capsule; the image is unchanged.";
    }
  }

  function renderActive() {
    $("#active-result").hidden = !activeId;
    $("#empty-result").hidden = Boolean(activeId);
    $("#discard-character").hidden = !activeId || !recent.includes(activeId);
    $("#remove-character").hidden = !activeId || !library.has(activeId);
    $("#use-character").hidden = !activeId || !library.has(activeId);
    $("#saved-state").hidden = !activeId;
    $("#selection-context").hidden = !activeId;
    $("#result-mode").hidden = !activeId || !MODE_LABELS[jobs.get(activeId)?.mode];
    if (!activeId) { $("#active-title").textContent = "Your character"; renderedId = null; sharedFile = null; return; }
    $("#result-mode").textContent = MODE_LABELS[jobs.get(activeId)?.mode] || "";
    $("#selection-context").textContent = "Selected result · your next idea is separate.";
    const saved = library.get(activeId);
    $("#active-title").textContent = saved?.name || "Original character";
    $("#saved-state").textContent = saved ? "Saved" : "Not saved";
    $("#keep-character").textContent = saved ? "Update name" : "Keep character";
    $("#keep-character").className = saved ? "btn btn-ghost" : "btn btn-primary";
    $("#keep-character").disabled = libraryBusy || !libraryLoaded;
    $("#remove-character").disabled = libraryBusy;
    $("#remove-character").hidden = !saved;
    $("#discard-character").hidden = !recent.includes(activeId);
    $("#use-character").hidden = !saved;
    $("#use-ltx").href = `/?character_id=${activeId}`;
    $("#use-h3").href = `/h3?character_id=${activeId}`;
    $("#use-timeline").href = `/timeline?character_id=${activeId}`;
    const baseLink = $("#inspect-base");
    if (baseLink) {
      const refined = jobs.get(activeId)?.status === "done" && jobs.get(activeId)?.face_refine === true;
      baseLink.hidden = !refined;
      baseLink.href = refined ? `/api/characters/jobs/${activeId}/base-image` : "";
    }
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
    loadFacePrompt(activeId);
    prepareShare(activeId);
  }

  function updateSelectionQuery(id, onlyIf = null) {
    if (typeof history === "undefined" || typeof location === "undefined" || !location.href) return;
    const url = new URL(location.href);
    if (!url.searchParams.has("job_id") || (onlyIf && url.searchParams.get("job_id") !== onlyIf)) return;
    if (id) url.searchParams.set("job_id", id); else url.searchParams.delete("job_id");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  async function restorePendingIntent() {
    if (latestGeneration) return;
    const id = readStorage(PENDING_KEY);
    if (!validId(id) || !recent.includes(id)) return;
    const job = jobs.get(id);
    latestGeneration = {id, mode:job?.mode, selectionEpoch, serial:0};
    renderGenerationState();
    if (job?.status === "done") await choose(id, {automatic:true});
    else if (job?.status === "error" || job?.status === "unavailable") writeStorage(PENDING_KEY, "");
  }

  async function choose(id, {automatic = false} = {}) {
    if (!validId(id) || (!recent.includes(id) && !library.has(id))) return;
    // An empty canvas can still have a user's selection in flight; completion is not intent.
    if (automatic && pendingExplicitEpoch === selectionEpoch) return;
    const epoch = ++selectionEpoch;
    if (!automatic) { pendingExplicitEpoch = epoch; writeStorage(PENDING_KEY, ""); }
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
      updateSelectionQuery(id);
      if (latestGeneration?.id === id) writeStorage(PENDING_KEY, "");
      renderActive();
      renderShelves();
      if (!automatic) {
        const result = $("#active-result");
        result.scrollIntoView({block:"start", behavior:"auto"});
        result.focus({preventScroll:true});
      }
      renderGenerationState();
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
          if (job.status === "error" && latestGeneration?.id === id) writeStorage(PENDING_KEY, "");
          if (job.status === "done" && latestGeneration?.id === id && latestGeneration.selectionEpoch === selectionEpoch) {
            await choose(id, {automatic:true});
          } else if (job.status === "done" && !activeId && !restoringSelection && !latestGeneration) {
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

  async function reuseIdea() {
    const id = activeId, epoch = draftEpoch, selected = selectionEpoch;
    if (!id) return;
    const button = $("#reuse-idea");
    if (button.disabled) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/characters/jobs/${id}/capsule`);
      if (!response.ok) throw new Error();
      const capsule = await response.json();
      const recipe = capsule.recipe;
      if (id !== activeId || selected !== selectionEpoch || epoch !== draftEpoch) return;
      if (!recipe || typeof recipe.raw_direction !== "string" || !recipe.raw_direction.trim()) throw new Error();
      const facts = recipe.schema_version === 7 && recipe.direction_facts;
      if (facts && recipe.raw_direction === buildDirection(facts)) {
        directionFacts = Object.freeze({...facts});
        directionOrigin = "generated";
      } else {
        directionFacts = null;
        directionOrigin = "user_authored";
      }
      directionField.value = recipe.raw_direction;
      clearAxes();
      if (directionFacts && recipe.selections && typeof recipe.selections === "object") {
        for (const [key, value] of Object.entries(recipe.selections)) if (axisByKey.has(key) && typeof value === "string" && value !== "model_decides" && value) axisValues.set(key, value);
      }
      renderRefinements(); renderRefineOptions(); renderOptions();
      $("#idea-editor").open = !directionFacts;
      notice("Idea loaded. Generate creates a new character; identity can change.");
    } catch { notice("Could not load this idea. Your draft and selected result are unchanged."); }
    finally { button.disabled = false; }
  }

  /* ---- submission never removes a useful active result ---- */
  async function submit(event) {
    event.preventDefault();
    showError("");
    const direction = directionField.value.trim();
    // A changed textarea is authored prose, even if an integration omitted its input event.
    // Never parse that prose or send the old generated facts alongside it.
    if (directionFacts && direction !== buildDirection(directionFacts)) {
      directionOrigin = "user_authored";
      directionFacts = null;
      clearAxes();
    }
    if (!direction) { showError("Describe the character first — or press Try another."); return; }
    if (/character sheet/i.test(direction)) {
      showError("Say “turnaround” instead: “character sheet” makes FLUX 3 draw an illustration."); return;
    }
    const button = $("#generate");
    if (button.disabled) return;
    button.disabled = true;
    const serial = ++submissionSerial;
    const submittedSelectionEpoch = selectionEpoch;
    const seed = randomSeed();
    // Freeze this explicit request before project creation yields to another draft edit.
    const request = {direction, direction_facts:directionFacts ? {...directionFacts} : null,
      mode:$("#mode").value, trend_id:"original", selections:selections(), direction_origin:directionOrigin,
      sampler_seed:seed, upsampler_seed:randomSeed(), upsampler:$("#upsampler").value === "on",
      face_refine:$("#face-refine")?.checked === true};
    try {
      const projectId = await globalThis.OpenGenjutsuProject?.ensure();
      const response = await fetch("/api/characters/jobs", {
        method:"POST", headers:{"content-type":"application/json"},
        body:JSON.stringify({project_id:projectId, ...request}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !validId(payload.job_id)) { showError("The local app could not queue this character. Check runtime readiness and try again."); return; }
      globalThis.OpenGenjutsuProject?.acceptJob(payload.job_id, payload.project_id, 'flux3-klein-character');
      remember(payload.job_id);
      jobs.set(payload.job_id, {status:"queued", direction, mode:request.mode});
      if (!latestGeneration || serial > latestGeneration.serial) {
        latestGeneration = {id:payload.job_id, mode:request.mode, selectionEpoch:submittedSelectionEpoch, serial};
        writeStorage(PENDING_KEY, submittedSelectionEpoch === selectionEpoch ? payload.job_id : "");
      }
      renderShelves();
      notice("Character queued. Your selected result stays here while it runs.");
      watch(payload.job_id);
    } catch { showError("Could not reach the local app. Your selected result is unchanged."); }
    finally { button.disabled = false; }
  }

  /* ---- boot ---- */
  for (const tab of ["attempts", "saved"]) {
    const button = $(`#tab-${tab}`);
    button.addEventListener("click", () => selectShelfTab(tab));
    button.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      selectShelfTab(event.key === "Home" ? "attempts" : event.key === "End" ? "saved" : tab === "attempts" ? "saved" : "attempts", true);
    });
  }
  $("#reuse-idea").addEventListener("click", reuseIdea);
  $("#shuffle").addEventListener("click", shuffle);
  clearAxesButton.addEventListener("click", clearAxes);
  directionField.addEventListener("input", () => {
    directionOrigin = "user_authored";
    directionFacts = null;
    clearAxes();
  });
  $("#clear-jobs").addEventListener("click", () => {
    selectionEpoch++;
    for (const id of [...recent, ...(globalThis.OpenGenjutsuProject?.jobs("flux3-klein-character") || []).map(job => job.job_id)]) if (validId(id)) hiddenAttempts.add(id);
    persistHidden();
    watchers.clear();
    latestGeneration = null;
    writeStorage(PENDING_KEY, "");
    updateSelectionQuery(null);
    recent = [];
    if (activeId && !library.has(activeId)) { activeId = null; writeStorage(ACTIVE_KEY, ""); }
    persistAttempts(); renderActive(); renderShelves();
    notice("Recent attempts cleared. Saved characters and durable assets are unchanged; running jobs continue.");
  });
  $("#discard-character").addEventListener("click", () => removeAttempt(activeId));
  $("#keep-character").addEventListener("click", () => changeMembership("POST"));
  $("#remove-character").addEventListener("click", () => changeMembership("DELETE"));
  $("#refresh-library").addEventListener("click", () => { if (!libraryBusy) refreshLibrary(); });
  $("#active-image").addEventListener("load", () => { $("#image-state").textContent = jobs.get(activeId)?.face_refine === true
      ? "Completed PNG · face-refined result" : "Completed PNG · original result"; });
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
  $("#mode").addEventListener("change", event => {
    draftEpoch++;
    $("#mode-hint").textContent = MODE_HINTS[event.target.value];
    if (activeId) notice(`${MODE_LABELS[event.target.value]} applies to your next generation. The selected result is unchanged.`);
  });
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
    hiddenAttempts = readHidden();
    recent = [...new Set([...stored(), ...(globalThis.OpenGenjutsuProject?.jobs('flux3-klein-character') || []).map(job => job.job_id)])].filter(id => !hiddenAttempts.has(id)).slice(0, MAX_STORED);
    cachedActive = readStorage(ACTIVE_KEY);
    restoringSelection = validId(cachedActive);
    renderShelves();
    for (const id of recent) watch(id);
    await refreshLibrary();
    const explicit = typeof location !== 'undefined' ? new URLSearchParams(location.search).get('job_id') : null;
    if (validId(explicit) && globalThis.OpenGenjutsuProject?.containsJob(explicit)) {
      hiddenAttempts.delete(explicit); persistHidden();
      if (!recent.includes(explicit)) recent.unshift(explicit);
      await choose(explicit, {automatic:true});
      restoringSelection = false;
      await restorePendingIntent();
      return;
    }
    let attemptedRestore = false;
    if (selectionEpoch === initialSelectionEpoch && validId(cachedActive) && (library.has(cachedActive) || recent.includes(cachedActive))) {
      attemptedRestore = true;
      await choose(cachedActive, {automatic:true});
    }
    restoringSelection = false;
    await restorePendingIntent();
    if (!activeId && selectionEpoch === initialSelectionEpoch + Number(attemptedRestore)) {
      const completed = recent.find(id => jobs.get(id)?.status === "done");
      if (completed) choose(completed, {automatic:true});
    }
  })().catch(error => showError(error.message));
})();

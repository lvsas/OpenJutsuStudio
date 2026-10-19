/* Viral Character Maker — instant local hooks, one independent job per request.
 *
 * The direction describes only the CHARACTER. Medium, framing, views and environment belong to the
 * output mode, which the server owns: mixing them produced a passport-photo brief with no hook.
 */
(() => {
  "use strict";

  const ROLES = [
    "municipal locksmith", "competitive cheese judge", "night-shift lighthouse keeper",
    "unlicensed beekeeper", "freelance snake handler", "retired stunt double",
    "amateur taxidermist", "part-time opera understudy", "regional weather presenter",
    "semi-professional bagpipe tuner", "village blacksmith turned influencer",
    "independent traffic-cone collector",
  ];
  const HOOKS = [
    "a towering pompadour", "a blunt bowl cut with a deadpan fringe", "waist-length braids",
    "a shaved head with one long curl", "an asymmetric undercut", "enormous round glasses",
    "a moustache groomed into two spirals", "shoulder-length hair parted dead centre",
    "a bolted-on grin", "eyebrows drawn far too high",
  ];
  const OUTFITS = [
    "a tight mustard corduroy suit", "an oversized orange puffer jacket over a wetsuit",
    "a floor-length knitted cardigan with reindeer", "a white double-breasted tuxedo with shorts",
    "a hi-vis vest over full evening dress", "a leather apron over a ruffled shirt",
    "a full tartan three-piece with matching hat", "a raincoat two sizes too small",
  ];
  const PROPS = [
    "clutching a single glass honey jar", "holding a chrome accordion",
    "carrying an oversized ring of keys", "cradling a taxidermy owl",
    "balancing a teetering stack of plastic tubs", "wheeling a trolley full of turnips",
    "clutching a trophy engraved with someone else's name", "holding a fish, gently",
  ];
  const ATTITUDES = [
    "completely straight-faced", "suspiciously proud", "serene beyond all reason",
    "endearingly confused", "mid-sentence and furious", "beaming like it just won something",
    "deeply unimpressed", "as if it has just remembered something terrible",
  ];
  const STANCES = [
    "wide stance, arms held away from the body", "shoulders squared", "leaning slightly forward",
    "standing very still, chin lifted", "caught mid-step", "feet planted far apart",
  ];

  const AXES = [
    ["being", "Presentation", ["a woman", "a man", "an androgynous person", "a non-binary person"]],
    ["build", "Build", ["heavyweight and broad", "tall and wiry", "compact and stocky", "lean and lanky"]],
    ["skin_tone", "Skin tone", ["fair skin", "olive skin", "warm brown skin", "deep brown skin", "very dark brown skin"]],
    ["hair", "Hair", ["a blunt bowl cut", "a flat top", "a towering pompadour", "waist-length braids",
                      "a shaved head with a widow's peak", "slicked-back shoulder-length hair",
                      "an asymmetric undercut", "a two-spiral moustache"]],
    ["face", "Face", ["a wide closed-mouth smile", "an unblinking stare", "heavy-lidded calm eyes",
                      "a permanently surprised expression", "a vacant gormless expression"]],
    ["outfit", "Outfit", ["a tight corduroy suit", "an oversized yellow protective suit",
                          "a knitted ski jumper", "a worn leather apron over a white shirt",
                          "a pinstriped double-breasted blazer", "a white tuxedo with shorts"]],
    ["role", "Role", ["a beekeeper", "a municipal locksmith", "an accordion repairer",
                      "a night-shift lighthouse keeper", "a competitive cheese judge"]],
    ["era", "Era", ["seventies catalogue styling", "nineties documentary styling",
                    "contemporary studio styling", "eighties corporate video styling"]],
    ["accessory", "Accessory", ["a single glass honey jar", "a chrome accordion",
                                "an oversized ring of keys", "a folded paper map", "a taxidermy owl"]],
    ["absurdity", "Attitude", ["completely straight-faced", "endearingly confused",
                               "suspiciously proud", "serene beyond reason"]],
  ];

  const MODE_HINTS = {
    portrait: "One shareable studio photograph.",
    turnaround: "Four photographs of the same person — front, three-quarter, profile, back.",
  };
  const STORAGE_KEY = "opengenjutsu.characters.jobs";
  const MAX_STORED = 12;
  const HERO_COUNT = 1;
  const POLL_MS = 1500;

  const $ = (selector) => document.querySelector(selector);
  const form = $("#character-form");
  const directionField = $("#direction");
  const jobsHost = $("#jobs");
  const errorHost = $("#form-error");
  const countHost = $("#job-count");

  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const randomSeed = () => {
    const buffer = new Uint32Array(2);
    crypto.getRandomValues(buffer);
    return ((buffer[0] * 4294967296) + buffer[1]) % 9007199254740991;
  };

  /* ---- optional control: collapsed, and only ONE axis open at a time ----
   * Showing every axis and every option at once was the density failure: ~70 chips on screen.
   * The picker stays a single small row; opening an axis reveals only that axis. */

  const axisValues = new Map();
  const pickerHost = $("#axis-picker");
  const optionsHost = $("#axis-options");
  const pickerChips = new Map();
  let openAxis = null;

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
      pickerChips.get(key).setAttribute("aria-pressed",
        String(Boolean(axisValues.get(key))));
      pickerChips.get(key).dataset.open = String(openAxis === key);
    }
    if (!openAxis) {
      const hint = document.createElement("p");
      hint.className = "microcopy";
      hint.textContent = "Pick an axis to steer it. Blank means the model decides.";
      optionsHost.append(hint);
      return;
    }
    const [, label, choices] = AXES.find(([axisKey]) => axisKey === openAxis);

    const row = document.createElement("div");
    row.className = "axis-chips";

    for (const choice of choices) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = choice;
      chip.setAttribute("aria-pressed", String(axisValues.get(openAxis) === choice));
      chip.addEventListener("click", () => {
        setAxis(openAxis, axisValues.get(openAxis) === choice ? "" : choice);
      });
      row.append(chip);
    }

    const input = document.createElement("input");
    input.type = "text";
    input.className = "axis-input";
    input.maxLength = 300;
    input.placeholder = `or type your own ${label.toLowerCase()}`;
    input.setAttribute("aria-label", `${label}: custom value`);
    const current = axisValues.get(openAxis) || "";
    input.value = choices.includes(current) ? "" : current;
    input.addEventListener("input", () => setAxis(openAxis, input.value.trim()));
    row.append(input);

    optionsHost.append(row);
  }

  function setAxis(key, value) {
    if (value) axisValues.set(key, value);
    else axisValues.delete(key);
    renderOptions();
  }

  function clearAxes() {
    axisValues.clear();
    openAxis = null;
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

  /* ---- one legible hook per shuffle: the nonsense lives in the character ---- */

  function buildDirection() {
    return `An original character: an original ${pick(ROLES)} with ${pick(HOOKS)}, ` +
      `wearing ${pick(OUTFITS)}, ${pick(PROPS)}, ${pick(ATTITUDES)}, ${pick(STANCES)}.`;
  }

  function shuffle() {
    directionField.value = buildDirection();
    clearAxes();
    // A few axes ride along so the roll is never a blank slate; the hook above is what makes the
    // character memorable, the axes only steer it.
    for (const [key, , choices] of AXES) {
      if (Math.random() < 0.5) setAxis(key, pick(choices));
    }
  }

  /* ---- durable, independent job cards; only the newest stay large ---- */

  function stored() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string").slice(0, MAX_STORED) : [];
    } catch {
      return [];
    }
  }

  function store(ids) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.slice(0, MAX_STORED)));
  }

  function remember(id) {
    const ids = stored().filter((existing) => existing !== id);
    ids.unshift(id);
    store(ids);
  }

  function applyDensity() {
    const cards = [...jobsHost.querySelectorAll(".job-card")];
    cards.forEach((card, index) => {
      const active = card.dataset.state === "running" || card.dataset.state === "queued";
      card.dataset.density = index < HERO_COUNT || active ? "hero" : "compact";
    });
    countHost.textContent = cards.length === 0 ? "No jobs yet" : `${cards.length} in this session`;
  }

  function cardFor(id) {
    let card = jobsHost.querySelector(`[data-job="${id}"]`);
    if (card) return card;
    card = document.createElement("article");
    card.className = "job-card";
    card.dataset.job = id;
    card.dataset.density = "hero";
    card.innerHTML = `<div class="job-head"><span class="job-state">queued</span><span class="job-step"></span></div>
      <div class="job-body"></div>`;
    jobsHost.prepend(card);
    applyDensity();
    return card;
  }

  function paint(card, job) {
    card.querySelector(".job-state").textContent = job.status;
    card.querySelector(".job-step").textContent = job.step || "";
    card.dataset.state = job.status;
    applyDensity();
  }

  function showDirection(card, text) {
    const body = card.querySelector(".job-body");
    if (body.querySelector(".job-direction")) return;
    const node = document.createElement("p");
    node.className = "job-direction";
    node.textContent = text;
    body.append(node);
  }

  function showImage(card, id) {
    const body = card.querySelector(".job-body");
    if (body.querySelector(".job-image")) return;
    const image = document.createElement("img");
    image.className = "job-image";
    image.alt = "Generated original character";
    image.loading = "lazy";
    image.src = `/api/characters/jobs/${id}/image`;
    const link = document.createElement("a");
    link.className = "job-download";
    link.href = `/api/characters/jobs/${id}/image?download=1`;
    link.textContent = "Open full size";
    body.append(image, link);
  }

  async function showCaption(card, id) {
    if (card.querySelector(".job-caption")) return;
    try {
      const response = await fetch(`/api/characters/jobs/${id}/caption`);
      if (!response.ok) return;
      const text = await response.text();
      const node = document.createElement("details");
      node.className = "job-caption";
      const summary = document.createElement("summary");
      summary.textContent = "What the model actually wrote";
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      node.append(summary, paragraph);
      card.querySelector(".job-body").append(node);
    } catch {
      /* a missing caption is not a failed render */
    }
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function watch(id) {
    const card = cardFor(id);
    for (;;) {
      let job;
      try {
        const response = await fetch(`/api/characters/jobs/${id}`);
        if (!response.ok) throw new Error(`status ${response.status}`);
        job = await response.json();
      } catch {
        paint(card, { status: "offline", step: "waiting for the local app" });
        await sleep(POLL_MS * 2);
        continue;
      }
      paint(card, job);
      if (job.status === "done") {
        showImage(card, id);
        await showCaption(card, id);
        return;
      }
      if (job.status === "error") {
        const node = document.createElement("p");
        node.className = "job-error";
        node.textContent = job.error || "The render failed.";
        card.querySelector(".job-body").append(node);
        return;
      }
      await sleep(POLL_MS);
    }
  }

  /* ---- submission ---- */

  function showError(message) {
    errorHost.textContent = message;
    errorHost.hidden = !message;
  }

  async function submit(event) {
    event.preventDefault();
    showError("");
    const direction = directionField.value.trim();
    if (!direction) {
      showError("Describe the character first — or press Shuffle.");
      return;
    }
    if (/character sheet/i.test(direction)) {
      showError("Say “turnaround” instead: “character sheet” makes FLUX 3 draw an illustration.");
      return;
    }
    const button = $("#generate");
    button.disabled = true;
    const seed = randomSeed();
    try {
      const response = await fetch("/api/characters/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          direction,
          mode: $("#mode").value,
          trend_id: "original",
          selections: selections(),
          sampler_seed: seed,
          upsampler_seed: seed,
          upsampler: $("#upsampler").value === "on",
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(payload.detail || "The local app refused this character.");
        return;
      }
      remember(payload.job_id);
      showDirection(cardFor(payload.job_id), direction);
      watch(payload.job_id);
    } catch {
      showError("Could not reach the local app.");
    } finally {
      // A queued job must never lock the next request: this form is always ready again.
      button.disabled = false;
    }
  }

  /* ---- boot ---- */

  $("#shuffle").addEventListener("click", shuffle);
  $("#clear-axes").addEventListener("click", clearAxes);
  $("#clear-jobs").addEventListener("click", () => {
    jobsHost.replaceChildren();
    store([]);
    applyDensity();
  });
  $("#mode").addEventListener("change", (event) => {
    $("#mode-hint").textContent = MODE_HINTS[event.target.value];
  });
  form.addEventListener("submit", submit);

  shuffle();

  fetch("/api/characters/readiness")
    .then((response) => response.json())
    .then((report) => {
      const badge = $("#readiness");
      badge.textContent = report.ready ? "Local studio ready" : (report.issues || []).join(" ");
      badge.dataset.state = report.ready ? "ok" : "blocked";
    })
    .catch(() => {
      $("#readiness").textContent = "Local studio unreachable";
    });

  for (const id of stored().reverse()) watch(id);
})();

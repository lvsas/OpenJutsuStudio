/* Viral Character Maker — instant local hooks, one independent job per request.
 *
 * The direction describes only the CHARACTER. Medium, framing, views and environment belong to the
 * output mode, which the server owns: mixing them produced a passport-photo brief with no hook.
 */
(() => {
  "use strict";

  // Curated complete looks avoid accidental "costume" collisions from independently shuffled lists.
  // The vocabulary is contemporary, wearable and prop-free by default; the server freezes the
  // matching generated-origin anti-prop policy with the recipe.
  const LOOKS = [
    {
      role: "nightlife creative", build: "tall with a relaxed athletic build",
      hair: "a lacquered micro bob with a razor-sharp fringe", outfit: "a cropped cherry-red bomber over a sheer black layer, low-slung puddle trousers and slim trainers",
      attitude: "standing calm and self-assured with a direct expression",
    },
    {
      role: "independent stylist", build: "compact and athletic",
      hair: "a soft wolf cut with bleached face-framing pieces", outfit: "a boxy denim jacket over a graphic knit with a long cargo skirt and heavy boots",
      attitude: "standing easy and focused with a warm, direct expression",
    },
    {
      role: "editorial producer", build: "lean and long-limbed",
      hair: "sculpted finger waves with a clean side part", outfit: "an oversized pinstripe suit with a fitted waistcoat and pointed boots",
      attitude: "standing composed with a subtle, knowing smile",
    },
    {
      role: "digital art director", build: "broad-shouldered with an easy stance",
      hair: "a platinum buzz cut with a sharp graphic shaved line", outfit: "a cropped cobalt technical jacket over a ribbed tank with wide asymmetric parachute trousers",
      attitude: "standing relaxed, clear-eyed and quietly confident",
    },
    {
      role: "fashion student", build: "slim with an upright posture",
      hair: "a glossy blunt bob with a micro fringe", outfit: "an asymmetric butter-yellow knit with wide tailored trousers and platform loafers",
      attitude: "standing still with a cool, unforced expression",
    },
    {
      role: "music visual director", build: "tall with a lean, balanced silhouette",
      hair: "long lacquered braids with an exact centre part", outfit: "a cropped moto jacket over a mesh layer with low-rise trousers and square-toe boots",
      attitude: "standing open and observant with a calm natural smile",
    },
    {
      role: "downtown curator", build: "compact with a solid build",
      hair: "defined natural curls with a deep side part", outfit: "a sculptural zip-up jacket over a striped knit with wide black trousers",
      attitude: "standing grounded, wry and completely at ease",
    },
    {
      role: "street-style filmmaker", build: "tall and softly built",
      hair: "long dark butterfly layers with a deep side part", outfit: "a cropped olive work jacket with an asymmetric pleated midi skirt and tall boots",
      attitude: "standing quietly alert with a focused, natural expression",
    },
  ];

  const AXES = [
    ["being", "Presentation", ["a woman", "a man", "an androgynous person", "a non-binary person"]],
    ["build", "Build", ["tall with a relaxed athletic build", "compact with a solid build", "lean and long-limbed", "broad-shouldered with an easy stance"]],
    ["skin_tone", "Skin tone", ["fair skin", "olive skin", "warm brown skin", "deep brown skin", "very dark brown skin"]],
    ["hair", "Hair", ["a lacquered micro bob with a razor-sharp fringe", "a soft wolf cut with bleached face-framing pieces", "sculpted finger waves with a clean side part", "a platinum buzz cut with a sharp graphic shaved line", "a glossy blunt bob with a micro fringe", "long lacquered braids with an exact centre part"]],
    ["face", "Expression", ["a calm closed-mouth smile", "focused clear eyes", "a wry natural expression", "a warm relaxed expression", "a cool, unforced expression", "deadpan calm"]],
    ["outfit", "Outfit", ["a cropped cherry-red bomber over a sheer black layer with low-slung puddle trousers", "a boxy denim jacket over a graphic knit with a long cargo skirt", "an oversized pinstripe suit with a fitted waistcoat", "a cropped cobalt technical jacket over a ribbed tank with wide asymmetric parachute trousers", "an asymmetric butter-yellow knit with wide tailored trousers", "a cropped moto jacket over a mesh layer with low-rise trousers"]],
    ["role", "Role", ["a nightlife creative", "an independent stylist", "an editorial producer", "a digital art director", "a fashion student", "a music visual director"]],
    ["era", "Era", ["viral contemporary street style", "late-night editorial styling", "new-tailoring street style", "fashion-week off-duty styling"]],
    ["attitude", "Energy", ["calm and focused", "wry and composed", "warm and relaxed", "cool and self-assured", "guarded but steady"]],
  ];

  const REFINEMENTS = [
    ["appearance", "Change the hair or expression", ["hair", "face"], "Hair and expression · model decides"],
    ["style", "Change the style", ["outfit", "era"], "Outfit and era · model decides"],
    ["story", "Change the story", ["role", "attitude"], "Role and energy · model decides"],
    ["identity", "Make identity specific", ["being", "build", "skin_tone"], "Presentation and build · model decides"],
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
  const proposalSummary = $("#proposal-summary");
  const refineListHost = $("#refine-list");
  const refineOptionsHost = $("#refine-options");
  const clearAxesButton = $("#clear-axes");
  const jobsHost = $("#jobs");
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
    proposalSummary.textContent = directionField.value.trim();
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
    return `A shareable contemporary editorial street-style portrait of an original ${look.role}: ${look.build}, ${look.hair}, wearing ${look.outfit}, ${look.attitude}.`;
  }

  function shuffle() {
    directionOrigin = "generated";
    directionField.value = buildDirection();
    clearAxes();
    syncProposalSummary();
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
          direction_origin: directionOrigin,
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
  clearAxesButton.addEventListener("click", clearAxes);
  directionField.addEventListener("input", () => {
    directionOrigin = "user_authored";
    syncProposalSummary();
  });
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

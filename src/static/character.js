/* Viral Character Maker — instant local proposals, independent asynchronous jobs. */
(() => {
  "use strict";

  const AXES = [
    ["being", "Presentation", ["a woman", "a man", "an androgynous person", "a non-binary person"]],
    ["build", "Build", ["heavyweight and broad", "tall and wiry", "compact and stocky", "lean and lanky"]],
    ["skin_tone", "Skin tone", ["fair skin", "olive skin", "warm brown skin", "deep brown skin", "very dark brown skin"]],
    ["hair", "Hair", ["a blunt bowl cut", "a flat top", "a towering pompadour", "waist-length braids", "a shaved head with a widow's peak", "slicked-back shoulder-length hair", "an asymmetric undercut"]],
    ["face", "Face", ["a wide closed-mouth smile", "an unblinking stare", "heavy-lidded calm eyes", "a permanently surprised expression", "a vacant gormless expression"]],
    ["outfit", "Outfit", ["a tight corduroy suit", "an oversized yellow protective suit", "a knitted ski jumper", "a worn leather apron over a white shirt", "a pinstriped double-breasted blazer"]],
    ["role", "Role", ["a beekeeper", "a municipal locksmith", "an accordion repairer", "a night-shift lighthouse keeper", "a competitive cheese judge"]],
    ["era", "Era", ["seventies catalogue styling", "nineties documentary styling", "contemporary studio styling"]],
    ["accessory", "Accessory", ["a single glass honey jar", "a chrome accordion", "an oversized ring of keys", "a folded paper map"]],
    ["absurdity", "Absurdity", ["completely straight-faced", "endearingly confused", "suspiciously proud", "serene beyond reason"]],
  ];
  const MODE_HINTS = {
    portrait: "One shareable studio photograph.",
    turnaround: "Four studio photographs of the same original person — a reference sheet, in photographic wording.",
  };
  const OPENINGS = [
    "Studio photograph, full body,",
    "Studio photograph, three-quarter body,",
    "Studio photograph, eye-level medium portrait,",
  ];
  const STORAGE_KEY = "opengenjutsu.characters.jobs";
  const MAX_STORED = 12;
  const POLL_MS = 1500;

  const $ = (selector) => document.querySelector(selector);
  const form = $("#character-form");
  const directionField = $("#direction");
  const modeField = $("#mode");
  const axesHost = $("#axes");
  const jobsHost = $("#jobs");
  const errorHost = $("#form-error");
  const countHost = $("#job-count");

  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const randomSeed = () => {
    const buffer = new Uint32Array(2);
    crypto.getRandomValues(buffer);
    return ((buffer[0] * 4294967296) + buffer[1]) % 9007199254740991;
  };

  /* ---- local, instant proposal ---- */

  const axisFields = new Map();
  for (const [key, label, choices] of AXES) {
    const wrapper = document.createElement("label");
    wrapper.className = "field axis";
    const caption = document.createElement("span");
    caption.textContent = label;
    const input = document.createElement("input");
    input.name = key;
    input.type = "text";
    input.maxLength = 300;
    input.placeholder = "model decides";
    input.setAttribute("list", `axis-${key}`);
    const suggestions = document.createElement("datalist");
    suggestions.id = `axis-${key}`;
    for (const choice of choices) {
      const option = document.createElement("option");
      option.value = choice;
      suggestions.append(option);
    }
    wrapper.append(caption, input, suggestions);
    axesHost.append(wrapper);
    axisFields.set(key, input);
  }

  function shuffle() {
    const opening = pick(OPENINGS);
    const role = pick(AXES.find(([key]) => key === "role")[2]);
    directionField.value = `${opening} an original ${role} against a plain mid-grey seamless backdrop, ` +
      "soft even high-key studio lighting, sharp focus, unmarked single-colour clothing, no text, no logos, no watermark.";
    for (const [key, , choices] of AXES) {
      const target = axisFields.get(key);
      // An axis is only proposed when it was already in play or the roll picks it: the shuffle
      // stays surprising without silently filling every field.
      target.value = Math.random() < 0.45 ? pick(choices) : "";
    }
  }

  function clearAxes() {
    for (const input of axisFields.values()) input.value = "";
  }

  function selections() {
    const chosen = {};
    for (const [key, input] of axisFields) {
      const value = input.value.trim();
      if (value) chosen[key] = value;
    }
    return chosen;
  }

  /* ---- durable, independent job cards ---- */

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
    renderCount();
  }

  function renderCount() {
    const total = jobsHost.children.length;
    countHost.textContent = total === 0 ? "No jobs yet" : `${total} in this session`;
  }

  function cardFor(id) {
    let card = jobsHost.querySelector(`[data-job="${id}"]`);
    if (card) return card;
    card = document.createElement("article");
    card.className = "job-card";
    card.dataset.job = id;
    card.innerHTML = `<div class="job-head"><span class="job-state">queued</span><span class="job-step"></span></div>
      <div class="job-body"></div>`;
    jobsHost.prepend(card);
    renderCount();
    return card;
  }

  function paint(card, job) {
    card.querySelector(".job-state").textContent = job.status;
    card.querySelector(".job-step").textContent = job.step || "";
    card.dataset.state = job.status;
  }

  function showDirection(card, text) {
    card.querySelector(".job-body").insertAdjacentHTML(
      "beforeend", `<p class="job-direction"></p>`);
    card.querySelector(".job-direction").textContent = text;
  }

  function showImage(card, id) {
    const body = card.querySelector(".job-body");
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
    try {
      const response = await fetch(`/api/characters/jobs/${id}/caption`);
      if (!response.ok) return;
      const text = await response.text();
      const node = document.createElement("details");
      node.className = "job-caption";
      node.innerHTML = "<summary>What the model actually wrote</summary>";
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      node.append(paragraph);
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
      showError("Say “turnaround” instead of “character sheet”: that phrase makes FLUX 3 draw an illustration.");
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
          mode: modeField.value,
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
  modeField.addEventListener("change", () => {
    $("#mode-hint").textContent = MODE_HINTS[modeField.value];
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

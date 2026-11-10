// Elektro Celje outages card.
//
// The integration builds all texts in Python. This card only reads the card
// attributes of the planned_outages sensors and draws them.
// The card builds the DOM with createElement and textContent only. It never
// puts feed text into HTML markup.

const PLATFORM = "elektro_celje";
const CARD_TYPE = "elektro-celje-card";
const EDITOR_TYPE = "elektro-celje-card-editor";
// The integration gives this sort value to an outage without a known start.
const UNKNOWN_SORT = "9999-12-31T00:00:00+00:00";

const EDITOR_TEXTS = {
  en: {
    devices: "Locations",
    devicesHelp: "Leave empty to show all locations.",
    title: "Title",
    days_ahead: "Days ahead",
    days_aheadHelp: "Show outages from today up to this many days ahead. Leave empty to show all.",
    show_empty: "Show when nothing is planned",
    show_emptyHelp: "Otherwise the card hides itself.",
    show_ended: "Show the outages that ended today",
    nothingPlanned: "No planned outages",
  },
  sl: {
    devices: "Lokacije",
    devicesHelp: "Pustite prazno za vse lokacije.",
    title: "Naslov",
    days_ahead: "Dni vnaprej",
    days_aheadHelp: "Prikaži izklope od danes do toliko dni vnaprej. Pustite prazno za vse.",
    show_empty: "Prikaži, ko ni načrtovanih izklopov",
    show_emptyHelp: "Sicer se kartica skrije.",
    show_ended: "Prikaži danes končane izklope",
    nothingPlanned: "Ni načrtovanih izklopov",
  },
};

function editorTexts(lang) {
  return String(lang || "").toLowerCase().startsWith("sl")
    ? EDITOR_TEXTS.sl
    : EDITOR_TEXTS.en;
}

/**
 * Return the card options with their defaults.
 *
 * devices: the device IDs of the locations to show; empty means all.
 * daysAhead: show "next" outages that start up to this many days after
 * today; null means all. showEmpty: show the card when nothing is planned.
 * showEnded: show the outages that ended today.
 */
export function cardOptions(config = {}) {
  const days = Number(config.days_ahead);
  return {
    devices: Array.isArray(config.devices) ? config.devices.filter(Boolean) : [],
    daysAhead:
      config.days_ahead === undefined || config.days_ahead === null || config.days_ahead === "" ||
      !Number.isFinite(days) || days < 0
        ? null
        : Math.floor(days),
    showEmpty: config.show_empty === true,
    showEnded: config.show_ended !== false,
  };
}

function localDay(time) {
  const d = new Date(time);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

// True when the outage starts later than daysAhead days after today.
function beyond(item, daysAhead, now) {
  if (daysAhead === null || item.sort === UNKNOWN_SORT) return false;
  const start = Date.parse(item.sort ?? "");
  if (Number.isNaN(start)) return false;
  const days = Math.round((localDay(start) - localDay(now)) / 86400000);
  return days > daysAhead;
}

function itemsOf(attributes) {
  return Array.isArray(attributes.card) ? attributes.card : [];
}

function bySort(a, b) {
  const x = String(a.sort ?? "");
  const y = String(b.sort ?? "");
  return x < y ? -1 : x > y ? 1 : 0;
}

function fill(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (all, key) =>
    key in values ? String(values[key]) : all,
  );
}

/**
 * Return the text "ends in 1 h 12 min" for the end of a live outage.
 *
 * The integration gives the templates in card_labels. The text is empty when
 * the end or a template is missing, or when the end has passed.
 */
export function formatRemaining(end, now, labels) {
  const time = Date.parse(end ?? "");
  if (Number.isNaN(time) || !labels?.ends_in || !labels?.minutes) return "";
  const left = Math.ceil((time - now) / 60000);
  if (left <= 0) return "";
  const h = Math.floor(left / 60);
  const m = left % 60;
  let duration;
  if (h === 0) duration = fill(labels.minutes, { m });
  else if (m === 0 && labels.hours) duration = fill(labels.hours, { h });
  else duration = fill(labels.hours_minutes ?? labels.minutes, { h, m });
  return fill(labels.ends_in, { d: duration });
}

function banner(kind, item) {
  const location = item.location ?? "";
  const sub = item.detail ? `${location} · ${item.detail}` : location;
  return { kind, title: item.title ?? "", sub };
}

function liveBanner(item, labels, now) {
  if (!labels.now) return banner("live", item);
  const left = formatRemaining(item.end, now, labels) || item.detail || "";
  const span = item.span ?? "";
  return {
    kind: "live",
    title: `${labels.now} · ${item.location ?? ""}`,
    sub: span && left ? `${span} · ${left}` : span || left,
  };
}

function stamp(value) {
  const time = Date.parse(value ?? "");
  return Number.isNaN(time) ? null : time;
}

/**
 * Return the entity IDs of the integration that have card attributes.
 *
 * With a list of device IDs, return only the entities of those locations.
 */
export function cardEntities(states, entities, devices = []) {
  return Object.keys(entities ?? {})
    .filter((eid) => entities[eid]?.platform === PLATFORM)
    .filter((eid) => !devices.length || devices.includes(entities[eid]?.device_id))
    .filter((eid) => states?.[eid]?.attributes?.card !== undefined)
    .sort();
}

/**
 * Merge the card attributes of all locations into one render model.
 *
 * The banner shows the first live outage, or else the next outage.
 * Each other live outage has its own banner. The list shows the other
 * planned outages, grouped by day. The banner outage is not in the list.
 */
export function buildModel(states, entities, now = Date.now(), config = {}) {
  const options = cardOptions(config);
  const items = [];
  let problem = null;
  let labels = {};
  let footer = null;
  let oldest = null;
  for (const eid of cardEntities(states, entities, options.devices)) {
    const attributes = states[eid].attributes;
    items.push(
      ...itemsOf(attributes).filter(
        (i) =>
          (i.group !== "next" || !beyond(i, options.daysAhead, now)) &&
          (i.group !== "ended" || options.showEnded),
      ),
    );
    if (!problem && attributes.card_problem) {
      problem = {
        title: attributes.card_problem_title || attributes.card_problem,
        detail: attributes.card_problem_title
          ? attributes.card_problem_detail || ""
          : "",
      };
    }
    if (attributes.card_labels) labels = attributes.card_labels;
    if (attributes.card_footer) {
      const time = stamp(attributes.last_success);
      if (footer === null || (time !== null && (oldest === null || time < oldest))) {
        footer = attributes.card_footer;
        oldest = time;
      }
    }
  }

  const live = items.filter((i) => i.group === "live").sort(bySort);
  const next = items.filter((i) => i.group === "next").sort(bySort);
  const ended = items.filter((i) => i.group === "ended").sort(bySort);
  const nothing = items.length === 0 && !problem;
  const hidden = nothing && !options.showEmpty;

  const banners = live.map((i) => liveBanner(i, labels, now));
  if (!live.length && next.length) banners.push(banner("next", next[0]));
  const rest = live.length ? next : next.slice(1);

  const days = [];
  for (const i of rest) {
    const day = i.day ?? "";
    if (!days.length || days[days.length - 1].day !== day) {
      days.push({ day, rows: [] });
    }
    days[days.length - 1].rows.push({
      location: i.location ?? "",
      span: i.span ?? i.row ?? "",
      chip: i.chip ?? "",
    });
  }

  return {
    hidden,
    // With show_empty, the card says "No planned outages" instead of hiding.
    empty: nothing && options.showEmpty
      ? labels.nothing_planned || EDITOR_TEXTS.en.nothingPlanned
      : null,
    countdown: live.some((i) => i.end),
    problem,
    banners,
    planned: days.length ? { label: labels.also_planned ?? "", days } : null,
    ended: ended.length
      ? {
          label: labels.ended_today ?? "",
          rows: ended.map((i) => ({
            location: i.location ?? "",
            title: i.title ?? "",
          })),
        }
      : null,
    footer: hidden ? null : footer,
  };
}

const STYLE = `
  :host { display: block; }
  :host([hidden]) { display: none; }
  ha-card {
    display: block;
    overflow: hidden;
    color: var(--primary-text-color);
    background: var(--ha-card-background, var(--card-background-color));
  }
  .content { padding: 14px 16px; font-size: 14px; line-height: 1.35; }
  .banner {
    border-radius: calc(var(--ha-card-border-radius, 12px) - 2px);
    padding: 10px 12px;
    margin-bottom: 6px;
    font-weight: 600;
  }
  .banner small {
    display: block;
    font-size: 13px;
    font-weight: 400;
    opacity: 0.85;
    margin-top: 2px;
  }
  .banner.next {
    background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent);
    color: color-mix(
      in srgb, var(--warning-color, #ffa600) 70%, var(--primary-text-color)
    );
  }
  .banner.live { background: var(--error-color, #db4437); color: #fff; }
  .banner.problem {
    background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
    color: var(--primary-text-color);
    font-weight: 500;
  }
  .sec {
    font-size: 12px;
    color: var(--secondary-text-color);
    margin: 14px 0 2px;
    padding-top: 10px;
    border-top: 1px solid var(--divider-color);
  }
  .content > .sec:first-child,
  .content > .ended:first-child > .sec:first-child {
    margin-top: 0;
    padding-top: 0;
    border-top: 0;
  }
  .day {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--secondary-text-color);
    margin: 12px 0 6px;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 2px 10px;
    padding: 8px 10px;
    margin-bottom: 6px;
    border-radius: calc(var(--ha-card-border-radius, 12px) - 4px);
    background: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
  }
  .row .loc { grid-column: 1; grid-row: 1; font-weight: 600; }
  .row .time {
    grid-column: 1;
    grid-row: 2;
    white-space: nowrap;
    font-size: 13px;
    color: var(--secondary-text-color);
  }
  .row .chip { grid-column: 2; grid-row: 1 / span 2; align-self: center; }
  .chip {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
    background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent);
    color: color-mix(
      in srgb, var(--warning-color, #ffa600) 70%, var(--primary-text-color)
    );
  }
  .ended { font-size: 12px; color: var(--secondary-text-color); }
  .ended .sec { font-size: 11px; }
  .ended .done { margin-top: 4px; }
  .empty { color: var(--secondary-text-color); }
  .content > .empty + .footer { margin-top: 4px; }
  .footer { font-size: 12px; color: var(--secondary-text-color); margin-top: 10px; }
  .placeholder {
    padding: 16px;
    text-align: center;
    font-size: 13px;
    color: var(--secondary-text-color);
  }
`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderContent(model) {
  const content = el("div", "content");
  if (model.empty) content.append(el("div", "empty", model.empty));
  if (model.problem) {
    const node = el("div", "banner problem", `⚠ ${model.problem.title}`);
    if (model.problem.detail) node.append(el("small", "", model.problem.detail));
    content.append(node);
  }
  for (const b of model.banners) {
    const node = el("div", `banner ${b.kind}`);
    node.append(`${b.kind === "live" ? "🔌" : "⚡"} ${b.title}`);
    if (b.sub) node.append(el("small", "", b.sub));
    content.append(node);
  }
  if (model.planned) {
    content.append(el("div", "sec", model.planned.label));
    for (const day of model.planned.days) {
      content.append(el("div", "day", day.day));
      for (const r of day.rows) {
        const row = el("div", "row");
        row.append(el("span", "loc", r.location), el("span", "time", r.span));
        if (r.chip) row.append(el("span", "chip", r.chip));
        content.append(row);
      }
    }
  }
  if (model.ended) {
    const ended = el("div", "ended");
    ended.append(el("div", "sec", model.ended.label));
    for (const r of model.ended.rows) {
      ended.append(el("div", "done", `✓ ${r.location} · ${r.title}`));
    }
    content.append(ended);
  }
  if (model.footer) content.append(el("div", "footer", model.footer));
  return content;
}

function defineCard() {
  class ElektroCeljeCard extends HTMLElement {
    constructor() {
      super();
      this._config = {};
      this._hass = null;
      this._editMode = false;
      this._preview = false;
      this._entityIds = [];
      this._entitiesRef = null;
      this._seen = null;
      this._model = null;
      this._timer = null;
      this.attachShadow({ mode: "open" });
    }

    connectedCallback() {
      this._syncTimer();
    }

    disconnectedCallback() {
      this._stopTimer();
    }

    _stopTimer() {
      if (this._timer !== null) {
        clearInterval(this._timer);
        this._timer = null;
      }
    }

    // While a live outage shows, count down once a minute.
    _syncTimer() {
      const needed = Boolean(this._model?.countdown) && this.isConnected !== false;
      if (!needed) {
        this._stopTimer();
      } else if (this._timer === null) {
        this._timer = setInterval(() => this._tick(), 60000);
      }
    }

    _tick() {
      if (!this._hass) return;
      this._model = buildModel(this._hass.states, this._hass.entities, Date.now(), this._config);
      this._render();
    }

    static getStubConfig() {
      return {};
    }

    static getConfigElement() {
      return document.createElement(EDITOR_TYPE);
    }

    setConfig(config) {
      if (config?.devices !== undefined && !Array.isArray(config.devices)) {
        throw new Error("devices must be a list of device IDs");
      }
      this._config = { ...(config ?? {}) };
      this._seen = null;
      this._update();
    }

    set hass(hass) {
      this._hass = hass;
      this._update();
    }

    get hass() {
      return this._hass;
    }

    set editMode(value) {
      this._editMode = Boolean(value);
      this._seen = null;
      this._update();
    }

    get editMode() {
      return this._editMode;
    }

    set preview(value) {
      this._preview = Boolean(value);
      this._seen = null;
      this._update();
    }

    get preview() {
      return this._preview;
    }

    getCardSize() {
      const m = this._model;
      if (!m || m.hidden) return 1;
      let size = 1 + m.banners.length + (m.problem ? 1 : 0);
      for (const d of m.planned?.days ?? []) size += 1 + d.rows.length;
      if (m.ended) size += 1;
      return size;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 6 };
    }

    _states() {
      const hass = this._hass;
      if (hass.entities !== this._entitiesRef) {
        this._entitiesRef = hass.entities;
        this._entityIds = Object.keys(hass.entities ?? {}).filter(
          (eid) => hass.entities[eid]?.platform === PLATFORM,
        );
      }
      return this._entityIds.map((eid) => hass.states[eid]);
    }

    _update() {
      if (!this._hass) return;
      // A new state object means that the state or an attribute changed.
      const seen = this._states();
      if (
        this._seen &&
        seen.length === this._seen.length &&
        seen.every((s, n) => s === this._seen[n])
      ) {
        return;
      }
      this._seen = seen;
      this._model = buildModel(this._hass.states, this._hass.entities, Date.now(), this._config);
      this._render();
    }

    _render() {
      this._syncTimer();
      const model = this._model;
      const editing = this._editMode || this._preview;
      const hide = model.hidden && !editing;
      const root = this.shadowRoot;
      const style = el("style", "", STYLE);
      if (hide) {
        root.replaceChildren(style);
      } else {
        const card = el("ha-card");
        if (this._config.title) card.header = this._config.title;
        if (model.hidden) {
          card.append(el("div", "placeholder", "Elektro Celje: nothing planned"));
        } else {
          card.append(renderContent(model));
        }
        root.replaceChildren(style, card);
      }
      if (this.hidden !== hide) {
        this.hidden = hide;
        this.dispatchEvent(
          new CustomEvent("card-visibility-changed", {
            detail: { value: !hide },
            bubbles: true,
            composed: true,
          }),
        );
      }
    }
  }

  class ElektroCeljeCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = { ...(config ?? {}) };
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    _render() {
      if (!this._hass || !this._config) return;
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.schema = [
          {
            name: "devices",
            selector: { device: { integration: PLATFORM, multiple: true } },
          },
          { name: "title", selector: { text: {} } },
          {
            name: "days_ahead",
            selector: { number: { min: 0, max: 30, mode: "box" } },
          },
          { name: "show_empty", selector: { boolean: {} } },
          { name: "show_ended", selector: { boolean: {} } },
        ];
        this._form.addEventListener("value-changed", (ev) => {
          const config = { ...this._config, ...ev.detail.value };
          // Keep the YAML short: drop empty values and the defaults.
          for (const key of Object.keys(config)) {
            const value = config[key];
            if (
              value === undefined ||
              value === null ||
              value === "" ||
              (Array.isArray(value) && value.length === 0)
            ) {
              delete config[key];
            }
          }
          if (config.show_empty === false) delete config.show_empty;
          if (config.show_ended === true) delete config.show_ended;
          this._config = config;
          this.dispatchEvent(
            new CustomEvent("config-changed", {
              detail: { config },
              bubbles: true,
              composed: true,
            }),
          );
        });
        this.appendChild(this._form);
      }
      const t = editorTexts(this._hass.locale?.language || this._hass.language);
      this._form.computeLabel = (s) => t[s.name] || s.name;
      this._form.computeHelper = (s) => t[`${s.name}Help`] || "";
      this._form.hass = this._hass;
      this._form.data = { show_empty: false, show_ended: true, ...this._config };
    }
  }

  if (!customElements.get(CARD_TYPE)) {
    customElements.define(CARD_TYPE, ElektroCeljeCard);
  }
  if (!customElements.get(EDITOR_TYPE)) {
    customElements.define(EDITOR_TYPE, ElektroCeljeCardEditor);
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Elektro Celje outages",
      description:
        "Planned power outages of your Elektro Celje locations. " +
        "The card hides itself when nothing is planned.",
      preview: true,
    });
  }
}

if (typeof window !== "undefined" && typeof customElements !== "undefined") {
  defineCard();
}

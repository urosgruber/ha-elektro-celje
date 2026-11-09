// Render tests of the card with a very small fake DOM. No npm package needed.
import assert from "node:assert/strict";
import { test } from "node:test";

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.className = "";
    this._text = "";
  }
  append(...nodes) {
    for (const n of nodes) {
      this.children.push(typeof n === "string" ? new FakeText(n) : n);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  set textContent(value) {
    this.children = [];
    this._text = String(value);
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join("");
  }
  find(className) {
    const found = [];
    const walk = (n) => {
      if (n.className?.split(" ").includes(className)) found.push(n);
      (n.children ?? []).forEach(walk);
    };
    walk(this);
    return found;
  }
}

class FakeText {
  constructor(text) {
    this.textContent = text;
  }
}

const registry = new Map();
globalThis.window = globalThis;
globalThis.HTMLElement = class extends FakeNode {
  constructor() {
    super("host");
    this.hidden = false;
    this.events = [];
  }
  attachShadow() {
    this.shadowRoot = new FakeNode("#shadow");
    return this.shadowRoot;
  }
  dispatchEvent(event) {
    this.events.push(event);
  }
};
globalThis.customElements = {
  get: (name) => registry.get(name),
  define: (name, cls) => registry.set(name, cls),
};
globalThis.CustomEvent = class {
  constructor(type, init) {
    this.type = type;
    Object.assign(this, init);
  }
};
globalThis.document = { createElement: (tag) => new FakeNode(tag) };

await import("../../custom_components/elektro_celje/frontend/elektro-celje-card.js");
const Card = registry.get("elektro-celje-card");

function hass(card, problem = null) {
  const eid = "sensor.dom_planned_outages";
  return {
    states: {
      [eid]: {
        entity_id: eid,
        state: "1",
        attributes: {
          card,
          card_problem: problem,
          card_labels: { also_planned: "Also planned", ended_today: "Ended today" },
          card_footer: "Checked Mon 9 Nov 2026, 16:23 · elektro-celje.si",
          last_success: "2026-11-09T15:23:00+00:00",
        },
      },
    },
    entities: { [eid]: { entity_id: eid, platform: "elektro_celje" } },
  };
}

const NEXT = {
  location: "TP Zabukovica",
  group: "next",
  sort: "2026-11-10T07:30:00+00:00",
  title: "Tomorrow, Tue 10 Nov · 08:30–11:00",
  detail: "2 h 30 min · tomorrow",
  day: "Tue 10 Nov",
  span: "08:30–11:00 · 2 h 30 min",
  chip: "tomorrow",
};
const LATER = {
  ...NEXT,
  location: "TP Lopata",
  sort: "2026-11-12T07:00:00+00:00",
  day: "Thu 12 Nov",
  span: "08:00–14:00 · 6 h",
  chip: "in 3 days",
};

test("the card registers in the card picker", () => {
  assert.ok(Card);
  assert.deepEqual(Card.getStubConfig(), {});
  const entry = window.customCards.find((c) => c.type === "elektro-celje-card");
  assert.equal(entry.name, "Elektro Celje outages");
});

test("the card hides itself when nothing is planned", () => {
  const card = new Card();
  card.setConfig({});
  card.hass = hass([]);
  assert.equal(card.hidden, true);
  assert.equal(card.shadowRoot.find("content").length, 0);
  assert.equal(card.events.at(-1).type, "card-visibility-changed");
  assert.equal(card.getCardSize(), 1);
});

test("the card shows a placeholder in edit mode", () => {
  const card = new Card();
  card.setConfig({});
  card.hass = hass([]);
  card.editMode = true;
  assert.equal(card.hidden, false);
  const [placeholder] = card.shadowRoot.find("placeholder");
  assert.equal(placeholder.textContent, "Elektro Celje: nothing planned");
});

test("the card draws the banner, the day list, the chip and the footer", () => {
  const card = new Card();
  card.setConfig({ title: "Power" });
  card.hass = hass([NEXT, LATER]);
  const root = card.shadowRoot;
  assert.equal(card.hidden, false);
  const [banner] = root.find("banner");
  assert.equal(
    banner.textContent,
    "⚡ Tomorrow, Tue 10 Nov · 08:30–11:00TP Zabukovica · 2 h 30 min · tomorrow",
  );
  assert.equal(root.find("day")[0].textContent, "Thu 12 Nov");
  assert.equal(root.find("loc")[0].textContent, "TP Lopata");
  assert.equal(root.find("time")[0].textContent, "08:00–14:00 · 6 h");
  assert.equal(root.find("chip")[0].textContent, "in 3 days");
  assert.equal(root.find("footer")[0].textContent.startsWith("Checked"), true);
  const [haCard] = root.children.filter((c) => c.tagName === "ha-card");
  assert.equal(haCard.header, "Power");
});

test("feed text stays text", () => {
  const card = new Card();
  card.setConfig({});
  card.hass = hass([{ ...NEXT, location: "<img src=x onerror=alert(1)>" }]);
  const [banner] = card.shadowRoot.find("banner");
  assert.ok(banner.textContent.includes("<img src=x onerror=alert(1)>"));
});

test("the card renders again only when a state object changes", () => {
  const card = new Card();
  card.setConfig({});
  const h = hass([NEXT]);
  card.hass = h;
  const first = card.shadowRoot.children[1];
  card.hass = { ...h };
  assert.equal(card.shadowRoot.children[1], first);
  const changed = hass([LATER]);
  card.hass = { ...h, states: changed.states };
  assert.notEqual(card.shadowRoot.children[1], first);
});

test("one timer runs while a live outage shows, and it stops after", () => {
  const timers = new Set();
  let nextId = 1;
  const realSet = globalThis.setInterval;
  const realClear = globalThis.clearInterval;
  globalThis.setInterval = () => {
    const id = nextId++;
    timers.add(id);
    return id;
  };
  globalThis.clearInterval = (id) => timers.delete(id);
  try {
    const live = {
      ...NEXT,
      group: "live",
      title: "Outage now · 08:30–11:00",
      detail: "until 11:00",
      span: "08:30–11:00",
      chip: "",
      end: "2099-01-01T00:00:00+00:00",
    };
    const card = new Card();
    card.setConfig({});
    card.hass = hass([live]);
    card.hass = hass([live, LATER]);
    assert.equal(timers.size, 1);
    card.disconnectedCallback();
    assert.equal(timers.size, 0);
    card.connectedCallback();
    assert.equal(timers.size, 1);
    card.hass = hass([NEXT]);
    assert.equal(timers.size, 0);
  } finally {
    globalThis.setInterval = realSet;
    globalThis.clearInterval = realClear;
  }
});

test("the problem banner has a title and a small line", () => {
  const card = new Card();
  card.setConfig({});
  const h = hass([], "Cannot read the Elektro Celje feed. Old.");
  const attrs = h.states["sensor.dom_planned_outages"].attributes;
  attrs.card_problem_title = "Cannot read the Elektro Celje feed";
  attrs.card_problem_detail = "Last good check: today 12:23 · the list below may be old";
  card.hass = h;
  const [banner] = card.shadowRoot.find("problem");
  assert.equal(
    banner.textContent,
    "⚠ Cannot read the Elektro Celje feedLast good check: today 12:23 · the list below may be old",
  );
  assert.equal(banner.children.at(-1).tagName, "small");
});

// Tests of the render model of the Elektro Celje card. Run: node --test tests/js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { buildModel } from "../../custom_components/elektro_celje/frontend/elektro-celje-card.js";

const CARD_URL = new URL(
  "../../custom_components/elektro_celje/frontend/elektro-celje-card.js",
  import.meta.url,
);
const LABELS = { also_planned: "Also planned", ended_today: "Ended today" };

function item(location, group, sort, extra = {}) {
  return {
    location,
    group,
    sort,
    title: `${location} ${sort}`,
    detail: "",
    day: "Thu 12 Nov",
    row: "08:00–14:00 · 6 h · in 3 days",
    span: "08:00–14:00 · 6 h",
    chip: "in 3 days",
    ...extra,
  };
}

function hass(locations, extraStates = {}) {
  const states = { ...extraStates };
  const entities = {};
  locations.forEach((loc, n) => {
    const eid = `sensor.loc${n}_planned_outages`;
    states[eid] = {
      entity_id: eid,
      state: String(loc.card?.length ?? 0),
      attributes: {
        card: loc.card ?? [],
        card_footer: loc.footer ?? null,
        card_problem: loc.problem ?? null,
        card_labels: LABELS,
        last_success: loc.lastSuccess ?? null,
      },
    };
    entities[eid] = { entity_id: eid, platform: "elektro_celje" };
    // The other sensors of the location have no card attribute.
    const other = `sensor.loc${n}_last_checked`;
    states[other] = { entity_id: other, state: "x", attributes: {} };
    entities[other] = { entity_id: other, platform: "elektro_celje" };
  });
  return { states, entities };
}

test("hidden when there is no item and no problem", () => {
  const h = hass([{ card: [], footer: "Checked today" }]);
  const model = buildModel(h.states, h.entities);
  assert.equal(model.hidden, true);
});

test("hidden when no entity of the integration exists", () => {
  const model = buildModel({}, {});
  assert.equal(model.hidden, true);
});

test("ignores entities of other platforms", () => {
  const h = hass([]);
  h.states["sensor.other"] = {
    entity_id: "sensor.other",
    state: "1",
    attributes: { card: [item("X", "next", "2026-11-10")] },
  };
  h.entities["sensor.other"] = { entity_id: "sensor.other", platform: "template" };
  assert.equal(buildModel(h.states, h.entities).hidden, true);
});

test("the banner outage is not repeated in the list", () => {
  const h = hass([
    {
      card: [
        item("Dom", "next", "2026-11-12T07:00:00+00:00", { day: "Thu 12 Nov" }),
        item("Dom", "next", "2026-11-10T07:30:00+00:00", {
          title: "Tomorrow, Tue 10 Nov · 08:30–11:00",
          detail: "2 h 30 min · tomorrow",
          day: "Tue 10 Nov",
        }),
      ],
      footer: "Checked",
    },
  ]);
  const model = buildModel(h.states, h.entities);
  assert.equal(model.hidden, false);
  assert.deepEqual(model.banners, [
    {
      kind: "next",
      title: "Tomorrow, Tue 10 Nov · 08:30–11:00",
      sub: "Dom · 2 h 30 min · tomorrow",
    },
  ]);
  assert.equal(model.planned.label, "Also planned");
  assert.equal(model.planned.days.length, 1);
  assert.equal(model.planned.days[0].day, "Thu 12 Nov");
  assert.deepEqual(model.planned.days[0].rows, [
    { location: "Dom", span: "08:00–14:00 · 6 h", chip: "in 3 days" },
  ]);
});

test("one banner without a list when only one outage is planned", () => {
  const h = hass([{ card: [item("Dom", "next", "2026-11-10")] }]);
  const model = buildModel(h.states, h.entities);
  assert.equal(model.banners.length, 1);
  assert.equal(model.planned, null);
});

test("two live outages give two live banners, and all next go to the list", () => {
  const h = hass([
    {
      card: [
        item("Dom", "live", "2026-11-09T10:00:00+00:00", {
          title: "Outage now · 11:00–13:00",
          detail: "until 13:00",
        }),
        item("Dom", "next", "2026-11-12T07:00:00+00:00"),
      ],
    },
    {
      card: [
        item("Vikend", "live", "2026-11-09T09:00:00+00:00", {
          title: "Outage now · all day",
          detail: "",
        }),
      ],
    },
  ]);
  const model = buildModel(h.states, h.entities);
  assert.deepEqual(
    model.banners.map((b) => [b.kind, b.sub]),
    [
      ["live", "Vikend"],
      ["live", "Dom · until 13:00"],
    ],
  );
  assert.equal(model.planned.days[0].rows.length, 1);
});

test("the list groups the other outages by day, across locations, by sort", () => {
  const h = hass([
    {
      card: [
        item("Dom", "next", "2026-11-10T07:00:00+00:00", { day: "Tue 10 Nov" }),
        item("Dom", "next", "2026-11-13T07:00:00+00:00", { day: "Fri 13 Nov" }),
      ],
    },
    {
      card: [
        item("Vikend", "next", "2026-11-12T09:00:00+00:00", { day: "Thu 12 Nov" }),
        item("Vikend", "next", "2026-11-12T07:00:00+00:00", { day: "Thu 12 Nov" }),
      ],
    },
  ]);
  const model = buildModel(h.states, h.entities);
  assert.equal(model.banners[0].sub.startsWith("Dom"), true);
  assert.deepEqual(
    model.planned.days.map((d) => [d.day, d.rows.length]),
    [
      ["Thu 12 Nov", 2],
      ["Fri 13 Nov", 1],
    ],
  );
});

test("a row falls back to the row text when span is missing", () => {
  const old = item("Dom", "next", "2026-11-13");
  delete old.span;
  delete old.chip;
  const h = hass([{ card: [item("Dom", "next", "2026-11-10"), old] }]);
  const row = buildModel(h.states, h.entities).planned.days[0].rows[0];
  assert.deepEqual(row, {
    location: "Dom",
    span: "08:00–14:00 · 6 h · in 3 days",
    chip: "",
  });
});

test("ended today is a muted section, without a banner", () => {
  const h = hass([
    {
      card: [
        item("Dom", "ended", "2026-11-09T07:00:00+00:00", {
          title: "08:00–10:00 · ended",
        }),
      ],
      footer: "Checked",
    },
  ]);
  const model = buildModel(h.states, h.entities);
  assert.equal(model.hidden, false);
  assert.deepEqual(model.banners, []);
  assert.equal(model.planned, null);
  assert.deepEqual(model.ended, {
    label: "Ended today",
    rows: [{ location: "Dom", title: "08:00–10:00 · ended" }],
  });
  assert.equal(model.footer, "Checked");
});

test("a feed problem shows the card even without items", () => {
  const h = hass([{ card: [], problem: "Cannot read the Elektro Celje feed." }]);
  const model = buildModel(h.states, h.entities);
  assert.equal(model.hidden, false);
  assert.equal(model.problem, "Cannot read the Elektro Celje feed.");
  assert.deepEqual(model.banners, []);
});

test("the footer comes from the location with the oldest good check", () => {
  const h = hass([
    {
      card: [item("Dom", "next", "2026-11-10")],
      footer: "Checked new",
      lastSuccess: "2026-11-09T15:23:00+00:00",
    },
    {
      card: [],
      footer: "Checked old",
      lastSuccess: "2026-11-09T12:23:00+01:00",
    },
    { card: [], footer: null, lastSuccess: null },
  ]);
  assert.equal(buildModel(h.states, h.entities).footer, "Checked old");
});

test("the card never puts text into innerHTML", () => {
  const source = readFileSync(CARD_URL, "utf-8");
  assert.equal(source.includes("innerHTML"), false);
  assert.equal(source.includes("insertAdjacentHTML"), false);
});

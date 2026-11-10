// Tests of the card options. Run: node --test tests/js/*.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildModel,
  cardEntities,
  cardOptions,
} from "../../custom_components/elektro_celje/frontend/elektro-celje-card.js";

// Noon UTC is the same calendar day in UTC and in Central Europe.
const NOW = Date.parse("2026-11-10T12:00:00Z");
const LABELS = {
  also_planned: "Also planned",
  ended_today: "Ended today",
  nothing_planned: "Ni načrtovanih izklopov",
};

function outage(location, group, isoDay, extra = {}) {
  return {
    location,
    group,
    sort: `${isoDay}T12:00:00+00:00`,
    title: `${location} ${isoDay}`,
    detail: "",
    day: isoDay,
    span: "08:00–14:00",
    chip: "",
    ...extra,
  };
}

// Two locations, each one a device with one card sensor.
function hass(cards) {
  const states = {};
  const entities = {};
  Object.entries(cards).forEach(([device, card]) => {
    const eid = `sensor.${device}_planned_outages`;
    states[eid] = {
      entity_id: eid,
      state: String(card.length),
      attributes: {
        card,
        card_labels: LABELS,
        card_footer: `Checked · ${device}`,
        last_success: "2026-11-10T11:00:00+00:00",
      },
    };
    entities[eid] = { entity_id: eid, platform: "elektro_celje", device_id: device };
  });
  return { states, entities };
}

test("the options have defaults", () => {
  assert.deepEqual(cardOptions({}), {
    devices: [],
    daysAhead: null,
    showEmpty: false,
    showEnded: true,
  });
  assert.equal(cardOptions({ days_ahead: "7" }).daysAhead, 7);
  assert.equal(cardOptions({ days_ahead: -1 }).daysAhead, null);
  assert.equal(cardOptions({ days_ahead: "x" }).daysAhead, null);
  assert.equal(cardOptions({ days_ahead: 0 }).daysAhead, 0);
});

test("no devices means all locations", () => {
  const h = hass({ home: [], cottage: [] });
  assert.deepEqual(cardEntities(h.states, h.entities), [
    "sensor.cottage_planned_outages",
    "sensor.home_planned_outages",
  ]);
});

test("devices limit the card to those locations", () => {
  const h = hass({
    home: [outage("Home", "next", "2026-11-12")],
    cottage: [outage("Cottage", "next", "2026-11-11")],
  });
  const model = buildModel(h.states, h.entities, NOW, { devices: ["home"] });
  assert.equal(model.banners.length, 1);
  assert.match(model.banners[0].sub, /^Home/);
  assert.equal(model.planned, null);
  assert.equal(model.footer, "Checked · home");
});

test("days ahead drops later outages and keeps live and unknown ones", () => {
  const h = hass({
    home: [
      outage("Home", "live", "2026-11-03"),
      outage("Home", "next", "2026-11-10"),
      outage("Home", "next", "2026-11-13"),
      outage("Home", "next", "2026-11-14"),
      { ...outage("Home", "next", "x"), sort: "9999-12-31T00:00:00+00:00" },
    ],
  });
  const model = buildModel(h.states, h.entities, NOW, { days_ahead: 3 });
  const days = model.planned.days.map((d) => d.day);
  // Today and up to 3 days after today stay. The 14th is 4 days ahead.
  assert.deepEqual(days, ["2026-11-10", "2026-11-13", "x"]);
  assert.equal(model.banners[0].kind, "live");
});

test("days ahead 0 keeps today only", () => {
  const h = hass({
    home: [outage("Home", "next", "2026-11-10"), outage("Home", "next", "2026-11-11")],
  });
  const model = buildModel(h.states, h.entities, NOW, { days_ahead: 0 });
  assert.equal(model.banners.length, 1);
  assert.equal(model.planned, null);
});

test("the card hides when days ahead drops every outage", () => {
  const h = hass({ home: [outage("Home", "next", "2026-11-25")] });
  const model = buildModel(h.states, h.entities, NOW, { days_ahead: 7 });
  assert.equal(model.hidden, true);
});

test("show_ended false hides the ended section", () => {
  const h = hass({
    home: [outage("Home", "next", "2026-11-12"), outage("Home", "ended", "2026-11-10")],
  });
  assert.ok(buildModel(h.states, h.entities, NOW, {}).ended);
  assert.equal(buildModel(h.states, h.entities, NOW, { show_ended: false }).ended, null);
});

test("show_empty shows the label and the footer instead of hiding", () => {
  const h = hass({ home: [] });
  const hidden = buildModel(h.states, h.entities, NOW, {});
  assert.equal(hidden.hidden, true);
  assert.equal(hidden.empty, null);
  const shown = buildModel(h.states, h.entities, NOW, { show_empty: true });
  assert.equal(shown.hidden, false);
  assert.equal(shown.empty, "Ni načrtovanih izklopov");
  assert.equal(shown.footer, "Checked · home");
});

test("show_empty has an English text when the label is missing", () => {
  const model = buildModel({}, {}, NOW, { show_empty: true });
  assert.equal(model.empty, "No planned outages");
});

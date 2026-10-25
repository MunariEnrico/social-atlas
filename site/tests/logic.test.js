// Run: node --test site/tests/logic.test.js
const test = require("node:test");
const assert = require("node:assert");
const L = require("../assets/logic.js");

const ev = (o) => ({ id: o.id || Math.random().toString(36), title: o.title || "x", city: o.city || "paris", timezone: o.tz || "Europe/Paris", booking: {}, ...o });

test("local dates respect the event's timezone", () => {
  assert.deepStrictEqual(L.localParts("2026-11-01T03:30:00+00:00", "America/New_York"), { date: "2026-10-31", time: "23:30" });
  assert.deepStrictEqual(L.localParts("2026-11-20", "Europe/Paris"), { date: "2026-11-20", time: null });
});

test("long runs are kept off individual calendar days", () => {
  const show = ev({ start: "2026-05-09", end: "2026-11-22" });
  assert.strictEqual(L.eventDates(show).long, true);
  assert.strictEqual(L.occursOn(show, "2026-10-25"), false);
  assert.strictEqual(L.runningOn(show, "2026-10-25"), true);
  const fair = ev({ start: "2026-11-12", end: "2026-11-15" });
  assert.deepStrictEqual(L.eventDates(fair).dates, ["2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"]);
  const opera = ev({ start: "2026-11-13", end: "2026-11-22", occurrences: ["2026-11-13", "2026-11-17"] });
  assert.ok(L.occursOn(opera, "2026-11-17") && !L.occursOn(opera, "2026-11-16"));
});

test("month grid starts on Monday and covers the month", () => {
  const g = L.monthGrid(2026, 11);
  assert.strictEqual(g[0].date, "2026-10-26");
  assert.ok(g.some((c) => c.date === "2026-11-30" && c.inMonth));
  assert.strictEqual(g.length % 7, 0);
});

test("flight links: LUX and VCE departures, Cortina via Venice, same-city", () => {
  const p = L.flightLinks("LUX", "paris", "2026-11-12", "2026-11-15");
  assert.strictEqual(p.kind, "search_links");
  assert.ok(p.links.find((l) => l.provider === "Kayak").url.endsWith("/flights/LUX-PAR/2026-11-12/2026-11-15?sort=bestflight_a"));
  assert.ok(p.links.find((l) => l.provider === "Google Flights").url.includes(encodeURIComponent("from LUX to PAR on 2026-11-12 through 2026-11-15")));
  assert.ok(p.links.find((l) => l.provider === "Skyscanner").url.includes("/lux/cdg/261112/261115/"));
  assert.ok(p.rail, "rail alternative offered for Luxembourg–Paris");
  const v = L.flightLinks("VCE", "london", "2027-06-28");
  assert.ok(v.links[0].url.includes(encodeURIComponent("One way flights from VCE to LON on 2027-06-28")));
  assert.strictEqual(v.rail, null);
  const c = L.flightLinks("LUX", "cortina", "2027-01-14", "2027-01-18");
  assert.ok(c.links[0].url.includes("VCE") && c.ground.length && c.alternatives.length);
  const cv = L.flightLinks("VCE", "cortina", "2027-01-14");
  assert.strictEqual(cv.links.length, 0);
  assert.ok(cv.ground.length);
  assert.strictEqual(L.flightLinks("LUX", "luxembourg", "2026-11-01").links.length, 0);
  assert.strictEqual(L.flightLinks("VCE", "venice", "2026-11-01").links.length, 0);
});

test("itinerary conflicts use only published times", () => {
  const a = ev({ id: "a", title: "Dinner", start: "2026-11-13T19:00:00+01:00", end: "2026-11-13T22:00:00+01:00" });
  const b = ev({ id: "b", title: "Opera", start: "2026-11-13T20:00:00+01:00", end: "2026-11-13T23:00:00+01:00" });
  const c = ev({ id: "c", title: "Talk", start: "2026-11-14T10:00:00+01:00" });
  const d = ev({ id: "d", title: "Pop-up", start: "2026-11-14T11:30:00+01:00" });
  const e = ev({ id: "e", title: "Fair", start: "2026-11-14", all_day: true });
  const r = L.itineraryConflicts([a, b, c, d, e]);
  assert.deepStrictEqual(r.conflicts.map((x) => [x.a, x.b, x.type]), [["a", "b", "overlap"], ["c", "d", "possible"]]);
  assert.deepStrictEqual(r.untimed, [{ id: "e", reason: "time not published" }]);
});

test("filters: free, reservation, restricted access, date range", () => {
  const free = ev({ booking: { free: true, reservation: "unknown", access: "public" }, start: "2026-11-01" });
  const vip = ev({ booking: { free: false, reservation: "required", access: "invitation_only" }, start: "2026-12-01" });
  assert.ok(L.matchFilters(free, { price: "free" }) && !L.matchFilters(vip, { price: "free" }));
  assert.ok(L.matchFilters(vip, { reservation: "required" }) && !L.matchFilters(free, { reservation: "required" }));
  assert.ok(L.matchFilters(vip, { access: "restricted" }) && !L.matchFilters(free, { access: "restricted" }));
  assert.ok(L.matchFilters(free, { from: "2026-10-30", to: "2026-11-05" }) && !L.matchFilters(vip, { from: "2026-10-30", to: "2026-11-05" }));
});

test("trip suggestions mark unconfirmed dates as tentative", () => {
  const now = new Date("2026-10-25T12:00:00Z");
  const list = [
    ev({ id: "pp", city: "paris", start: "2026-11-12", end: "2026-11-15", trip_suitable: true, verification_status: "confirmed" }),
    ev({ id: "rg", city: "paris", start: "2027-05-23", end: "2027-06-06", trip_suitable: true, verification_status: "announced_pending" }),
    ev({ id: "nf", city: "paris", start: null, expected_window: { from: "2027-02-10", to: "2027-02-17" }, trip_suitable: true, verification_status: "expected" }),
    ev({ id: "old", city: "paris", start: "2026-09-01", end: "2026-09-03", trip_suitable: true, verification_status: "past" }),
  ];
  const s = L.tripSuggestions(list, "paris", now);
  assert.deepStrictEqual(s.map((x) => [x.event.id, x.tentative]), [["pp", false], ["nf", true], ["rg", true]]);
  assert.strictEqual(s[0].from, "2026-11-11");
  assert.strictEqual(s[0].to, "2026-11-16");
});

test("search finds events, sources and accounts", () => {
  const data = { events: [ev({ title: "Paris Photo", venue_name: "Grand Palais" })], signals: [], sources: [{ name: "Whitney", city: "nyc", type: "official_venue" }], accounts: [{ handle: "mustdonyc", city: "nyc", platform: "instagram" }] };
  assert.strictEqual(L.search(data, "grand palais").events.length, 1);
  assert.strictEqual(L.search(data, "whitney").sources.length, 1);
  assert.strictEqual(L.search(data, "mustdo").accounts.length, 1);
});

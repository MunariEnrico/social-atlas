/* SOCIAL ATLAS — pure logic shared by the browser app and the Node tests.
   No DOM access here. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.AtlasLogic = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const LABELS = {
    verification: {
      confirmed: "Confirmed",
      announced_pending: "Announced — verification pending",
      expected: "Expected — not confirmed",
      needs_review: "Needs manual review",
      postponed: "Postponed",
      cancelled: "Cancelled",
      past: "Past event",
    },
    reservation: { required: "Required", recommended: "Recommended", not_required: "Not required", unknown: "Unknown — needs verification" },
    registration: { required: "Required", optional: "Optional", not_required: "Not required", unknown: "Unknown — needs verification" },
    tickets: {
      ticketed: "Ticketed", free_registration: "Free registration", free_entry: "Free entry without registration",
      paid_reservation: "Paid reservation", available_verified: "Ticket availability verified",
      sold_out_verified: "Sold out — verified", not_on_sale_verified: "Not yet on sale — verified", unknown: "Availability unknown",
    },
    access: {
      public: "Public", public_ticketed: "Public, ticketed", invitation_only: "Invitation-only", members_only: "Members-only",
      industry_only: "Industry-only", restricted: "Restricted access", unknown: "Unknown — needs verification",
    },
    urgency: { act_now: "Act now", last_chance: "Last chance", book_soon: "Book soon", plan_ahead: "Plan ahead", monitor: "Monitor", information_pending: "Information pending", none: "" },
    radar: {
      just_discovered: "Just discovered", before_everyone_knows: "Before everyone knows", social_signals: "Social signals",
      last_minute: "Last-minute", worth_planning: "Worth planning for",
    },
    signal: { opening: "Opening", announcement: "Announcement", news: "News", retrospective: "Review / recap", submission: "Submitted URL" },
  };

  const CITY_ORDER = ["luxembourg", "venice", "cortina", "paris", "nyc", "london"];

  // ------------------------------------------------------------------ dates
  const isDateOnly = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);
  const fmtCache = {};
  function partsFmt(tz) {
    if (!fmtCache[tz]) {
      fmtCache[tz] = new Intl.DateTimeFormat("en-GB", {
        timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
      });
    }
    return fmtCache[tz];
  }
  /** {date:'YYYY-MM-DD', time:'HH:MM'|null} in timezone tz */
  function localParts(value, tz) {
    if (!value) return null;
    if (isDateOnly(value)) return { date: value, time: null };
    const d = value instanceof Date ? value : new Date(value);
    if (isNaN(d)) return null;
    const p = {};
    for (const x of partsFmt(tz || "UTC").formatToParts(d)) p[x.type] = x.value;
    const hour = p.hour === "24" ? "00" : p.hour;
    return { date: `${p.year}-${p.month}-${p.day}`, time: `${hour}:${p.minute}` };
  }
  const todayIn = (tz, now) => localParts(now || new Date(), tz).date;
  function addDays(dateStr, n) {
    const d = new Date(dateStr + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function daysBetween(a, b) {
    return Math.round((new Date(b + "T12:00:00Z") - new Date(a + "T12:00:00Z")) / 86400000);
  }
  function weekStart(dateStr) {
    const d = new Date(dateStr + "T12:00:00Z");
    const dow = (d.getUTCDay() + 6) % 7; // Monday = 0
    return addDays(dateStr, -dow);
  }
  /** local start/end dates of an event, in its own timezone */
  function eventSpan(ev) {
    const tz = ev.timezone || "UTC";
    const s = localParts(ev.start, tz);
    if (!s) return null;
    const e = localParts(ev.end, tz) || s;
    return { start: s.date, end: e.date < s.date ? s.date : e.date, startTime: s.time, endTime: localParts(ev.end, tz)?.time || null };
  }
  /** Which local dates does the event occur on? Long runs (>14 days) are "on view" spans. */
  function eventDates(ev) {
    const tz = ev.timezone || "UTC";
    if (ev.occurrences && ev.occurrences.length) {
      return { dates: ev.occurrences.map((o) => localParts(o, tz)?.date).filter(Boolean), long: false };
    }
    const sp = eventSpan(ev);
    if (!sp) return { dates: [], long: false };
    const len = daysBetween(sp.start, sp.end);
    if (len > 14) return { dates: [sp.start, sp.end], long: true, span: sp };
    const out = [];
    for (let i = 0; i <= len; i++) out.push(addDays(sp.start, i));
    return { dates: out, long: false };
  }
  function occursOn(ev, dateStr) {
    const ed = eventDates(ev);
    if (ed.long) return false;
    return ed.dates.includes(dateStr);
  }
  function runningOn(ev, dateStr) {
    const sp = eventSpan(ev);
    return !!(sp && sp.start <= dateStr && dateStr <= sp.end);
  }
  function inRange(ev, from, to) {
    const sp = eventSpan(ev);
    if (!sp) return false;
    return sp.start <= to && sp.end >= from;
  }
  function isPast(ev, now) {
    if (ev.verification_status === "past") return true;
    const sp = eventSpan(ev);
    if (!sp) return false;
    return sp.end < todayIn(ev.timezone || "UTC", now);
  }

  // ------------------------------------------------------------------ formatting
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  function fmtDay(dateStr, withYear) {
    const [y, m, d] = dateStr.split("-").map(Number);
    const wd = WEEKDAYS[(new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7];
    return `${wd} ${d} ${MONTHS[m - 1]}${withYear ? " " + y : ""}`;
  }
  function fmtWhen(ev, now) {
    const sp = eventSpan(ev);
    if (!sp) {
      if (ev.expected_window) return `Expected around ${fmtDay(ev.expected_window.from, true)} – ${fmtDay(ev.expected_window.to, true)} (estimate)`;
      return ev.end ? `Until ${fmtDay(localParts(ev.end, ev.timezone).date, true)} — start not announced` : "Date not announced";
    }
    const thisYear = todayIn(ev.timezone || "UTC", now).slice(0, 4);
    const showYear = sp.start.slice(0, 4) !== thisYear || sp.end.slice(0, 4) !== thisYear;
    let s = fmtDay(sp.start, showYear);
    if (sp.end !== sp.start) s += ` – ${fmtDay(sp.end, showYear)}`;
    if (sp.startTime && !ev.all_day) s += `, ${sp.startTime}` + (sp.endTime && sp.end === sp.start ? `–${sp.endTime}` : "");
    if (ev.occurrences && ev.occurrences.length > 1) s += ` (${ev.occurrences.length} dates)`;
    return s;
  }
  function fmtRelative(iso, now) {
    if (!iso) return "never";
    const ms = (now || new Date()) - new Date(iso);
    const m = Math.round(ms / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.round(m / 60);
    if (h < 36) return `${h} h ago`;
    return `${Math.round(h / 24)} days ago`;
  }
  function fmtStamp(iso, tz) {
    if (!iso) return "—";
    const p = localParts(iso, tz || "Europe/Luxembourg");
    return `${fmtDay(p.date, true)}, ${p.time}`;
  }

  // ------------------------------------------------------------------ filters & search
  const BOOKING_NEEDS = (b) => b.reservation === "required" || b.registration === "required" ||
    ["ticketed", "paid_reservation", "free_registration", "available_verified"].includes(b.tickets);
  function matchFilters(ev, f, now) {
    if (!f) return true;
    const b = ev.booking || {};
    if (f.city && f.city !== "all" && ev.city !== f.city) return false;
    if (f.category && f.category !== "all" && ev.category !== f.category) return false;
    if (f.verification && f.verification !== "all" && ev.verification_status !== f.verification) return false;
    if (f.price === "free" && b.free !== true) return false;
    if (f.price === "paid" && b.free !== false) return false;
    if (f.reservation === "required" && b.reservation !== "required") return false;
    if (f.registration === "required" && b.registration !== "required") return false;
    if (f.ticketing === "ticketed" && !["ticketed", "available_verified", "sold_out_verified", "not_on_sale_verified", "paid_reservation"].includes(b.tickets)) return false;
    if (f.ticketing === "unticketed" && !["free_entry"].includes(b.tickets)) return false;
    if (f.ticketing === "available" && b.tickets !== "available_verified") return false;
    if (f.access === "public" && !["public", "public_ticketed"].includes(b.access)) return false;
    if (f.access === "restricted" && !["invitation_only", "members_only", "industry_only", "restricted"].includes(b.access)) return false;
    if (f.official && !(ev.sources || []).some((s) => s.official)) return false;
    if (f.newly && !(ev.radar || []).includes("just_discovered")) return false;
    if (f.lastMinute && !(ev.radar || []).includes("last_minute")) return false;
    if (f.trip && !ev.trip_suitable) return false;
    if (f.urgency && f.urgency !== "all" && ev.urgency !== f.urgency) return false;
    if (f.neighborhood && f.neighborhood !== "all" && (ev.neighborhood || "") !== f.neighborhood) return false;
    if (f.from || f.to) {
      if (!eventSpan(ev)) return false;
      if (!inRange(ev, f.from || "0000-01-01", f.to || "9999-12-31")) return false;
    }
    if (f.discoveredWithin) {
      const d = new Date(ev.first_discovered_at);
      if ((now || new Date()) - d > f.discoveredWithin * 86400000) return false;
    }
    if (f.q && !textMatch(ev, f.q)) return false;
    return true;
  }
  function norm(s) {
    return (s || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }
  function textMatch(ev, q) {
    const hay = norm([ev.title, ev.venue_name, ev.neighborhood, ev.category, ev.subcategory, ev.description, (ev.tags || []).join(" "),
      (ev.sources || []).map((s) => s.name).join(" "), ev.city].join(" "));
    return norm(q).split(/\s+/).filter(Boolean).every((t) => hay.includes(t));
  }
  function search(data, q) {
    const nq = norm(q).trim();
    if (!nq) return { events: [], signals: [], sources: [], accounts: [] };
    const terms = nq.split(/\s+/);
    const has = (s) => { const h = norm(s); return terms.every((t) => h.includes(t)); };
    return {
      events: data.events.filter((e) => textMatch(e, q)).slice(0, 40),
      signals: data.signals.filter((s) => has(`${s.title} ${s.summary || ""} ${s.source_name} ${s.city || ""}`)).slice(0, 20),
      sources: data.sources.filter((s) => has(`${s.name} ${s.city} ${(s.categories || []).join(" ")} ${s.type}`)).slice(0, 20),
      accounts: data.accounts.filter((a) => has(`${a.handle} ${a.owner || ""} ${a.city} ${a.platform}`)).slice(0, 20),
    };
  }

  // ------------------------------------------------------------------ calendar grids
  function monthGrid(year, month /* 1-12 */) {
    const first = `${year}-${String(month).padStart(2, "0")}-01`;
    const start = weekStart(first);
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const d = addDays(start, i);
      cells.push({ date: d, inMonth: Number(d.slice(5, 7)) === month });
    }
    while (cells.length > 35 && cells.slice(-7).every((c) => !c.inMonth)) cells.splice(-7, 7);
    return cells;
  }

  // ------------------------------------------------------------------ trips
  const DEPARTURES = {
    LUX: { code: "LUX", name: "Luxembourg Airport", city: "luxembourg" },
    VCE: { code: "VCE", name: "Venice Marco Polo Airport", city: "venice" },
  };
  // Destination airports. `search` is the code used in flight searches (metro codes where
  // the search engines support them); alternatives are optional and explained.
  const DESTINATIONS = {
    luxembourg: { search: "LUX", label: "Luxembourg (LUX)" },
    venice: { search: "VCE", label: "Venice Marco Polo (VCE)", alternatives: [{ code: "TSF", why: "Treviso is about 40 km away and some low-cost routes only serve it" }] },
    cortina: {
      search: null, label: "No airport in Cortina",
      via: "VCE",
      alternatives: [
        { code: "TSF", why: "Treviso is a similar distance from Cortina as Venice" },
        { code: "INN", why: "Innsbruck can be closer from the north; mountain roads in winter can be slow" },
      ],
      ground: [
        { label: "Cortina Express (coach from Venice airport)", url: "https://www.cortinaexpress.it/" },
        { label: "Dolomiti Bus (regional buses)", url: "https://www.dolomitibus.it/" },
      ],
    },
    paris: { search: "PAR", skyscanner: "cdg", label: "Paris (CDG / ORY)", rail: { from: "luxembourg", label: "Direct trains Luxembourg ↔ Paris Est (SNCF Connect)", url: "https://www.sncf-connect.com/en-en/" } },
    nyc: { search: "NYC", skyscanner: "jfk", label: "New York (JFK / EWR / LGA)" },
    london: { search: "LON", skyscanner: "lhr", label: "London (LHR / LGW / LCY / STN / LTN)" },
  };
  function yymmdd(d) { return d.slice(2, 4) + d.slice(5, 7) + d.slice(8, 10); }
  /** Pre-filled search links. These are search links, not verified flight data. */
  function flightLinks(dep, destCity, out, back) {
    const d = DESTINATIONS[destCity];
    const res = { kind: "search_links", notes: [], links: [], alternatives: [], ground: [], rail: null };
    if (!d || !DEPARTURES[dep] || !out) return res;
    if (DEPARTURES[dep].city === destCity) {
      res.notes.push(`You are departing from ${DEPARTURES[dep].name} — no flight needed for ${destCity === "venice" ? "Venice" : "Luxembourg"}.`);
      return res;
    }
    let target = d.search;
    if (!target) {
      // Cortina: fly to Venice (unless already departing from there), then go by road
      res.ground = d.ground || [];
      if (dep === "VCE") {
        res.notes.push("Cortina has no airport. From Venice it is a road transfer — check the ground options below for current timetables.");
        return res;
      }
      target = d.via;
      res.notes.push("Cortina has no airport: these searches go to Venice Marco Polo (VCE), then continue by road.");
    }
    const sky = (d.skyscanner || target).toLowerCase();
    const q = back ? `Flights from ${dep} to ${target} on ${out} through ${back}` : `One way flights from ${dep} to ${target} on ${out}`;
    res.links.push({ provider: "Google Flights", url: "https://www.google.com/travel/flights?q=" + encodeURIComponent(q) + "&curr=EUR" });
    res.links.push({ provider: "Kayak", url: `https://www.kayak.com/flights/${dep}-${target}/${out}${back ? "/" + back : ""}?sort=bestflight_a` });
    res.links.push({ provider: "Skyscanner", url: `https://www.skyscanner.net/transport/flights/${dep.toLowerCase()}/${sky}/${yymmdd(out)}/${back ? yymmdd(back) + "/" : ""}` });
    for (const alt of d.alternatives || []) {
      if (alt.code === dep) continue;
      res.alternatives.push({
        code: alt.code, why: alt.why,
        url: "https://www.google.com/travel/flights?q=" + encodeURIComponent(back ? `Flights from ${dep} to ${alt.code} on ${out} through ${back}` : `One way flights from ${dep} to ${alt.code} on ${out}`),
      });
    }
    if (d.rail && DEPARTURES[dep].city === d.rail.from) res.rail = { label: d.rail.label, url: d.rail.url, why: "Optional alternative: city-centre to city-centre rail can compete with flying on this route." };
    return res;
  }

  /** Overlap detection for an itinerary. Only times that are actually published are used. */
  function itineraryConflicts(items) {
    const timed = [], untimed = [];
    for (const it of items) {
      const sp = eventSpan(it);
      if (!sp) { untimed.push({ id: it.id, reason: "date not confirmed" }); continue; }
      if (it.all_day || !sp.startTime) { untimed.push({ id: it.id, reason: "time not published" }); continue; }
      const start = new Date(it.start).getTime();
      const end = it.end && !isDateOnly(it.end) ? new Date(it.end).getTime() : null;
      timed.push({ id: it.id, title: it.title, start, end, day: sp.start });
    }
    timed.sort((a, b) => a.start - b.start);
    const conflicts = [];
    for (let i = 0; i < timed.length; i++) {
      for (let j = i + 1; j < timed.length; j++) {
        const a = timed[i], b = timed[j];
        if (a.day !== b.day && (!a.end || a.end < b.start)) continue;
        if (a.end && b.start < a.end) conflicts.push({ a: a.id, b: b.id, type: "overlap", message: `${a.title} and ${b.title} overlap` });
        else if (!a.end && b.start - a.start < 3 * 3600000) conflicts.push({ a: a.id, b: b.id, type: "possible", message: `${a.title} has no published end time and ${b.title} starts within 3 hours` });
      }
    }
    return { conflicts, untimed };
  }

  /** Suggest travel windows around trip-worthy events in a city. */
  function tripSuggestions(events, city, now, limit) {
    const today = todayIn("Europe/Luxembourg", now);
    const pool = events.filter((e) => e.city === city && e.trip_suitable && !["past", "cancelled"].includes(e.verification_status));
    const out = [];
    for (const e of pool) {
      const sp = eventSpan(e);
      if (sp && sp.end < today) continue;
      let from, to, tentative = e.verification_status !== "confirmed";
      if (sp) {
        const long = daysBetween(sp.start, sp.end) > 7;
        if (long) {
          const anchor = sp.start > today ? sp.start : (daysBetween(today, sp.end) > 10 ? addDays(today, 7) : sp.end);
          from = sp.start > today ? addDays(sp.start, -1) : addDays(anchor, -2);
          to = sp.start > today ? addDays(sp.start, 2) : addDays(anchor, 1);
          if (to > addDays(sp.end, 1)) to = addDays(sp.end, 1);
        } else {
          from = addDays(sp.start, -1);
          to = addDays(sp.end, 1);
        }
        if (from < today) from = today;
      } else if (e.expected_window) {
        from = addDays(e.expected_window.from, -1); to = addDays(e.expected_window.to, 1); tentative = true;
      } else continue;
      out.push({ event: e, from, to, nights: Math.max(1, daysBetween(from, to)), tentative,
        why: e.description || e.title, score: (e.scores?.relevance || 0) - (tentative ? 15 : 0) });
    }
    out.sort((a, b) => a.from.localeCompare(b.from));
    return limit ? out.slice(0, limit) : out;
  }

  // ------------------------------------------------------------------ my events
  const COLLECTIONS = { saved: "Saved", must: "Must attend", tobook: "To book", booked: "Booked" };
  function collectionOf(entry, ev, now) {
    if (ev && isPast(ev, now)) return "past";
    return entry.status || "saved";
  }

  return {
    LABELS, CITY_ORDER, COLLECTIONS, DEPARTURES, DESTINATIONS, MONTHS, MONTHS_LONG, WEEKDAYS,
    isDateOnly, localParts, todayIn, addDays, daysBetween, weekStart, eventSpan, eventDates, occursOn, runningOn, inRange, isPast,
    fmtDay, fmtWhen, fmtRelative, fmtStamp, matchFilters, textMatch, search, monthGrid, flightLinks, itineraryConflicts,
    tripSuggestions, collectionOf, BOOKING_NEEDS, norm,
  };
});

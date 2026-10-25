/* SOCIAL ATLAS — static single-page app. Reads the pipeline's JSON; keeps personal
   selections (My Events, trips) in this browser only. */
(() => {
  "use strict";
  const L = window.AtlasLogic;
  const CFG = window.ATLAS_CONFIG || {};
  const HOME_TZ = CFG.homeTimezone || "Europe/Luxembourg";
  const $main = document.getElementById("main");
  const $overlay = document.getElementById("overlay");

  // ------------------------------------------------------------------ utils
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
  const link = (u, text, cls) => (safeUrl(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer"${cls ? ` class="${cls}"` : ""}>${esc(text)}</a>` : esc(text));
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };
  const now = () => new Date();
  const store = {
    get(key, dflt) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : dflt; } catch { return dflt; } },
    set(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); return true; } catch { return false; } },
  };
  let toastTimer;
  function toast(msg) {
    let t = document.querySelector(".toast");
    if (!t) { t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), 2600);
  }

  // ------------------------------------------------------------------ state
  const S = {
    data: null,
    my: store.get("atlas.my.v1", {}),
    trips: store.get("atlas.trips.v1", []),
    storageOk: store.set("atlas.probe", 1),
    radarTab: "just_discovered",
    filters: {},
  };
  const saveMy = () => store.set("atlas.my.v1", S.my);
  const saveTrips = () => store.set("atlas.trips.v1", S.trips);

  async function loadData() {
    if (window.ATLAS_EMBEDDED) return window.ATLAS_EMBEDDED;
    const base = CFG.dataPath || "data/";
    const names = ["meta", "events", "signals", "sources", "runs", "briefing", "archive"];
    const out = {};
    await Promise.all(names.map(async (n) => {
      try {
        const r = await fetch(`${base}${n}.json`, { cache: "no-cache" });
        out[n] = r.ok ? await r.json() : null;
      } catch { out[n] = null; }
    }));
    return out;
  }
  function prepare(raw) {
    const d = {
      meta: raw.meta || { cities: {}, city_order: L.CITY_ORDER, categories: {} },
      events: raw.events || [],
      signals: raw.signals || [],
      sources: (raw.sources && raw.sources.sources) || [],
      accounts: (raw.sources && raw.sources.accounts) || [],
      runs: raw.runs || [],
      briefing: raw.briefing,
      archive: raw.archive || [],
      missing: Object.entries(raw).filter(([, v]) => v == null).map(([k]) => k),
    };
    d.byId = Object.fromEntries(d.events.map((e) => [e.id, e]));
    for (const a of d.archive) if (!d.byId[a.id]) d.byId[a.id] = { ...a, booking: {}, archived: true };
    d.cityName = (c) => (d.meta.cities[c] && d.meta.cities[c].name) || ({ multi: "Multi-city" }[c] || c || "—");
    d.catName = (c) => d.meta.categories[c] || c || "—";
    d.live = d.events.filter((e) => !["past", "cancelled"].includes(e.verification_status));
    return d;
  }

  // ------------------------------------------------------------------ routing
  function parseRoute() {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, qs] = h.split("?");
    const parts = path.split("/").filter(Boolean);
    return { page: parts[0] || "overview", arg: parts[1] || null, q: Object.fromEntries(new URLSearchParams(qs || "")) };
  }
  function go(page, arg, q) {
    const qs = q && Object.keys(q).length ? "?" + new URLSearchParams(q).toString() : "";
    location.hash = `#/${page === "overview" ? "" : page}${arg ? "/" + arg : ""}${qs}`;
  }
  function setQuery(patch) {
    const r = parseRoute();
    const q = { ...r.q, ...patch };
    for (const k of Object.keys(q)) if (q[k] === "" || q[k] == null) delete q[k];
    go(r.page, r.arg, q);
  }

  // ------------------------------------------------------------------ components
  const V = L.LABELS;
  function chipVerification(ev) {
    const v = ev.verification_status || "needs_review";
    return `<span class="chip v-${esc(v)}" title="Verification status">${esc(V.verification[v] || v)}</span>`;
  }
  function chipsBooking(ev, compact) {
    const b = ev.booking || {};
    const out = [];
    if (b.tickets === "sold_out_verified") out.push(`<span class="chip soldout">Sold out — verified</span>`);
    if (b.reservation === "required") out.push(`<span class="chip need">Reservation required</span>`);
    else if (b.reservation === "recommended") out.push(`<span class="chip need">Reservation recommended</span>`);
    if (b.registration === "required") out.push(`<span class="chip need">Registration required</span>`);
    if (["invitation_only", "members_only", "industry_only", "restricted"].includes(b.access)) out.push(`<span class="chip need">${esc(V.access[b.access])}</span>`);
    if (b.tickets === "available_verified") out.push(`<span class="chip free">Tickets available (as of check)</span>`);
    else if (b.tickets === "not_on_sale_verified") out.push(`<span class="chip">Not yet on sale</span>`);
    else if (["ticketed", "paid_reservation"].includes(b.tickets)) out.push(`<span class="chip">${esc(V.tickets[b.tickets])}</span>`);
    if (b.free === true) out.push(`<span class="chip free">Free</span>`);
    else if (b.price && b.price.display && !compact) out.push(`<span class="chip">${esc(b.price.display)}</span>`);
    if (!out.length) out.push(`<span class="chip unknown">Booking requirements unverified</span>`);
    return out.join("");
  }
  function chipUrgency(ev) {
    const u = ev.urgency;
    return u && V.urgency[u] && !["monitor", "information_pending"].includes(u) ? `<span class="chip u-${esc(u)}">${esc(V.urgency[u])}</span>` : "";
  }
  function dateBlock(ev) {
    const sp = L.eventSpan(ev);
    if (!sp) return `<div class="date"><span class="tbd">TBA</span></div>`;
    const today = L.todayIn(ev.timezone || HOME_TZ);
    const running = sp.start < today && sp.end >= today;
    const shown = running ? sp.end : sp.start;
    const [, m, d] = shown.split("-").map(Number);
    return `<div class="date" aria-hidden="true">${running ? `<span class="m" style="margin:0 0 3px">until</span>` : ""}<span class="d">${d}</span><span class="m">${L.MONTHS[m - 1]}</span></div>`;
  }
  function savedBtn(ev) {
    const on = !!S.my[ev.id];
    return `<button class="icon-btn" type="button" data-save="${esc(ev.id)}" aria-pressed="${on}" title="${on ? "Saved — open to change" : "Save to My events"}">${on ? "Saved" : "Save"}</button>`;
  }
  function evRow(ev, opts = {}) {
    if (!ev) return "";
    const where = [...new Set([ev.venue_name, ev.neighborhood, opts.showCity === false ? null : S.data.cityName(ev.city)].filter(Boolean))].join(", ");
    const sp = L.eventSpan(ev);
    const runningNote = sp && sp.end > sp.start && L.daysBetween(sp.start, sp.end) > 14 ? ` — on until ${L.fmtDay(sp.end)}` : "";
    return `<article class="ev" data-ev="${esc(ev.id)}">
      ${dateBlock(ev)}
      <div>
        <h3><a href="#" data-open="${esc(ev.id)}">${esc(ev.title)}</a></h3>
        <div class="meta">${esc(L.fmtWhen(ev))}${esc(runningNote)}${where ? `<br>${esc(where)}` : ""}</div>
        ${opts.why ? `<div class="why">${esc(opts.why)}</div>` : ""}
        <div class="chips">${chipUrgency(ev)}${chipVerification(ev)}${chipsBooking(ev, true)}</div>
      </div>
      <div class="act">${savedBtn(ev)}</div>
    </article>`;
  }
  function evList(list, empty, opts) {
    if (!list.length) return `<div class="empty">${empty}</div>`;
    return `<div class="ev-list">${list.map((e) => evRow(e, opts)).join("")}</div>`;
  }
  function signalRow(s) {
    const linked = s.linked_event_id && S.data.byId[s.linked_event_id];
    const confirms = [
      V.signal[s.signal_type] || s.signal_type,
      s.mentioned_dates && s.mentioned_dates.length ? `mentions ${s.mentioned_dates.map((d) => L.fmtDay(d)).join(", ")} (unverified)` : "no event date stated",
    ].join("; ");
    return `<div class="signal">
      <a class="t" href="${esc(safeUrl(s.url) || "#")}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
      <div class="meta">${esc(s.source_name)}${s.via ? ` via ${esc(s.via)}` : ""}, ${esc(S.data.cityName(s.city))}${s.published_at ? `, published ${esc(L.fmtDay(L.localParts(s.published_at, HOME_TZ).date))}` : ""}, found ${esc(L.fmtRelative(s.discovered_at))}</div>
      <div class="confirms">What it confirms: ${esc(confirms)}.
        ${linked ? `Matches <a href="#" data-open="${esc(linked.id)}">${esc(linked.title)}</a> (${esc(V.verification[linked.verification_status] || "")}).` : "Not independently verified."}</div>
    </div>`;
  }
  function sectionHead(title, desc, more) {
    return `<div class="section-head"><div><h2>${esc(title)}</h2>${desc ? `<p>${desc}</p>` : ""}</div>${more || ""}</div>`;
  }
  const sortByStart = (a, b) => (a.start || "9999").localeCompare(b.start || "9999");
  const byRel = (a, b) => (b.scores?.relevance || 0) - (a.scores?.relevance || 0);

  // ------------------------------------------------------------------ chrome
  function renderChrome(route) {
    document.querySelectorAll(".nav a").forEach((a) => a.toggleAttribute("aria-current", false));
    const nav = document.querySelector(`.nav a[data-nav="${route.page === "event" ? "overview" : route.page}"]`);
    if (nav) nav.setAttribute("aria-current", "page");
    const strip = document.getElementById("city-strip");
    strip.innerHTML = (S.data.meta.city_order || L.CITY_ORDER)
      .map((c) => `<a href="#/city/${c}"${route.page === "city" && route.arg === c ? ' aria-current="page"' : ""}>${esc(S.data.cityName(c))}</a>`).join("");
    const m = S.data.meta;
    const ok = m.last_successful_run;
    document.getElementById("footer").innerHTML = `
      <span>Data generated ${esc(L.fmtStamp(m.generated_at, HOME_TZ))} (${esc(HOME_TZ)}). Last successful collection: ${ok ? esc(L.fmtRelative(ok.finished_at)) : "none recorded yet"}.</span>
      <span>Personal selections are stored in this browser only${S.storageOk ? "" : " — storage is unavailable here, so they will not persist"}.</span>`;
  }

  // ------------------------------------------------------------------ pages
  function pageOverview() {
    const d = S.data;
    const m = d.meta;
    const last = m.last_run, ok = m.last_successful_run;
    const fresh = ok
      ? `<span class="${last && last.status === "failed" ? "bad" : "ok"}">${last && last.status === "failed" ? "Latest collection failed" : "Collection running normally"}</span>
         <span>Last successful collection ${esc(L.fmtRelative(ok.finished_at))} — ${esc(ok.sources_ok)} of ${esc(ok.sources_attempted)} sources answered.</span>`
      : `<span class="bad">No successful collection recorded yet</span>`;
    const band = (m.city_order || L.CITY_ORDER).map((c) => {
      const tz = m.cities[c]?.tz || "UTC";
      const t = L.localParts(now(), tz);
      const today = t.date;
      const todayN = d.live.filter((e) => e.city === c && (L.occursOn(e, today))).length;
      const week = d.live.filter((e) => e.city === c && L.inRange(e, today, L.addDays(today, 6)) && !L.eventDates(e).long).length;
      const next = d.live.filter((e) => e.city === c && L.eventSpan(e) && L.eventSpan(e).start >= today && !L.eventDates(e).long).sort(sortByStart)[0];
      const hr = Number(t.time.slice(0, 2));
      return `<a href="#/city/${c}">
        <span class="bc-name">${esc(d.cityName(c))}</span>
        <span class="bc-time${hr < 7 || hr >= 23 ? " bc-night" : ""}">${esc(t.time)}</span>
        <span class="bc-zone">${esc(L.fmtDay(today))}</span>
        <span class="bc-today">${todayN ? `${todayN} today, ` : "Nothing listed today, "}${week} this week</span>
        ${next ? `<span class="bc-next">Next: ${esc(next.title)}</span>` : ""}
      </a>`;
    }).join("");

    const homeToday = L.todayIn(HOME_TZ);
    const b = d.briefing;
    const todayItems = b && b.date === homeToday ? b.sections.top_today.map((i) => d.byId[i.event_id]).filter(Boolean) :
      d.live.filter((e) => L.occursOn(e, L.todayIn(e.timezone))).sort(byRel).slice(0, 6);
    const radar = d.live.filter((e) => (e.radar || []).some((r) => ["just_discovered", "before_everyone_knows"].includes(r))).sort((a, b2) => b2.scores.insider - a.scores.insider).slice(0, 4);
    const openingsSig = d.signals.filter((s) => s.signal_type === "opening").slice(0, 8);
    const weekEnd = L.addDays(homeToday, 7);
    const weekByCity = (m.city_order || L.CITY_ORDER).map((c) => {
      const list = d.live.filter((e) => e.city === c && L.eventSpan(e) && L.eventSpan(e).start > homeToday && L.eventSpan(e).start <= weekEnd).sort(byRel).slice(0, 3);
      return list.length ? `<div><h3 class="small muted" style="margin:6px 0 2px;font-weight:600">${esc(d.cityName(c))}</h3>${evList(list, "", { showCity: false })}</div>` : "";
    }).join("");
    const planning = d.live.filter((e) => (e.radar || []).includes("worth_planning")).sort(sortByStart).slice(0, 6);
    const alerts = d.live.filter((e) => ["act_now", "book_soon"].includes(e.urgency)).sort(sortByStart).slice(0, 6);
    const failing = d.sources.filter((s) => s.state && s.state.last_status === "failed");
    return `
      <section class="hero">
        <div><h1>What's on, what's next, what to book.</h1></div>
        <div><p>Six cities, checked every day against venues, institutions, local press and public news. Every listing shows where it came from and what you need to get in.</p>
        <div class="freshness" style="margin-top:12px">${fresh} <a href="#/health">System health</a></div></div>
      </section>
      <h2 class="visually-hidden">City snapshot</h2>
      <nav class="band" aria-label="City snapshot">${band}</nav>

      <section class="section">${sectionHead("Today's highlights", "Happening today in each city's local time, ranked by relevance.", `<a class="more" href="#/briefing">Daily briefing</a>`)}
        ${evList(todayItems, "<strong>Nothing listed for today yet.</strong> The briefing fills in as soon as a collection run finds events dated today.")}</section>

      <div class="cols">
        <section class="section">${sectionHead("The Insider Radar", "Recent discoveries with little coverage so far.", `<a class="more" href="#/radar">Open the radar</a>`)}
          ${evList(radar, "No early discoveries right now.")}</section>
        <section class="section">${sectionHead("New openings", "Restaurants, bars, galleries and venues reported as opening. Leads from press — not verified events.")}
          ${openingsSig.length ? openingsSig.map(signalRow).join("") : `<div class="empty">No openings reported in the monitored press this week.</div>`}</section>
      </div>

      <section class="section">${sectionHead("This week across cities", "The strongest listings in the next seven days.")}
        ${weekByCity ? `<div class="cols">${weekByCity}</div>` : `<div class="empty">No listings in the next seven days.</div>`}</section>

      <div class="cols">
        <section class="section">${sectionHead("Booking alerts", "Upcoming events where acting soon matters: tickets, reservations or registration.")}
          ${evList(alerts, "No time-sensitive bookings right now.")}</section>
        <section class="section">${sectionHead("Worth planning for", "Events worth building a trip around.", `<a class="more" href="#/trips">Trip planner</a>`)}
          ${evList(planning, "Nothing flagged for trip planning yet.")}</section>
      </div>

      <section class="section">${sectionHead("Discovery health", "What the last collection actually did.", `<a class="more" href="#/health">Details</a>`)}
        <div class="stats">
          <div class="stat"><div class="k">Last successful run</div><div class="v">${ok ? esc(L.fmtRelative(ok.finished_at)) : "—"}</div></div>
          <div class="stat"><div class="k">Sources answering</div><div class="v">${ok ? `${esc(ok.sources_ok)}/${esc(ok.sources_attempted)}` : "—"}</div></div>
          <div class="stat"><div class="k">Sources failing now</div><div class="v ${failing.length ? "bad" : ""}">${failing.length}</div></div>
          <div class="stat"><div class="k">Upcoming events stored</div><div class="v">${d.live.length}</div></div>
          <div class="stat"><div class="k">Press &amp; social leads (45 days)</div><div class="v">${d.signals.length}</div></div>
        </div></section>`;
  }

  // ---------------- filters UI shared by radar & city pages
  function filterBar(f, opts) {
    const d = S.data;
    const sel = (key, label, options) => `<label>${label}<select data-filter="${key}">${options.map(([v, t]) => `<option value="${esc(v)}"${(f[key] || "all") === v ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
    const cats = [["all", "All"], ...Object.entries(d.meta.categories)];
    const ver = [["all", "Any"], ...Object.entries(V.verification).filter(([k]) => k !== "past")];
    const neigh = opts.neighborhoods ? [["all", "Any"], ...opts.neighborhoods.map((n) => [n, n])] : null;
    const cb = (key, label) => `<label><input type="checkbox" data-filter="${key}"${f[key] ? " checked" : ""}> ${label}</label>`;
    return `<div class="filters" role="group" aria-label="Filters">
      ${opts.city ? sel("city", "City", [["all", "All"], ...(d.meta.city_order || []).map((c) => [c, d.cityName(c)])]) : ""}
      ${sel("category", "Category", cats)}
      ${neigh ? sel("neighborhood", "Area", neigh) : ""}
      <label>From <input type="date" data-filter="from" value="${esc(f.from || "")}"></label>
      <label>To <input type="date" data-filter="to" value="${esc(f.to || "")}"></label>
      ${sel("price", "Price", [["all", "Any"], ["free", "Free"], ["paid", "Paid"]])}
      ${sel("ticketing", "Tickets", [["all", "Any"], ["ticketed", "Ticketed"], ["unticketed", "Free entry"], ["available", "Availability verified"]])}
      ${sel("access", "Access", [["all", "Any"], ["public", "Public"], ["restricted", "Restricted"]])}
      ${sel("verification", "Status", ver)}
      ${sel("urgency", "Time", [["all", "Any"], ["act_now", "Act now"], ["book_soon", "Book soon"], ["plan_ahead", "Plan ahead"]])}
      ${cb("reservationReq", "Reservation required")}
      ${cb("registrationReq", "Registration required")}
      ${cb("official", "Official source")}
      ${opts.extra ? cb("newly", "Newly discovered") + cb("lastMinute", "Last-minute") + cb("trip", "Trip-worthy") : ""}
      <button class="btn ghost small reset" type="button" data-filter-reset>Clear filters</button>
    </div>`;
  }
  function filtersFromQuery(q) {
    return {
      city: q.city, category: q.category, neighborhood: q.neighborhood, from: q.from, to: q.to, price: q.price, ticketing: q.ticketing,
      access: q.access, verification: q.verification, urgency: q.urgency, official: q.official === "1",
      reservation: q.reservationReq === "1" ? "required" : null, registration: q.registrationReq === "1" ? "required" : null,
      newly: q.newly === "1", lastMinute: q.lastMinute === "1", trip: q.trip === "1",
      reservationReq: q.reservationReq === "1", registrationReq: q.registrationReq === "1",
    };
  }

  function pageRadar(route) {
    const d = S.data;
    const tab = route.q.tab || "just_discovered";
    const f = filtersFromQuery(route.q);
    const discWithin = route.q.disc ? Number(route.q.disc) : null;
    const pick = (bucket) => d.live.filter((e) => (e.radar || []).includes(bucket) && L.matchFilters(e, { ...f, discoveredWithin: discWithin }));
    const sigs = d.signals.filter((s) => ["opening", "announcement", "submission"].includes(s.signal_type) &&
      (!f.city || f.city === "all" || s.city === f.city) && (!f.category || f.category === "all" || s.category === f.category));
    const counts = {
      just_discovered: pick("just_discovered").length, before_everyone_knows: pick("before_everyone_knows").length,
      social_signals: sigs.length, last_minute: pick("last_minute").length, worth_planning: pick("worth_planning").length,
    };
    const desc = {
      just_discovered: "Found by the pipeline in the last three days, newest first. Researched marquee events are excluded.",
      before_everyone_knows: "Early discoveries with limited coverage detected: one monitored source so far, plus a niche or limited format. This is a heuristic about our own coverage — not proof that something is exclusive.",
      social_signals: "Public posts and articles announcing openings, pop-ups and launches. Each lead says what it actually confirms and whether we could match it to a verified listing.",
      last_minute: "Starting within three days, or in its final week. Ticket availability is only shown when an official source states it.",
      worth_planning: "Future events worth a trip. Unannounced editions are labelled expected, with estimated windows.",
    }[tab];
    let body;
    if (tab === "social_signals") {
      const byType = (t) => sigs.filter((s) => s.signal_type === t);
      body = `<div class="cols"><div><h3 class="small" style="font-weight:700;margin-bottom:6px">Openings</h3>${byType("opening").slice(0, 40).map(signalRow).join("") || `<div class="empty">No opening reports.</div>`}</div>
        <div><h3 class="small" style="font-weight:700;margin-bottom:6px">Announcements, pop-ups and submissions</h3>${[...byType("announcement"), ...byType("submission")].slice(0, 40).map(signalRow).join("") || `<div class="empty">No announcements.</div>`}</div></div>`;
    } else {
      let list = pick(tab);
      if (tab === "just_discovered") list.sort((a, b) => (b.first_discovered_at || "").localeCompare(a.first_discovered_at || "") || byRel(a, b));
      else if (tab === "before_everyone_knows") list.sort((a, b) => b.scores.insider - a.scores.insider);
      else list.sort(sortByStart);
      const why = (e) => tab === "before_everyone_knows" ? (e.scores.reasons.insider || []).join("; ") :
        tab === "just_discovered" ? `Discovered ${L.fmtRelative(e.first_discovered_at)} via ${(e.sources || [])[0]?.name || "—"}` :
        tab === "worth_planning" ? planHint(e) : (e.scores.reasons.relevance || []).join("; ");
      body = `<div class="ev-list">${list.slice(0, 80).map((e) => evRow(e, { why: why(e) })).join("")}</div>${list.length ? "" : `<div class="empty">Nothing in this section with the current filters.</div>`}`;
    }
    return `<div class="page-head"><h1>The Insider Radar</h1><p>New, niche and time-sensitive finds across the six cities.</p></div>
      <div class="tabs" role="tablist">${Object.keys(counts).map((k) => `<a role="tab" href="#/radar?${new URLSearchParams({ ...route.q, tab: k })}" aria-selected="${k === tab}">${esc(V.radar[k])}<span class="count">${counts[k]}</span></a>`).join("")}</div>
      ${filterBar(f, { city: true })}
      <div class="filters" style="margin-top:-12px"><label>Discovered <select data-filter="disc">${[["", "any time"], ["1", "last 24 hours"], ["3", "last 3 days"], ["7", "last 7 days"]].map(([v, t]) => `<option value="${v}"${(route.q.disc || "") === v ? " selected" : ""}>${t}</option>`).join("")}</select></label></div>
      <p class="muted small" style="margin:0 0 14px;max-width:80ch">${esc(desc)}</p>
      ${body}`;
  }
  function planHint(e) {
    const sp = L.eventSpan(e);
    const status = V.verification[e.verification_status];
    if (!sp) return `${status}. ${e.date_basis || "Dates not announced."}`;
    const days = L.daysBetween(L.todayIn(e.timezone), sp.start);
    const lead = days > 120 ? "Plan 3+ months ahead" : days > 45 ? "Plan 1–3 months ahead" : days > 0 ? "Plan now" : "Already running";
    return `${status}. ${lead}${e.booking?.booking_deadline ? `; booking deadline ${e.booking.booking_deadline}` : ""}.`;
  }

  function pageBriefing() {
    const d = S.data, b = d.briefing;
    if (!b) return `<div class="page-head"><h1>Daily briefing</h1></div><div class="empty"><strong>No briefing has been generated yet.</strong> It is written by the daily collection run from stored events.</div>`;
    const withWhy = (items, empty) => {
      const list = items.map((i) => d.byId[i.event_id] ? [d.byId[i.event_id], i.why] : null).filter(Boolean);
      return list.length ? `<div class="ev-list">${list.map(([e, w]) => evRow(e, { why: w })).join("")}</div>` : `<div class="empty">${empty}</div>`;
    };
    const s = b.sections;
    const stale = b.date !== L.todayIn(HOME_TZ);
    const changes = s.changes.length ? `<div class="table-wrap"><table><thead><tr><th>Event</th><th>What changed</th><th>From</th><th>To</th></tr></thead><tbody>${s.changes.map((c) => `<tr><td><a href="#" data-open="${esc(c.event_id)}">${esc(c.title)}</a></td><td>${esc(c.field.replace("booking.", "booking: "))}</td><td>${esc(c.old)}</td><td>${esc(c.new)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">No changes to listed events in the last two days.</div>`;
    const sigList = (arr, empty) => arr.length ? arr.map((x) => `<div class="signal"><a class="t" href="${esc(safeUrl(x.url) || "#")}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a><div class="meta">${esc(x.source)}, ${esc(d.cityName(x.city))}</div></div>`).join("") : `<div class="empty">${empty}</div>`;
    return `<div class="page-head"><h1>Briefing for ${esc(L.fmtDay(b.date, true))}</h1>
      <p>Written at ${esc(L.fmtStamp(b.generated_at, HOME_TZ))} from ${esc(b.counts.live_events)} stored upcoming events. Each pick says why it is here.</p>
      ${stale ? `<div class="warn">This briefing is from ${esc(L.fmtDay(b.date, true))}. Today's run has not completed yet — check System health.</div>` : ""}</div>
      <section class="section">${sectionHead("Top five for today")}${withWhy(s.top_today, "Nothing dated today in the stored listings.")}</section>
      <section class="section">${sectionHead("Tonight", "Evening starts (17:00 or later, local time) not already in the top five.")}${withWhy(s.tonight, "No evening listings beyond the top five.")}</section>
      <section class="section">${sectionHead("This week")}${withWhy(s.this_week, "No further listings this week.")}</section>
      <div class="cols">
        <section class="section">${sectionHead("New openings", "Reported in the last seven days.")}${sigList(s.new_openings, "No openings reported this week.")}</section>
        <section class="section">${sectionHead("Discovered in the last 24 hours")}${withWhy(s.discovered_24h, "No new listings in the last 24 hours.")}${s.discovered_24h_signals.length ? `<h3 class="small" style="font-weight:700;margin:14px 0 4px">New leads</h3>${sigList(s.discovered_24h_signals, "")}` : ""}</section>
      </div>
      <div class="cols">
        <section class="section">${sectionHead("Booking deadlines", "Deadlines or ticket releases in the next two weeks.")}${withWhy(s.booking_deadlines, "No deadlines published in the next two weeks.")}</section>
        <section class="section">${sectionHead("Last-minute")}${withWhy(s.last_minute, "No last-minute listings.")}</section>
      </div>
      <section class="section">${sectionHead("Changes to listed events")}${changes}</section>
      <section class="section">${sectionHead("Worth planning a trip around")}${withWhy(s.plan_a_trip, "Nothing flagged yet.")}</section>`;
  }

  // ---------------- city calendars
  function pageCity(route) {
    const d = S.data;
    const city = route.arg && d.meta.cities[route.arg] ? route.arg : "luxembourg";
    const tz = d.meta.cities[city].tz;
    const today = L.todayIn(tz);
    const view = ["day", "week", "month", "year"].includes(route.q.view) ? route.q.view : "month";
    const anchor = /^\d{4}-\d{2}-\d{2}$/.test(route.q.date || "") ? route.q.date : today;
    const f = filtersFromQuery(route.q);
    // past listings come from the archive so earlier months still show what happened
    const cityEvents = [...d.events, ...d.archive.map((a) => d.byId[a.id]).filter((a) => a && a.archived)]
      .filter((e) => e.city === city && e.verification_status !== "cancelled");
    const neighborhoods = [...new Set(cityEvents.map((e) => e.neighborhood).filter(Boolean))].sort();
    const list = cityEvents.filter((e) => L.matchFilters(e, f));
    const tLocal = L.localParts(now(), tz);
    const tentative = (e) => ["expected", "announced_pending"].includes(e.verification_status);
    const mark = (e) => e.verification_status === "expected" ? " (expected)" : "";
    let cal = "";
    const nav = (delta, unit) => {
      let x = anchor;
      if (unit === "day") x = L.addDays(anchor, delta);
      if (unit === "week") x = L.addDays(anchor, 7 * delta);
      if (unit === "month") { const [y, m] = anchor.split("-").map(Number); const dt = new Date(Date.UTC(y, m - 1 + delta, 1)); x = dt.toISOString().slice(0, 10); }
      if (unit === "year") x = `${Number(anchor.slice(0, 4)) + delta}-01-01`;
      return x;
    };
    const toolbar = (title) => `<div class="cal-toolbar">
      <div class="tabs" role="tablist" style="margin:0">${["day", "week", "month", "year"].map((v) => `<button role="tab" type="button" data-view="${v}" aria-selected="${v === view}">${v[0].toUpperCase() + v.slice(1)}</button>`).join("")}</div>
      <button class="icon-btn" type="button" data-date="${nav(-1, view)}" aria-label="Previous ${view}">‹</button>
      <h2>${esc(title)}</h2>
      <button class="icon-btn" type="button" data-date="${nav(1, view)}" aria-label="Next ${view}">›</button>
      <button class="btn ghost small" type="button" data-date="${today}">Today</button></div>`;
    const longs = list.filter((e) => L.eventDates(e).long);
    if (view === "month") {
      const [y, m] = anchor.split("-").map(Number);
      const cells = L.monthGrid(y, m);
      const maxN = Math.max(1, ...cells.map((c) => list.filter((e) => L.occursOn(e, c.date)).length));
      cal = toolbar(`${L.MONTHS_LONG[m - 1]} ${y}`) + `<div class="month" role="grid">${L.WEEKDAYS.map((w) => `<div class="wd">${w}</div>`).join("")}
        ${cells.map((c) => {
          const evs = list.filter((e) => L.occursOn(e, c.date)).sort(byRel);
          return `<button type="button" class="cell${c.inMonth ? "" : " out"}${c.date === today ? " today" : ""}" data-date="${c.date}" data-view-to="day" aria-label="${esc(L.fmtDay(c.date, true))}: ${evs.length} events">
            <span class="n">${Number(c.date.slice(8))}</span>
            ${evs.length ? `<span class="density" style="width:${Math.round((evs.length / maxN) * 100)}%"></span>` : ""}
            ${evs.slice(0, 3).map((e) => `<span class="it${tentative(e) ? " tent" : ""}">${esc(e.title)}${mark(e)}</span>`).join("")}
            ${evs.length > 3 ? `<span class="more">+${evs.length - 3} more</span>` : ""}
          </button>`;
        }).join("")}</div>
        <div class="legend"><span>Bar length = number of listings that day</span><span><i>Italic</i> = date announced or expected, not yet confirmed by the organiser</span></div>`;
      const monthStart = cells[0].date, monthEnd = cells[cells.length - 1].date;
      const onview = longs.filter((e) => L.inRange(e, monthStart, monthEnd)).sort(sortByStart);
      cal += onview.length ? `<div class="onview">${sectionHead("On view this month", "Exhibitions and long runs — shown here rather than on every day.")}${evList(onview, "", { showCity: false })}</div>` : "";
    } else if (view === "week") {
      const ws = L.weekStart(anchor);
      const days = Array.from({ length: 7 }, (_, i) => L.addDays(ws, i));
      cal = toolbar(`${L.fmtDay(days[0])} – ${L.fmtDay(days[6], true)}`) + `<div class="week">${days.map((day) => {
        const evs = list.filter((e) => L.occursOn(e, day)).sort((a, b) => (L.localParts(a.start, tz)?.time || "00").localeCompare(L.localParts(b.start, tz)?.time || "00"));
        return `<div class="day${day === today ? " today" : ""}"><h3>${esc(L.fmtDay(day))}</h3>${evs.map((e) => {
          const t = e.all_day ? "All day" : (L.localParts(e.start, tz)?.time || "");
          return `<button type="button" class="wi" data-open="${esc(e.id)}"><span class="tm">${esc(t)}, ${esc(d.catName(e.category))}</span>${esc(e.title)}${mark(e)}</button>`;
        }).join("") || `<span class="muted small">—</span>`}</div>`;
      }).join("")}</div>`;
      const onview = longs.filter((e) => L.inRange(e, days[0], days[6])).sort(sortByStart);
      cal += onview.length ? `<div class="onview">${sectionHead("On view this week")}${evList(onview, "", { showCity: false })}</div>` : "";
    } else if (view === "day") {
      const evs = list.filter((e) => L.occursOn(e, anchor)).sort(sortByStart);
      const running = longs.filter((e) => L.runningOn(e, anchor));
      cal = toolbar(L.fmtDay(anchor, true)) + evList(evs, "Nothing listed on this day.", { showCity: false }) +
        (running.length ? `<div class="onview">${sectionHead("Also on view")}${evList(running, "", { showCity: false })}</div>` : "");
    } else {
      const y = Number(anchor.slice(0, 4));
      const yearList = list.filter((e) => {
        const sp = L.eventSpan(e);
        if (sp) return sp.start.slice(0, 4) <= String(y) && sp.end.slice(0, 4) >= String(y);
        return e.expected_window && e.expected_window.from.slice(0, 4) === String(y);
      });
      const major = yearList.filter((e) => e.trip_suitable || e.curated || (e.scores?.relevance || 0) >= 70);
      cal = toolbar(String(y)) + `<p class="muted small" style="margin-bottom:14px">Major dates only: festivals, fairs, fashion weeks, sport and trip-worthy events. Italic entries are expected or announced but not yet confirmed by the organiser.</p>
        <div class="year">${L.MONTHS_LONG.map((mn, i) => {
          const mm = String(i + 1).padStart(2, "0");
          const items = major.filter((e) => {
            const sp = L.eventSpan(e);
            const s = sp ? sp.start : e.expected_window.from;
            return s.slice(0, 7) === `${y}-${mm}` || (sp && sp.start.slice(0, 7) < `${y}-${mm}` && sp.end.slice(0, 7) >= `${y}-${mm}` && i === 0 && sp.start.slice(0, 4) < String(y));
          }).sort(sortByStart);
          return `<div class="mo"><h3>${mn}</h3><ul>${items.map((e) => `<li class="${e.verification_status === "confirmed" ? "" : "tent"}"><button type="button" data-open="${esc(e.id)}"><span class="d">${esc(L.fmtWhen(e))}</span>${esc(e.title)}${mark(e)}</button></li>`).join("") || `<li class="muted small">—</li>`}</ul></div>`;
        }).join("")}</div>`;
    }

    const up = list.filter((e) => e.verification_status !== "past");
    const featured = up.filter((e) => !L.eventDates(e).long).sort(byRel).slice(0, 4);
    const group = (cats) => up.filter((e) => cats.includes(e.category)).sort(byRel).slice(0, 5);
    const sigs = d.signals.filter((s) => s.city === city && ["opening", "announcement"].includes(s.signal_type)).slice(0, 8);
    const radar = up.filter((e) => (e.radar || []).some((r) => ["just_discovered", "before_everyone_knows", "last_minute"].includes(r))).sort((a, b) => b.scores.insider - a.scores.insider).slice(0, 5);
    const major = up.filter((e) => e.trip_suitable).sort(sortByStart).slice(0, 6);
    const deadlines = up.filter((e) => e.booking?.booking_deadline || ["act_now", "book_soon"].includes(e.urgency)).sort(sortByStart).slice(0, 6);
    const srcs = d.sources.filter((s) => s.city === city);
    return `<div class="page-head"><h1>${esc(d.cityName(city))}</h1>
        <p>${esc(tLocal.time)} local time (${esc(tz)}). ${up.length} upcoming listings and ${d.signals.filter((s) => s.city === city).length} press and social leads. ${cityNote(city)}</p></div>
      ${filterBar(f, { neighborhoods, extra: true })}
      <section>${cal}</section>
      <div class="cols">
        <section class="section">${sectionHead("Featured")}${evList(featured, "No listings match.", { showCity: false })}</section>
        <section class="section">${sectionHead("Insider Radar here")}${evList(radar, "No early or last-minute finds right now.", { showCity: false })}</section>
      </div>
      <div class="cols">
        <section class="section">${sectionHead("New openings and announcements", "Leads from press and public posts.")}${sigs.map(signalRow).join("") || `<div class="empty">No openings reported recently.</div>`}</section>
        <section class="section">${sectionHead("Upcoming major events")}${evList(major, "None flagged yet.", { showCity: false })}</section>
      </div>
      <div class="cols">
        <section class="section">${sectionHead("Restaurants & nightlife")}${evList(group(["food", "nightlife"]), "No restaurant or bar events listed — openings appear in the leads above.", { showCity: false })}</section>
        <section class="section">${sectionHead("Art, design & culture")}${evList(group(["art", "design", "culture", "fashion"]), "None listed.", { showCity: false })}</section>
      </div>
      <div class="cols">
        <section class="section">${sectionHead("Business & networking")}${evList(group(["business"]), "No business events listed.", { showCity: false })}</section>
        <section class="section">${sectionHead("Sports & outdoors")}${evList(group(["sports", "seasonal"]), "None listed.", { showCity: false })}</section>
      </div>
      <section class="section">${sectionHead("Booking deadlines")}${evList(deadlines, "No booking deadlines coming up.", { showCity: false })}</section>
      <section class="section">${sectionHead("Local sources", `${srcs.filter((s) => s.method !== "manual").length} monitored automatically, ${srcs.filter((s) => s.method === "manual").length} checked by hand.`, `<a class="more" href="#/sources?city=${city}">All sources</a>`)}
        <div class="table-wrap"><table><thead><tr><th>Source</th><th>Kind</th><th>Status</th><th>Last success</th></tr></thead><tbody>
        ${srcs.map((s) => `<tr><td>${link(s.url, s.name)}</td><td>${esc(methodLabel(s.method))}</td><td>${statusCell(s)}</td><td>${esc(s.state?.last_success_at ? L.fmtRelative(s.state.last_success_at) : "—")}</td></tr>`).join("")}</tbody></table></div></section>`;
  }
  function cityNote(city) {
    return {
      venice: "Areas follow the sestieri of the historic centre; Mestre and the mainland are named separately.",
      cortina: "Mountain season matters: winter openings, lifts and Dolomites events are tracked with extra care.",
      nyc: "Areas use borough and neighbourhood names.",
    }[city] || "";
  }
  const methodLabel = (m) => ({ jsonld_detail: "Official pages (structured data)", jsonld_page: "Official page (structured data)", rss_events: "Official event feed", rss_news: "News feed", bing_news: "News search", tribe_api: "Organiser calendar API", paris_opendata: "City open data", ical: "Calendar feed", curated: "Researched by hand", manual: "Manual check only" }[m] || m);
  function statusCell(s) {
    const st = s.state || {};
    if (s.method === "manual") return `<span class="st-manual">Not monitored — ${esc(s.reason || "manual")}</span>`;
    if (!st.last_status) return `<span class="st-skipped">Not yet checked</span>`;
    const cls = { ok: "st-ok", failed: "st-failed", partial: "st-partial", manual: "st-manual" }[st.last_status] || "";
    const label = { ok: "Working", failed: "Failing", partial: "Partly working" }[st.last_status] || st.last_status;
    return `<span class="${cls}">${label}</span>${st.last_error ? `<br><span class="small err">${esc(st.last_error.slice(0, 140))}</span>` : ""}`;
  }

  // ---------------- trip planner
  function pageTrips(route) {
    const d = S.data;
    const city = d.meta.cities[route.q.city] ? route.q.city : (route.q.city === undefined ? "paris" : "paris");
    const dep = route.q.dep === "VCE" ? "VCE" : "LUX";
    const trip = route.q.trip ? S.trips.find((t) => t.id === route.q.trip) : null;
    if (trip) return pageTripDetail(trip);
    const sugg = (d.meta.city_order || L.CITY_ORDER).flatMap((c) => L.tripSuggestions(d.events, c, now()).map((s) => ({ ...s, city: c })))
      .sort((a, b) => a.from.localeCompare(b.from));
    const forCity = sugg.filter((s) => s.city === city);
    const cards = (arr) => arr.length ? `<div class="trip-grid">${arr.slice(0, 12).map((s) => {
      const e = s.event;
      const fl = L.flightLinks(dep, s.city, s.from, s.to);
      return `<div class="trip-card">
        <div class="kind">${esc(d.cityName(s.city))}, ${esc(L.fmtDay(s.from))} – ${esc(L.fmtDay(s.to, true))}, ${s.nights} night${s.nights > 1 ? "s" : ""}${s.tentative ? " (tentative dates)" : ""}</div>
        <h3>${esc(e.title)}</h3>
        <div class="chips">${chipVerification(e)}${chipsBooking(e, true)}</div>
        <p class="small muted">${esc(s.why)}</p>
        ${s.tentative ? `<div class="warn">${e.verification_status === "expected" ? "Dates are not announced; the window is an estimate." : "Dates come from an announcement not yet confirmed by the organiser."}</div>` : ""}
        <div class="flight-links">${fl.links.map((l) => link(l.url, `Search ${l.provider}`, "btn ghost small")).join("") || fl.notes.map((n) => `<span class="small muted">${esc(n)}</span>`).join("")}</div>
        <div><button class="btn small" type="button" data-plan='${esc(JSON.stringify({ city: s.city, dep, out: s.from, back: s.to, ev: e.id }))}'>Plan this trip</button></div>
      </div>`;
    }).join("")}</div>` : `<div class="empty">No trip-worthy events stored for this city yet.</div>`;
    return `<div class="page-head"><h1>Trip planner</h1><p>Pick a city and dates, or start from an event worth travelling for. Flight options are pre-filled searches from ${esc(L.DEPARTURES[dep].name)} — Social Atlas does not check live fares or seats.</p></div>
      <form class="form" id="trip-form">
        <label class="wide">Destination<select name="city">${(d.meta.city_order || L.CITY_ORDER).map((c) => `<option value="${c}"${c === city ? " selected" : ""}>${esc(d.cityName(c))}</option>`).join("")}</select></label>
        <div class="wide"><span class="small muted" style="display:block;margin-bottom:4px">Departure airport</span>
          <div class="seg" role="group" aria-label="Departure airport">${Object.values(L.DEPARTURES).map((a) => `<button type="button" data-dep="${a.code}" aria-pressed="${a.code === dep}">${esc(a.code)} — ${esc(a.name.replace(" Airport", ""))}</button>`).join("")}</div></div>
        <label>Departure date<input type="date" name="out" required></label>
        <label>Return date<input type="date" name="back"></label>
        <label><span><input type="checkbox" name="flex"> Flexible by a few days</span></label>
        <label>Max travel budget (optional)<input type="text" name="budget" inputmode="decimal" placeholder="e.g. 400 EUR"></label>
        <label>Preferred flight times<select name="times"><option value="">Any</option><option>Morning</option><option>Afternoon</option><option>Evening</option></select></label>
        <label class="full">Priorities and notes<input type="text" name="notes" placeholder="e.g. one big dinner, a gallery opening, no red-eyes"></label>
        <div class="full"><button class="btn" type="submit">Create trip</button></div>
      </form>
      <section class="section">${sectionHead(`Worth the trip to ${d.cityName(city)}`, "Suggested travel windows built around stored events.")}${cards(forCity)}</section>
      ${S.trips.length ? `<section class="section">${sectionHead("Your trips")}<div class="trip-grid">${S.trips.map(tripCard).join("")}</div></section>` : ""}
      <section class="section">${sectionHead("All upcoming trip ideas")}${cards(sugg.filter((s) => s.city !== city))}</section>`;
  }
  function tripCard(t) {
    const d = S.data;
    const n = (t.eventIds || []).length;
    return `<div class="trip-card"><div class="kind">${esc(t.dep)} to ${esc(d.cityName(t.city))}</div><h3>${esc(d.cityName(t.city))}, ${esc(L.fmtDay(t.out))}${t.back ? ` – ${esc(L.fmtDay(t.back, true))}` : ""}</h3>
      <p class="small muted">${n} event${n === 1 ? "" : "s"} in the itinerary${t.notes ? `. ${esc(t.notes)}` : ""}</p>
      <div><a class="btn small" href="#/trips?trip=${esc(t.id)}">Open itinerary</a> <button class="btn ghost small" type="button" data-trip-del="${esc(t.id)}">Delete trip</button></div></div>`;
  }
  function pageTripDetail(t) {
    const d = S.data;
    const tz = d.meta.cities[t.city]?.tz || "UTC";
    const end = t.back || t.out;
    const from = t.flex ? L.addDays(t.out, -2) : t.out, to = t.flex ? L.addDays(end, 2) : end;
    const chosen = (t.eventIds || []).map((id) => d.byId[id]).filter(Boolean);
    const candidates = d.live.filter((e) => e.city === t.city && L.inRange(e, from, to) && !(t.eventIds || []).includes(e.id)).sort(byRel);
    const { conflicts, untimed } = L.itineraryConflicts(chosen);
    const fl = L.flightLinks(t.dep, t.city, t.out, t.back);
    const days = [];
    for (let x = t.out; x <= end; x = L.addDays(x, 1)) days.push(x);
    const dayOf = (e) => { const sp = L.eventSpan(e); if (!sp) return null; return days.find((x) => x >= sp.start && x <= sp.end && (!L.eventDates(e).long ? L.occursOn(e, x) : true)) || null; };
    const unplaced = chosen.filter((e) => !dayOf(e));
    const itemRow = (e) => `<div class="ev" data-ev="${esc(e.id)}">${dateBlock(e)}<div><h3><a href="#" data-open="${esc(e.id)}">${esc(e.title)}</a></h3>
        <div class="meta">${esc(L.fmtWhen(e))}${e.venue_name ? `<br>${esc(e.venue_name)}${e.venue_address ? `, ${esc(e.venue_address)}` : ""}` : ""}</div>
        <div class="chips">${chipVerification(e)}${chipsBooking(e)}${S.my[e.id]?.status === "booked" ? `<span class="chip free">You marked this booked</span>` : ""}</div>
        ${e.booking?.primary_action ? `<div style="margin-top:8px">${link(e.booking.primary_action.url, e.booking.primary_action.label, "btn ghost small")}</div>` : ""}</div>
        <div class="act"><button class="icon-btn" type="button" data-trip-remove="${esc(t.id)}|${esc(e.id)}">Remove</button></div></div>`;
    return `<div class="page-head"><h1>${esc(d.cityName(t.city))} trip</h1>
      <p>${esc(L.fmtDay(t.out, true))}${t.back ? ` to ${esc(L.fmtDay(t.back, true))}` : " (one way)"}, departing ${esc(L.DEPARTURES[t.dep].name)}${t.flex ? ", flexible by two days" : ""}.${t.budget ? ` Budget: ${esc(t.budget)}.` : ""}${t.times ? ` Prefers ${esc(t.times.toLowerCase())} flights.` : ""}</p>
      <p><a href="#/trips">Back to trip planner</a></p></div>
      <section class="section">${sectionHead("Getting there", "Search links open the provider with your route and dates pre-filled. Prices, schedules and seats are not checked by Social Atlas.")}
        <div class="trip-card">
          <div class="kind">Verified flight information</div><p class="small">None. No flight-data API is connected, so no fares, flight numbers or schedules are shown here.</p>
          <div class="kind" style="margin-top:6px">Search links</div>
          ${fl.notes.map((n) => `<p class="small">${esc(n)}</p>`).join("")}
          <div class="flight-links">${fl.links.map((l) => link(l.url, `Check ${l.provider}`, "btn small")).join("")}</div>
          ${fl.alternatives.length ? `<div class="kind" style="margin-top:6px">Optional alternative airports</div>${fl.alternatives.map((a) => `<p class="small">${link(a.url, `Search ${a.code}`)}: ${esc(a.why)}.</p>`).join("")}` : ""}
          ${fl.rail ? `<p class="small">${link(fl.rail.url, fl.rail.label)} — ${esc(fl.rail.why)}</p>` : ""}
          ${fl.ground.length ? `<div class="kind" style="margin-top:6px">Ground transfer</div>${fl.ground.map((g) => `<p class="small">${link(g.url, g.label)}</p>`).join("")}` : ""}
        </div></section>
      <section class="section">${sectionHead("Itinerary")}
        ${conflicts.map((c) => `<div class="warn ${c.type === "overlap" ? "red" : ""}" style="margin-bottom:8px">${esc(c.message)}.</div>`).join("")}
        ${untimed.length ? `<p class="small muted" style="margin-bottom:8px">${untimed.length} item(s) have no published time, so overlaps with them cannot be checked.</p>` : ""}
        ${days.map((x) => { const items = chosen.filter((e) => dayOf(e) === x); return `<div class="itin-day"><h4>${esc(L.fmtDay(x, true))}</h4>${items.length ? items.map(itemRow).join("") : `<p class="muted small">Nothing planned.</p>`}</div>`; }).join("")}
        ${unplaced.length ? `<div class="itin-day"><h4>Outside the trip dates or undated</h4>${unplaced.map(itemRow).join("")}</div>` : ""}
        <p class="small muted" style="margin-top:10px">Travel times between venues are not estimated: no routing data is connected.</p></section>
      <section class="section">${sectionHead("Add events from these dates", t.flex ? "Includes two days either side." : "")}
        ${candidates.length ? `<div class="ev-list">${candidates.slice(0, 40).map((e) => evRow(e, { showCity: false }).replace(`<div class="act">`, `<div class="act"><button class="icon-btn" type="button" data-trip-add="${esc(t.id)}|${esc(e.id)}">Add</button>`)).join("")}</div>` : `<div class="empty">No stored listings fall inside these dates yet.</div>`}</section>
      <section class="section">${sectionHead("Notes")}<form class="form" data-trip-notes="${esc(t.id)}"><label class="full">Priorities and notes<textarea name="notes" rows="3">${esc(t.notes || "")}</textarea></label><div class="full"><button class="btn small" type="submit">Save notes</button></div></form></section>`;
  }

  // ---------------- my events
  function pageMy(route) {
    const d = S.data;
    const tab = route.q.tab || "saved";
    const entries = Object.entries(S.my).map(([id, m]) => ({ id, m, ev: d.byId[id] || m.snapshot }));
    const groups = { saved: [], must: [], tobook: [], booked: [], past: [] };
    for (const x of entries) {
      const c = L.collectionOf(x.m, x.ev);
      (groups[c] || groups.saved).push(x);
      if (x.m.priority && c !== "past" && c !== "must") groups.must.push(x);
    }
    const labels = { ...L.COLLECTIONS, past: "Past events" };
    const rows = (groups[tab] || []).sort((a, b) => (a.ev?.start || "9").localeCompare(b.ev?.start || "9"));
    return `<div class="page-head"><h1>My events</h1><p>Your saved events, priorities and bookings. Stored in this browser only — use export to move them to another device.</p>
      ${S.storageOk ? "" : `<div class="warn red">This browser is blocking storage, so selections will be lost when you close the page.</div>`}</div>
      <div class="tabs" role="tablist">${Object.keys(groups).map((k) => `<a role="tab" href="#/my?tab=${k}" aria-selected="${k === tab}">${esc(labels[k])}<span class="count">${groups[k].length}</span></a>`).join("")}</div>
      ${rows.length ? rows.map(({ id, m, ev }) => `
        <div class="ev" style="cursor:default">${ev ? dateBlock(ev) : `<div class="date"><span class="tbd">—</span></div>`}
          <div>
            <h3>${ev && d.byId[id] ? `<a href="#" data-open="${esc(id)}">${esc(ev.title)}</a>` : esc(ev?.title || id)}</h3>
            <div class="meta">${ev ? `${esc(L.fmtWhen(ev))}, ${esc(d.cityName(ev.city))}` : ""}${!d.byId[id] ? " — no longer in the current data" : ""}</div>
            ${ev && d.byId[id] ? `<div class="chips">${chipVerification(ev)}${chipsBooking(ev, true)}</div>` : ""}
            <form class="status-row" data-my-form="${esc(id)}">
              <label class="small">Status <select name="status">${Object.entries(L.COLLECTIONS).map(([k, v]) => `<option value="${k}"${(m.status || "saved") === k ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
              <label class="small"><input type="checkbox" name="priority"${m.priority ? " checked" : ""}> Priority</label>
              <label class="small">Booking reference <input type="text" name="ref" value="${esc(m.ref || "")}" style="width:9em;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:var(--surface)"></label>
              <label class="small" style="flex-basis:100%">Note <input type="text" name="note" value="${esc(m.note || "")}" style="width:100%;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:var(--surface)"></label>
              <label class="small">Add to trip <select name="trip"><option value="">—</option>${S.trips.filter((t) => !ev || t.city === ev.city).map((t) => `<option value="${esc(t.id)}"${(t.eventIds || []).includes(id) ? " selected" : ""}>${esc(d.cityName(t.city))} ${esc(L.fmtDay(t.out))}</option>`).join("")}</select></label>
              <button class="btn small" type="submit">Save</button>
              <button class="btn ghost small" type="button" data-unsave="${esc(id)}">Remove</button>
            </form>
          </div></div>`).join("") : `<div class="empty">No events here yet. Use <strong>Save</strong> on any listing.</div>`}
      <section class="section">${sectionHead("Move your data", "Export a file with your saved events and trips, or import one from another browser.")}
        <button class="btn ghost small" type="button" data-export>Export JSON</button>
        <label class="btn ghost small" style="cursor:pointer">Import JSON<input type="file" accept="application/json" data-import hidden></label></section>`;
  }

  // ---------------- sources
  function pageSources(route) {
    const d = S.data;
    const city = route.q.city || "all";
    const method = route.q.method || "all";
    const list = d.sources.filter((s) => (city === "all" || s.city === city) && (method === "all" || (method === "auto" ? s.method !== "manual" : s.method === "manual")));
    const accts = d.accounts.filter((a) => city === "all" || a.city === city);
    const perf = d.sources.filter((s) => s.state?.totals).sort((a, b) => (b.state.totals.verified_events - a.state.totals.verified_events) || (b.state.totals.events + b.state.totals.signals - a.state.totals.events - a.state.totals.signals)).slice(0, 15);
    const repo = CFG.repo;
    const relLabel = { 1: "Official", 2: "Organiser / partner", 3: "Publication", 4: "Aggregator / social" };
    return `<div class="page-head"><h1>Source intelligence</h1><p>Every place Social Atlas looks, how it looks there, and whether that is working. Numbers come from the collection logs.</p></div>
      <div class="filters">
        <label>City <select data-q="city">${[["all", "All"], ...(d.meta.city_order || []).map((c) => [c, d.cityName(c)]), ["multi", "Multi-city"]].map(([v, t]) => `<option value="${v}"${v === city ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
        <label>Collection <select data-q="method">${[["all", "All"], ["auto", "Automatic"], ["manual", "Manual only"]].map(([v, t]) => `<option value="${v}"${v === method ? " selected" : ""}>${t}</option>`).join("")}</select></label>
        <span class="small muted">${list.length} sources, ${list.filter((s) => s.method !== "manual").length} collected automatically</span>
      </div>
      <section>${sectionHead("Source directory")}
      <div class="table-wrap"><table><thead><tr><th>Source</th><th>City</th><th>Type and reliability</th><th>Collection</th><th>Status</th><th>Last success</th><th>Last event / lead</th><th>Found</th></tr></thead><tbody>
      ${list.map((s) => `<tr><td>${link(s.url, s.name)}${s.query ? `<br><span class="small muted">Queries: ${esc(Array.isArray(s.query) ? s.query.join("; ") : s.query)}</span>` : ""}</td>
        <td>${esc(d.cityName(s.city))}</td><td>${esc((s.type || "").replace(/_/g, " "))}<br><span class="small muted">${esc(relLabel[s.reliability] || "")}</span></td>
        <td>${esc(methodLabel(s.method))}${s.frequency_days && s.frequency_days !== 1 ? `<br><span class="small muted">every ${esc(s.frequency_days)} days</span>` : ""}</td>
        <td>${statusCell(s)}</td><td>${esc(s.state?.last_success_at ? L.fmtRelative(s.state.last_success_at) : "—")}</td>
        <td>${esc(s.state?.last_event_found_at ? L.fmtRelative(s.state.last_event_found_at) : s.state?.last_signal_found_at ? L.fmtRelative(s.state.last_signal_found_at) + " (lead)" : "—")}</td>
        <td>${s.state?.totals ? `${s.state.totals.events} events, ${s.state.totals.verified_events} confirmed, ${s.state.totals.signals} leads` : "—"}</td></tr>`).join("")}
      </tbody></table></div></section>
      <section class="section">${sectionHead("Source performance", "Ranked by confirmed events, then by everything found. Duplicates = listings also found elsewhere.")}
        <div class="table-wrap"><table><thead><tr><th>Source</th><th>Events</th><th>Confirmed</th><th>Also found elsewhere</th><th>Leads</th><th>Consecutive failures</th></tr></thead><tbody>
        ${perf.map((s) => `<tr><td>${esc(s.name)}</td><td>${s.state.totals.events}</td><td>${s.state.totals.verified_events}</td><td>${s.state.totals.duplicates}</td><td>${s.state.totals.signals}</td><td>${esc(s.state.consecutive_failures ?? "—")}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="small muted" style="margin-top:8px">Inaccessible right now: ${d.sources.filter((s) => s.state?.last_status === "failed").map((s) => esc(s.name)).join(", ") || "none"}.</p></section>
      <section class="section">${sectionHead("Influencer & insider accounts", "Public accounts linked from each organisation's own website, plus accounts you add. Audience figures are not tracked. None of these platforms is collected automatically.")}
        <div class="table-wrap"><table><thead><tr><th>Account</th><th>Platform</th><th>City</th><th>Why it matters</th><th>Verified by</th><th>Monitoring</th><th>Events attributed</th></tr></thead><tbody>
        ${accts.map((a) => `<tr><td>${link(a.url, "@" + a.handle)}</td><td>${esc(a.platform)}</td><td>${esc(d.cityName(a.city))}</td><td>${esc(a.relevance || "")}${a.topics?.length ? `<br><span class="small muted">${esc(a.topics.join(", "))}</span>` : ""}</td><td class="small">${esc(a.verified_by || "")}</td><td class="small">${esc(a.monitoring || "")}</td>
          <td>${d.events.filter((e) => (e.social_accounts || []).some((x) => x.handle && x.handle.toLowerCase() === a.handle.toLowerCase())).length}</td></tr>`).join("")}
        </tbody></table></div></section>
      <section class="section">${sectionHead("Submit a URL", "An event page, venue, article or public post. The next run fetches it once; if it has structured event data it is listed as announced, otherwise it is kept as a lead for manual entry.")}
        <form class="form" id="submit-form">
          <label class="wide">Public URL<input type="url" name="url" required placeholder="https://"></label>
          <label>City<select name="city"><option value="">Detect</option>${(d.meta.city_order || []).map((c) => `<option value="${c}">${esc(d.cityName(c))}</option>`).join("")}</select></label>
          <label>Note<input type="text" name="note" placeholder="Where you saw it"></label>
          <div class="full">${repo ? `<button class="btn" type="submit">Open submission on GitHub</button> <span class="small muted">Creates a pre-filled issue; the submission workflow adds it to the next run.</span>`
            : `<button class="btn" type="submit">Copy entry for submissions.yaml</button> <span class="small muted">Set <code>repo</code> in config.js to submit through GitHub issues instead.</span>`}</div>
        </form></section>
      <section class="section">${sectionHead("Adding a source")}<p class="small" style="max-width:75ch">Test the address with <code>python scripts/probe_source.py URL</code>, then add an entry to <code>data/sources.yaml</code> with the method the probe suggests (structured event data, feed, or manual). The README explains each field.</p></section>`;
  }

  // ---------------- health
  function pageHealth() {
    const d = S.data, m = d.meta;
    const last = d.runs[0];
    const run = (r, label) => `<div class="stat"><div class="k">${label}</div><div class="v ${r && r.status === "failed" ? "bad" : ""}">${r ? esc(L.fmtRelative(r.finished_at || r.started_at)) : "—"}</div><div class="small muted">${r ? `${esc(r.status)}, ${esc(r.trigger)} on ${esc(r.runner)}` : "none recorded"}</div></div>`;
    const ev = d.events;
    const missingBooking = ev.filter((e) => e.verification_status !== "past" && e.booking && e.booking.access === "unknown" && e.booking.tickets === "unknown").length;
    const conflicts = ev.filter((e) => (e.conflicts || []).length).length;
    const review = ev.filter((e) => e.verification_status === "needs_review").length;
    const possibleDup = ev.filter((e) => (e.review_flags || []).some((f) => f.startsWith("possible duplicate"))).length;
    const unreachable = ev.filter((e) => (e.review_flags || []).includes("official page unreachable on last check")).length;
    const repo = CFG.repo;
    const gh = (path) => (repo ? `https://github.com/${repo}/${path}` : null);
    const ctrl = (label, path, help) => `<div class="trip-card"><h3 style="font-size:1.15rem">${esc(label)}</h3><p class="small muted">${esc(help)}</p>${repo ? link(gh(path), "Open on GitHub", "btn small") : `<span class="small muted">Set <code>repo</code> in config.js to enable this link.</span>`}</div>`;
    return `<div class="page-head"><h1>System health</h1><p>What the automated pipeline actually did. Nothing here is simulated: it is read from the run log the pipeline writes.</p></div>
      <section>${sectionHead("Data collection")}
        <div class="stats">${run(m.last_scheduled_run, "Last scheduled run")}${run(m.last_run, "Last attempted run")}${run(m.last_successful_run, "Last successful run")}
          <div class="stat"><div class="k">Sources attempted / answered / failed</div><div class="v">${last ? `${last.sources_attempted} / ${last.sources_ok} / ${last.sources_failed}` : "—"}</div><div class="small muted">${last ? `${last.sources_skipped || 0} skipped as recently checked, ${last.sources_manual || 0} manual-only` : ""}</div></div>
          <div class="stat"><div class="k">Events discovered / updated</div><div class="v">${last ? `${last.events_new} / ${last.events_updated}` : "—"}</div><div class="small muted">${last ? `${last.signals_new} new leads` : ""}</div></div>
        </div>
        ${last && last.status === "success" && !last.events_new ? `<p class="small muted" style="margin-top:8px">The last run succeeded and found no new events — that is different from a failure.</p>` : ""}
        ${last && last.status === "failed" ? `<div class="warn red" style="margin-top:10px">The last run failed. ${esc((last.errors || [])[0] || "")}</div>` : ""}</section>
      <section class="section">${sectionHead("Event processing", "Current state of the stored listings.")}
        <div class="stats">
          <div class="stat"><div class="k">Extracted in last run</div><div class="v">${last ? esc(last.events_extracted) : "—"}</div></div>
          <div class="stat"><div class="k">Duplicates merged (last run)</div><div class="v">${last ? esc(last.duplicates_merged) : "—"}</div></div>
          <div class="stat"><div class="k">Needing manual review</div><div class="v ${review ? "bad" : ""}">${review}</div></div>
          <div class="stat"><div class="k">Booking information missing</div><div class="v">${missingBooking}</div></div>
          <div class="stat"><div class="k">Conflicting dates</div><div class="v ${conflicts ? "bad" : ""}">${conflicts}</div></div>
          <div class="stat"><div class="k">Possible duplicates flagged</div><div class="v">${possibleDup}</div></div>
          <div class="stat"><div class="k">Official page unreachable</div><div class="v ${unreachable ? "bad" : ""}">${unreachable}</div></div>
          <div class="stat"><div class="k">Failed extraction tasks (last run)</div><div class="v ${last && last.sources_failed ? "bad" : ""}">${last ? esc(last.sources_failed) : "—"}</div></div>
        </div></section>
      <section class="section">${sectionHead("Logs & errors — last run", last ? `Run ${esc(last.run_id)} started ${esc(L.fmtStamp(last.started_at, HOME_TZ))}${last.github_run_url ? ` · ${link(last.github_run_url, "GitHub log")}` : ""}` : "")}
        ${last ? `<div class="table-wrap"><table><thead><tr><th>Source</th><th>Task</th><th>Result</th><th>Found</th><th>Error or note</th><th>Retries</th></tr></thead><tbody>
        ${(last.per_source || []).map((p) => { const s = d.sources.find((x) => x.id === p.id); return `<tr><td>${esc(s ? s.name : p.id)}</td><td>${esc(s ? methodLabel(s.method) : "")}</td><td class="st-${esc(p.status)}">${esc(p.status)}</td><td>${p.events ?? ""}${p.events != null ? " events, " : ""}${p.signals ?? ""}${p.signals != null ? " leads" : ""}</td><td class="small">${p.errors && p.errors.length ? `<span class="err">${esc(p.errors.join(" | ").slice(0, 300))}</span>` : esc((p.notes || []).join("; ").slice(0, 200) || p.note || "")}</td><td>${esc(p.retries ?? "")}</td></tr>`; }).join("")}
        </tbody></table></div>` : `<div class="empty">No run has been recorded yet.</div>`}</section>
      <section class="section">${sectionHead("Run history")}
        <div class="table-wrap"><table><thead><tr><th>Started</th><th>Trigger</th><th>Runner</th><th>Result</th><th>Sources ok / tried</th><th>New events</th><th>Updated</th><th>New leads</th></tr></thead><tbody>
        ${d.runs.slice(0, 30).map((r) => `<tr><td>${esc(L.fmtStamp(r.started_at, HOME_TZ))}</td><td>${esc(r.trigger)}</td><td>${esc(r.runner)}</td><td class="st-${r.status === "success" ? "ok" : esc(r.status)}">${esc(r.status)}</td><td>${esc(r.sources_ok)} / ${esc(r.sources_attempted)}</td><td>${esc(r.events_new)}</td><td>${esc(r.events_updated)}</td><td>${esc(r.signals_new)}</td></tr>`).join("")}
        </tbody></table></div></section>
      <section class="section">${sectionHead("Manual controls", "These run on GitHub, behind your GitHub sign-in. The website itself holds no credentials.")}
        <div class="trip-grid">
          ${ctrl("Run a collection now", "actions/workflows/collect.yml", "Click “Run workflow”. Leave the options empty for a normal run.")}
          ${ctrl("Refresh selected sources", "actions/workflows/collect.yml", "Run workflow with source ids (comma-separated) in the “sources” box.")}
          ${ctrl("Retry failed sources", "actions/workflows/collect.yml", "Run workflow with mode “retry-failed”.")}
          ${ctrl("Reprocess stored events", "actions/workflows/collect.yml", "Run workflow with mode “reprocess” — no network, recomputes statuses, scores and the briefing.")}
          ${ctrl("Verify or correct an event", `edit/${CFG.branch || "main"}/data/overrides.yaml`, "Add the event id with a status, note or corrected fields. Applied on the next run.")}
          ${ctrl("Submit a URL", "issues/new?template=submit-url.yml", "Adds a page to the next run's queue.")}
        </div></section>`;
  }

  function pageSearch(route) {
    const q = route.q.q || "";
    const r = L.search(S.data, q);
    const d = S.data;
    return `<div class="page-head"><h1>Search</h1><p>${esc(r.events.length)} events, ${esc(r.signals.length)} leads, ${esc(r.sources.length + r.accounts.length)} sources and accounts for “${esc(q)}”.</p></div>
      <section class="section">${sectionHead("Events")}${evList(r.events, "No events match.")}</section>
      <div class="cols"><section class="section">${sectionHead("Leads")}${r.signals.map(signalRow).join("") || `<div class="empty">No leads match.</div>`}</section>
      <section class="section">${sectionHead("Sources and accounts")}${[...r.sources.map((s) => `<div class="signal">${link(s.url, s.name, "t")}<div class="meta">${esc(d.cityName(s.city))}, ${esc(methodLabel(s.method))}</div></div>`), ...r.accounts.map((a) => `<div class="signal">${link(a.url, "@" + a.handle, "t")}<div class="meta">${esc(a.platform)}, ${esc(d.cityName(a.city))}</div></div>`)].join("") || `<div class="empty">No sources match.</div>`}</section></div>`;
  }

  // ------------------------------------------------------------------ drawer
  function openEvent(id) {
    const d = S.data;
    const e = d.byId[id];
    if (!e) return;
    const b = e.booking || {};
    const lab = (group, v) => (v && V[group][v]) || V[group].unknown;
    const cell = (k, v, full, unknown) => `<div${full ? ' class="full"' : ""}><dt>${esc(k)}</dt><dd${unknown ? ' class="unknown"' : ""}>${v}</dd></div>`;
    const price = b.price ? `${esc(b.price.display || "")}${b.price.per_person && !/per person/i.test(b.price.display || "") ? " per person" : ""}${b.price.fees_included === true ? ", fees included" : ""}${b.price.source_url ? `<br><span class="small muted">Source: ${link(b.price.source_url, host(b.price.source_url))}${b.price.verified_at ? `, checked ${esc(L.fmtStamp(b.price.verified_at, HOME_TZ))}` : ""}</span>` : ""}` : (b.free === false ? "Price not published" : "Price not verified");
    const links = [["Official reservation", b.reservation_url], ["Official tickets", b.ticket_url], ["Registration", b.registration_url], ["Official page", e.official_url], ["Source", e.source_url]]
      .filter(([, u]) => safeUrl(u)).filter(([, u], i, arr) => arr.findIndex(([, x]) => x === u) === i)
      .map(([t, u]) => `${link(u, t)} <span class="small muted">(${esc(host(u))})</span>`).join("<br>");
    const my = S.my[id];
    const sc = e.scores || {};
    const bar = (k, label, note) => `<div class="score"><span>${label}</span><span class="bar"><i style="width:${sc[k] || 0}%"></i></span><span>${sc[k] ?? "—"}</span></div>${note ? `<p class="small muted" style="margin:-2px 0 8px 130px">${esc(note)}</p>` : ""}`;
    const repo = CFG.repo;
    $overlay.innerHTML = `<div class="scrim" data-close></div>
      <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dw-title">
        <button class="icon-btn close" type="button" data-close aria-label="Close">✕</button>
        <div class="kind">${esc(d.cityName(e.city))}, ${esc(d.catName(e.category))}${e.subcategory ? `, ${esc(e.subcategory.replace(/_/g, " "))}` : ""}</div>
        <h2 id="dw-title">${esc(e.title)}</h2>
        <div class="when">${esc(L.fmtWhen(e))}</div>
        ${e.date_basis ? `<div class="small muted">${esc(e.date_basis)}</div>` : ""}
        <div class="where">${esc([...new Set([e.venue_name, e.venue_address, e.neighborhood].filter(Boolean))].join(", ") || "Venue not published")}</div>
        <div class="chips" style="margin:12px 0">${chipUrgency(e)}${chipVerification(e)}</div>
        ${e.description ? `<p style="max-width:62ch">${esc(e.description)}</p>` : ""}
        ${b.primary_action ? `<div style="margin-top:14px">${link(b.primary_action.url, b.primary_action.label, "btn")} <span class="small muted">Opens ${esc(host(b.primary_action.url))}. Opening it does not mark anything as booked.</span></div>` : ""}

        <h3>Booking &amp; access</h3>
        <dl class="ba">
          ${cell("Reservation", esc(lab("reservation", b.reservation)), false, !b.reservation || b.reservation === "unknown")}
          ${cell("Registration", esc(lab("registration", b.registration)), false, !b.registration || b.registration === "unknown")}
          ${cell("Tickets", esc(lab("tickets", b.tickets)), false, !b.tickets || b.tickets === "unknown")}
          ${cell("Access", esc(lab("access", b.access)), false, !b.access || b.access === "unknown")}
          ${cell("Price", price, true, !b.price)}
          ${cell("Deadlines", esc([b.booking_deadline && `Book by ${b.booking_deadline}`, b.ticket_release && `Tickets released ${b.ticket_release}`, b.booking_deadline_note].filter(Boolean).join(". ") || "None published"), true, !(b.booking_deadline || b.ticket_release || b.booking_deadline_note))}
          ${links ? cell("Links", links, true) : ""}
          ${b.access_notes || b.dress_code || b.age_restriction ? cell("Access notes", esc([b.access_notes, b.dress_code && `Dress code: ${b.dress_code}`, b.age_restriction && `Age: ${b.age_restriction}`].filter(Boolean).join(" ")), true) : ""}
          ${cell("Last verified", esc(e.last_verified_at ? L.fmtStamp(e.last_verified_at, HOME_TZ) : "Not verified against an official source"), true, !e.last_verified_at)}
        </dl>
        ${(b.evidence || []).length || (b.inferred || []).length ? `<ul class="note-list">${(b.evidence || []).map((x) => `<li>${esc(x)}</li>`).join("")}${(b.inferred || []).map((x) => `<li>Inferred, not stated: ${esc(x)}</li>`).join("")}</ul>` : ""}
        <p class="small muted" style="margin-top:8px">Free entry does not mean no booking is needed, and a missing booking link does not mean walk-in. Unknown stays unknown until a source says otherwise.</p>

        <h3>My plans</h3>
        <div class="status-row">${Object.entries(L.COLLECTIONS).map(([k, v]) => `<button class="icon-btn" type="button" data-set-status="${esc(id)}|${k}" aria-pressed="${my && (my.status || "saved") === k}">${esc(v)}</button>`).join("")}
          ${my ? `<button class="icon-btn" type="button" data-unsave="${esc(id)}">Remove</button>` : ""}</div>
        ${S.trips.filter((t) => t.city === e.city).length ? `<div class="status-row">${S.trips.filter((t) => t.city === e.city).map((t) => `<button class="icon-btn" type="button" data-trip-add="${esc(t.id)}|${esc(id)}">Add to ${esc(L.fmtDay(t.out))} trip</button>`).join("")}</div>` : `<p class="small muted"><a href="#/trips?city=${esc(e.city)}" data-close>Create a ${esc(d.cityName(e.city))} trip</a> to add this to an itinerary.</p>`}

        <h3>Why it is listed</h3>
        ${bar("relevance", "Relevance", (sc.reasons?.relevance || []).join("; "))}
        ${bar("insider", "Insider (heuristic)", (sc.reasons?.insider || []).join("; ") || "Widely covered or researched")}
        ${bar("actionability", "Actionability", (sc.reasons?.actionability_gaps || []).length ? "Gaps: " + sc.reasons.actionability_gaps.join(", ") : "")}

        <h3>Verification</h3>
        <dl class="kv">
          <dt>Status</dt><dd>${esc(V.verification[e.verification_status] || "")}${e.manually_verified ? " (set by manual review)" : ""}</dd>
          <dt>Confidence</dt><dd>${esc(e.confidence || "—")}</dd>
          <dt>Event date</dt><dd>${esc(L.fmtWhen(e))}</dd>
          <dt>Published</dt><dd>${esc(e.published_at ? L.fmtStamp(e.published_at, HOME_TZ) : "Not stated by the source")}</dd>
          <dt>First discovered</dt><dd>${esc(L.fmtStamp(e.first_discovered_at, HOME_TZ))}</dd>
          <dt>Last updated</dt><dd>${esc(L.fmtStamp(e.last_updated_at, HOME_TZ))}</dd>
          <dt>Last verified</dt><dd>${esc(e.last_verified_at ? L.fmtStamp(e.last_verified_at, HOME_TZ) : "Never")}</dd>
          ${e.link_check ? `<dt>Official link check</dt><dd>${e.link_check.ok ? "Reachable" : `Failed (${esc(e.link_check.error || e.link_check.status)})`}, ${esc(L.fmtRelative(e.link_check.checked_at))}</dd>` : ""}
        </dl>
        ${(e.conflicts || []).map((c) => `<div class="warn red" style="margin-top:8px">Sources disagree on ${esc(c.field)}: ${Object.entries(c.values).map(([k, v]) => `${esc(k)} says ${esc(v)}`).join("; ")}.</div>`).join("")}
        ${(e.review_flags || []).map((f) => `<div class="warn" style="margin-top:8px">${esc(f)}</div>`).join("")}
        <ul class="note-list">${(e.verification_evidence || []).map((x) => `<li>${x.url ? link(x.url, x.publisher || host(x.url)) : esc(x.publisher || "")}${x.note ? `: ${esc(x.note)}` : ""}${x.checked_at ? ` <span class="muted">(${esc(L.fmtStamp(x.checked_at, HOME_TZ))})</span>` : ""}</li>`).join("")}</ul>

        <h3>Sources</h3>
        <ul class="note-list">${(e.sources || []).map((s) => `<li>${s.url ? link(s.url, s.name) : esc(s.name)} — ${esc({ 1: "official", 2: "organiser / partner", 3: "publication", 4: "aggregator" }[s.reliability] || "")}, seen ${esc(L.fmtRelative(s.seen_at))}</li>`).join("")}</ul>
        ${(e.social_accounts || []).length ? `<p class="small" style="margin-top:6px">Accounts: ${e.social_accounts.map((a) => link(a.url, "@" + a.handle)).join(", ")}</p>` : ""}
        ${(e.history || []).length ? `<h3>Changes</h3><ul class="note-list">${e.history.map((h) => `<li>${esc(L.fmtStamp(h.at, HOME_TZ))}: ${esc(h.field)} changed from ${esc(h.old)} to ${esc(h.new)} (${esc(h.source)})</li>`).join("")}</ul>` : ""}
        <h3>Something wrong?</h3>
        <p class="small">${repo ? `${link(`https://github.com/${repo}/edit/${CFG.branch || "main"}/data/overrides.yaml`, "Correct or verify this event")} using id <code>${esc(e.id)}</code>.` : `Add a correction for id <code>${esc(e.id)}</code> to <code>data/overrides.yaml</code>.`}</p>
      </aside>`;
    document.body.style.overflow = "hidden";
    $overlay.querySelector(".close").focus();
  }
  function closeDrawer() {
    $overlay.innerHTML = "";
    document.body.style.overflow = "";
  }

  // ------------------------------------------------------------------ interactions
  function snapshot(ev) {
    return ev ? { title: ev.title, city: ev.city, start: ev.start, end: ev.end, timezone: ev.timezone, all_day: ev.all_day } : null;
  }
  function setStatus(id, status) {
    const ev = S.data.byId[id];
    S.my[id] = { ...(S.my[id] || { savedAt: new Date().toISOString() }), status, snapshot: snapshot(ev) };
    saveMy();
  }
  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-open],[data-save],[data-close],[data-set-status],[data-unsave],[data-view],[data-date],[data-dep],[data-plan],[data-trip-add],[data-trip-remove],[data-trip-del],[data-export],[data-filter-reset]");
    if (!t) {
      const row = ev.target.closest(".ev[data-ev]");
      if (row && !ev.target.closest("a,button,input,select,label,form")) { openEvent(row.dataset.ev); }
      return;
    }
    const ds = t.dataset;
    if ("open" in ds) { ev.preventDefault(); openEvent(ds.open); return; }
    if ("close" in ds) { if (t.tagName === "A") { closeDrawer(); return; } ev.preventDefault(); closeDrawer(); return; }
    if ("save" in ds) {
      if (S.my[ds.save]) { openEvent(ds.save); return; }
      setStatus(ds.save, "saved"); toast("Saved to My events"); t.setAttribute("aria-pressed", "true"); t.textContent = "Saved"; return;
    }
    if ("setStatus" in ds) {
      const [id, st] = ds.setStatus.split("|");
      setStatus(id, st);
      toast(st === "booked" ? "Marked as booked" : `Moved to ${L.COLLECTIONS[st]}`);
      openEvent(id); render(); return;
    }
    if ("unsave" in ds) { delete S.my[ds.unsave]; saveMy(); toast("Removed from My events"); closeDrawer(); render(); return; }
    if ("view" in ds) { setQuery({ view: ds.view }); return; }
    if ("date" in ds) { setQuery({ date: ds.date, ...(ds.viewTo ? { view: ds.viewTo } : {}) }); return; }
    if ("dep" in ds) { setQuery({ dep: ds.dep }); return; }
    if ("plan" in ds) {
      const p = JSON.parse(ds.plan);
      const trip = { id: "t" + Date.now().toString(36), city: p.city, dep: p.dep, out: p.out, back: p.back, flex: false, eventIds: [p.ev], createdAt: new Date().toISOString() };
      S.trips.push(trip); saveTrips(); go("trips", null, { trip: trip.id }); return;
    }
    if ("tripAdd" in ds) {
      const [tid, eid] = ds.tripAdd.split("|");
      const tr = S.trips.find((x) => x.id === tid);
      if (tr && !tr.eventIds.includes(eid)) { tr.eventIds.push(eid); saveTrips(); toast("Added to the itinerary"); }
      if (!S.my[eid]) setStatus(eid, "saved");
      closeDrawer(); render(); return;
    }
    if ("tripRemove" in ds) {
      const [tid, eid] = ds.tripRemove.split("|");
      const tr = S.trips.find((x) => x.id === tid);
      if (tr) { tr.eventIds = tr.eventIds.filter((x) => x !== eid); saveTrips(); render(); }
      return;
    }
    if ("tripDel" in ds) { S.trips = S.trips.filter((x) => x.id !== ds.tripDel); saveTrips(); toast("Trip deleted"); render(); return; }
    if ("export" in ds) {
      const blob = new Blob([JSON.stringify({ my: S.my, trips: S.trips, exported_at: new Date().toISOString() }, null, 1)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "social-atlas-my-events.json"; a.click(); URL.revokeObjectURL(a.href); return;
    }
    if ("filterReset" in ds) {
      const r = parseRoute();
      const keep = {}; for (const k of ["view", "date", "tab"]) if (r.q[k]) keep[k] = r.q[k];
      go(r.page, r.arg, keep); return;
    }
  });
  document.addEventListener("change", (ev) => {
    const t = ev.target;
    if (t.dataset.filter) {
      const key = t.dataset.filter;
      setQuery({ [key]: t.type === "checkbox" ? (t.checked ? "1" : "") : (t.value === "all" ? "" : t.value) });
    } else if (t.dataset.q) {
      setQuery({ [t.dataset.q]: t.value === "all" ? "" : t.value });
    } else if ("import" in t.dataset && t.files[0]) {
      t.files[0].text().then((txt) => {
        try {
          const j = JSON.parse(txt);
          if (j.my && typeof j.my === "object") S.my = { ...S.my, ...j.my };
          if (Array.isArray(j.trips)) { const ids = new Set(S.trips.map((x) => x.id)); S.trips.push(...j.trips.filter((x) => x && x.id && !ids.has(x.id))); }
          saveMy(); saveTrips(); toast("Imported"); render();
        } catch { toast("That file is not a Social Atlas export"); }
      });
    }
  });
  document.addEventListener("submit", (ev) => {
    const f = ev.target;
    if (f.id === "search-form") { ev.preventDefault(); const q = document.getElementById("q").value.trim(); if (q) go("search", null, { q }); return; }
    if (f.id === "trip-form") {
      ev.preventDefault();
      const fd = new FormData(f);
      const r = parseRoute();
      const out = fd.get("out"), back = fd.get("back");
      if (back && back < out) { toast("The return date is before the departure date"); return; }
      const trip = { id: "t" + Date.now().toString(36), city: fd.get("city"), dep: r.q.dep === "VCE" ? "VCE" : "LUX", out, back: back || null,
        flex: !!fd.get("flex"), budget: fd.get("budget") || "", times: fd.get("times") || "", notes: fd.get("notes") || "", eventIds: [], createdAt: new Date().toISOString() };
      S.trips.push(trip); saveTrips(); go("trips", null, { trip: trip.id }); return;
    }
    if (f.dataset.tripNotes) {
      ev.preventDefault();
      const tr = S.trips.find((x) => x.id === f.dataset.tripNotes);
      if (tr) { tr.notes = new FormData(f).get("notes"); saveTrips(); toast("Notes saved"); }
      return;
    }
    if (f.dataset.myForm) {
      ev.preventDefault();
      const id = f.dataset.myForm, fd = new FormData(f);
      const m = S.my[id] || {};
      S.my[id] = { ...m, status: fd.get("status"), priority: !!fd.get("priority"), ref: fd.get("ref") || "", note: fd.get("note") || "", snapshot: snapshot(S.data.byId[id]) || m.snapshot };
      const tid = fd.get("trip");
      for (const tr of S.trips) {
        if (tr.id === tid && !tr.eventIds.includes(id)) tr.eventIds.push(id);
      }
      saveMy(); saveTrips(); toast("Saved"); render(); return;
    }
    if (f.id === "submit-form") {
      ev.preventDefault();
      const fd = new FormData(f);
      const url = String(fd.get("url") || "").trim();
      if (!/^https?:\/\//i.test(url)) { toast("Enter a public http(s) address"); return; }
      if (CFG.repo) {
        const u = `https://github.com/${CFG.repo}/issues/new?template=submit-url.yml&title=${encodeURIComponent("Submit: " + url.slice(0, 80))}&url=${encodeURIComponent(url)}&city=${encodeURIComponent(fd.get("city") || "")}&note=${encodeURIComponent(fd.get("note") || "")}`;
        window.open(u, "_blank", "noopener");
      } else {
        const y = `- url: ${url}\n  city: ${fd.get("city") || ""}\n  note: "${String(fd.get("note") || "").replace(/"/g, "'")}"\n  submitted_at: "${new Date().toISOString()}"\n`;
        navigator.clipboard?.writeText(y).then(() => toast("Copied — paste it into data/submissions.yaml"), () => toast("Copy failed; select the text manually"));
      }
    }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && $overlay.innerHTML) closeDrawer(); });
  document.getElementById("theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("atlas.theme", next);
  });
  const savedTheme = store.get("atlas.theme", null);
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;

  // ------------------------------------------------------------------ render
  function render() {
    if (!S.data) return;
    const route = parseRoute();
    renderChrome(route);
    let html;
    switch (route.page) {
      case "radar": html = pageRadar(route); break;
      case "briefing": html = pageBriefing(route); break;
      case "city": html = pageCity(route); break;
      case "trips": html = pageTrips(route); break;
      case "my": html = pageMy(route); break;
      case "sources": html = pageSources(route); break;
      case "health": html = pageHealth(route); break;
      case "search": html = pageSearch(route); break;
      default: html = pageOverview(route);
    }
    if (S.data.missing.includes("events")) html = `<div class="warn red" style="margin-bottom:18px">The event data could not be loaded (data/events.json). Run the pipeline, or check that the site was deployed with its data folder.</div>` + html;
    $main.innerHTML = html;
    if (route.q.e) openEvent(route.q.e);
  }
  let lastPage = null;
  window.addEventListener("hashchange", () => {
    const r = parseRoute();
    render();
    if (lastPage !== r.page + r.arg) { window.scrollTo(0, 0); lastPage = r.page + r.arg; }
  });
  setInterval(() => { if (!$overlay.innerHTML && ["overview", "city"].includes(parseRoute().page)) render(); }, 60000);

  loadData().then((raw) => { S.data = prepare(raw); render(); }).catch((err) => {
    $main.innerHTML = `<div class="warn red">Social Atlas could not start: ${esc(err.message)}</div>`;
  });

  // exposed for tests / debugging
  window.__atlas = { S, render, openEvent };
})();

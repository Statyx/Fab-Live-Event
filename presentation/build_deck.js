// Publicis Live — Live Event Center — Architecture Vision deck. Consulting-grade style
// (light canvas + white cards, color = meaning, Segoe UI, left→right pipeline architecture).
// Run: npm install && node build_deck.js
const pptxgen = require("pptxgenjs");

const C = {
  navy:   "16123A",  // deep indigo cover / architecture bg
  teal:   "7B5CFF",  // electric-violet primary accent (Live/event feel)
  red:    "E86A63",  // pain / congestion
  green:  "5FB877",  // success / value
  yellow: "E0A93B",  // logic / method
  blue:   "5A8DE0",  // personas / structure
  tealBg: "EEEAFC",
  blueBg: "EAF1FC",
  canvas: "F5F6F8",
  card:   "FFFFFF",
  ink:    "1F2A37",
  muted:  "5B6B7B",
  line:   "E2E6EB",
  white:  "FFFFFF",
};
const F = "Segoe UI";
const FS = "Segoe UI Semibold";
const W = 13.333, H = 7.5;

const pres = new pptxgen();
pres.defineLayout({ name: "W", width: W, height: H });
pres.layout = "W";
pres.author = "Clément Droinat";
pres.title = "Publicis Live — Live Event Operations — Architecture Vision";

const bg = (s, c) => (s.background = { color: c });
function topbar(s) { s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.14, fill: { color: C.teal }, line: { type: "none" } }); }
function pageTitle(s, kick, ttl) {
  s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 0.55, w: 0.16, h: 0.66, fill: { color: C.teal }, line: { type: "none" } });
  s.addText(kick.toUpperCase(), { x: 0.85, y: 0.5, w: 11, h: 0.3, fontFace: FS, fontSize: 12, color: C.teal, charSpacing: 2, bold: true });
  s.addText(ttl, { x: 0.83, y: 0.78, w: 11.8, h: 0.55, fontFace: FS, fontSize: 26, bold: true, color: C.ink });
}
function foot(s, n) {
  s.addText("LEC · Live Event Operations on Microsoft Fabric · Publicis Live", { x: 0.55, y: H - 0.4, w: 10, h: 0.3, fontFace: F, fontSize: 9, color: C.muted });
  s.addText(`${n}`, { x: W - 0.85, y: H - 0.4, w: 0.4, h: 0.3, fontFace: F, fontSize: 9, color: C.muted, align: "right" });
}
function block(s, x, y, w, h, accent, icon, header, bullets, opts = {}) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.06, fill: { color: opts.fill || C.card }, line: { color: C.line, width: 1 },
    shadow: { type: "outer", color: "8A97A6", blur: 7, offset: 2, angle: 90, opacity: 0.18 } });
  s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.12, w: 0.09, h: h - 0.24, fill: { color: accent }, line: { type: "none" } });
  s.addText([{ text: icon + "  ", options: { fontSize: 13 } }, { text: header, options: { bold: true, color: accent, fontSize: 13 } }],
    { x: x + 0.22, y: y + 0.14, w: w - 0.4, h: 0.36, fontFace: FS, valign: "middle" });
  if (bullets && bullets.length) {
    s.addText(bullets.map((b, i) => ({ text: b, options: { bullet: { indent: 12 }, breakLine: i < bullets.length - 1, color: C.ink } })),
      { x: x + 0.28, y: y + 0.54, w: w - 0.5, h: h - 0.66, fontFace: F, fontSize: opts.fs || 11.5, color: C.ink, valign: "top", lineSpacingMultiple: 1.05 });
  }
}
function arrow(s, x, y, w, c = C.teal) { s.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color: c, width: 2.5, endArrowType: "triangle" } }); }

// ── Slide 1 — Title ──
(() => {
  const s = pres.addSlide(); bg(s, C.navy); topbar(s);
  const nodes = [[10.7,1.4],[11.9,2.2],[10.3,3.0],[11.7,3.8],[12.5,2.8],[11.0,4.6]];
  for (const [a,b] of nodes) for (const [c,d] of nodes) if (a!==c) s.addShape(pres.shapes.LINE,{x:a+0.12,y:b+0.12,w:c-a,h:d-b,line:{color:"31285C",width:0.75}});
  for (const [a,b] of nodes) s.addShape(pres.shapes.OVAL,{x:a,y:b,w:0.24,h:0.24,fill:{color:C.teal},line:{type:"none"}});
  s.addShape(pres.shapes.OVAL,{x:10.3,y:3.0,w:0.24,h:0.24,fill:{color:C.red},line:{type:"none"}});

  s.addText("MICROSOFT FABRIC · FABRIC IQ", { x: 0.8, y: 1.55, w: 9, h: 0.4, fontFace: FS, fontSize: 13, color: C.teal, charSpacing: 4, bold: true });
  s.addText("Live Event Operations", { x: 0.75, y: 1.95, w: 10.0, h: 1.0, fontFace: FS, fontSize: 40, bold: true, color: C.white });
  s.addText("Publicis Live · Architecture Vision", { x: 0.78, y: 2.95, w: 10, h: 0.6, fontFace: F, fontSize: 22, color: C.teal });
  const pills = [["Detection","real-time crowd & queues",C.red],["Root cause","natural-language RCA",C.teal],["Business impact","VIP sponsors at risk",C.yellow]];
  pills.forEach((p,i)=>{ const x=0.8+i*3.0;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y:3.95,w:2.8,h:1.05,rectRadius:0.06,fill:{color:"221A4A"},line:{color:"31285C",width:1}});
    s.addShape(pres.shapes.RECTANGLE,{x,y:3.95,w:2.8,h:0.07,fill:{color:p[2]},line:{type:"none"}});
    s.addText(p[0],{x:x+0.2,y:4.1,w:2.5,h:0.4,fontFace:FS,fontSize:15,bold:true,color:C.white});
    s.addText(p[1],{x:x+0.2,y:4.5,w:2.5,h:0.4,fontFace:F,fontSize:11,color:"B4AAD8"});
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.82, y: 5.55, w: 2.4, h: 0.035, fill: { color: C.teal }, line: { type: "none" } });
  s.addText([{ text: "Clément Droinat", options: { bold: true, color: C.white, breakLine: true } }, { text: "Solution Engineer · Data & AI", options: { color: "B4AAD8" } }],
    { x: 0.8, y: 5.7, w: 9, h: 0.7, fontFace: F, fontSize: 13 });
})();

// ── Slide 2 — Use case 1: Detection ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "Use case · 01", "Real-time crowd & queue detection");
  const LX = 0.55, RX = 6.85, CW = 5.9;
  block(s, LX, 1.55, CW, 1.45, C.red, "⚠", "Today's pain", ["Congestion spotted too late, on the ground","Teams watch CCTV, no unified signal","Badges / vision / observations siloed","No link to sessions or sponsors"]);
  block(s, LX, 3.15, CW/2 - 0.12, 1.55, C.blue, "⬇", "Inputs", ["Badge passages (Kudelski)","Occupancy & density (XXII/Paradox)","Field observations (Dalux)"], { fs: 11 });
  block(s, LX + CW/2 + 0.12, 3.15, CW/2 - 0.12, 1.55, C.green, "⬆", "Outputs", ["Autonomous alert","Named gate / zone / metric","Recommended remediation"], { fs: 11 });
  block(s, LX, 4.85, CW, 1.55, C.yellow, "🔍", "Detection logic", ["Gate congestion: wait_time_s > 600 (10 min)","Zone saturation: occupancy_pct > 90","Crowd density > 4 · comfort < 30","Evaluated every 5 minutes on live data"]);

  block(s, RX, 1.55, CW, 1.45, C.blue, "👤", "Personas & scope", ["Operations lead → acts on alerts","Production → flow & staffing","Safety officer → crowd risk"]);
  block(s, RX, 3.15, CW, 1.55, C.teal, "⚙", "How Fabric does it", ["Operations Agent over Eventhouse / KQL","Auto-generated playbook (4 rules)","Alerts to Teams · runs autonomously","No pipelines to babysit"]);
  block(s, RX, 4.85, CW, 1.55, C.green, "✅", "Success criteria", ["Detect before attendee/safety impact","Mean-time-to-detect: minutes → seconds","Remediation suggested, human decides","KPI: fewer congestion & safety incidents"]);
  foot(s, 2);
})();

// ── Slide 3 — Use case 2: RCA & Impact ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "Use case · 02", "Root-cause & sponsor impact");
  const LX = 0.55, RX = 6.85, CW = 5.9;
  block(s, LX, 1.55, CW, 1.45, C.red, "⚠", "Today's pain", ["“Which session / sponsor is impacted?” = manual joins","Zones, telemetry, program in 3 tools","RCA takes an on-the-ground runaround","VIP exposure discovered too late"]);
  block(s, LX, 3.15, CW/2 - 0.12, 1.55, C.blue, "⬇", "Inputs", ["Natural-language question","Ontology (BIM topology)","Live telemetry bindings"], { fs: 11 });
  block(s, LX + CW/2 + 0.12, 3.15, CW/2 - 0.12, 1.55, C.green, "⬆", "Outputs", ["Culprit gate & zone","Impacted sessions","Ranked VIP sponsors"], { fs: 11 });
  block(s, LX, 4.85, CW, 1.55, C.yellow, "🔮", "RCA & impact logic", ["Multi-hop graph traversal (GQL)","Gate → Zone → Session → Customer","VIP flag surfaced first","BIM m² + live telemetry unified in ontology"]);

  block(s, RX, 1.55, CW, 1.45, C.blue, "👤", "Personas & scope", ["Ops lead → triage & RCA","Project manager → session impact","Account team → VIP sponsor care"]);
  block(s, RX, 3.15, CW, 1.55, C.teal, "⚙", "How Fabric does it", ["Data Agent over the Fabric IQ ontology","NL → GQL / KQL, 18 few-shots","Graph = traversal · KQL = time-series","One semantic layer, many questions"]);
  block(s, RX, 4.85, CW, 1.55, C.green, "✅", "Success criteria", ["RCA in seconds, in plain language","Impact in sessions & sponsors, not asset IDs","3 VIP sponsors surfaced instantly","KPI: faster, business-aware response"]);
  foot(s, 3);
})();

// ── Slide 4 — Solution ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "The solution", "Fabric IQ + autonomous agents");
  const cols = [
    ["1", "Data platform", C.blue, ["Lakehouse — BIM topology (Delta)","Eventhouse / KQL — live telemetry","Drop-zone ingest · notebooks"]],
    ["2", "Semantic layer", C.teal, ["Ontology — 8 entities · 9 relations","Graph Model — multi-hop GQL","TimeSeries bindings (BIM + KPIs)"]],
    ["3", "AI & consumption", C.yellow, ["Operations Agent — autonomous","Data Agent — NL → GQL/KQL","RTI dashboard (4 personas) · Activator"]],
  ];
  cols.forEach((c, i) => { const x = 0.55 + i * 4.16;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.6, w: 3.9, h: 2.35, rectRadius: 0.06, fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: { type: "outer", color: "8A97A6", blur: 7, offset: 2, angle: 90, opacity: 0.18 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: 1.85, w: 0.6, h: 0.6, fill: { color: c[2] }, line: { type: "none" } });
    s.addText(c[0], { x: x + 0.25, y: 1.85, w: 0.6, h: 0.6, fontFace: FS, fontSize: 20, bold: true, color: C.white, align: "center", valign: "middle" });
    s.addText(c[1], { x: x + 1.0, y: 1.9, w: 2.8, h: 0.5, fontFace: FS, fontSize: 16, bold: true, color: C.ink, valign: "middle" });
    s.addText(c[3].map((b, j) => ({ text: b, options: { bullet: { indent: 12 }, breakLine: j < c[3].length - 1 } })), { x: x + 0.3, y: 2.6, w: 3.4, h: 1.25, fontFace: F, fontSize: 11.5, color: C.ink, lineSpacingMultiple: 1.1 });
    if (i < 2) arrow(s, x + 3.9, 2.75, 0.24, C.muted);
  });
  const vals = [["Unified", "One workspace · OneLake · no ETL"], ["Real-time", "Live telemetry, sub-second traversal"], ["Agentic", "Detects & reasons, human in the loop"], ["Reusable", "One frame for every event / edition"]];
  vals.forEach((v, i) => { const x = 0.55 + i * 3.12;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 4.3, w: 2.95, h: 1.5, rectRadius: 0.06, fill: { color: C.tealBg }, line: { color: C.teal, width: 1 } });
    s.addText(v[0], { x: x + 0.2, y: 4.45, w: 2.6, h: 0.4, fontFace: FS, fontSize: 15, bold: true, color: C.teal });
    s.addText(v[1], { x: x + 0.2, y: 4.85, w: 2.6, h: 0.85, fontFace: F, fontSize: 11.5, color: C.ink, valign: "top" });
  });
  s.addText("This bridges business ↔ architecture: the same ontology powers every consumer.", { x: 0.55, y: 6.0, w: 12.2, h: 0.4, fontFace: F, fontSize: 13, italic: true, color: C.muted, align: "center" });
  foot(s, 4);
})();

// ── Slide 5 — Architecture (dark pipeline) ──
(() => {
  const s = pres.addSlide(); bg(s, C.navy); topbar(s);
  s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 0.55, w: 0.16, h: 0.66, fill: { color: C.teal }, line: { type: "none" } });
  s.addText("ARCHITECTURE", { x: 0.85, y: 0.5, w: 11, h: 0.3, fontFace: FS, fontSize: 12, color: C.teal, charSpacing: 2, bold: true });
  s.addText("End-to-end pipeline — one ontology, many consumers", { x: 0.83, y: 0.78, w: 11.8, h: 0.55, fontFace: FS, fontSize: 24, bold: true, color: C.white });

  const stages = [
    ["1", "SOURCES", C.blue, ["Badges · vision","Observations","BIM · program"]],
    ["2", "INGEST", C.blue, ["Drop zone","Pipelines","Notebooks → Delta"]],
    ["3", "STORE", C.teal, ["Lakehouse (BIM)","Eventhouse / KQL","(live telemetry)"]],
    ["4", "MODEL", C.teal, ["Fabric IQ ontology","Graph Model (GQL)","TimeSeries bindings"]],
    ["5", "REASON", C.yellow, ["Operations Agent","Data Agent","4-persona dashboard"]],
    ["6", "ACT", C.red, ["Ops lead","Autonomous alerts","VIP sponsor care"]],
  ];
  const n = stages.length, gap = 0.2, x0 = 0.6, sw = (W - 2 * x0 - (n - 1) * gap) / n, y = 2.0, sh = 3.7;
  stages.forEach((st, i) => { const x = x0 + i * (sw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: sw, h: sh, rectRadius: 0.06, fill: { color: "221A4A" }, line: { color: "31285C", width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: 0.62, fill: { color: st[2] }, line: { type: "none" } });
    s.addText(st[0], { x: x + 0.12, y: y + 0.06, w: 0.5, h: 0.5, fontFace: FS, fontSize: 18, bold: true, color: C.navy, valign: "middle" });
    s.addText(st[1], { x: x + 0.5, y: y + 0.06, w: sw - 0.55, h: 0.5, fontFace: FS, fontSize: 13, bold: true, color: C.navy, valign: "middle" });
    s.addText(st[3].map((b, j) => ({ text: b, options: { breakLine: j < st[3].length - 1 } })), { x: x + 0.16, y: y + 0.8, w: sw - 0.3, h: sh - 1.0, fontFace: F, fontSize: 10.5, color: "DAD3F0", valign: "top", lineSpacingMultiple: 1.15 });
    if (i < n - 1) s.addShape(pres.shapes.LINE, { x: x + sw + 0.02, y: y + sh / 2, w: gap - 0.04, h: 0, line: { color: C.teal, width: 2, endArrowType: "triangle" } });
  });
  s.addText("Built once, consumed everywhere — the ontology is the keystone between detection, RCA and impact.", { x: 0.6, y: 6.05, w: 12.1, h: 0.4, fontFace: F, fontSize: 13, italic: true, color: C.teal, align: "center" });
  foot(s, 5);
})();

// ── Slide 6 — 4 persona reports ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "Reporting", "Four persona reports, one model");
  const p = [
    ["Management", C.teal, ["Peak attendees · avg occupancy","m² utilization · decision points","Critical alarms at a glance"]],
    ["Production", C.red, ["Gate wait-time & worst gates","Crowd density risk","Live alarms & flow"]],
    ["Chefs de projet", C.yellow, ["Session/zone fill rate","Zones over 90% occupancy","Comfort index · observations"]],
    ["Client (sponsor)", C.green, ["Salle Aspen occupancy & comfort","Sponsored-zone attendance","Premium-zone experience"]],
  ];
  p.forEach((c, i) => { const col = i % 2, row = Math.floor(i / 2);
    const x = 0.7 + col * 6.1, y = 1.75 + row * 2.15;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 5.8, h: 1.9, rectRadius: 0.06, fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: { type: "outer", color: "8A97A6", blur: 7, offset: 2, angle: 90, opacity: 0.18 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 5.8, h: 0.07, fill: { color: c[1] }, line: { type: "none" } });
    s.addText(c[0], { x: x + 0.25, y: y + 0.2, w: 5.3, h: 0.4, fontFace: FS, fontSize: 17, bold: true, color: c[1] });
    s.addText(c[2].map((b, j) => ({ text: b, options: { bullet: { indent: 12 }, breakLine: j < c[2].length - 1 } })), { x: x + 0.3, y: y + 0.7, w: 5.3, h: 1.1, fontFace: F, fontSize: 12.5, color: C.ink, valign: "top" });
  });
  s.addText("Real-time (30s refresh) — comparison silos per client, extensible edition N vs N-1.", { x: 0.7, y: 6.05, w: 11.9, h: 0.4, fontFace: F, fontSize: 13, italic: true, color: C.muted, align: "center" });
  foot(s, 6);
})();

// ── Slide 7 — Demo storyline ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "The demo", "One gate → three VIP sponsors");
  const chain = [
    ["GATE-05", "Access gate · Aspen", "queue ≈ 25 min", C.red],
    ["Salle Aspen", "zone saturates", "occupancy > 90 · density up", C.yellow],
    ["Sessions", "AI for Good", "Beauty & AI · Smart City", C.teal],
    ["3 VIP sponsors", "Microsoft", "L'Oreal · Ville de Paris", C.green],
  ];
  chain.forEach((c, i) => { const x = 0.55 + i * 3.18;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.3, w: 2.75, h: 2.15, rectRadius: 0.06, fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: { type: "outer", color: "8A97A6", blur: 7, offset: 2, angle: 90, opacity: 0.18 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.3, w: 2.75, h: 0.08, fill: { color: c[3] }, line: { type: "none" } });
    s.addText(c[0], { x: x + 0.2, y: 2.55, w: 2.4, h: 0.6, fontFace: FS, fontSize: 15, bold: true, color: i === 0 ? C.red : (i === 3 ? C.green : C.ink) });
    s.addText([{ text: c[1], options: { breakLine: true, color: C.ink } }, { text: c[2], options: { color: C.muted, fontSize: 11 } }], { x: x + 0.2, y: 3.2, w: 2.45, h: 1.1, fontFace: F, fontSize: 12, valign: "top" });
    if (i < 3) arrow(s, x + 2.78, 3.35, 0.36, C.muted);
  });
  const acts = [["ACT 1 · Detect","Operations Agent alerts autonomously",C.red],["ACT 2 · Diagnose","Data Agent RCA via the graph",C.teal],["ACT 3 · Impact","VIP sponsors surfaced",C.green]];
  acts.forEach((a,i)=>{ const x=0.55+i*4.16;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y:4.95,w:3.9,h:1.15,rectRadius:0.06,fill:{color:C.card},line:{color:a[2],width:1.25}});
    s.addText(a[0],{x:x+0.2,y:5.08,w:3.6,h:0.4,fontFace:FS,fontSize:13,bold:true,color:a[2]});
    s.addText(a[1],{x:x+0.2,y:5.46,w:3.6,h:0.55,fontFace:F,fontSize:11.5,color:C.ink,valign:"top"});
  });
  foot(s, 7);
})();

// ── Slide 8 — Roadmap ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "Roadmap", "Phase 1 → phase 2");
  const rows = [
    ["Batch daily reports", "Drop zone → Lakehouse → 4 persona dashboards", "PHASE 1", C.green],
    ["Real-time detection", "Eventhouse + Operations Agent + Data Activator", "PHASE 1", C.green],
    ["Data Agent (NL Q&A)", "Session fill · wait peaks · VIP impact", "PHASE 1", C.green],
    ["Edition N vs N-1", "Cross-edition comparison, same geometry", "NEXT", C.teal],
    ["More sources", "Kudelski / XXII / Paradox / Dalux live feeds", "PLANNED", C.yellow],
    ["Foundry phase 2", "Agent per event acts on the same ontology", "FUTURE", C.blue],
  ];
  rows.forEach((r, i) => { const y = 1.65 + i * 0.82;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.55, y, w: 12.2, h: 0.7, rectRadius: 0.05, fill: { color: C.card }, line: { color: C.line, width: 1 } });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.75, y: y + 0.17, w: 1.5, h: 0.36, rectRadius: 0.18, fill: { color: r[3] }, line: { type: "none" } });
    s.addText(r[2], { x: 0.75, y: y + 0.17, w: 1.5, h: 0.36, fontFace: FS, fontSize: 9.5, bold: true, color: C.white, align: "center", valign: "middle" });
    s.addText([{ text: r[0] + "    ", options: { bold: true, color: C.ink } }, { text: r[1], options: { color: C.muted, fontSize: 12 } }], { x: 2.5, y, w: 10.1, h: 0.7, fontFace: F, fontSize: 14, valign: "middle" });
  });
  foot(s, 8);
})();

// ── Slide 9 — Vision Foundry ──
(() => {
  const s = pres.addSlide(); bg(s, C.canvas); pageTitle(s, "Vision", "Fabric IQ today — Foundry tomorrow");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.55, y: 1.65, w: 5.9, h: 3.7, rectRadius: 0.06, fill: { color: C.card }, line: { color: C.teal, width: 1.25 }, shadow: { type: "outer", color: "8A97A6", blur: 7, offset: 2, angle: 90, opacity: 0.18 } });
  s.addText("TODAY · Microsoft Fabric", { x: 0.85, y: 1.85, w: 5.4, h: 0.4, fontFace: FS, fontSize: 14, bold: true, color: C.teal, charSpacing: 1 });
  s.addText([
    { text: "Read & reason over the ontology", options: { bold: true, color: C.ink, breakLine: true, fontSize: 15 } },
    { text: "Data Agent — interactive NL Q&A", options: { bullet: { indent: 12 }, color: C.ink, breakLine: true } },
    { text: "Operations Agent — autonomous monitoring", options: { bullet: { indent: 12 }, color: C.ink, breakLine: true } },
    { text: "RTI dashboard (4 personas) + Data Activator", options: { bullet: { indent: 12 }, color: C.ink } },
  ], { x: 0.85, y: 2.4, w: 5.3, h: 2.7, fontFace: F, fontSize: 13, lineSpacingMultiple: 1.3 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 6.85, y: 1.65, w: 5.9, h: 3.7, rectRadius: 0.06, fill: { color: C.blueBg }, line: { color: C.blue, width: 1.25 } });
  s.addText("TOMORROW · Microsoft Foundry", { x: 7.15, y: 1.85, w: 5.4, h: 0.4, fontFace: FS, fontSize: 14, bold: true, color: C.blue, charSpacing: 1 });
  s.addText([
    { text: "An agent per event, on the same ontology", options: { bold: true, color: C.ink, breakLine: true, fontSize: 15 } },
    { text: "Project teams ask in natural language", options: { bullet: { indent: 12 }, color: C.ink, breakLine: true } },
    { text: "Answers span current + previous editions", options: { bullet: { indent: 12 }, color: C.ink, breakLine: true } },
    { text: "Client perimeter respected (data isolation)", options: { bullet: { indent: 12 }, color: C.ink } },
  ], { x: 7.15, y: 2.4, w: 5.3, h: 2.7, fontFace: F, fontSize: 13, lineSpacingMultiple: 1.3 });

  arrow(s, 6.35, 3.5, 0.55, C.blue);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.55, y: 5.6, w: 12.2, h: 0.75, rectRadius: 0.06, fill: { color: C.tealBg }, line: { color: C.teal, width: 1 } });
  s.addText("The ontology is built once — Fabric is the brain, Foundry agents are the hands.", { x: 0.55, y: 5.6, w: 12.2, h: 0.75, fontFace: FS, fontSize: 15, italic: true, bold: true, color: C.ink, align: "center", valign: "middle" });
  foot(s, 9);
})();

// ── Slide 10 — Closing ──
(() => {
  const s = pres.addSlide(); bg(s, C.navy); topbar(s);
  s.addText("From signal to decision —\nwhile the event is live.", { x: 0.8, y: 2.2, w: 11.7, h: 1.9, fontFace: FS, fontSize: 36, bold: true, color: C.white, lineSpacingMultiple: 1.05 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.85, y: 4.15, w: 2.4, h: 0.04, fill: { color: C.teal }, line: { type: "none" } });
  s.addText([
    { text: "Autonomous detection", options: { color: C.red, bold: true } },
    { text: "   →   ", options: { color: "B4AAD8" } },
    { text: "natural-language RCA", options: { color: C.teal, bold: true } },
    { text: "   →   ", options: { color: "B4AAD8" } },
    { text: "quantified sponsor impact", options: { color: C.yellow, bold: true } },
  ], { x: 0.8, y: 4.5, w: 11.7, h: 0.6, fontFace: F, fontSize: 18 });
  s.addText("Clément Droinat · Solution Engineer, Data & AI", { x: 0.8, y: 6.4, w: 11.7, h: 0.4, fontFace: F, fontSize: 13, color: "B4AAD8" });
})();

pres.writeFile({ fileName: "LEC_Architecture_Vision.pptx" }).then(f => console.log("OK:", f));

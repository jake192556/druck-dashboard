/* 유동성 나침반 — 정적 PWA. data/latest.json 하나만 읽는다. */
(() => {
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const tone = (v) => (v == null ? "neutral" : v >= 15 ? "good" : v <= -15 ? "bad" : "neutral");
  const toneColor = (v) => css(`--${tone(v)}`);
  const signed = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + v);

  function svg(tag, attrs = {}, parent) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }

  // ------------------------------------------------------------ gauge
  function drawGauge(score) {
    const g = $("gauge");
    g.innerHTML = "";
    const cx = 100, cy = 100, r = 80;
    const pt = (s) => {
      const a = Math.PI * (1 - (s + 100) / 200);
      return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
    };
    const arc = (a, b, color, w = 14) => {
      const [x1, y1] = pt(a), [x2, y2] = pt(b);
      svg("path", { d: `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`, stroke: color, "stroke-width": w, fill: "none", "stroke-linecap": "butt" }, g);
    };
    arc(-100, -15, css("--bad"));
    arc(-15, 15, css("--neutral"));
    arc(15, 100, css("--good"));
    const s = Math.max(-100, Math.min(100, score));
    const [nx, ny] = pt(s);
    svg("line", { x1: cx, y1: cy, x2: nx, y2: ny, stroke: css("--text"), "stroke-width": 3, "stroke-linecap": "round" }, g);
    svg("circle", { cx, cy, r: 6, fill: css("--text") }, g);
    [["-100", 18], ["0", 100], ["+100", 182]].forEach(([lab, x]) => {
      const tt = svg("text", { x, y: x === 100 ? 12 : 116, "text-anchor": "middle", fill: css("--muted"), "font-size": 9 }, g);
      tt.textContent = lab;
    });
  }

  // ------------------------------------------------------------ line charts
  function scale(vals, h, pad) {
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (lo === hi) { lo -= 1; hi += 1; }
    return { lo, hi, y: (v) => pad + (h - 2 * pad) * (1 - (v - lo) / (hi - lo)) };
  }

  function scoreChart(el, pts) {
    el.innerHTML = "";
    if (!pts || pts.length < 2) { el.textContent = "데이터 없음"; return; }
    const W = 340, H = 150, P = 14;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}` }, el);
    const x = (i) => 28 + (W - 36) * (i / (pts.length - 1));
    const y = (v) => P + (H - 2 * P) * (1 - (v + 100) / 200);
    // 구간 배경
    [[100, 15, "--good"], [15, -15, "--neutral"], [-15, -100, "--bad"]].forEach(([a, b, c]) => {
      svg("rect", { x: 28, y: y(a), width: W - 36, height: y(b) - y(a), fill: css(c), opacity: 0.07 }, s);
    });
    [100, 50, 0, -50, -100].forEach((v) => {
      svg("line", { x1: 28, x2: W - 8, y1: y(v), y2: y(v), stroke: css("--line"), "stroke-width": v === 0 ? 1.2 : 0.6 }, s);
      const t = svg("text", { x: 22, y: y(v) + 3, "text-anchor": "end", fill: css("--muted"), "font-size": 9 }, s);
      t.textContent = v;
    });
    const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[1]).toFixed(1)}`).join("");
    svg("path", { d, fill: "none", stroke: css("--accent"), "stroke-width": 2, "stroke-linejoin": "round" }, s);
    const last = pts[pts.length - 1];
    svg("circle", { cx: x(pts.length - 1), cy: y(last[1]), r: 4, fill: toneColor(last[1]) }, s);
    dateTicks(s, pts, x, H);
  }

  function dualChart(el, pts) {
    el.innerHTML = "";
    if (!pts || pts.length < 2) { el.textContent = "데이터 없음"; return; }
    const W = 340, H = 160, P = 16;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}` }, el);
    const x = (i) => 8 + (W - 16) * (i / (pts.length - 1));
    const a = scale(pts.map((p) => p[1]), H - 14, P);
    const b = scale(pts.map((p) => p[2]), H - 14, P);
    [0.25, 0.5, 0.75].forEach((f) => svg("line", { x1: 8, x2: W - 8, y1: P + (H - 14 - 2 * P) * f, y2: P + (H - 14 - 2 * P) * f, stroke: css("--line"), "stroke-width": 0.6 }, s));
    const path = (sc, k) => pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${sc.y(p[k]).toFixed(1)}`).join("");
    svg("path", { d: path(b, 2), fill: "none", stroke: css("--accent2"), "stroke-width": 1.6, opacity: 0.85 }, s);
    svg("path", { d: path(a, 1), fill: "none", stroke: css("--accent"), "stroke-width": 2 }, s);
    const last = pts[pts.length - 1];
    const t1 = svg("text", { x: W - 8, y: 12, "text-anchor": "end", fill: css("--accent"), "font-size": 10 }, s);
    t1.textContent = `$${(last[1] / 1000).toFixed(2)}T`;
    const t2 = svg("text", { x: 8, y: 12, fill: css("--accent2"), "font-size": 10 }, s);
    t2.textContent = `SPY ${last[2]}`;
    dateTicks(s, pts, x, H);
  }

  function dateTicks(s, pts, x, H) {
    const n = pts.length;
    [0, Math.floor(n / 2), n - 1].forEach((i, k) => {
      const t = svg("text", { x: x(i), y: H - 2, "text-anchor": ["start", "middle", "end"][k], fill: css("--muted"), "font-size": 9 }, s);
      t.textContent = pts[i][0].slice(0, 7);
    });
  }

  function rsChart(el, rows) {
    el.innerHTML = "";
    if (!rows || !rows.length) { el.textContent = "데이터 없음"; return; }
    const m = Math.max(5, ...rows.map((r) => Math.abs(r.rel)));
    for (const r of rows) {
      const w = (Math.abs(r.rel) / m) * 50;
      const left = r.rel >= 0 ? 50 : 50 - w;
      const color = r.rel >= 2 ? css("--good") : r.rel <= -2 ? css("--bad") : css("--neutral");
      el.insertAdjacentHTML("beforeend", `
        <div class="rs-row">
          <div>${esc(r.name)} <span class="muted small">${esc(r.ticker)}</span></div>
          <div class="rs-track"><span class="mid"></span><span class="rs-bar" style="left:${left}%;width:${w}%;background:${color}"></span></div>
          <div class="rs-val" style="color:${color}">${r.rel > 0 ? "+" : ""}${r.rel.toFixed(1)}</div>
        </div>`);
    }
  }

  // ------------------------------------------------------------ lists
  function fmtVal(i) {
    if (i.value == null) return "";
    const v = Math.abs(i.value) >= 1000 ? i.value.toLocaleString("ko-KR", { maximumFractionDigits: 0 }) : i.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
    return `${v}${i.unit ? " " + i.unit : ""}`;
  }

  function indItem(i) {
    const cls = i.info ? "info" : i.signal == null ? "info" : `s${i.signal}`;
    return `<li>
      <div class="ind-head"><span class="ind-name"><span class="dot ${cls}"></span>${esc(i.name)}</span><span class="ind-val">${esc(fmtVal(i))}</span></div>
      <div class="ind-change">${esc(i.change_label)}${i.info ? ' <span class="muted small">(참고)</span>' : ""}</div>
      <div class="ind-note">${esc(i.note)}</div>
    </li>`;
  }

  function list(el, items) {
    el.innerHTML = items && items.length ? items.map((t) => `<li>${esc(t)}</li>`).join("") : `<li class="empty">없음</li>`;
  }

  function pillars(el, ps) {
    el.innerHTML = "";
    for (const p of ps) {
      const sc = p.score;
      const w = sc == null ? 0 : Math.abs(sc) / 2;
      const left = sc == null ? 50 : sc >= 0 ? 50 : 50 - w;
      el.insertAdjacentHTML("beforeend", `
        <details class="card pillar">
          <summary>
            <span class="p-name">${esc(p.name)}<span class="p-weight">가중치 ${Math.round(p.weight * 100)}%</span></span>
            <span class="pill ${tone(sc)}">${signed(sc)}</span>
            <div class="p-bar"><span class="mid"></span><span style="left:${left}%;width:${w}%;background:${toneColor(sc)}"></span></div>
          </summary>
          <ul class="ind-list">${p.indicators.map(indItem).join("") || '<li class="muted">데이터 없음</li>'}</ul>
        </details>`);
    }
  }

  // ------------------------------------------------------------ render
  function render(d) {
    const gen = d.generated_at ? new Date(d.generated_at).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "";
    $("asof").textContent = `기준일 ${d.asof} · 갱신 ${gen}`;

    document.querySelectorAll(".banner").forEach((b) => b.remove());
    if (d.sample) banner("샘플(가짜) 데이터입니다. GitHub Actions가 처음 실행되면 실제 데이터로 바뀝니다.");
    if (d.missing && d.missing.length) banner(`일부 데이터 누락: ${d.missing.join(", ")}`);

    drawGauge(d.score);
    $("regime").textContent = `${signed(d.score)} · ${d.regime.label}`;
    $("regime").style.color = toneColor(d.score);
    $("regimeDesc").textContent = d.regime.desc;

    $("stance").textContent = d.brief.stance;
    $("leadership").textContent = d.brief.leadership ? "🏁 " + d.brief.leadership : "";
    $("koreaLine").textContent = d.brief.korea ? "🇰🇷 " + d.brief.korea : "";
    list($("supports"), d.brief.supports);
    list($("risks"), d.brief.risks);
    list($("watch"), d.brief.watch);

    scoreChart($("scoreChart"), d.charts?.score_history);
    dualChart($("liqChart"), d.charts?.liquidity);
    rsChart($("rsChart"), d.charts?.relative);
    pillars($("pillars"), d.pillars);

    const ks = d.korea?.score;
    $("koreaScore").textContent = signed(ks);
    $("koreaScore").className = `pill ${tone(ks)}`;
    $("koreaList").innerHTML = (d.korea?.indicators || []).map(indItem).join("") || '<li class="muted">데이터 없음</li>';
  }

  function banner(text, err) {
    const b = document.createElement("div");
    b.className = "banner" + (err ? " err" : "");
    b.textContent = text;
    $("app").prepend(b);
  }

  async function load() {
    $("refreshBtn").disabled = true;
    try {
      const r = await fetch(`data/latest.json?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      render(d);
      try { localStorage.setItem("lc_last", JSON.stringify(d)); } catch (_) {}
    } catch (e) {
      let cached = null;
      try { cached = JSON.parse(localStorage.getItem("lc_last")); } catch (_) {}
      if (cached) { render(cached); banner("오프라인 — 마지막으로 받은 데이터를 표시합니다."); }
      else banner("데이터를 불러오지 못했습니다. 잠시 후 다시 시도하세요.", true);
    } finally {
      $("refreshBtn").disabled = false;
    }
  }

  // ------------------------------------------------------------ PWA
  let deferred;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    $("installBtn").hidden = false;
  });
  $("installBtn").addEventListener("click", async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    $("installBtn").hidden = true;
  });
  $("refreshBtn").addEventListener("click", load);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }

  load();
})();

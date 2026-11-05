// Browserversion der Stadtkarten-Werkstatt: leitet die /api-Aufrufe der Oberfläche (stadtkarte/ui/index.html) an
// den Web Worker (worker.js) um, in dem der Python-Kern mit Pyodide läuft. Die Oberfläche selbst bleibt unverändert.
(() => {
  const worker = new Worker(new URL("worker.js", document.currentScript.src), {type: "module"});
  const offen = new Map();
  let nr = 0;
  worker.onmessage = e => { const p = offen.get(e.data.id); offen.delete(e.data.id); p && p(e.data); };
  worker.onerror = e => { for (const p of offen.values()) p({status: 500, ctype: "application/json", body: new TextEncoder().encode(JSON.stringify({error: "Der Rechenteil im Browser ist abgestürzt: " + (e.message || "unbekannt")}))}); offen.clear(); };
  const frage = msg => new Promise(res => { const id = ++nr; offen.set(id, res); worker.postMessage({...msg, id}); });

  // Messwerte für den Prototyp: in der Konsole und unter window.stadtkarteZeiten
  const zeiten = window.stadtkarteZeiten = {laden: null, anfragen: []};
  const t0 = performance.now();
  const hinweis = document.createElement("div");
  hinweis.style.cssText = "position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:99;padding:8px 14px;" +
    "border-radius:6px;background:#2b2118;color:#f3e9d2;font:14px/1.4 Spectral,Georgia,serif;box-shadow:0 2px 8px #0005";
  hinweis.textContent = "Die Werkstatt wird im Browser geladen (beim ersten Mal rund 30 MB) …";
  document.addEventListener("DOMContentLoaded", () => document.body.append(hinweis));
  const bereit = frage({method: "READY"}).then(r => {
    if (!r.ready) throw new Error(new TextDecoder().decode(r.body));
    zeiten.laden = {...r.ready, gesamt: performance.now() - t0};
    console.info("Werkstatt geladen:", Object.entries(zeiten.laden).map(([k, v]) => `${k} ${(v / 1000).toFixed(1)} s`).join(", "));
    hinweis.remove();
  }).catch(e => { hinweis.textContent = "Die Werkstatt konnte nicht geladen werden: " + e.message; throw e; });

  const echt = window.fetch.bind(window);
  async function api(url, opts = {}) {
    await bereit;
    const u = new URL(url, location.href);
    const t = performance.now();
    const r = await frage({method: (opts.method || "GET").toUpperCase(), path: u.pathname.replace(/^.*(\/api\/)/, "$1"),
                           query: u.search, body: opts.body || ""});
    const ms = performance.now() - t;
    zeiten.anfragen.push({pfad: u.pathname.replace(/^.*\/api\//, "/api/") + u.search, ms: Math.round(ms), python_ms: Math.round(r.ms || 0)});
    console.info(`${u.pathname.replace(/^.*\/api\//, "/api/")}${u.search}: ${(ms / 1000).toFixed(2)} s`);
    return r;
  }
  const antwort = r => new Response(r.body, {status: r.status, headers: {"Content-Type": r.ctype}});
  const speichern = r => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([r.body], {type: r.ctype}));
    a.download = r.filename || "stadtkarte";
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  };

  window.fetch = async (url, opts) => {
    const pfad = new URL(String(url), location.href).pathname;
    if (!/\/api\//.test(pfad)) return echt(url, opts);
    const r = await api(String(url), opts);
    if (/\/api\/save$/.test(pfad) && r.status === 200) {   // „Alles speichern“: ein ZIP in den Download-Ordner
      speichern(r);
      return new Response(JSON.stringify({paths: [r.filename], folder: "den Download-Ordner"}),
                          {status: 200, headers: {"Content-Type": "application/json"}});
    }
    return antwort(r);
  };
  window.stadtkarteDownload = async url => {
    const r = await api(url);
    if (r.status === 200) return speichern(r);
    let msg = r.status; try { msg = JSON.parse(new TextDecoder().decode(r.body)).error; } catch (e) {}
    alert("Download fehlgeschlagen: " + msg);
  };
})();

// Web Worker der Browserversion: lädt Pyodide, den Python-Kern der Werkstatt und resvg-wasm und beantwortet die
// /api-Anfragen der Oberfläche (werkstatt.js) nacheinander mit stadtkarte/ui/browser.py.
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";
import { initWasm, Resvg } from "https://cdn.jsdelivr.net/npm/@resvg/resvg-wasm@2.6.2/index.mjs";

const APP = "/home/pyodide/werkstatt";
let py, handle;
const fonts = new Map();

// Für resvg_py.py: SVG -> PNG (zoom 0 = volle Größe); Schriften liegen im Dateisystem von Pyodide
self.stadtkarteRender = (svg, zoom, fontFiles) => {
  const buffers = fontFiles.map(f => { if (!fonts.has(f)) fonts.set(f, py.FS.readFile(f)); return fonts.get(f); });
  const opts = {font: {fontBuffers: buffers, loadSystemFonts: false, defaultFontFamily: "EB Garamond"}};
  if (zoom) opts.fitTo = {mode: "zoom", value: zoom};
  const r = new Resvg(svg, opts);
  const img = r.render();
  const png = img.asPng();
  img.free(); r.free();
  return png;
};

const zeit = {};
const bereit = (async () => {
  let t = performance.now();
  const [pyodide, , zip] = await Promise.all([
    loadPyodide(),
    initWasm(fetch("https://cdn.jsdelivr.net/npm/@resvg/resvg-wasm@2.6.2/index_bg.wasm")),
    fetch(new URL("werkstatt.zip", import.meta.url)).then(r => { if (!r.ok) throw new Error("werkstatt.zip fehlt"); return r.arrayBuffer(); }),
  ]);
  py = pyodide;
  zeit.pyodide = performance.now() - t; t = performance.now();
  await py.loadPackage(["numpy", "shapely", "pillow", "pyyaml"]);
  zeit.pakete = performance.now() - t; t = performance.now();
  py.unpackArchive(zip, "zip", {extractDir: APP});
  py.runPython(`import sys, os; sys.path.insert(0, "${APP}"); os.chdir("${APP}")`);
  handle = py.pyimport("stadtkarte.ui.browser").handle;
  zeit.werkstatt = performance.now() - t;
  return zeit;
})();

self.onmessage = async e => {
  const {id, method, path, query, body} = e.data;
  try {
    if (method === "READY") return self.postMessage({id, ready: await bereit});
    await bereit;
    const t = performance.now();
    const r = handle(method, path, query || "", body || "");
    const res = r.toJs({dict_converter: Object.fromEntries});
    r.destroy();
    const out = res.body;   // Uint8Array
    self.postMessage({id, status: res.status, ctype: res.ctype, filename: res.filename, body: out,
                      ms: performance.now() - t}, [out.buffer]);
  } catch (err) {
    self.postMessage({id, status: 500, ctype: "application/json; charset=utf-8",
                      body: new TextEncoder().encode(JSON.stringify({error: String(err.message || err)}))});
  }
};

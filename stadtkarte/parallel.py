"""Rendern (SVG -> PNG) und Rauschtexturen in eigenen Prozessen.

resvg hält während des Renderns die GIL, Threads helfen daher nicht. Mehrere voneinander unabhängige Bilder
(Vorschau, volle Ansicht, PNG mit Beschriftung, Bild der interaktiven Karte) entstehen so gleichzeitig auf
mehreren Kernen, und der Hauptprozess bleibt frei. Das Modul ist absichtlich schlank: ein Render-Prozess lädt
nur resvg, nicht numpy, Shapely oder den Generator.

Dieselben Prozesse rechnen vorab die Texturen, die nicht von der Stadt abhängen (render.prewarm), während der Generator
im Hauptprozess läuft. Threads statt Prozesse bremsten den Generator durch die gemeinsame GIL stärker, als sie einbrachten.

Klappt der Prozess-Pool nicht (z.B. eingeschränkte Umgebung), wird wie bisher im eigenen Prozess gerendert.
Im Browser (Pyodide) gibt es weder Prozesse noch Threads: dort wird von Anfang an seriell gerechnet.
"""
import multiprocessing
import os
import sys
import threading
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

BROWSER = sys.platform == "emscripten"   # Pyodide: keine Prozesse, keine Threads
_POOL = None
_BROKEN = BROWSER
_LOCK = threading.Lock()


def _watch_parent():
    """Läuft in jedem Render-Prozess: endet das Hauptprogramm (auch hart, z.B. per kill), endet er mit."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def wait():
        parent.join()
        os._exit(0)
    threading.Thread(target=wait, daemon=True).start()


def _render(svg, zoom, font):
    import resvg_py
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=zoom, font_files=[font] if font else None))


def _font():
    from .styles import FONT_FILE
    return str(FONT_FILE) if FONT_FILE.exists() else None


def _pool():
    global _POOL
    with _LOCK:
        if _POOL is None and not _BROKEN:
            workers = max(1, min(3, os.cpu_count() or 1))
            _POOL = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                                        initializer=_watch_parent)
        return _POOL


def _give_up():
    """Pool unbrauchbar: künftig im eigenen Prozess rendern."""
    global _POOL, _BROKEN
    with _LOCK:
        _BROKEN = True
        pool, _POOL = _POOL, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


class _Job:
    """Wie ein Future (result()), rendert aber selbst, falls der Render-Prozess ausfällt. Ein Fehler des Auftrags
    selbst (z.B. ein ungültiges SVG) kommt unverändert beim Aufrufer an und lässt den Pool in Ruhe."""

    def __init__(self, fut, args):
        self._fut, self._args = fut, args

    def cancel(self):
        """Nimmt einen Auftrag zurück, der noch wartet (läuft er schon, läuft er zu Ende). Wird sein Ergebnis später
        doch gebraucht, rendert result() selbst."""
        return self._fut.cancel()

    def result(self):
        try:
            return self._fut.result()
        except CancelledError:   # zurückgenommen und doch gebraucht: der Pool ist in Ordnung, nur selbst rendern
            return _render(*self._args)
        except (BrokenProcessPool, OSError):   # Prozess abgestürzt, beendet oder nicht erreichbar
            _give_up()
            return _render(*self._args)


def _texturen(specs):
    """Läuft im Render-Prozess: Rauschtexturen und Papier nacheinander. specs: [("textur" | "papier", Argumente), ...]."""
    out = []
    for kind, args in specs:
        if kind == "textur":
            from .noise import _texture
            out.append(_texture(*args))
        else:
            from .papier import _image
            out.append(_image(*args))
    return out


def submit_texturen(specs):
    """Rechnet Texturen in einem Render-Prozess; liefert ein Future mit den Data-URIs oder None, wenn kein Pool da ist."""
    pool = _pool()
    if pool is None:
        return None
    try:
        return pool.submit(_texturen, specs)
    except Exception:
        _give_up()
        return None


def mode():
    """'prozesse', solange der Pool arbeitet, sonst 'seriell' (für Statusanzeige und Selbsttest)."""
    return "seriell" if _BROKEN else "prozesse"


def shutdown():
    """Render-Prozesse beenden (beim Schließen der Werkstatt)."""
    global _POOL
    with _LOCK:
        pool, _POOL = _POOL, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


class Sofort:
    """Wie ein ThreadPoolExecutor, rechnet aber sofort im Aufrufer (für den Browser, wo es keine Threads gibt)."""

    def submit(self, fn, *args, **kw):
        done = Future()
        try:
            done.set_result(fn(*args, **kw))
        except Exception as e:  # noqa: BLE001 - wie beim Pool erst bei result()
            done.set_exception(e)
        return done


def png_async(svg, zoom=None):
    """Startet das Rendern im Hintergrund; .result() liefert die PNG-Bytes."""
    args = (svg, zoom, _font())
    pool = _pool()
    if pool is not None:
        try:
            return _Job(pool.submit(_render, *args), args)
        except Exception:
            _give_up()
    done = Future()   # kein Pool: hier rendern; ein Fehler kommt wie beim Pool erst bei result()
    try:
        done.set_result(_render(*args))
    except Exception as e:  # noqa: BLE001 - an result() weiterreichen
        done.set_exception(e)
    return done

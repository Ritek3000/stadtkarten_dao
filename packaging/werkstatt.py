"""Startpunkt des gebündelten Programms (PyInstaller): öffnet die Stadtkarten-Werkstatt im Browser."""
import os
import sys

if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    # PyInstaller setzt LD_LIBRARY_PATH auf den Programmordner. Aufgerufene Programme (xdg-open, /bin/sh)
    # würden sonst die mitgebrachten Bibliotheken laden, z.B. eine fremde libreadline
    # ("symbol lookup error: /bin/sh: undefined symbol: rl_trim_arg_from_keyseq").
    # Das eigene Programm ist bereits geladen; die Änderung wirkt nur auf gestartete Unterprozesse.
    orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        os.environ["LD_LIBRARY_PATH"] = orig
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)

import multiprocessing  # noqa: E402

if __name__ == "__main__":
    # Render-Prozesse (stadtkarte/parallel.py) starten das gebündelte Programm erneut; freeze_support übernimmt
    # sie hier, bevor die Oberfläche geladen wird
    multiprocessing.freeze_support()

from stadtkarte.ui.__main__ import main  # noqa: E402  (erst nach dem Bereinigen der Umgebung importieren)

if __name__ == "__main__":
    main()

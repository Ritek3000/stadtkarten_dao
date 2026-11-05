const istDunkel = () => document.documentElement.dataset.theme
  ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
const designBeschriften = () => {
  $("#btnTheme").setAttribute("aria-pressed", String(istDunkel()));
  $("#btnTheme").setAttribute("aria-label", istDunkel() ? "Zum hellen Design wechseln" : "Zum dunklen Design wechseln");
};
$("#btnTheme").onclick = () => {
  const next = istDunkel() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("dao-theme", next); } catch (e) {}
  designBeschriften();
};
designBeschriften();

// Bürger-Menü der Kopfzeile (wie auf den übrigen Seiten von dao-rpg.de): Klick außerhalb oder Esc schließt es
{
  const burger = $("#burger"), menue = $("#menu");
  const zeigen = offen => { burger.setAttribute("aria-expanded", String(offen)); menue.hidden = !offen; menue.classList.toggle("open", offen); };
  burger.addEventListener("click", e => { e.stopPropagation(); zeigen(menue.hidden); });
  document.addEventListener("click", e => { if (!menue.hidden && !menue.contains(e.target)) zeigen(false); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !menue.hidden) { zeigen(false); burger.focus(); } });
}

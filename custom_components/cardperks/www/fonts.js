// Loads the CardPerks fonts into the Home Assistant document so the CardPerks theme
// can use them. Fonts are document-scoped, so one <link> here reaches every card.
// Wire it up in configuration.yaml:
//   frontend:
//     extra_module_url:
//       - /cardperks/static/fonts.js
(() => {
  const href = "/cardperks/static/fonts.css";
  if (document.querySelector(`link[href="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
})();

/* Public, non-secret settings for the static site. No credentials ever go here. */
window.ATLAS_CONFIG = {
  // "owner/repository" on GitHub. Used only to build links to Actions, Issues and the
  // overrides file (all of which require you to be signed in to GitHub). Leave empty to hide.
  repo: "MunariEnrico/social-atlas",
  branch: "main",
  // Where the pipeline output lives relative to index.html.
  dataPath: "data/",
  // Timezone used for "today" in the Overview and Daily Briefing.
  homeTimezone: "Europe/Luxembourg",
};

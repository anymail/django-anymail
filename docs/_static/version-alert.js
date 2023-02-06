"use strict";

// Similar to https://github.com/readthedocs/readthedocs.org/blob/5.2.3/readthedocs/core/static-src/core/js/doc-embed/version-compare.js
// but adds admonition for the "latest" version -- which is (unreleased) main branch.

function warnOnLatestVersion() {
  // The warning text and link is really specific to RTD hosting,
  // so we can just check their global to determine version:
  if (!window.READTHEDOCS_DATA || window.READTHEDOCS_DATA.version !== "latest") {
    return; // not latest, or not on RTD
  }

  var warning = document.createElement("div");
  warning.setAttribute("class", "admonition danger");
  warning.innerHTML =
    "<p class='first admonition-title'>Note</p> " +
    "<p class='last'> " +
    "This document is for an <strong>unreleased development version</strong>. " +
    "Documentation is available for the <a href='/en/stable/'>current stable release</a>, " +
    "or for older versions through the &ldquo;v:&rdquo; menu at bottom left." +
    "</p>";
  warning.querySelector("a").href = window.location.pathname.replace(
    "/latest",
    "/stable"
  );

  var parent =
    document.querySelector("div.body") ||
    document.querySelector("div.document") ||
    document.body;
  parent.insertBefore(warning, parent.firstChild);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", warnOnLatestVersion);
} else {
  warnOnLatestVersion();
}

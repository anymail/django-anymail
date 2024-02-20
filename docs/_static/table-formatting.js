/**
 * Return the first sibling of el that matches CSS selector, or null if no matches.
 * @param {HTMLElement} el
 * @param {string} selector
 * @returns {HTMLElement|null}
 */
function nextSiblingMatching(el, selector) {
  while (el && el.nextElementSibling) {
    el = el.nextElementSibling;
    if (el.matches(selector)) {
      return el;
    }
  }
  return null;
}

/**
 * Convert runs of empty <td> elements to a colspan on the first <td>.
 */
function collapseEmptyTableCells() {
  document.querySelectorAll(".rst-content tr:has(td:empty)").forEach((tr) => {
    for (
      let spanStart = tr.querySelector("td");
      spanStart;
      spanStart = nextSiblingMatching(spanStart, "td")
    ) {
      let emptyCell;
      while ((emptyCell = nextSiblingMatching(spanStart, "td:empty"))) {
        emptyCell.remove();
        spanStart.colSpan++;
      }
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", collapseEmptyTableCells);
} else {
  collapseEmptyTableCells();
}

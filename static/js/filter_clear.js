/*
 * The "Clear filters" button of the list search form (templates/frontend/_search_form.html), on the
 * World lists and the character sheet's own lists alike.
 *
 * It puts every filter of its form back to "no filter" - pills on "All", checkboxes unticked,
 * dropdowns on their empty option - and leaves the search text alone. Whether the button shows at
 * all is CSS (base.html: it appears while some filter is set), so there is no state to keep in
 * step here. Re-running the search is up to the page: this fires a bubbling `filtersclear` event on
 * the form once the fields are reset, which the World lists (base.html) turn into a re-fetch and
 * the character sheet (character_sheet.js) into a re-filter of its rows.
 */
(function () {
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-filter-clear]");
    if (!button) return;
    var form = button.closest("form");
    if (!form) return;
    event.preventDefault();

    form.querySelectorAll(".world-pills input[type=radio]").forEach(function (radio) {
      radio.checked = !radio.value;
    });
    form.querySelectorAll(".filter-popover").forEach(function (popover) {
      popover.querySelectorAll("input[type=checkbox]").forEach(function (box) { box.checked = false; });
      popover.open = false;
      var summary = popover.querySelector(".filter-button");
      if (!summary) return;
      summary.classList.remove("active");
      var badge = summary.querySelector(".filter-count");
      if (badge) badge.remove();
    });
    form.querySelectorAll("select.filter-select").forEach(function (select) {
      select.value = "";
      select.classList.remove("active");
    });
    form.dispatchEvent(new CustomEvent("filtersclear", { bubbles: true }));
  });
})();

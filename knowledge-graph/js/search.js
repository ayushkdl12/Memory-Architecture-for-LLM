/* ============================================================
   SEARCH + RESET
============================================================ */
(function () {
  const searchInput = document.getElementById("search");

  searchInput.addEventListener("input", function () {
    const query = this.value.toLowerCase();
    cy.nodes().forEach(node => {
      const label = (node.data("label") || "").toLowerCase();
      node.style("opacity", query === "" || label.includes(query) ? 1 : 0.12);
    });
  });

  function resetSearch() {
    searchInput.value = "";
    cy.nodes().style("opacity", 1);
  }

  window.resetSearch = resetSearch;
})();
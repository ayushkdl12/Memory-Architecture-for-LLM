/* ============================================================
   APP: filters, stats, legend, info panel, controls
============================================================ */
(function () {
  const types = window.KG_TYPES || {};
  let activeFilter = "all";

  /* ---------------- statistics ---------------- */
  function updateStats() {
    document.getElementById("stats").innerHTML =
      "Nodes: " + cy.nodes().length + "<br>" +
      "Relationships: " + cy.edges().length;
  }

  /* ---------------- entity type filters ---------------- */
  function buildFilters() {
    const container = document.getElementById("typeFilters");
    const present = [];
    cy.nodes().forEach(n => {
      const t = n.data("type");
      if (!present.includes(t)) present.push(t);
    });

    const order = Object.keys(types).filter(t => present.includes(t));
    const add = (label, type, color) => {
      const b = document.createElement("button");
      b.className = "filter-btn" + (type === "all" ? " active" : "");
      b.dataset.type = type;
      b.innerHTML = '<span class="filter-dot" style="background:' +
        (color || "#94a3b8") + '"></span>' + label;
      b.addEventListener("click", () => setFilter(type));
      container.appendChild(b);
    };

    add("All Entities", "all", "#94a3b8");
    order.forEach(t => add(t, t, types[t]));
  }

  function setFilter(type) {
    activeFilter = type;
    document.querySelectorAll(".filter-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.type === type);
    });
    cy.nodes().forEach(node => {
      const match = type === "all" || node.data("type") === type;
      node.style("opacity", match ? 1 : 0.12);
    });
    cy.edges().forEach(edge => {
      const a = edge.source().style("opacity");
      const b = edge.target().style("opacity");
      edge.style("opacity", Math.min(Number(a), Number(b), 1));
    });
  }

  /* ---------------- legend ---------------- */
  function buildLegend() {
    const legend = document.getElementById("legend");
    legend.innerHTML = '<div class="legend-title">Legend</div>';
    Object.keys(types).forEach(t => {
      const item = document.createElement("div");
      item.className = "legend-item";
      item.innerHTML = '<span class="dot" style="background:' + types[t] +
        '"></span>' + t;
      legend.appendChild(item);
    });
    const rel = document.createElement("div");
    rel.className = "legend-item";
    rel.innerHTML = '<span class="line"></span>relationship';
    legend.appendChild(rel);
    const rep = document.createElement("div");
    rep.className = "legend-item";
    rep.innerHTML = '<span class="line dashed"></span>superseded / REPLACED';
    legend.appendChild(rep);
  }

  /* ---------------- info panel ---------------- */
  function showInfo(node) {
    const d = node.data();
    document.getElementById("infoPanel").style.display = "block";
    document.getElementById("infoTitle").innerText = d.label;
    document.getElementById("infoType").innerText = d.type;
    document.getElementById("infoDescription").innerText =
      d.description || "-";

    const statusRow = document.getElementById("infoStatusRow");
    if (d.status) {
      statusRow.style.display = "";
      const el = document.getElementById("infoStatus");
      el.innerText = d.status;
      el.className = d.status === "ARCHIVED" ? "archived" : "active";
    } else {
      statusRow.style.display = "none";
    }

    document.getElementById("infoConnections").innerText =
      node.connectedEdges().length;

    cy.elements().removeClass("highlighted");
    node.addClass("highlighted");
    node.connectedEdges().addClass("highlighted");
    node.connectedEdges().connectedNodes().addClass("highlighted");
  }

  function hideInfo() {
    document.getElementById("infoPanel").style.display = "none";
    cy.elements().removeClass("highlighted");
  }

  cy.on("tap", "node", evt => showInfo(evt.target));
  cy.on("tap", evt => {
    if (evt.target === cy) hideInfo();
  });
  document.getElementById("infoPanel").addEventListener("click", evt => {
    if (evt.target.classList.contains("info-close")) hideInfo();
  });

  /* ---------------- controls ---------------- */
  function zoomIn() {
    cy.zoom({ level: cy.zoom() * 1.25,
              renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }
  function zoomOut() {
    cy.zoom({ level: cy.zoom() * 0.8,
              renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }
  function fitGraph() { cy.fit(cy.elements(), 60); }

  function resetGraph() {
    hideInfo();
    resetSearch();
    setFilter("all");
    fitGraph();
  }

  window.zoomIn = zoomIn;
  window.zoomOut = zoomOut;
  window.fitGraph = fitGraph;
  window.resetGraph = resetGraph;

  /* ---------------- init ---------------- */
  buildFilters();
  buildLegend();
  updateStats();
  cy.on("layoutstop", updateStats);
})();
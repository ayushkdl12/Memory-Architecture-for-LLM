/* ============================================================
   GRAPH: cytoscape instance + style
   Data comes from window.GRAPH_DATA (js/data.js, generated).
============================================================ */
(function () {
  const data = window.GRAPH_DATA;

  function nodeStyle(selector, bg) {
    return {
      selector: selector,
      style: { "background-color": bg }
    };
  }

  const style = [
    /* ----- default node ----- */
    {
      selector: "node",
      style: {
        "label": "data(label)",
        "text-valign": "center",
        "text-halign": "center",
        "color": "#ffffff",
        "font-size": "12px",
        "font-weight": "bold",
        "text-wrap": "wrap",
        "text-max-width": "110px",
        "width": "80px",
        "height": "80px",
        "border-width": 2,
        "border-color": "#ffffff",
        "shape": "ellipse"
      }
    },

    /* ----- archived nodes (superseded / inactive) ----- */
    {
      selector: "node[status = 'ARCHIVED']",
      style: {
        "border-width": 2,
        "border-style": "dashed",
        "border-color": "#475569",
        "opacity": 0.55,
        "text-opacity": 0.55
      }
    },

    /* ----- typed nodes ----- */
    nodeStyle('node[type = "Person"]', "#38bdf8"),
    nodeStyle('node[type = "Project"]', "#a78bfa"),
    nodeStyle('node[type = "Technology"]', "#22c55e"),
    nodeStyle('node[type = "Organization"]', "#f59e0b"),
    nodeStyle('node[type = "Location"]', "#ef4444"),
    nodeStyle('node[type = "Event"]', "#ec4899"),
    nodeStyle('node[type = "Document"]', "#64748b"),
    nodeStyle('node[type = "Preference"]', "#f472b6"),

    /* ----- edges ----- */
    {
      selector: "edge",
      style: {
        "label": "data(label)",
        "width": 2,
        "line-color": "#64748b",
        "target-arrow-color": "#64748b",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "font-size": "9px",
        "color": "#cbd5e1",
        "text-background-color": "#020617",
        "text-background-opacity": 1,
        "text-background-padding": "3px"
      }
    },

    /* ----- superseded relationships (dashed) ----- */
    {
      selector: "edge[style = 'archived']",
      style: {
        "line-style": "dashed",
        "line-color": "#64748b",
        "opacity": 0.7
      }
    },

    /* ----- temporal versioning edge (REPLACED) ----- */
    {
      selector: "edge[style = 'version']",
      style: {
        "line-style": "dashed",
        "line-color": "#fbbf24",
        "target-arrow-color": "#fbbf24",
        "width": 2.5,
        "font-weight": "bold"
      }
    },

    /* ----- highlighted (on selection) ----- */
    {
      selector: "node.highlighted",
      style: {
        "border-width": 5,
        "border-color": "#ffffff"
      }
    },
    {
      selector: "edge.highlighted",
      style: {
        "line-color": "#60a5fa",
        "opacity": 1,
        "width": 3
      }
    },
    {
      selector: ":selected",
      style: {
        "border-width": 5,
        "border-color": "#ffffff"
      }
    }
  ];

  const cy = cytoscape({
    container: document.getElementById("cy"),
    elements: data.elements,
    style: style,
    layout: {
      name: "cose",
      animate: true,
      padding: 80,
      nodeRepulsion: 600000,
      idealEdgeLength: 160,
      edgeElasticity: 120
    },
    minZoom: 0.2,
    maxZoom: 4
  });

  window.cy = cy;
  window.KG_TYPES = data.types;
})();
"use client";

export default function KnowledgeGraphView() {
  return (
    <div style={{ height: "calc(100vh - 220px)", minHeight: 480 }}>
      <iframe
        src="/knowledge-graph/index.html"
        title="Knowledge Graph Explorer"
        style={{
          width: "100%",
          height: "100%",
          border: "1px solid #1e293b",
          borderRadius: 10,
          background: "#0f1220",
        }}
      />
    </div>
  );
}

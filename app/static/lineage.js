const SVG_NS = "http://www.w3.org/2000/svg";

const GROUPS = [
  {key: "dataset", label: "Datasets"},
  {key: "pipeline", label: "Pipelines"},
  {key: "reporting", label: "BI & reporting"},
  {key: "ml", label: "ML assets"},
  {key: "other", label: "Other assets"}
];

export function assetGroup(assetType = "") {
  const value = assetType.toLowerCase();
  if (value === "pipeline" || value === "data_job" || value === "dataflow") {
    return "pipeline";
  }
  if (value === "dashboard" || value === "chart") return "reporting";
  if (value === "ml_model" || value === "feature_table" || value.startsWith("ml_")) {
    return "ml";
  }
  if (value === "dataset" || value === "table" || value === "view") return "dataset";
  return "other";
}

export function assetTypeLabel(assetType = "") {
  const labels = {
    dataset: "Dataset",
    pipeline: "Pipeline",
    dashboard: "Dashboard",
    chart: "Chart",
    feature_table: "Feature table",
    ml_model: "ML model"
  };
  return labels[assetType] || assetType.replaceAll("_", " ") || "Asset";
}

function svgElement(tag, attributes = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attributes).forEach(([name, value]) => {
    node.setAttribute(name, String(value));
  });
  return node;
}

function truncated(value, maximum) {
  const text = String(value || "Unnamed asset");
  return text.length <= maximum ? text : `${text.slice(0, maximum - 1)}…`;
}

function edgePath(source, target) {
  const sourceX = source.x + source.width / 2;
  const sourceY = source.y + source.height;
  const targetX = target.x + target.width / 2;
  const targetY = target.y;
  const bend = Math.max(34, Math.abs(targetY - sourceY) * 0.48);
  return `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + bend}, ${targetX} ${targetY - bend}, ${targetX} ${targetY}`;
}

function nodeGroup(asset, box, {source = false} = {}) {
  const groupName = assetGroup(asset.asset_type);
  const group = svgElement("g", {
    class: `node-group ${source ? "source-node" : ""}`.trim(),
    tabindex: "0",
    role: "button",
    "aria-label": `${source ? "Source asset" : "Downstream asset"}: ${asset.name}. ${assetTypeLabel(asset.asset_type)}, ${asset.platform || "unknown platform"}, ${asset.criticality || "unknown"} criticality.`
  });

  const card = svgElement("rect", {
    class: "node-card",
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    rx: 9
  });
  const bar = svgElement("rect", {
    class: `node-type-bar ${source ? "dataset" : groupName}`,
    x: box.x,
    y: box.y,
    width: 4,
    height: box.height,
    rx: 2
  });
  const name = svgElement("text", {
    class: "node-name",
    x: box.x + 15,
    y: box.y + (source ? 33 : 25)
  });
  name.textContent = truncated(asset.name, 29);

  const platform = svgElement("text", {
    class: "node-meta",
    x: box.x + 15,
    y: box.y + (source ? 49 : 43)
  });
  platform.textContent = `${asset.platform || "Unknown"} · ${assetTypeLabel(asset.asset_type)}`;

  const criticality = svgElement("text", {
    class: "node-criticality",
    x: box.x + box.width - 12,
    y: box.y + box.height - 10,
    "text-anchor": "end"
  });
  criticality.textContent = String(asset.criticality || "unknown").toUpperCase();

  group.append(card, bar, name, platform, criticality);

  if (source) {
    const sourceLabel = svgElement("text", {
      class: "source-label",
      x: box.x + 15,
      y: box.y + 15
    });
    sourceLabel.textContent = "SOURCE";
    group.append(sourceLabel);
  }

  return group;
}

export function renderLineage(container, {rootAsset, assets = [], edges = []}, onSelect) {
  container.replaceChildren();
  if (!rootAsset) return;

  const grouped = GROUPS
    .map(group => ({
      ...group,
      assets: assets.filter(asset => assetGroup(asset.asset_type) === group.key)
    }))
    .filter(group => group.assets.length);

  const nodeWidth = 220;
  const nodeHeight = 64;
  const nodeGapX = 12;
  const nodeGapY = 14;
  const groupGap = 22;
  const outer = 24;
  const maxRows = 10;
  const groupTop = 146;
  const nodesTop = 190;

  const groupsWithLayout = grouped.map(group => ({
    ...group,
    columns: Math.ceil(group.assets.length / maxRows),
    rows: Math.min(maxRows, group.assets.length)
  }));

  const contentWidth = groupsWithLayout.reduce(
    (sum, group) => sum + group.columns * nodeWidth + (group.columns - 1) * nodeGapX,
    0
  ) + Math.max(0, groupsWithLayout.length - 1) * groupGap;
  const width = Math.max(780, contentWidth + outer * 2);
  const maxRowsUsed = Math.max(1, ...groupsWithLayout.map(group => group.rows));
  const height = Math.max(480, nodesTop + maxRowsUsed * (nodeHeight + nodeGapY) + outer);
  const rootBox = {
    x: width / 2 - nodeWidth / 2,
    y: 28,
    width: nodeWidth,
    height: 72
  };

  const svg = svgElement("svg", {
    class: "lineage-svg",
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    role: "group",
    "aria-label": `Lineage graph with one source and ${assets.length} downstream assets`
  });

  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: "lineage-arrow",
    viewBox: "0 0 10 10",
    refX: "8",
    refY: "5",
    markerWidth: "5",
    markerHeight: "5",
    orient: "auto-start-reverse"
  });
  const arrow = svgElement("path", {d: "M 0 0 L 10 5 L 0 10 z"});
  marker.append(arrow);
  defs.append(marker);
  svg.append(defs);

  const positions = new Map([[rootAsset.urn, rootBox]]);
  let cursorX = outer;
  groupsWithLayout.forEach(group => {
    const groupWidth = group.columns * nodeWidth + (group.columns - 1) * nodeGapX;
    const background = svgElement("rect", {
      class: "group-surface",
      x: cursorX - 7,
      y: groupTop,
      width: groupWidth + 14,
      height: height - groupTop - 14,
      rx: 12
    });
    const label = svgElement("text", {
      class: "group-label",
      x: cursorX + 3,
      y: groupTop + 25
    });
    label.textContent = `${group.label} · ${group.assets.length}`;
    svg.append(background, label);

    group.assets.forEach((asset, index) => {
      const column = Math.floor(index / maxRows);
      const row = index % maxRows;
      positions.set(asset.urn, {
        x: cursorX + column * (nodeWidth + nodeGapX),
        y: nodesTop + row * (nodeHeight + nodeGapY),
        width: nodeWidth,
        height: nodeHeight
      });
    });
    cursorX += groupWidth + groupGap;
  });

  const availableEdges = edges.length
    ? edges
    : assets.map(asset => ({source: rootAsset.urn, target: asset.urn}));
  const edgeElements = [];
  availableEdges.forEach(edge => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const path = svgElement("path", {
      class: "edge",
      d: edgePath(source, target),
      "marker-end": "url(#lineage-arrow)"
    });
    svg.append(path);
    edgeElements.push({element: path, edge});
  });

  const nodeElements = [];
  const allNodes = [rootAsset, ...assets];
  allNodes.forEach((asset, index) => {
    const box = positions.get(asset.urn);
    if (!box) return;
    const group = nodeGroup(asset, box, {source: index === 0});
    const select = () => {
      nodeElements.forEach(item => {
        item.element.classList.toggle("is-selected", item.asset.urn === asset.urn);
      });
      edgeElements.forEach(item => {
        item.element.classList.toggle(
          "is-connected",
          item.edge.source === asset.urn || item.edge.target === asset.urn
        );
      });
      onSelect(asset);
    };
    group.addEventListener("click", select);
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    svg.append(group);
    nodeElements.push({element: group, asset});
  });

  container.append(svg);
  nodeElements[0]?.element.classList.add("is-selected");
  onSelect(rootAsset);
}

const state = {
  rows: [],
  query: "",
  decision: "all",
  sort: "score-desc",
};

const formatNumber = (value, digits = 2) => {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "-";
};

const parseCsv = (text) => {
  const rows = [];
  let current = "";
  let row = [];
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"' && quoted && next === '"') {
      current += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(current);
      current = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(current);
      if (row.some((cell) => cell.length > 0)) rows.push(row);
      row = [];
      current = "";
    } else {
      current += char;
    }
  }

  if (current || row.length) {
    row.push(current);
    rows.push(row);
  }

  const headers = rows.shift().map((item) => item.replace(/^\uFEFF/, ""));
  return rows.map((cells) => Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""])));
};

const latestRows = (rows) => {
  const latestKey = rows
    .map((row) => `${row.run_date}|${row.data_latest_completed_day}`)
    .sort()
    .at(-1);
  return rows.filter((row) => `${row.run_date}|${row.data_latest_completed_day}` === latestKey);
};

const visibleRows = () => {
  const query = state.query.trim().toLowerCase();
  const filtered = state.rows.filter((row) => {
    const matchesQuery = !query || `${row.symbol} ${row.name}`.toLowerCase().includes(query);
    const matchesDecision = state.decision === "all" || row.decision === state.decision;
    return matchesQuery && matchesDecision;
  });

  return filtered.sort((a, b) => {
    if (state.sort === "change-desc") return Number(b.change_pct) - Number(a.change_pct);
    if (state.sort === "volume-desc") return Number(b.volume_ratio) - Number(a.volume_ratio);
    if (state.sort === "symbol-asc") return String(a.symbol).localeCompare(String(b.symbol));
    return Number(b.score) - Number(a.score);
  });
};

const trendClass = (value) => Number(value) >= 0 ? "pos" : "neg";

const renderMetrics = () => {
  const rows = state.rows;
  const hold = rows.filter((row) => row.decision === "hold").length;
  const reject = rows.length - hold;
  const avgScore = rows.reduce((sum, row) => sum + Number(row.score || 0), 0) / Math.max(rows.length, 1);

  document.querySelector("#metric-total").textContent = rows.length;
  document.querySelector("#metric-hold").textContent = hold;
  document.querySelector("#metric-reject").textContent = reject;
  document.querySelector("#metric-score").textContent = formatNumber(avgScore, 1);

  const first = rows[0];
  document.querySelector("#subtitle").textContent = first
    ? `Updated ${first.run_date}. Latest completed trading day: ${first.data_latest_completed_day}`
    : "No data";
};

const renderCards = (rows) => {
  const cards = document.querySelector("#cards");
  if (!rows.length) {
    cards.innerHTML = '<div class="empty">No matching symbols</div>';
    return;
  }

  cards.innerHTML = rows.map((row) => `
    <article class="card">
      <div class="card-head">
        <div>
          <div class="symbol">${row.symbol}</div>
          <div class="name">${row.name}</div>
        </div>
        <span class="tag ${row.decision}">${row.decision}</span>
      </div>
      <div class="card-grid">
        <div><span class="label">Score</span><span class="value">${formatNumber(row.score)}</span></div>
        <div><span class="label">Close</span><span class="value">${formatNumber(row.close)}</span></div>
        <div><span class="label">Change</span><span class="value ${trendClass(row.change_pct)}">${formatNumber(row.change_pct)}%</span></div>
        <div><span class="label">Vol Ratio</span><span class="value">${formatNumber(row.volume_ratio)}</span></div>
      </div>
      <div class="action">${row.tracking_action || "-"}</div>
    </article>
  `).join("");
};

const renderTable = (rows) => {
  document.querySelector("#table-body").innerHTML = rows.map((row) => `
    <tr>
      <td>${row.symbol}</td>
      <td>${row.name}</td>
      <td><span class="tag ${row.decision}">${row.decision}</span></td>
      <td>${formatNumber(row.score)}</td>
      <td>${formatNumber(row.close)}</td>
      <td class="${trendClass(row.change_pct)}">${formatNumber(row.change_pct)}%</td>
      <td>${formatNumber(row.volume_ratio)}</td>
      <td>${row.pattern_type || "-"}</td>
      <td>${row.tracking_action || "-"}</td>
    </tr>
  `).join("");
};

const render = () => {
  const rows = visibleRows();
  renderMetrics();
  renderCards(rows);
  renderTable(rows);
};

const bindControls = () => {
  document.querySelector("#search").addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });
  document.querySelector("#decision-filter").addEventListener("change", (event) => {
    state.decision = event.target.value;
    render();
  });
  document.querySelector("#sort").addEventListener("change", (event) => {
    state.sort = event.target.value;
    render();
  });
};

const main = async () => {
  bindControls();
  const response = await fetch("reports/tracking_log.csv", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.rows = latestRows(parseCsv(await response.text()));
  render();
};

main().catch((error) => {
  document.querySelector("#subtitle").textContent = "Data failed to load";
  document.querySelector("#cards").innerHTML = `<div class="empty">${error.message}</div>`;
});

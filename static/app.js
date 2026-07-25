const targetEl = document.getElementById("target");
const statusEl = document.getElementById("currentStatus");
const outageCountEl = document.getElementById("outageCount");
const totalDowntimeEl = document.getElementById("totalDowntime");
const lastCheckEl = document.getElementById("lastCheck");
const updatedEl = document.getElementById("updated");
const rangeLabelEl = document.getElementById("rangeLabel");
const outageListEl = document.getElementById("outageList");

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "numeric",
  day: "numeric",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function formatDateTime(value) {
  return value ? dateFormatter.format(new Date(value)).replace(",", "") : "--";
}

function sameLocalDay(first, second) {
  const a = new Date(first);
  const b = new Date(second);
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate();
}

function formatRange(outage) {
  const start = formatDateTime(outage.start);
  if (outage.ongoing || !outage.end) return `${start}–ongoing`;
  const end = sameLocalDay(outage.start, outage.end)
    ? timeFormatter.format(new Date(outage.end))
    : formatDateTime(outage.end);
  return `${start}–${end}`;
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (remainder || !parts.length) parts.push(`${remainder}s`);
  return parts.join(" ");
}

function renderOutages(outages) {
  outageListEl.replaceChildren();
  if (!outages.length) {
    const empty = document.createElement("p");
    empty.className = "emptyState";
    empty.textContent = "No outages recorded during this period.";
    outageListEl.append(empty);
    return;
  }

  outages.forEach((outage) => {
    const row = document.createElement("article");
    row.className = `outageRow${outage.ongoing ? " ongoing" : ""}`;

    const details = document.createElement("div");
    const range = document.createElement("strong");
    range.textContent = formatRange(outage);
    const label = document.createElement("span");
    label.textContent = outage.ongoing ? "Outage in progress" : "Service restored";
    details.append(range, label);

    const duration = document.createElement("div");
    duration.className = "duration";
    const durationLabel = document.createElement("span");
    durationLabel.textContent = "Duration";
    const durationValue = document.createElement("strong");
    durationValue.textContent = formatDuration(outage.durationSeconds);
    duration.append(durationLabel, durationValue);

    row.append(details, duration);
    outageListEl.append(row);
  });
}

function updateStatus(latest) {
  statusEl.classList.remove("up", "down");
  if (!latest) {
    statusEl.textContent = "Waiting";
  } else if (latest.ok) {
    statusEl.textContent = "Online";
    statusEl.classList.add("up");
  } else {
    statusEl.textContent = "Outage";
    statusEl.classList.add("down");
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/outages", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const totalDowntime = data.outages.reduce(
      (total, outage) => total + outage.durationSeconds,
      0,
    );

    targetEl.textContent = data.targetUrl;
    rangeLabelEl.textContent = `Last ${data.retentionDays} days`;
    outageCountEl.textContent = data.outages.length;
    totalDowntimeEl.textContent = formatDuration(totalDowntime);
    lastCheckEl.textContent = data.latest ? formatDateTime(data.latest.time) : "--";
    updatedEl.textContent = `Updated ${formatDateTime(data.generatedAt)}`;
    updateStatus(data.latest);
    renderOutages(data.outages);
  } catch (error) {
    statusEl.textContent = "Error";
    statusEl.classList.remove("up");
    statusEl.classList.add("down");
    updatedEl.textContent = String(error);
  }
}

refresh();
setInterval(refresh, 5000);

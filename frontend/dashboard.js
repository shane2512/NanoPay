function resolveApiBase() {
    const override = (window.NANOPAY_API_BASE || "").trim();
    if (override) {
        return override.replace(/\/+$/, "");
    }

    // If loaded from file://, force localhost coordinator endpoint.
    if (window.location.protocol === "file:") {
        return "http://localhost:8000";
    }

    const host = window.location.hostname || "localhost";
    return `${window.location.protocol}//${host}:8000`;
}

const API_BASE = resolveApiBase();
const API_URL = `${API_BASE}/api/research`;
const WS_URL = `${API_BASE.replace(/^http/i, "ws")}/ws`;

const inputScreen = document.getElementById("input-screen");
const dashboardScreen = document.getElementById("dashboard-screen");
const queryInput = document.getElementById("query-input");
const budgetSlider = document.getElementById("budget-slider");
const budgetValue = document.getElementById("budget-value");
const runBtn = document.getElementById("run-btn");

const statSpent = document.getElementById("stat-spent");
const statTxCount = document.getElementById("stat-tx-count");
const statProgress = document.getElementById("stat-progress");
const txFeed = document.getElementById("tx-feed");
const reportContent = document.getElementById("report-content");
const marginTableBody = document.getElementById("margin-table-body");
const connectionStatus = document.getElementById("connection-status");
const connectionLabel = document.getElementById("connection-label");

let ws = null;
let settledCount = 0;
let totalSpent = 0;
let targetTransactions = 0;
let liveEventsSeen = false;

budgetSlider.oninput = () => {
    budgetValue.innerText = `$${parseFloat(budgetSlider.value).toFixed(2)}`;
};

function connectWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        return;
    }

    setConnectionState("connecting", "WebSocket: connecting");
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        setConnectionState("live", "WebSocket: live");
        ws.send("ping");
    };

    ws.onclose = () => {
        setConnectionState("down", "WebSocket: disconnected");
    };

    ws.onerror = () => {
        setConnectionState("down", "WebSocket: unavailable");
    };

    ws.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            handleSocketPayload(payload);
        } catch (error) {
            console.warn("Invalid WS payload", error);
        }
    };
}

function setConnectionState(mode, label) {
    connectionLabel.textContent = label;
    connectionStatus.className = "w-2.5 h-2.5 rounded-full";
    connectionStatus.style.background = "var(--cherry-red)";
}

function handleSocketPayload(payload) {
    const type = payload?.type;
    if (!type) return;

    if (type === "research_started") {
        targetTransactions = payload.target_transactions || targetTransactions;
        statProgress.innerText = "0%";
    }

    if (type === "payment_settled") {
        liveEventsSeen = true;
        settledCount += 1;
        totalSpent = payload.total_spent ?? totalSpent + Number(payload.amount || 0);

        statSpent.innerText = `$${Number(totalSpent).toFixed(3)} USDC`;
        statTxCount.innerText = `${settledCount}`;
        if (targetTransactions > 0) {
            statProgress.innerText = `${Math.min(100, Math.round((settledCount / targetTransactions) * 100))}%`;
        }

        appendTransactionRow({
            domain: payload.domain,
            question: payload.question,
            amount: payload.amount,
            tx_hash: payload.tx_hash,
            arc_url: payload.arc_url,
        });
    }

    if (type === "payment_error") {
        appendErrorRow(payload.domain, payload.error);
    }

    if (type === "report_ready") {
        renderReportWithFallback(payload.report, [], payload.summary || {});
        if (payload.summary?.margin_analysis) {
            renderMarginTable(payload.summary.margin_analysis.rows || []);
        }
    }
}

async function startResearch() {
    const query = queryInput.value.trim();
    const budget = parseFloat(budgetSlider.value);

    if (!query) {
        alert("Please enter a research query.");
        return;
    }

    connectWebSocket();
    resetDashboard();

    inputScreen.classList.add("hidden");
    dashboardScreen.classList.remove("hidden");

    runBtn.disabled = true;
    runBtn.classList.add("opacity-70", "cursor-not-allowed");

    try {
        const response = await fetch(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query,
                budget_cap: budget,
                target_transactions: 12,
            }),
        });

        const data = await response.json();
        if (!response.ok || data.status === "error") {
            throw new Error(data.message || `Coordinator request failed (${response.status})`);
        }

        // Fallback rendering when websocket is unavailable.
        if (!liveEventsSeen) {
            processResultsFallback(data);
        } else {
            // Ensure final state is synced even with WS events.
            statSpent.innerText = `$${Number(data.summary?.total_spent || 0).toFixed(3)} USDC`;
            statTxCount.innerText = `${data.summary?.transaction_count || 0}`;
            statProgress.innerText = "100%";
            renderReportWithFallback(data.report, data.details || [], data.summary || {});
            if (data.summary?.margin_analysis?.rows) {
                renderMarginTable(data.summary.margin_analysis.rows);
            }
        }
    } catch (error) {
        console.error("Research error:", error);
        alert("Research failed. Check coordinator and specialist services.");
        inputScreen.classList.remove("hidden");
        dashboardScreen.classList.add("hidden");
    } finally {
        runBtn.disabled = false;
        runBtn.classList.remove("opacity-70", "cursor-not-allowed");
    }
}

function resetDashboard() {
    settledCount = 0;
    totalSpent = 0;
    targetTransactions = 0;
    liveEventsSeen = false;

    txFeed.innerHTML = '<div class="text-slate-400 text-center py-10 italic">Waiting for payment-settled events...</div>';
    reportContent.innerHTML = `
        <div class="flex flex-col items-center justify-center h-full text-slate-400 italic">
            <i class="fas fa-spinner fa-spin text-3xl mb-4"></i>
            <p>Coordinator is decomposing, settling, and synthesizing...</p>
        </div>
    `;
    marginTableBody.innerHTML = '<tr class="border-b border-slate-800/80"><td colspan="4" class="py-4 text-slate-400 italic">Waiting for results...</td></tr>';

    statSpent.innerText = "$0.000 USDC";
    statTxCount.innerText = "0";
    statProgress.innerText = "0%";
}

function processResultsFallback(data) {
    const details = data.details || [];
    let running = 0;
    const total = details.length || 1;

    txFeed.innerHTML = "";
    for (let i = 0; i < details.length; i += 1) {
        const tx = details[i];
        running += Number(tx.amount || 0);
        appendTransactionRow(tx, true);
        statSpent.innerText = `$${running.toFixed(3)} USDC`;
        statTxCount.innerText = `${i + 1}`;
        statProgress.innerText = `${Math.round(((i + 1) / total) * 100)}%`;
    }

    renderReportWithFallback(data.report, details, data.summary || {});
    renderMarginTable(data.summary?.margin_analysis?.rows || []);
}

function appendTransactionRow(tx, prepend = true) {
    if (txFeed.querySelector(".italic")) {
        txFeed.innerHTML = "";
    }

    const amount = Number(tx.amount || 0).toFixed(3);
    const arcUrl = tx.arc_url || "https://testnet.arcscan.app/address/0xcF1c22178A8F195860581ff18E17337253EDc340";
    const row = document.createElement("div");
    row.className = "glass p-4 rounded-2xl flex justify-between items-center gap-3 animate-fade-in border-l-4";
    row.style.borderLeft = "4px solid var(--cherry-red)";
    row.innerHTML = `
        <div class="flex flex-col min-w-0">
            <span class="text-xs font-bold uppercase tracking-wide" style="color: var(--cherry-red);">${escapeHtml(tx.domain || "GENERAL")}</span>
            <span class="text-sm truncate" style="color: var(--cherry-red);">${escapeHtml(tx.question || "")}</span>
        </div>
        <div class="flex items-center gap-3 shrink-0">
                <span class="font-mono text-sm" style="color: var(--cherry-red);">$${amount}</span>
                <a href="${arcUrl}" target="_blank" rel="noreferrer"
                    class="text-xs px-2 py-1 rounded border transition-colors"
                    style="background: var(--butter-yellow); color: var(--cherry-red); border: 1px solid var(--cherry-red);">
                    <i class="fas fa-external-link-alt"></i> Arc
                </a>
        </div>
    `;

    if (prepend) {
        txFeed.prepend(row);
    } else {
        txFeed.append(row);
    }
}

function appendErrorRow(domain, error) {
    const row = document.createElement("div");
    row.className = "glass p-3 rounded-2xl border-l-4 text-sm";
    row.style.borderLeft = "4px solid var(--cherry-red)";
    row.style.color = "var(--cherry-red)";
    row.innerHTML = `<strong>${escapeHtml(domain || "GENERAL")}</strong>: ${escapeHtml(error || "Unknown error")}`;
    txFeed.prepend(row);
}

function renderMarginTable(rows) {
    if (!rows.length) {
        marginTableBody.innerHTML = '<tr class="border-b border-slate-800/80"><td colspan="4" class="py-4 text-slate-400 italic">No margin data returned.</td></tr>';
        return;
    }

    marginTableBody.innerHTML = "";
    for (const row of rows) {
        const tr = document.createElement("tr");
        const isCircle = row.rail === "Circle Nanopayments on Arc";
        tr.className = "";
        tr.style.borderBottom = "1px solid var(--cherry-red)";
        if (isCircle) {
            tr.style.background = "var(--butter-yellow)";
            tr.style.color = "var(--cherry-red)";
            tr.style.fontWeight = "bold";
        }

        const relative = row.multiplier_vs_circle == null
            ? "-"
            : `${Number(row.multiplier_vs_circle).toFixed(2)}x`;

        tr.innerHTML = `
            <td class="py-3 pr-4 font-semibold">${escapeHtml(row.rail || "")}</td>
            <td class="py-3 pr-4">${escapeHtml(row.base_fee || "")}</td>
            <td class="py-3 pr-4">$${Number(row.cost_for_run || 0).toFixed(4)}</td>
            <td class="py-3">${relative}</td>
        `;
        marginTableBody.append(tr);
    }
}

function renderReportWithFallback(report, details = [], summary = {}) {
    const text = String(report || "").trim();
    if (reportLooksLowContent(text)) {
        reportContent.innerHTML = formatMarkdown(buildClientFallbackReport(details, summary));
        return;
    }
    reportContent.innerHTML = formatMarkdown(text);
}

function reportLooksLowContent(report) {
    if (!report) {
        return true;
    }

    const lines = report.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!lines.length) {
        return true;
    }

    const bodyLines = lines.filter((line) => !line.startsWith("#"));
    const bodyText = bodyLines.join(" ");
    return bodyLines.length < 3 || bodyText.length < 90;
}

function buildClientFallbackReport(details, summary) {
    const txCount = Number(summary?.transaction_count || details.length || 0);
    const spent = Number(summary?.total_spent || 0);
    const domainCounts = {};

    for (const row of details || []) {
        const domain = String(row?.domain || "GENERAL").toUpperCase();
        domainCounts[domain] = (domainCounts[domain] || 0) + 1;
    }

    const domainSummary = Object.keys(domainCounts).length
        ? Object.entries(domainCounts)
            .map(([domain, count]) => `${domain}: ${count}`)
            .join(", ")
        : "No domain-level detail returned in this response.";

    const sampleFindings = (details || []).slice(0, 6).map((row) => {
        const question = String(row?.question || "").trim();
        let answer = String(row?.answer || "").replace(/\s+/g, " ").trim();
        if (!answer) {
            answer = "No specialist answer text was included in the response.";
        }
        if (answer.length > 180) {
            answer = `${answer.slice(0, 177)}...`;
        }
        return `- ${question}: ${answer}`;
    });

    return [
        "## Executive Summary",
        `- Transactions settled: ${txCount}`,
        `- Total spend: $${spent.toFixed(3)} USDC`,
        `- Domain coverage: ${domainSummary}`,
        "- This fallback report was generated because the model response lacked sufficient detail.",
        "",
        "## Key Findings by Domain",
        ...(sampleFindings.length
            ? sampleFindings
            : ["- No specialist findings were included in the final payload."]),
        "",
        "## Risks and Unknowns",
        "- Partial responses or upstream timeouts can reduce evidence quality.",
        "- Specialist findings should be validated against primary sources.",
        "",
        "## Recommended Next Actions",
        "- Re-run targeted prompts for weak or missing domains.",
        "- Increase budget/timeout only where repeated timeouts occur.",
        "- Export transaction hashes and verify Arc settlement links for auditability.",
    ].join("\n");
}

function formatMarkdown(text) {
    if (!text) return "";
    return escapeHtml(text)
        .replace(/^### (.*$)/gim, '<h3 class="text-xl font-semibold" style="color: var(--cherry-red);">$1</h3>')
        .replace(/^## (.*$)/gim, '<h2 class="text-2xl font-bold" style="color: var(--cherry-red);">$1</h2>')
        .replace(/^# (.*$)/gim, '<h1 class="text-3xl font-black mb-4" style="color: var(--cherry-red);">$1</h1>')
        .replace(/^- (.*)$/gim, '<li class="ml-5 list-disc mb-1" style="color: var(--cherry-red);">$1</li>')
        .replace(/\*\*(.*?)\*\*/gim, "<strong style=\"color: var(--cherry-red);\">$1</strong>")
        .replace(/\n\n/g, "<br><br>")
        .replace(/\n/g, "<br>");
}

function escapeHtml(str) {
    return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

runBtn.onclick = startResearch;
connectWebSocket();

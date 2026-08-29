const chat = document.getElementById("chat");
const form = document.getElementById("ask-form");
const input = document.getElementById("topic-input");
const sendBtn = document.getElementById("send-btn");

// Mermaid renders on-demand (startOnLoad: false) since diagrams are
// added dynamically after each API response, not present on page load.
mermaid.initialize({ startOnLoad: false, theme: "dark" });
let mermaidDiagramCounter = 0;

// --- Auto-growing textarea, like a real chat input (no character cap) ---
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
});

// Enter sends; Shift+Enter inserts a newline (standard chat UX)
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

/** Calls the backend. Returns parsed JSON on success, throws on failure. */
async function fetchAnswer(topic) {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
  const data = await res.json();
  if (!res.ok) {
    const err = new Error(data.error || "Something went wrong.");
    err.isApiError = true;
    throw err;
  }
  return data;
}

function buildTextHtml(explanation) {
  return escapeHtml(explanation);
}

/**
 * Renders a Mermaid diagram into a container element. Mermaid's render()
 * is async and returns SVG markup - if the LLM produced invalid flowchart
 * syntax, this throws, so callers should fall back to a text note instead
 * of leaving a broken diagram in the chat.
 */
async function renderMermaidInto(container, mermaidSource) {
  const id = `mermaid-diagram-${++mermaidDiagramCounter}`;
  const { svg } = await mermaid.render(id, mermaidSource);
  container.innerHTML = svg;
}

/**
 * Renders a user message bubble with hover actions: ✎ edit, ⧉ copy.
 * Editing removes this exchange and everything after it, then
 * resubmits the edited text — same behavior as editing in a normal chat app.
 */
function addUserMessage(topic) {
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap user";

  const bubble = document.createElement("div");
  bubble.className = "msg user";
  bubble.textContent = topic;

  const actions = document.createElement("div");
  actions.className = "msg-actions";
  actions.innerHTML = `
    <button type="button" title="Edit" data-action="edit">✎</button>
    <button type="button" title="Copy" data-action="copy">⧉</button>
  `;

  wrap.appendChild(bubble);
  wrap.appendChild(actions);
  chat.appendChild(wrap);

  actions.querySelector('[data-action="copy"]').addEventListener("click", () => {
    navigator.clipboard.writeText(topic);
  });

  actions.querySelector('[data-action="edit"]').addEventListener("click", () => {
    startEdit(wrap, bubble, actions, topic);
  });

  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
  return wrap;
}

function startEdit(wrap, bubble, actions, originalTopic) {
  bubble.style.display = "none";
  actions.style.display = "none";

  const box = document.createElement("textarea");
  box.className = "edit-box";
  box.value = originalTopic;
  box.rows = Math.min(10, Math.max(2, originalTopic.split("\n").length));

  const editActions = document.createElement("div");
  editActions.className = "edit-actions";
  editActions.innerHTML = `
    <button type="button" class="cancel-btn">Cancel</button>
    <button type="button" class="save-btn">Save & Submit</button>
  `;

  wrap.insertBefore(box, bubble);
  wrap.appendChild(editActions);
  box.focus();

  editActions.querySelector(".cancel-btn").addEventListener("click", () => {
    box.remove();
    editActions.remove();
    bubble.style.display = "";
    actions.style.display = "";
  });

  editActions.querySelector(".save-btn").addEventListener("click", () => {
    const newTopic = box.value.trim();
    if (!newTopic) return;

    // Drop this exchange and everything after it, then re-run from here.
    let node = wrap;
    while (node) {
      const next = node.nextSibling;
      node.remove();
      node = next;
    }
    askNewQuestion(newTopic);
  });
}

/**
 * Renders a bot answer bubble with hover actions: ↻ regenerate, ⧉ copy.
 * Builds the text first, then (if a diagram was returned) renders the
 * Mermaid SVG into a separate container appended after the text -
 * Mermaid needs an async render call, so this can't be a synchronous
 * innerHTML assignment like the old image-based version.
 */
async function renderBotMessage(bubble, explanation, diagram, diagramError) {
  bubble.innerHTML = buildTextHtml(explanation);

  if (diagram) {
    const diagramContainer = document.createElement("div");
    diagramContainer.className = "diagram-container";
    bubble.appendChild(diagramContainer);
    try {
      await renderMermaidInto(diagramContainer, diagram);
    } catch (err) {
      diagramContainer.innerHTML = `<em style="color:#9aa0a6;">Diagram could not be rendered (invalid flowchart syntax).</em>`;
    }
  } else if (diagramError) {
    const note = document.createElement("div");
    note.innerHTML = `<em style="color:#9aa0a6;">${escapeHtml(diagramError)}</em>`;
    bubble.appendChild(note);
  }
}

function addBotMessageShell(topic) {
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap bot";

  const bubble = document.createElement("div");
  bubble.className = "msg bot";
  bubble.innerHTML = '<span class="spinner">Thinking…</span>';

  const actions = document.createElement("div");
  actions.className = "msg-actions";
  actions.innerHTML = `
    <button type="button" title="Regenerate" data-action="regenerate">↻</button>
    <button type="button" title="Copy" data-action="copy">⧉</button>
  `;
  actions.style.display = "none"; // shown once the real answer lands

  wrap.appendChild(bubble);
  wrap.appendChild(actions);
  chat.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });

  let currentExplanation = "";

  actions.querySelector('[data-action="copy"]').addEventListener("click", () => {
    navigator.clipboard.writeText(currentExplanation);
  });

  actions.querySelector('[data-action="regenerate"]').addEventListener("click", async () => {
    actions.style.display = "none";
    bubble.innerHTML = '<span class="spinner">Regenerating…</span>';
    try {
      const data = await fetchAnswer(topic);
      currentExplanation = data.explanation;
      await renderBotMessage(bubble, data.explanation, data.diagram, data.diagram_error);
    } catch (err) {
      bubble.innerHTML = `<span style="color:#ffb4b4;">${escapeHtml(err.message)}</span>`;
    } finally {
      actions.style.display = "";
    }
  });

  return {
    async setAnswer(explanation, diagram, diagramError) {
      currentExplanation = explanation;
      await renderBotMessage(bubble, explanation, diagram, diagramError);
      actions.style.display = "";
    },
    setError(message) {
      bubble.innerHTML = `<span style="color:#ffb4b4;">${escapeHtml(message)}</span>`;
    },
  };
}

/** Full new exchange: adds a user bubble + a bot bubble, then fetches. */
async function askNewQuestion(topic) {
  addUserMessage(topic);
  const botShell = addBotMessageShell(topic);
  sendBtn.disabled = true;
  try {
    const data = await fetchAnswer(topic);
    await botShell.setAnswer(data.explanation, data.diagram, data.diagram_error);
  } catch (err) {
    botShell.setError(err.isApiError ? err.message : "Network error — is the server running?");
  } finally {
    sendBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const topic = input.value.trim();
  if (!topic) return;
  input.value = "";
  input.style.height = "auto";
  askNewQuestion(topic);
});
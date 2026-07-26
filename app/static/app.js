const $ = (id) => document.getElementById(id);
const messages = $("messages");

function authHeaders(json = true) {
  const headers = {Authorization: `Bearer ${$("apiKey").value.trim()}`};
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

function addMessage(kind, text, sources = []) {
  const article = document.createElement("article");
  article.className = kind;
  const body = document.createElement("div");
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.appendChild(paragraph);
  if (sources.length) {
    const sourceBox = document.createElement("div");
    sourceBox.className = "sources";
    sourceBox.textContent = "Sources: " + sources.map(s => `${s.document} #${s.chunk} (${Math.round(s.score * 100)}%)`).join(" · ");
    body.appendChild(sourceBox);
  }
  if (kind === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "G";
    article.appendChild(avatar);
  }
  article.appendChild(body);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

$("file").addEventListener("change", () => {
  $("uploadStatus").textContent = $("file").files[0]?.name || "TXT, MD, CSV, or PDF · 10 MB maximum";
});

$("uploadBtn").addEventListener("click", async () => {
  const file = $("file").files[0];
  if (!file) return void ($("uploadStatus").textContent = "Choose a document first.");
  const data = new FormData();
  data.append("file", file);
  $("uploadStatus").textContent = "Indexing…";
  try {
    const response = await fetch(`/v1/documents?tenant_id=${encodeURIComponent($("tenant").value)}`, {method:"POST", headers:authHeaders(false), body:data});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Indexing failed");
    $("uploadStatus").textContent = `${result.document}: ${result.chunks} chunks indexed.`;
  } catch (error) {
    $("uploadStatus").textContent = error.message;
  }
});

$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  addMessage("user", prompt);
  $("prompt").value = "";
  const thinking = addMessage("assistant thinking", "Searching approved knowledge and generating a grounded answer…");
  try {
    const response = await fetch("/v1/chat", {
      method:"POST",
      headers:authHeaders(),
      body:JSON.stringify({messages:[{role:"user",content:prompt}], tenant_id:$("tenant").value, temperature:0.1})
    });
    const result = await response.json();
    thinking.remove();
    if (!response.ok) throw new Error(result.detail || "Request failed");
    addMessage("assistant", result.answer, result.sources);
  } catch (error) {
    thinking.remove();
    const item = addMessage("assistant", error.message);
    item.classList.add("error");
  }
});


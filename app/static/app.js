const $ = (id) => document.getElementById(id);
const messages = $("messages");
const promptInput = $("prompt");
const starterPanel = $("starterPanel");
const sendButton = $("sendButton");
const conversation = [];

const greeting =
  "Hello! I'm the ACI Chatbot Assistant. I can help you with information about ACI Infotech's " +
  "services, industries, technology capabilities, and case studies.";

function appendAnswerText(container, text) {
  const blocks = text.split(/\n{2,}/).filter(Boolean);
  for (const block of blocks) {
    const paragraph = document.createElement("p");
    paragraph.textContent = block;
    container.appendChild(paragraph);
  }
}

function addCopyButton(container, text) {
  const button = document.createElement("button");
  button.className = "copy-answer";
  button.type = "button";
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
    window.setTimeout(() => {
      button.textContent = "Copy";
    }, 1400);
  });
  container.appendChild(button);
}

function addMessage(kind, text) {
  const article = document.createElement("article");
  article.className = kind;

  if (kind.startsWith("assistant")) {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "A";
    article.appendChild(avatar);
  }

  const body = document.createElement("div");
  body.className = "message-copy";

  if (kind.includes("thinking")) {
    const thinking = document.createElement("div");
    thinking.className = "thinking-label";
    thinking.innerHTML = "<span></span><span></span><span></span><em>Searching approved ACI sources</em>";
    body.appendChild(thinking);
  } else {
    appendAnswerText(body, text);
    if (kind.startsWith("assistant") && !kind.includes("error")) {
      addCopyButton(body, text);
    }
  }

  article.appendChild(body);
  messages.appendChild(article);
  messages.scrollTo({top: messages.scrollHeight, behavior: "smooth"});
  return article;
}

function setBusy(busy) {
  promptInput.disabled = busy;
  sendButton.disabled = busy;
  sendButton.classList.toggle("loading", busy);
}

function resizeComposer() {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 170)}px`;
  $("characterCount").textContent = `${promptInput.value.length} / 12000`;
}

function resetChat() {
  conversation.length = 0;
  messages.replaceChildren();
  addMessage("assistant welcome", greeting);
  starterPanel.hidden = false;
  promptInput.value = "";
  resizeComposer();
  promptInput.focus();
}

async function askQuestion(text) {
  const prompt = text.trim();
  if (!prompt || sendButton.disabled) return;

  starterPanel.hidden = true;
  addMessage("user", prompt);
  conversation.push({role: "user", content: prompt});
  promptInput.value = "";
  resizeComposer();
  setBusy(true);

  const thinking = addMessage("assistant thinking", "");
  try {
    const response = await fetch("/v1/web-chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        messages: conversation.slice(-10),
        tenant_id: "aci-infotech",
        temperature: 0.1,
        max_tokens: 900,
      }),
    });
    const result = await response.json();
    thinking.remove();
    if (!response.ok) {
      throw new Error(result.detail || "The chatbot is temporarily unavailable.");
    }
    addMessage("assistant", result.answer);
    conversation.push({role: "assistant", content: result.answer});
  } catch (error) {
    thinking.remove();
    addMessage(
      "assistant error",
      `${error.message} Please wait a moment and try again.`
    );
  } finally {
    setBusy(false);
    promptInput.focus();
  }
}

async function updateHealth() {
  const status = $("liveStatus");
  try {
    const response = await fetch("/health", {cache: "no-store"});
    const result = await response.json();
    const healthy = response.ok && result.status === "healthy";
    status.className = `live-status ${healthy ? "online" : "degraded"}`;
    status.querySelector("span").textContent = healthy
      ? "Knowledge base online"
      : "Knowledge base warming up";
  } catch {
    status.className = "live-status degraded";
    status.querySelector("span").textContent = "Connection unavailable";
  }
}

$("chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  askQuestion(promptInput.value);
});

document.querySelectorAll("#suggestions button").forEach((button) => {
  button.addEventListener("click", () => askQuestion(button.textContent));
});

promptInput.addEventListener("input", resizeComposer);
promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chatForm").requestSubmit();
  }
});

$("newChat").addEventListener("click", resetChat);

resetChat();
updateHealth();
window.setInterval(updateHealth, 60000);

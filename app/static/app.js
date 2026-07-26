const $ = (id) => document.getElementById(id);
const messages = $("messages");
const promptInput = $("prompt");
const conversation = [];

function addMessage(kind, text, sources = []) {
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
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.appendChild(paragraph);

  if (sources.length) {
    const sourceBox = document.createElement("div");
    sourceBox.className = "sources";
    const bestScore = Math.round(Math.max(...sources.map((source) => source.score)) * 100);
    sourceBox.textContent = `Grounded in ACI knowledge · ${sources.length} matches · best ${bestScore}%`;
    body.appendChild(sourceBox);
  }

  article.appendChild(body);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

async function askQuestion(text) {
  const prompt = text.trim();
  if (!prompt) return;

  $("suggestions").hidden = true;
  addMessage("user", prompt);
  conversation.push({role: "user", content: prompt});
  promptInput.value = "";
  promptInput.disabled = true;

  const thinking = addMessage("assistant thinking", "Searching the ACI knowledge base...");
  try {
    const response = await fetch("/v1/web-chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        messages: conversation.slice(-10),
        tenant_id: "aci-infotech",
        temperature: 0.1,
      }),
    });
    const result = await response.json();
    thinking.remove();
    if (!response.ok) throw new Error(result.detail || "The chatbot is temporarily unavailable.");
    addMessage("assistant", result.answer, result.sources);
    conversation.push({role: "assistant", content: result.answer});
  } catch (error) {
    thinking.remove();
    const item = addMessage("assistant error", error.message);
    item.classList.add("error");
  } finally {
    promptInput.disabled = false;
    promptInput.focus();
  }
}

$("chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  askQuestion(promptInput.value);
});

document.querySelectorAll("#suggestions button").forEach((button) => {
  button.addEventListener("click", () => askQuestion(button.textContent));
});

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chatForm").requestSubmit();
  }
});

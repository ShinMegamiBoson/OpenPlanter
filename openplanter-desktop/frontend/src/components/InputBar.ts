/** Input bar: prompt input + submit button. */
import { solve, cancel } from "../api/invoke";
import { appState } from "../state/store";

export function createInputBar(): HTMLElement {
  const bar = document.createElement("div");
  bar.className = "input-bar";

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Enter objective or /command...";
  input.autofocus = true;

  const submitBtn = document.createElement("button");
  submitBtn.textContent = "Send";

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Cancel";
  cancelBtn.style.display = "none";
  cancelBtn.style.background = "var(--error)";

  bar.appendChild(input);
  bar.appendChild(submitBtn);
  bar.appendChild(cancelBtn);

  async function handleSubmit() {
    const text = input.value.trim();
    if (!text) return;

    // Add user message
    appState.update((s) => ({
      ...s,
      isRunning: true,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "user" as const,
          content: text,
          timestamp: Date.now(),
        },
      ],
    }));

    input.value = "";

    try {
      await solve(text);
    } catch (e) {
      appState.update((s) => ({
        ...s,
        isRunning: false,
        messages: [
          ...s.messages,
          {
            id: crypto.randomUUID(),
            role: "system" as const,
            content: `Failed to start: ${e}`,
            timestamp: Date.now(),
          },
        ],
      }));
    }
  }

  async function handleCancel() {
    try {
      await cancel();
    } catch (e) {
      console.error("Cancel failed:", e);
    }
  }

  submitBtn.addEventListener("click", handleSubmit);
  cancelBtn.addEventListener("click", handleCancel);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === "Escape") {
      handleCancel();
    }
  });

  // Toggle buttons based on running state
  appState.subscribe(() => {
    const running = appState.get().isRunning;
    submitBtn.disabled = running;
    submitBtn.style.display = running ? "none" : "";
    cancelBtn.style.display = running ? "" : "none";
    input.disabled = running;
  });

  return bar;
}

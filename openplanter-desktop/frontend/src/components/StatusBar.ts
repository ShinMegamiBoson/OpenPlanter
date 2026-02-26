/** Status bar: model, provider, tokens, session info. */
import { appState } from "../state/store";

export function createStatusBar(): HTMLElement {
  const bar = document.createElement("div");
  bar.className = "status-bar";

  const providerEl = document.createElement("span");
  providerEl.className = "provider";

  const modelEl = document.createElement("span");
  modelEl.className = "model";

  const sessionEl = document.createElement("span");
  sessionEl.className = "session";

  const tokensEl = document.createElement("span");
  tokensEl.className = "tokens";

  bar.appendChild(providerEl);
  bar.appendChild(modelEl);
  bar.appendChild(sessionEl);
  bar.appendChild(tokensEl);

  function render() {
    const s = appState.get();
    providerEl.textContent = s.provider || "—";
    modelEl.textContent = s.model || "—";
    sessionEl.textContent = s.sessionId ? `session ${s.sessionId.slice(0, 8)}` : "";

    const inK = (s.inputTokens / 1000).toFixed(1);
    const outK = (s.outputTokens / 1000).toFixed(1);
    tokensEl.textContent = `${inK}k in / ${outK}k out`;
  }

  appState.subscribe(render);
  render();

  return bar;
}

/** Status bar: model, provider, tokens, reasoning, mode, session. */
import { appState } from "../state/store";

export function createStatusBar(): HTMLElement {
  const bar = document.createElement("div");
  bar.className = "status-bar";

  const providerEl = document.createElement("span");
  providerEl.className = "provider";

  const modelEl = document.createElement("span");
  modelEl.className = "model";

  const reasoningEl = document.createElement("span");
  reasoningEl.className = "reasoning";

  const zaiPlanEl = document.createElement("span");
  zaiPlanEl.className = "zai-plan";

  const modeEl = document.createElement("span");
  modeEl.className = "mode";

  const sessionEl = document.createElement("span");
  sessionEl.className = "session";

  const tokensEl = document.createElement("span");
  tokensEl.className = "tokens";

  bar.appendChild(providerEl);
  bar.appendChild(modelEl);
  bar.appendChild(reasoningEl);
  bar.appendChild(zaiPlanEl);
  bar.appendChild(modeEl);
  bar.appendChild(sessionEl);
  bar.appendChild(tokensEl);

  function render() {
    const s = appState.get();
    providerEl.textContent = s.provider || "\u2014";
    modelEl.textContent = s.model || "\u2014";
    reasoningEl.textContent = s.reasoningEffort
      ? `reasoning:${s.reasoningEffort}`
      : "";
    zaiPlanEl.textContent =
      s.provider === "zai" ? `zai:${s.zaiPlan || "paygo"}` : "";
    modeEl.textContent = s.recursive ? "recursive" : "flat";
    sessionEl.textContent = s.sessionId ? `session ${s.sessionId.slice(0, 8)}` : "";

    if (s.isRunning && s.currentStep > 0) {
      const health = s.loopHealth;
      if (health) {
        const guardrailText =
          health.metrics.guardrail_warnings > 0
            ? ` guard:${health.metrics.guardrail_warnings}`
            : "";
        sessionEl.textContent =
          `step ${s.currentStep} depth ${s.currentDepth} ` +
          `${health.phase} recon:${health.metrics.recon_streak} ` +
          `reject:${health.metrics.final_rejections}${guardrailText}`;
      } else {
        sessionEl.textContent = `step ${s.currentStep} depth ${s.currentDepth}`;
      }
    }

    const inK = (s.inputTokens / 1000).toFixed(1);
    const outK = (s.outputTokens / 1000).toFixed(1);
    tokensEl.textContent = `${inK}k in / ${outK}k out`;
  }

  appState.subscribe(render);
  render();

  return bar;
}

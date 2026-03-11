/** /zai-plan slash command handler. */
import { saveSettings, updateConfig } from "../api/invoke";
import { appState } from "../state/store";
import type { CommandResult } from "./model";

const VALID_ZAI_PLANS = ["paygo", "coding"];

/** Handle /zai-plan [plan] [--save]. */
export async function handleZaiPlanCommand(args: string): Promise<CommandResult> {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  const requestedPlan = parts[0]?.toLowerCase() ?? "";
  const save = parts.includes("--save");

  if (!requestedPlan) {
    const current = appState.get().zaiPlan || "paygo";
    return {
      action: "handled",
      lines: [
        `Z.AI plan: ${current}`,
        `Valid plans: ${VALID_ZAI_PLANS.join(", ")}`,
      ],
    };
  }

  if (!VALID_ZAI_PLANS.includes(requestedPlan)) {
    return {
      action: "handled",
      lines: [
        `Invalid Z.AI plan "${requestedPlan}". Expected: ${VALID_ZAI_PLANS.join(", ")}`,
      ],
    };
  }

  try {
    const config = await updateConfig({
      zai_plan: requestedPlan,
    });

    appState.update((s) => ({
      ...s,
      zaiPlan: config.zai_plan,
      provider: config.provider,
      model: config.model,
    }));

    const lines = [
      `Z.AI plan set to: ${config.zai_plan}`,
      `Endpoint family: ${config.zai_plan === "coding" ? "https://api.z.ai/api/coding/paas/v4" : "https://api.z.ai/api/paas/v4"}`,
    ];
    if (save) {
      await saveSettings({ zai_plan: config.zai_plan });
      lines.push("(Settings saved)");
    }

    return { action: "handled", lines };
  } catch (e) {
    return {
      action: "handled",
      lines: [`Failed to set Z.AI plan: ${e}`],
    };
  }
}

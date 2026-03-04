/** Category color map for graph nodes. */
export const CATEGORY_COLORS: Record<string, string> = {
  "campaign-finance": "#f97583",
  "contracts": "#79c0ff",
  "corporate": "#56d364",
  "financial": "#d2a8ff",
  "infrastructure": "#ffa657",
  "international": "#ff7b72",
  "lobbying": "#e3b341",
  "nonprofits": "#a5d6ff",
  "regulatory": "#7ee787",
  "sanctions": "#f778ba",
  "media": "#c9d1d9",
  "legal": "#b392f0",
};

export function getCategoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? "#8b949e";
}

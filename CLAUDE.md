## Stop Checklist

Before completing a task, check each item:

- Did you take advantage of ALL applicable skills?
- Did you take advantage of ALL applicable subagents?
- Don't guess about the state of the code or any APIs unless explicitly asked to
- If something doesn't work, your first priority must always be determine WHY it doesn't work unless doing so is impossible
- If you have written or modified code, ensure all components have been deterministically validated to be functioning as intended via breaking up any given process or change into the most granular steps possible and validating the conditions at the entry and exit of each of those steps
- If you have written or modified a user-facing feature, you MUST launch the actual application (`cargo tauri dev`) and exercise the feature at runtime before calling it done. Unit tests with mocked IPC/DOM do not catch webview-specific or integration failures.
- Do not ask the user to perform an action to validate the correctness of your work, you need to validate it yourself
- If the feature is functionally complete, create a temporary commit now. We'll squash the commits later as needed.

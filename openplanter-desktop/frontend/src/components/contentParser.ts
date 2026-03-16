/** Parse <tool_call> and <tool_result> XML blocks from agent content. */

/** Key argument names for tool call display (mirrors ChatPane's KEY_ARGS). */
const KEY_ARGS: Record<string, string> = {
  read_file: "path",
  write_file: "path",
  edit_file: "path",
  list_files: "directory",
  run_shell: "command",
  run_shell_bg: "command",
  kill_shell_bg: "pid",
  web_search: "query",
  fetch_url: "url",
  apply_patch: "path",
  hashline_edit: "path",
};

export type ContentSegment =
  | { type: "text"; text: string }
  | { type: "tool_call"; name: string; keyArg: string; rawArgs: string }
  | { type: "tool_result"; stdout: string; stderr: string; returncode: number | null };

const TAG_RE = /<(tool_call|tool_result)>([\s\S]*?)<\/\1>/g;

/**
 * Split content containing `<tool_call>` / `<tool_result>` XML into typed segments.
 * If the content has no XML tags, returns a single text segment (fast path).
 */
export function parseAgentContent(content: string): ContentSegment[] {
  // Fast path: no XML tags at all
  if (!content.includes("<tool_call>") && !content.includes("<tool_result>")) {
    return [{ type: "text", text: content }];
  }

  const segments: ContentSegment[] = [];
  let lastIndex = 0;

  for (const match of content.matchAll(TAG_RE)) {
    const matchStart = match.index!;
    // Text before this tag
    if (matchStart > lastIndex) {
      segments.push({ type: "text", text: content.slice(lastIndex, matchStart) });
    }

    const tagName = match[1] as "tool_call" | "tool_result";
    const inner = match[2].trim();

    if (tagName === "tool_call") {
      segments.push(parseToolCall(inner));
    } else {
      segments.push(parseToolResult(inner));
    }

    lastIndex = matchStart + match[0].length;
  }

  // Trailing text
  if (lastIndex < content.length) {
    segments.push({ type: "text", text: content.slice(lastIndex) });
  }

  return segments;
}

function parseToolCall(json: string): ContentSegment {
  try {
    const obj = JSON.parse(json);
    const name: string = obj.name ?? "unknown";
    const args = obj.arguments ?? {};
    const keyName = KEY_ARGS[name];
    const keyArg = keyName && typeof args[keyName] === "string" ? args[keyName] : "";
    return { type: "tool_call", name, keyArg, rawArgs: JSON.stringify(args) };
  } catch {
    return { type: "tool_call", name: "unknown", keyArg: "", rawArgs: json };
  }
}

function parseToolResult(json: string): ContentSegment {
  try {
    const obj = JSON.parse(json);
    return {
      type: "tool_result",
      stdout: typeof obj.stdout === "string" ? obj.stdout : "",
      stderr: typeof obj.stderr === "string" ? obj.stderr : "",
      returncode: typeof obj.returncode === "number" ? obj.returncode : null,
    };
  } catch {
    // Treat unparseable result as stdout
    return { type: "tool_result", stdout: json, stderr: "", returncode: null };
  }
}

/**
 * Strip `<tool_call>...</tool_call>` and `<tool_result>...</tool_result>` blocks,
 * leaving only prose text. Collapses excess whitespace.
 */
export function stripToolXml(text: string): string {
  if (!text.includes("<tool_call>") && !text.includes("<tool_result>")) {
    return text;
  }
  return text.replace(TAG_RE, "").replace(/\n{3,}/g, "\n\n").trim();
}

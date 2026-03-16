import { describe, it, expect } from "vitest";
import { parseAgentContent, stripToolXml } from "./contentParser";

describe("parseAgentContent", () => {
  it("returns single text segment for plain content", () => {
    const result = parseAgentContent("Hello world");
    expect(result).toEqual([{ type: "text", text: "Hello world" }]);
  });

  it("returns single text segment when no XML tags present", () => {
    const result = parseAgentContent("Some markdown **bold** text\n\nParagraph two.");
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe("text");
  });

  it("parses a tool_call block", () => {
    const content = `<tool_call>
{"name": "run_shell", "arguments": {"command": "echo test"}}
</tool_call>`;
    const result = parseAgentContent(content);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({
      type: "tool_call",
      name: "run_shell",
      keyArg: "echo test",
      rawArgs: '{"command":"echo test"}',
    });
  });

  it("parses a tool_result block", () => {
    const content = `<tool_result>
{"stdout": "test\\n", "stderr": "", "returncode": 0}
</tool_result>`;
    const result = parseAgentContent(content);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({
      type: "tool_result",
      stdout: "test\n",
      stderr: "",
      returncode: 0,
    });
  });

  it("parses mixed text, tool_call, and tool_result", () => {
    const content = `I'll verify the workspace...

<tool_call>
{"name": "run_shell", "arguments": {"command": "echo test"}}
</tool_call>

<tool_result>
{"stdout": "test\\n", "stderr": "", "returncode": 0}
</tool_result>

Environment confirmed.`;

    const result = parseAgentContent(content);
    expect(result).toHaveLength(5);
    expect(result[0].type).toBe("text");
    expect((result[0] as any).text).toContain("verify the workspace");
    expect(result[1].type).toBe("tool_call");
    expect((result[1] as any).name).toBe("run_shell");
    expect(result[2].type).toBe("text"); // whitespace between tags
    expect(result[3].type).toBe("tool_result");
    expect(result[4].type).toBe("text");
    expect((result[4] as any).text).toContain("Environment confirmed");
  });

  it("extracts key arg for known tools", () => {
    const content = `<tool_call>
{"name": "read_file", "arguments": {"path": "/src/main.ts"}}
</tool_call>`;
    const result = parseAgentContent(content);
    expect(result[0]).toMatchObject({
      type: "tool_call",
      name: "read_file",
      keyArg: "/src/main.ts",
    });
  });

  it("returns empty keyArg for unknown tools", () => {
    const content = `<tool_call>
{"name": "custom_tool", "arguments": {"data": "stuff"}}
</tool_call>`;
    const result = parseAgentContent(content);
    expect(result[0]).toMatchObject({
      type: "tool_call",
      name: "custom_tool",
      keyArg: "",
    });
  });

  it("handles malformed JSON in tool_call gracefully", () => {
    const content = `<tool_call>
not valid json
</tool_call>`;
    const result = parseAgentContent(content);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      type: "tool_call",
      name: "unknown",
      keyArg: "",
    });
  });

  it("handles malformed JSON in tool_result gracefully", () => {
    const content = `<tool_result>
raw output text
</tool_result>`;
    const result = parseAgentContent(content);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      type: "tool_result",
      stdout: "raw output text",
      stderr: "",
      returncode: null,
    });
  });

  it("handles tool_result with error", () => {
    const content = `<tool_result>
{"stdout": "", "stderr": "command not found", "returncode": 127}
</tool_result>`;
    const result = parseAgentContent(content);
    expect(result[0]).toEqual({
      type: "tool_result",
      stdout: "",
      stderr: "command not found",
      returncode: 127,
    });
  });

  it("handles multiple tool calls in sequence", () => {
    const content = `<tool_call>
{"name": "read_file", "arguments": {"path": "/a.ts"}}
</tool_call>

<tool_result>
{"stdout": "contents", "stderr": "", "returncode": 0}
</tool_result>

<tool_call>
{"name": "write_file", "arguments": {"path": "/b.ts"}}
</tool_call>

<tool_result>
{"stdout": "ok", "stderr": "", "returncode": 0}
</tool_result>`;

    const result = parseAgentContent(content);
    const types = result.map((s) => s.type);
    expect(types).toEqual(["tool_call", "text", "tool_result", "text", "tool_call", "text", "tool_result"]);
  });
});

describe("stripToolXml", () => {
  it("returns text unchanged when no XML tags present", () => {
    expect(stripToolXml("plain text")).toBe("plain text");
  });

  it("strips tool_call blocks", () => {
    const input = `Before\n\n<tool_call>\n{"name":"x","arguments":{}}\n</tool_call>\n\nAfter`;
    expect(stripToolXml(input)).toBe("Before\n\nAfter");
  });

  it("strips tool_result blocks", () => {
    const input = `Before\n\n<tool_result>\n{"stdout":"x","stderr":"","returncode":0}\n</tool_result>\n\nAfter`;
    expect(stripToolXml(input)).toBe("Before\n\nAfter");
  });

  it("strips multiple blocks and collapses whitespace", () => {
    const input = `Start\n\n<tool_call>\n{}\n</tool_call>\n\n\n\n<tool_result>\n{}\n</tool_result>\n\n\n\nEnd`;
    const result = stripToolXml(input);
    expect(result).toBe("Start\n\nEnd");
    // No triple newlines
    expect(result).not.toContain("\n\n\n");
  });

  it("returns empty string when content is only tool blocks", () => {
    const input = `<tool_call>\n{}\n</tool_call>\n\n<tool_result>\n{}\n</tool_result>`;
    expect(stripToolXml(input)).toBe("");
  });
});

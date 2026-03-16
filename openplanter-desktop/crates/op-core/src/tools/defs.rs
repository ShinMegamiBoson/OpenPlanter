/// Provider-neutral tool definitions for the OpenPlanter agent.
///
/// Single source of truth for tool schemas. Converter helpers produce the
/// provider-specific shapes expected by OpenAI and Anthropic APIs.
use serde_json::{Value, json};

struct ToolDef {
    name: &'static str,
    description: &'static str,
    parameters: Value,
}

fn mvp_tool_defs() -> Vec<ToolDef> {
    vec![
        // ── Filesystem ──
        ToolDef {
            name: "list_files",
            description: "List files in the workspace directory. Optionally filter with a glob pattern.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "glob": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files."
                    }
                },
                "required": [],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "search_files",
            description: "Search file contents in the workspace for a text or regex query.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text or regex to search for."
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional glob pattern to restrict which files are searched."
                    }
                },
                "required": ["query"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "read_file",
            description: "Read the contents of a file in the workspace. Lines are numbered LINE:HASH|content by default for use with hashline_edit. Set hashline=false for plain N|content.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative or absolute path within the workspace."
                    },
                    "hashline": {
                        "type": "boolean",
                        "description": "Prefix each line with LINE:HASH| format for content verification. Default true."
                    }
                },
                "required": ["path"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "write_file",
            description: "Create or overwrite a file in the workspace with the given content.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path for the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write."
                    }
                },
                "required": ["path", "content"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "edit_file",
            description: "Replace a specific text span in a file. Provide the exact old text to find and the new text to replace it with. The old text must appear exactly once in the file.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to edit."
                    },
                    "old_text": {
                        "type": "string",
                        "description": "The exact text to find and replace."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The replacement text."
                    }
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": false
            }),
        },
        // ── Shell ──
        ToolDef {
            name: "run_shell",
            description: "Execute a shell command from the workspace root and return its output.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute."
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds for this command (default: agent default, max: 600)."
                    }
                },
                "required": ["command"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "run_shell_bg",
            description: "Start a shell command in the background. Returns a job ID to check or kill later.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run in the background."
                    }
                },
                "required": ["command"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "check_shell_bg",
            description: "Check the status and output of a background job started with run_shell_bg.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID returned by run_shell_bg."
                    }
                },
                "required": ["job_id"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "kill_shell_bg",
            description: "Kill a background job started with run_shell_bg.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID returned by run_shell_bg."
                    }
                },
                "required": ["job_id"],
                "additionalProperties": false
            }),
        },
        // ── Web ──
        ToolDef {
            name: "web_search",
            description: "Search the web using the configured Exa, Firecrawl, Brave, or Tavily backend. Returns URLs, titles, snippets, and optional page text.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Web search query string."
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-20, default 10)."
                    },
                    "include_text": {
                        "type": "boolean",
                        "description": "Whether to include page text in results."
                    }
                },
                "required": ["query"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "fetch_url",
            description: "Fetch and return the text content of one or more URLs using the configured Exa, Firecrawl, Brave, or Tavily backend.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "List of URLs to fetch."
                    }
                },
                "required": ["urls"],
                "additionalProperties": false
            }),
        },
        // ── Patching ──
        ToolDef {
            name: "apply_patch",
            description: "Apply a Codex-style patch to one or more files. Use the *** Begin Patch / *** End Patch format with Update File, Add File, and Delete File operations.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "The full patch block in Codex patch format."
                    }
                },
                "required": ["patch"],
                "additionalProperties": false
            }),
        },
        ToolDef {
            name: "hashline_edit",
            description: "Edit a file using hash-anchored line references from read_file(hashline=true). Operations: set_line (replace one line), replace_lines (replace a range), insert_after (insert new lines after an anchor).",
            parameters: json!({
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "Relative path to the file." },
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "set_line": {
                                    "type": "string",
                                    "description": "Anchor 'N:HH' for single-line replace."
                                },
                                "replace_lines": {
                                    "type": "object",
                                    "description": "Range with 'start' and 'end' anchors.",
                                    "properties": {
                                        "start": { "type": "string" },
                                        "end": { "type": "string" }
                                    },
                                    "required": ["start", "end"],
                                    "additionalProperties": false
                                },
                                "insert_after": {
                                    "type": "string",
                                    "description": "Anchor 'N:HH' to insert after."
                                },
                                "content": {
                                    "type": "string",
                                    "description": "New content for the operation."
                                }
                            },
                            "required": [],
                            "additionalProperties": false
                        },
                        "description": "Edit operations: set_line, replace_lines, or insert_after."
                    }
                },
                "required": ["path", "edits"],
                "additionalProperties": false
            }),
        },
        // ── Meta ──
        ToolDef {
            name: "think",
            description: "Record an internal planning thought. Use this to reason about the task before acting.",
            parameters: json!({
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "Your planning thought or reasoning note."
                    }
                },
                "required": ["note"],
                "additionalProperties": false
            }),
        },
    ]
}

/// For OpenAI strict mode: make all properties required, wrapping optional ones
/// with `anyOf [original, null]`. Recurse into nested objects and array items.
fn strict_fixup(schema: &mut Value) {
    let Some(schema_type) = schema
        .get("type")
        .and_then(|t| t.as_str())
        .map(String::from)
    else {
        return;
    };

    if schema_type == "object" {
        let all_keys: Vec<String> = schema
            .get("properties")
            .and_then(|p| p.as_object())
            .map(|o| o.keys().cloned().collect())
            .unwrap_or_default();

        let required: Vec<String> = schema
            .get("required")
            .and_then(|r| r.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        // Recurse into each property first
        if let Some(props) = schema.get_mut("properties").and_then(|p| p.as_object_mut()) {
            for (_key, prop) in props.iter_mut() {
                strict_fixup(prop);
            }
        }

        // Wrap optional properties with anyOf [original, null]
        if let Some(props) = schema.get_mut("properties").and_then(|p| p.as_object_mut()) {
            for key in &all_keys {
                if required.contains(key) {
                    continue;
                }
                if let Some(prop) = props.get_mut(key) {
                    if let Some(original_type) = prop.get("type").cloned() {
                        let desc = prop.get("description").cloned();
                        let mut original_schema = json!({ "type": original_type });
                        // Copy non-type, non-description fields to original schema
                        if let Some(obj) = prop.as_object() {
                            for (k, v) in obj {
                                if k != "type" && k != "description" {
                                    original_schema[k] = v.clone();
                                }
                            }
                        }
                        let mut new_prop = json!({
                            "anyOf": [original_schema, { "type": "null" }]
                        });
                        if let Some(d) = desc {
                            new_prop["description"] = d;
                        }
                        *prop = new_prop;
                    }
                }
            }
        }

        // All properties required
        schema["required"] = json!(all_keys);
        schema["additionalProperties"] = json!(false);
    } else if schema_type == "array" {
        if let Some(items) = schema.get_mut("items") {
            strict_fixup(items);
        }
    }
}

/// Convert to OpenAI tools format: `[{ type: "function", function: { name, description, parameters, strict } }]`
pub fn to_openai_tools() -> Vec<Value> {
    mvp_tool_defs()
        .into_iter()
        .map(|def| {
            let mut params = def.parameters;
            strict_fixup(&mut params);
            json!({
                "type": "function",
                "function": {
                    "name": def.name,
                    "description": def.description,
                    "parameters": params,
                    "strict": true
                }
            })
        })
        .collect()
}

/// Convert to Anthropic tools format: `[{ name, description, input_schema }]`
pub fn to_anthropic_tools() -> Vec<Value> {
    mvp_tool_defs()
        .into_iter()
        .map(|def| {
            json!({
                "name": def.name,
                "description": def.description,
                "input_schema": def.parameters
            })
        })
        .collect()
}

/// Build tool definitions for the given provider.
pub fn build_tool_defs(provider: &str) -> Vec<Value> {
    match provider {
        "anthropic" => to_anthropic_tools(),
        _ => to_openai_tools(),
    }
}

/// List of all known tool names.
pub fn tool_names() -> Vec<&'static str> {
    mvp_tool_defs().iter().map(|d| d.name).collect()
}

/// Build curator-restricted tool definitions for the given provider.
///
/// Returns only filesystem + meta tools — no web, shell, or background job tools.
pub fn build_curator_tool_defs(provider: &str) -> Vec<Value> {
    use crate::engine::curator::CURATOR_TOOL_NAMES;

    let filtered: Vec<ToolDef> = mvp_tool_defs()
        .into_iter()
        .filter(|d| CURATOR_TOOL_NAMES.contains(&d.name))
        .collect();

    match provider {
        "anthropic" => filtered
            .into_iter()
            .map(|def| {
                json!({
                    "name": def.name,
                    "description": def.description,
                    "input_schema": def.parameters
                })
            })
            .collect(),
        _ => filtered
            .into_iter()
            .map(|def| {
                let mut params = def.parameters;
                strict_fixup(&mut params);
                json!({
                    "type": "function",
                    "function": {
                        "name": def.name,
                        "description": def.description,
                        "parameters": params,
                        "strict": true
                    }
                })
            })
            .collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_openai_tools_structure() {
        let tools = to_openai_tools();
        assert!(!tools.is_empty());
        for tool in &tools {
            assert_eq!(tool["type"], "function");
            assert!(tool["function"]["name"].is_string());
            assert!(tool["function"]["description"].is_string());
            assert!(tool["function"]["parameters"].is_object());
            assert_eq!(tool["function"]["strict"], true);
        }
    }

    #[test]
    fn test_anthropic_tools_structure() {
        let tools = to_anthropic_tools();
        assert!(!tools.is_empty());
        for tool in &tools {
            assert!(tool["name"].is_string());
            assert!(tool["description"].is_string());
            assert!(tool["input_schema"].is_object());
        }
    }

    #[test]
    fn test_openai_strict_all_required() {
        let tools = to_openai_tools();
        for tool in &tools {
            let params = &tool["function"]["parameters"];
            let props = params["properties"].as_object().unwrap();
            let required = params["required"].as_array().unwrap();
            assert_eq!(
                required.len(),
                props.len(),
                "All properties must be required in strict mode for tool {}",
                tool["function"]["name"]
            );
        }
    }

    #[test]
    fn test_tool_names() {
        let names = tool_names();
        assert!(names.contains(&"read_file"));
        assert!(names.contains(&"run_shell"));
        assert!(names.contains(&"web_search"));
        assert!(names.contains(&"think"));
        assert!(names.contains(&"apply_patch"));
    }

    #[test]
    fn test_build_tool_defs_anthropic() {
        let tools = build_tool_defs("anthropic");
        assert!(tools[0].get("input_schema").is_some());
        assert!(tools[0].get("type").is_none());
    }

    #[test]
    fn test_build_tool_defs_openai() {
        let tools = build_tool_defs("openai");
        assert_eq!(tools[0]["type"], "function");
    }

    #[test]
    fn test_strict_fixup_wraps_optional_with_anyof() {
        // list_files has only optional "glob" parameter
        let tools = to_openai_tools();
        let list_files = tools
            .iter()
            .find(|t| t["function"]["name"] == "list_files")
            .unwrap();
        let glob_prop = &list_files["function"]["parameters"]["properties"]["glob"];
        assert!(
            glob_prop.get("anyOf").is_some(),
            "Optional 'glob' should be wrapped with anyOf"
        );
    }

    #[test]
    fn test_curator_tool_defs_openai() {
        let tools = build_curator_tool_defs("openai");
        assert_eq!(tools.len(), 6, "curator should have exactly 6 tools");

        let names: Vec<String> = tools
            .iter()
            .map(|t| t["function"]["name"].as_str().unwrap().to_string())
            .collect();

        // Should include filesystem + meta tools
        assert!(names.contains(&"read_file".to_string()));
        assert!(names.contains(&"write_file".to_string()));
        assert!(names.contains(&"edit_file".to_string()));
        assert!(names.contains(&"list_files".to_string()));
        assert!(names.contains(&"search_files".to_string()));
        assert!(names.contains(&"think".to_string()));
        assert!(!names.contains(&"apply_patch".to_string()));
        assert!(!names.contains(&"hashline_edit".to_string()));

        // Should NOT include web, shell, or bg job tools
        assert!(!names.contains(&"web_search".to_string()));
        assert!(!names.contains(&"fetch_url".to_string()));
        assert!(!names.contains(&"run_shell".to_string()));
        assert!(!names.contains(&"run_shell_bg".to_string()));
        assert!(!names.contains(&"check_shell_bg".to_string()));
        assert!(!names.contains(&"kill_shell_bg".to_string()));
    }

    #[test]
    fn test_curator_tool_defs_anthropic() {
        let tools = build_curator_tool_defs("anthropic");
        assert_eq!(tools.len(), 6);

        // Anthropic format: flat with input_schema
        assert!(tools[0].get("input_schema").is_some());
        assert!(tools[0].get("type").is_none());
    }
}

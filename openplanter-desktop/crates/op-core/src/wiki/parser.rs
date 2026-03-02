// Wiki index.md parser and cross-reference extraction.
//
// Extracts structured entries from wiki/index.md and cross-references
// between wiki pages.

use serde::{Deserialize, Serialize};

/// A wiki entry parsed from index.md.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WikiEntry {
    pub title: String,
    pub path: String,
    pub category: String,
    pub aliases: Vec<String>,
}

/// A cross-reference between two wiki pages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WikiCrossRef {
    pub source: String,
    pub target: String,
    pub context: String,
}

/// Parse wiki/index.md content to extract entries and their categories.
///
/// Expects the index to be organized with `###` headings for categories
/// and markdown tables with `| Label | Path | Aliases |` rows beneath.
pub fn parse_index(content: &str) -> Vec<WikiEntry> {
    let mut entries = Vec::new();
    let mut current_category = String::new();

    for line in content.lines() {
        let trimmed = line.trim();

        // Category heading
        if trimmed.starts_with("### ") {
            current_category = trimmed[4..].trim().to_lowercase();
            // Normalize common category names
            current_category = current_category
                .replace(' ', "-")
                .replace('_', "-");
            continue;
        }

        // Table row (skip header and separator rows)
        if trimmed.starts_with('|') && !trimmed.starts_with("| -") && !trimmed.contains("---") {
            let cols: Vec<&str> = trimmed
                .split('|')
                .map(|c| c.trim())
                .filter(|c| !c.is_empty())
                .collect();

            // Skip header row (Label | Path | ...)
            if cols.len() >= 2 {
                let label = cols[0];
                let path = cols[1];

                // Skip if this looks like a header row
                if label.eq_ignore_ascii_case("label")
                    || label.eq_ignore_ascii_case("name")
                    || label.eq_ignore_ascii_case("source")
                {
                    continue;
                }

                let aliases = if cols.len() >= 3 && !cols[2].is_empty() {
                    cols[2]
                        .split(',')
                        .map(|a| a.trim().to_string())
                        .filter(|a| !a.is_empty())
                        .collect()
                } else {
                    vec![]
                };

                entries.push(WikiEntry {
                    title: label.to_string(),
                    path: path.to_string(),
                    category: current_category.clone(),
                    aliases,
                });
            }
        }
    }

    entries
}

/// Scan a wiki page for cross-references (markdown links to other wiki pages).
///
/// Looks for `[text](path)` links where the path points to another wiki file.
pub fn extract_cross_refs(page_path: &str, content: &str) -> Vec<WikiCrossRef> {
    let mut refs = Vec::new();
    let link_re = regex::Regex::new(r"\[([^\]]+)\]\(([^)]+\.md)\)").unwrap();

    for line in content.lines() {
        for cap in link_re.captures_iter(line) {
            let link_text = cap.get(1).unwrap().as_str();
            let link_target = cap.get(2).unwrap().as_str();

            // Skip self-references
            if link_target == page_path {
                continue;
            }

            refs.push(WikiCrossRef {
                source: page_path.to_string(),
                target: link_target.to_string(),
                context: link_text.to_string(),
            });
        }
    }

    refs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_index_basic() {
        let content = "\
### Corporate

| Label | Path | Aliases |
| --- | --- | --- |
| Acme Corp | wiki/acme-corp.md | AC, Acme |
| Widget Inc | wiki/widget-inc.md | |

### Campaign Finance

| Label | Path | Aliases |
| --- | --- | --- |
| PAC Fund Alpha | wiki/pac-fund-alpha.md | PFA |
";
        let entries = parse_index(content);
        assert_eq!(entries.len(), 3);
        assert_eq!(entries[0].title, "Acme Corp");
        assert_eq!(entries[0].category, "corporate");
        assert_eq!(entries[0].aliases, vec!["AC", "Acme"]);
        assert_eq!(entries[1].title, "Widget Inc");
        assert!(entries[1].aliases.is_empty());
        assert_eq!(entries[2].category, "campaign-finance");
    }

    #[test]
    fn test_parse_index_empty() {
        let entries = parse_index("");
        assert!(entries.is_empty());
    }

    #[test]
    fn test_parse_index_no_tables() {
        let entries = parse_index("### Corporate\n\nSome text here.\n");
        assert!(entries.is_empty());
    }

    #[test]
    fn test_extract_cross_refs() {
        let content = "\
## Cross References

See also [PAC Fund Alpha](wiki/pac-fund-alpha.md) for related filings.
Links to [Bank of West](wiki/bank-of-west.md) transactions.
";
        let refs = extract_cross_refs("wiki/acme-corp.md", content);
        assert_eq!(refs.len(), 2);
        assert_eq!(refs[0].source, "wiki/acme-corp.md");
        assert_eq!(refs[0].target, "wiki/pac-fund-alpha.md");
        assert_eq!(refs[0].context, "PAC Fund Alpha");
        assert_eq!(refs[1].target, "wiki/bank-of-west.md");
    }

    #[test]
    fn test_extract_cross_refs_skips_self() {
        let content = "See [Self](wiki/acme-corp.md) and [Other](wiki/other.md)";
        let refs = extract_cross_refs("wiki/acme-corp.md", content);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].target, "wiki/other.md");
    }

    #[test]
    fn test_extract_cross_refs_empty() {
        let refs = extract_cross_refs("wiki/test.md", "No links here.");
        assert!(refs.is_empty());
    }
}

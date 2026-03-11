// Fuzzy name registry for wiki entity matching.
//
// Uses Jaro-Winkler similarity from `strsim` for fuzzy string matching.

use strsim::jaro_winkler;

/// Registry of canonical names mapped to entity IDs, with fuzzy lookup.
pub struct NameRegistry {
    entries: Vec<(String, String)>, // (canonical_name, entity_id)
}

impl NameRegistry {
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
        }
    }

    /// Register a canonical name for an entity.
    pub fn register(&mut self, name: &str, entity_id: &str) {
        self.entries.push((name.to_string(), entity_id.to_string()));
    }

    /// Register multiple aliases for the same entity.
    pub fn register_aliases(&mut self, aliases: &[String], entity_id: &str) {
        for alias in aliases {
            self.entries.push((alias.clone(), entity_id.to_string()));
        }
    }

    /// Find the best match above the default threshold (0.85).
    ///
    /// Returns the entity_id and similarity score, or None if no match.
    pub fn find_best(&self, query: &str) -> Option<(String, f64)> {
        self.find_all(query, 0.85).into_iter().next()
    }

    /// Find all matches above the given threshold, sorted by score descending.
    pub fn find_all(&self, query: &str, threshold: f64) -> Vec<(String, f64)> {
        let query_lower = query.to_lowercase();
        let mut matches: Vec<(String, f64)> = self
            .entries
            .iter()
            .map(|(name, id)| {
                let score = jaro_winkler(&query_lower, &name.to_lowercase());
                (id.clone(), score)
            })
            .filter(|(_, score)| *score >= threshold)
            .collect();

        // Sort by score descending
        matches.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        // Deduplicate by entity_id (keep highest score)
        let mut seen = std::collections::HashSet::new();
        matches.retain(|(id, _)| seen.insert(id.clone()));

        matches
    }

    /// Returns the number of registered entries.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Returns true if the registry is empty.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

impl Default for NameRegistry {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_exact_match() {
        let mut reg = NameRegistry::new();
        reg.register("Acme Corp", "acme-corp");
        let result = reg.find_best("Acme Corp");
        assert!(result.is_some());
        let (id, score) = result.unwrap();
        assert_eq!(id, "acme-corp");
        assert!((score - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_fuzzy_match() {
        let mut reg = NameRegistry::new();
        reg.register("Acme Corporation", "acme-corp");
        let result = reg.find_best("Acme Corp");
        assert!(result.is_some());
        let (id, _) = result.unwrap();
        assert_eq!(id, "acme-corp");
    }

    #[test]
    fn test_no_match_below_threshold() {
        let mut reg = NameRegistry::new();
        reg.register("Acme Corp", "acme-corp");
        let result = reg.find_best("Completely Different Name");
        assert!(result.is_none());
    }

    #[test]
    fn test_case_insensitive() {
        let mut reg = NameRegistry::new();
        reg.register("ACME CORP", "acme-corp");
        let result = reg.find_best("acme corp");
        assert!(result.is_some());
        assert_eq!(result.unwrap().0, "acme-corp");
    }

    #[test]
    fn test_aliases() {
        let mut reg = NameRegistry::new();
        reg.register("Acme Corp", "acme-corp");
        reg.register_aliases(&["AC".to_string(), "Acme".to_string()], "acme-corp");
        assert_eq!(reg.len(), 3);

        let result = reg.find_best("Acme");
        assert!(result.is_some());
        assert_eq!(result.unwrap().0, "acme-corp");
    }

    #[test]
    fn test_find_all_sorted() {
        let mut reg = NameRegistry::new();
        reg.register("Alpha Corp", "alpha");
        reg.register("Alpha Corporation", "alpha-corp");
        reg.register("Beta Inc", "beta");
        let results = reg.find_all("Alpha Corp", 0.7);
        assert!(!results.is_empty());
        // Best match should be first
        assert!(results[0].1 >= results.last().unwrap().1);
    }

    #[test]
    fn test_find_all_deduplicates() {
        let mut reg = NameRegistry::new();
        reg.register("Acme Corp", "acme");
        reg.register("Acme Corporation", "acme");
        let results = reg.find_all("Acme Corp", 0.7);
        // Should only have one entry for "acme"
        assert_eq!(results.len(), 1);
    }

    #[test]
    fn test_empty_registry() {
        let reg = NameRegistry::new();
        assert!(reg.is_empty());
        assert!(reg.find_best("anything").is_none());
    }
}

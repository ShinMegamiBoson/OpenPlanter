// Acceptance criteria judge — evaluates whether model output meets criteria.

use serde::{Deserialize, Serialize};

/// Verdict from the acceptance criteria judge.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum JudgeVerdict {
    Pass,
    Fail,
    Partial,
}

/// Result of evaluating output against acceptance criteria.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JudgeResult {
    pub verdict: JudgeVerdict,
    pub reasoning: String,
    pub score: f64,
}

/// Evaluates whether model output satisfies the given acceptance criteria.
///
/// Currently uses keyword/heuristic matching. A future version can use
/// an LLM call for LLM-as-judge evaluation.
pub struct AcceptanceCriteriaJudge;

impl AcceptanceCriteriaJudge {
    pub fn new() -> Self {
        Self
    }

    /// Evaluate output against criteria using keyword heuristics.
    ///
    /// Extracts significant terms from the criteria and checks how many
    /// appear in the output. Returns Pass (>= 70%), Partial (>= 30%),
    /// or Fail (< 30%).
    pub fn evaluate(&self, criteria: &str, output: &str) -> JudgeResult {
        let terms = extract_terms(criteria);
        if terms.is_empty() {
            return JudgeResult {
                verdict: JudgeVerdict::Pass,
                reasoning: "No criteria terms to evaluate".into(),
                score: 1.0,
            };
        }

        let output_lower = output.to_lowercase();
        let matched: Vec<&str> = terms
            .iter()
            .filter(|t| output_lower.contains(&t.to_lowercase()))
            .copied()
            .collect();

        let score = matched.len() as f64 / terms.len() as f64;
        let verdict = if score >= 0.7 {
            JudgeVerdict::Pass
        } else if score >= 0.3 {
            JudgeVerdict::Partial
        } else {
            JudgeVerdict::Fail
        };

        let reasoning = format!(
            "Matched {}/{} criteria terms ({}): [{}]",
            matched.len(),
            terms.len(),
            format!("{:.0}%", score * 100.0),
            matched.join(", ")
        );

        JudgeResult {
            verdict,
            reasoning,
            score,
        }
    }
}

impl Default for AcceptanceCriteriaJudge {
    fn default() -> Self {
        Self::new()
    }
}

/// Extract significant terms from criteria text (words >= 4 chars, excluding stop words).
fn extract_terms(text: &str) -> Vec<&str> {
    const STOP_WORDS: &[&str] = &[
        "the", "and", "for", "are", "but", "not", "you", "all",
        "can", "has", "her", "was", "one", "our", "out", "with",
        "that", "this", "have", "from", "they", "been", "said",
        "each", "which", "their", "will", "other", "about", "many",
        "then", "them", "these", "some", "would", "make", "like",
        "into", "could", "time", "very", "when", "what", "your",
        "there", "should", "must", "also",
    ];

    text.split_whitespace()
        .filter(|w| {
            let clean = w.trim_matches(|c: char| !c.is_alphanumeric());
            clean.len() >= 4 && !STOP_WORDS.contains(&clean.to_lowercase().as_str())
        })
        .map(|w| w.trim_matches(|c: char| !c.is_alphanumeric()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pass_when_all_terms_present() {
        let judge = AcceptanceCriteriaJudge::new();
        let result = judge.evaluate(
            "Find connections between Acme Corp and lobbying groups",
            "The investigation found that Acme Corp has direct connections to several lobbying groups including Lobby Group One.",
        );
        assert_eq!(result.verdict, JudgeVerdict::Pass);
        assert!(result.score >= 0.7);
    }

    #[test]
    fn test_fail_when_no_terms_present() {
        let judge = AcceptanceCriteriaJudge::new();
        let result = judge.evaluate(
            "Find connections between Acme Corp and lobbying groups",
            "The weather today is sunny and warm.",
        );
        assert_eq!(result.verdict, JudgeVerdict::Fail);
        assert!(result.score < 0.3);
    }

    #[test]
    fn test_partial_when_some_terms_present() {
        let judge = AcceptanceCriteriaJudge::new();
        let result = judge.evaluate(
            "Investigate Acme Corp subsidiaries",
            "Acme Corp is a large corporation with many divisions.",
        );
        // "Investigate"(not matched), "Acme"(matched), "Corp"(matched), "subsidiaries"(not matched)
        // 2/4 = 0.5 => Partial
        assert_eq!(result.verdict, JudgeVerdict::Partial);
    }

    #[test]
    fn test_empty_criteria_passes() {
        let judge = AcceptanceCriteriaJudge::new();
        let result = judge.evaluate("", "any output");
        assert_eq!(result.verdict, JudgeVerdict::Pass);
        assert_eq!(result.score, 1.0);
    }

    #[test]
    fn test_extract_terms_filters_short_words() {
        let terms = extract_terms("I am a big dog");
        // Only "big" is >= 4 chars... actually "big" is 3 chars, so nothing
        // Wait: the threshold is >= 4 chars, so none of these pass
        // Actually let me re-check: "I"=1, "am"=2, "a"=1, "big"=3, "dog"=3
        // None are >= 4 chars
        assert!(terms.is_empty());
    }

    #[test]
    fn test_extract_terms_filters_stop_words() {
        let terms = extract_terms("this should have been filtered");
        // "this"=stop, "should"=stop, "have"=stop, "been"=stop, "filtered"=8 chars
        assert_eq!(terms, vec!["filtered"]);
    }

    #[test]
    fn test_case_insensitive_matching() {
        let judge = AcceptanceCriteriaJudge::new();
        let result = judge.evaluate("ACME CORP", "acme corp results");
        assert_eq!(result.verdict, JudgeVerdict::Pass);
    }

    #[test]
    fn test_serialization() {
        let result = JudgeResult {
            verdict: JudgeVerdict::Partial,
            reasoning: "test".into(),
            score: 0.5,
        };
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"partial\""));
        let parsed: JudgeResult = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.verdict, JudgeVerdict::Partial);
    }
}

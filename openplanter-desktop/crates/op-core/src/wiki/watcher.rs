// Filesystem watcher for wiki directory changes.
//
// Uses the `notify` crate to watch for file creates, modifications,
// and deletions in the wiki directory.

use notify::{Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use std::path::PathBuf;
use tokio::sync::mpsc;

/// A change event from the wiki filesystem watcher.
#[derive(Debug, Clone)]
pub struct WikiChangeEvent {
    pub path: PathBuf,
    pub kind: WikiChangeKind,
}

/// The kind of wiki filesystem change.
#[derive(Debug, Clone, PartialEq)]
pub enum WikiChangeKind {
    Created,
    Modified,
    Deleted,
}

/// Watches a wiki directory for filesystem changes.
pub struct WikiWatcher {
    _watcher: RecommendedWatcher,
}

impl WikiWatcher {
    /// Start watching a wiki directory.
    ///
    /// Returns the watcher and a receiver for change events. The receiver
    /// yields `WikiChangeEvent`s as files are created, modified, or deleted.
    pub fn start(
        wiki_dir: PathBuf,
    ) -> std::io::Result<(Self, mpsc::UnboundedReceiver<WikiChangeEvent>)> {
        let (tx, rx) = mpsc::unbounded_channel();

        let mut watcher = notify::recommended_watcher(move |result: Result<Event, notify::Error>| {
            let event = match result {
                Ok(e) => e,
                Err(err) => {
                    eprintln!("[wiki-watcher] error: {err}");
                    return;
                }
            };

            let kind = match event.kind {
                EventKind::Create(_) => WikiChangeKind::Created,
                EventKind::Modify(_) => WikiChangeKind::Modified,
                EventKind::Remove(_) => WikiChangeKind::Deleted,
                _ => return,
            };

            for path in event.paths {
                // Only watch .md files
                if path.extension().and_then(|e| e.to_str()) != Some("md") {
                    continue;
                }
                let _ = tx.send(WikiChangeEvent {
                    path,
                    kind: kind.clone(),
                });
            }
        })
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        watcher
            .watch(&wiki_dir, RecursiveMode::Recursive)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        Ok((Self { _watcher: watcher }, rx))
    }

    /// Stop watching by dropping the watcher.
    pub fn stop(self) {
        // Dropping self._watcher stops the watcher
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;
    use tokio::time::{sleep, Duration};

    #[tokio::test]
    async fn test_watcher_detects_create() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().to_path_buf();

        let (watcher, mut rx) = WikiWatcher::start(wiki_dir.clone()).unwrap();

        // Create a .md file
        std::fs::write(wiki_dir.join("test.md"), "# Test").unwrap();

        // Wait for the event
        let timeout = sleep(Duration::from_secs(2));
        tokio::pin!(timeout);

        let mut got_event = false;
        loop {
            tokio::select! {
                Some(event) = rx.recv() => {
                    if event.kind == WikiChangeKind::Created || event.kind == WikiChangeKind::Modified {
                        got_event = true;
                        break;
                    }
                }
                _ = &mut timeout => {
                    break;
                }
            }
        }

        assert!(got_event, "should have received a create/modify event");
        watcher.stop();
    }

    #[tokio::test]
    async fn test_watcher_ignores_non_md() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().to_path_buf();

        let (_watcher, mut rx) = WikiWatcher::start(wiki_dir.clone()).unwrap();

        // Create a non-.md file
        std::fs::write(wiki_dir.join("test.txt"), "not markdown").unwrap();

        // Wait briefly — should NOT receive an event
        sleep(Duration::from_millis(500)).await;

        let event = rx.try_recv();
        assert!(event.is_err(), "should not receive event for .txt file");
    }

    #[test]
    fn test_change_kind_clone() {
        let kind = WikiChangeKind::Modified;
        let cloned = kind.clone();
        assert_eq!(cloned, WikiChangeKind::Modified);
    }
}

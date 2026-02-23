"use client";

import React, { useCallback, useRef, useState } from "react";
import { uploadFile } from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Accepted file extensions. */
const ACCEPTED_EXTENSIONS = [".csv", ".json", ".xlsx"] as const;
/** Corresponding MIME types for the file input accept attribute. */
const ACCEPT_MIME =
  ".csv,.json,.xlsx,text/csv,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
/** Maximum file size in bytes (50 MB). */
const MAX_FILE_SIZE = 50 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  container: {
    padding: "var(--panel-padding)",
  } as React.CSSProperties,

  dropZone: (isDragging: boolean, hasError: boolean): React.CSSProperties => ({
    border: `2px dashed ${
      hasError
        ? "var(--accent-red)"
        : isDragging
          ? "var(--accent-blue)"
          : "var(--border-subtle)"
    }`,
    borderRadius: 8,
    padding: 20,
    textAlign: "center",
    cursor: "pointer",
    transition: "border-color 0.2s, background 0.2s",
    background: isDragging ? "rgba(74, 124, 255, 0.05)" : "transparent",
  }),

  dropLabel: {
    fontSize: 13,
    color: "var(--text-secondary)",
    lineHeight: 1.6,
  } as React.CSSProperties,

  dropHint: {
    fontSize: 11,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    marginTop: 6,
  } as React.CSSProperties,

  browseLink: {
    color: "var(--accent-blue)",
    cursor: "pointer",
    textDecoration: "underline",
    background: "none",
    border: "none",
    fontSize: 13,
    fontFamily: "inherit",
    padding: 0,
  } as React.CSSProperties,

  errorText: {
    fontSize: 12,
    color: "var(--accent-red)",
    marginTop: 8,
    fontFamily: "var(--font-mono)",
  } as React.CSSProperties,

  progressContainer: {
    marginTop: 10,
  } as React.CSSProperties,

  progressFilename: {
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    color: "var(--text-secondary)",
    marginBottom: 4,
  } as React.CSSProperties,

  progressBar: {
    height: 3,
    background: "var(--bg-tertiary)",
    borderRadius: 2,
    overflow: "hidden",
  } as React.CSSProperties,

  progressFill: (percent: number): React.CSSProperties => ({
    height: "100%",
    width: `${percent}%`,
    background: "var(--accent-blue)",
    borderRadius: 2,
    transition: "width 0.3s ease",
  }),

  successText: {
    fontSize: 12,
    color: "var(--accent-green)",
    marginTop: 8,
    fontFamily: "var(--font-mono)",
  } as React.CSSProperties,

  sizeLimit: {
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    marginTop: 4,
  } as React.CSSProperties,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Validate that a file has an accepted extension. */
function isAcceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

/** Format bytes to a human-readable string. */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface FileUploadProps {
  /** Investigation ID to upload files to. */
  investigationId: string;
  /** Called after a successful upload, with a message to send to the chat. */
  onUploadComplete?: (chatMessage: string) => void;
}

type UploadState =
  | { status: "idle" }
  | { status: "uploading"; filename: string; progress: number }
  | { status: "success"; filename: string; size: number }
  | { status: "error"; errorMessage: string };

export function FileUpload({
  investigationId,
  onUploadComplete,
}: FileUploadProps): React.ReactElement {
  const [isDragging, setIsDragging] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>({
    status: "idle",
  });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);

  // -----------------------------------------------------------------------
  // File validation and upload
  // -----------------------------------------------------------------------
  const processFile = useCallback(
    async (file: File): Promise<void> => {
      // Validate extension
      if (!isAcceptedFile(file)) {
        setUploadState({
          status: "error",
          errorMessage: `Unsupported file type. Only ${ACCEPTED_EXTENSIONS.join(", ")} files are accepted.`,
        });
        return;
      }

      // Validate size
      if (file.size > MAX_FILE_SIZE) {
        setUploadState({
          status: "error",
          errorMessage: `File is too large (${formatBytes(file.size)}). Maximum size is 50 MB.`,
        });
        return;
      }

      // Start upload
      setUploadState({
        status: "uploading",
        filename: file.name,
        progress: 0,
      });

      try {
        // Simulate progress updates since fetch doesn't support upload progress natively.
        // We'll show an indeterminate progress bar by advancing in steps.
        const progressInterval = setInterval(() => {
          setUploadState((prev) => {
            if (prev.status !== "uploading") return prev;
            // Advance progress towards 90% (remaining 10% on completion)
            const nextProgress = prev.progress + (90 - prev.progress) * 0.2;
            return { ...prev, progress: Math.min(nextProgress, 90) };
          });
        }, 300);

        const result = await uploadFile(investigationId, file);

        clearInterval(progressInterval);

        setUploadState({
          status: "success",
          filename: result.filename,
          size: result.size,
        });

        // Send a chat message about the uploaded file
        if (onUploadComplete) {
          onUploadComplete(
            `I've uploaded ${file.name} (${formatBytes(file.size)}) -- please ingest and analyze it.`,
          );
        }

        // Reset to idle after a few seconds
        setTimeout(() => {
          setUploadState({ status: "idle" });
        }, 4000);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Upload failed";
        setUploadState({ status: "error", errorMessage: message });
      }
    },
    [investigationId, onUploadComplete],
  );

  // -----------------------------------------------------------------------
  // Drag-and-drop handlers
  // -----------------------------------------------------------------------
  const handleDragEnter = useCallback(
    (e: React.DragEvent): void => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current += 1;
      if (dragCounterRef.current === 1) {
        setIsDragging(true);
      }
    },
    [],
  );

  const handleDragLeave = useCallback(
    (e: React.DragEvent): void => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current -= 1;
      if (dragCounterRef.current === 0) {
        setIsDragging(false);
      }
    },
    [],
  );

  const handleDragOver = useCallback((e: React.DragEvent): void => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent): void => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      dragCounterRef.current = 0;

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        processFile(files[0]);
      }
    },
    [processFile],
  );

  // -----------------------------------------------------------------------
  // Click-to-browse handler
  // -----------------------------------------------------------------------
  const handleBrowseClick = useCallback((): void => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>): void => {
      const files = e.target.files;
      if (files && files.length > 0) {
        processFile(files[0]);
      }
      // Reset so the same file can be re-selected
      e.target.value = "";
    },
    [processFile],
  );

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  const hasError = uploadState.status === "error";

  return (
    <div style={styles.container}>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPT_MIME}
        onChange={handleFileChange}
        style={{ display: "none" }}
      />

      {/* Drop zone */}
      <div
        style={styles.dropZone(isDragging, hasError)}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={handleBrowseClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleBrowseClick();
          }
        }}
      >
        <div style={styles.dropLabel}>
          {isDragging ? (
            "Drop file here"
          ) : (
            <>
              Drag and drop a file, or{" "}
              <span style={styles.browseLink}>browse</span>
            </>
          )}
        </div>
        <div style={styles.dropHint}>.csv, .json, .xlsx</div>
        <div style={styles.sizeLimit}>Max 50 MB</div>
      </div>

      {/* Upload progress */}
      {uploadState.status === "uploading" && (
        <div style={styles.progressContainer}>
          <div style={styles.progressFilename}>
            Uploading {uploadState.filename}...
          </div>
          <div style={styles.progressBar}>
            <div style={styles.progressFill(uploadState.progress)} />
          </div>
        </div>
      )}

      {/* Success message */}
      {uploadState.status === "success" && (
        <div style={styles.successText}>
          Uploaded {uploadState.filename} ({formatBytes(uploadState.size)})
        </div>
      )}

      {/* Error message */}
      {uploadState.status === "error" && (
        <div style={styles.errorText}>{uploadState.errorMessage}</div>
      )}
    </div>
  );
}

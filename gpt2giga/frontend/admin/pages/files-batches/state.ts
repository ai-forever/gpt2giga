export type FilesBatchesPage = "files-batches" | "files" | "batches";

export type FileSort =
  | "created_desc"
  | "created_asc"
  | "name_asc"
  | "name_desc"
  | "size_desc"
  | "size_asc";

export const DEFAULT_FILE_SORT: FileSort = "created_desc";

export interface FilesBatchesFilters {
  query: string;
  purpose: string;
  batchStatus: string;
  endpoint: string;
  fileSort: FileSort;
}

export interface FilesBatchesRouteState {
  selectedFileId: string;
  selectedBatchId: string;
  composeInputFileId: string;
}

export interface FilePreview {
  kind: "text" | "image" | "binary";
  filename: string;
  mimeType: string;
  textFallback: string;
  byteLength: number;
  lineCount: number;
  sampled?: boolean;
  sampledByteLength?: number;
  formatLabel: string;
  formatNote: string;
  contentKind?: string;
  contentKindNote?: string;
  sampleLabel?: string;
  sampleValue?: string;
  sampleNote?: string;
  dimensionsNote?: string;
  handoffRequestId?: string;
  handoffRequestCount?: number;
}

export interface DefinitionItem {
  label: string;
  value: string;
  note?: string;
}

export interface InspectorSelection {
  kind: "idle" | "file" | "batch";
  fileId?: string;
  batchId?: string;
  inputFileId?: string;
  outputFileId?: string;
  handoffRequestId?: string;
  handoffRequestCount?: number;
}

export type ArtifactApiFormat = "openai" | "anthropic" | "gemini";

export type BatchValidationSeverity = "error" | "warning" | "info";

export interface BatchValidationIssue {
  severity: BatchValidationSeverity;
  code: string;
  message: string;
  hint?: string | null;
  line?: number | null;
  column?: number | null;
  field?: string | null;
  raw_excerpt?: string | null;
}

export interface BatchValidationSummary {
  total_rows: number;
  error_count: number;
  warning_count: number;
}

export interface BatchValidationReport {
  valid: boolean;
  api_format: ArtifactApiFormat;
  detected_format?: ArtifactApiFormat | null;
  summary: BatchValidationSummary;
  issues: BatchValidationIssue[];
}

export type FileValidationStatus =
  | "not_validated"
  | "valid"
  | "valid_with_warnings"
  | "invalid"
  | "stale";

export interface FileValidationSnapshot {
  status: FileValidationStatus;
  total_rows?: number | null;
  error_count?: number | null;
  warning_count?: number | null;
  detected_format?: ArtifactApiFormat | null;
  validated_at?: number | null;
}

export interface FileRecord {
  id: string;
  api_format: ArtifactApiFormat;
  filename: string;
  purpose?: string | null;
  bytes?: number | null;
  status?: string | null;
  created_at?: number | null;
  content_kind?: string | null;
  download_path?: string | null;
  content_path?: string | null;
  delete_path?: string | null;
  validation?: FileValidationSnapshot | null;
  raw?: Record<string, unknown>;
}

export interface BatchRequestCounts {
  total?: number | null;
  completed?: number | null;
  failed?: number | null;
  succeeded?: number | null;
  errored?: number | null;
  processing?: number | null;
  pending?: number | null;
  cancelled?: number | null;
  expired?: number | null;
}

export interface BatchRecord {
  id: string;
  api_format: ArtifactApiFormat;
  endpoint?: string | null;
  status?: string | null;
  created_at?: number | null;
  input_file_id?: string | null;
  output_file_id?: string | null;
  output_kind?: "file" | "results" | null;
  output_path?: string | null;
  request_counts?: BatchRequestCounts;
  model?: string | null;
  display_name?: string | null;
  raw?: Record<string, unknown>;
}

export interface FilesBatchesInventory {
  filteredFiles: FileRecord[];
  filteredBatches: BatchRecord[];
  attentionBatches: number;
  outputReadyBatches: number;
  fileLookup: Map<string, FileRecord>;
  batchLookup: Map<string, BatchRecord>;
}

export const INVALID_JSON = "__invalid__";

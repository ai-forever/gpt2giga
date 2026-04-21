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

export type FileRecord = Record<string, unknown>;
export type BatchRecord = Record<string, unknown>;

export interface FilesBatchesInventory {
  filteredFiles: FileRecord[];
  filteredBatches: BatchRecord[];
  attentionBatches: number;
  outputReadyBatches: number;
  fileLookup: Map<string, FileRecord>;
  batchLookup: Map<string, BatchRecord>;
}

export const INVALID_JSON = "__invalid__";

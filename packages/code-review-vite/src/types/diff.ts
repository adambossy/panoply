export interface ParsedDiff {
  files: DiffFile[];
}

export interface DiffFile {
  oldPath: string;
  newPath: string;
  hunks: Hunk[];
  additions: number;
  deletions: number;
}

export interface Hunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  header: string;
  lines: DiffLine[];
}

export interface DiffLine {
  type: 'addition' | 'deletion' | 'context';
  content: string;
}


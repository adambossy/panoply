import type { Hunk } from './diff';

export interface FunctionNode {
  name: string;
  file: string;
  shortFile: string;
  lineNumber: number;
  changeType: 'addition' | 'deletion' | 'modification';
  additions: number;
  deletions: number;
  type: 'function' | 'method' | 'class' | 'arrow';
  fullLine: string;
  hunk: Hunk;
}

export interface FunctionPattern {
  regex: RegExp;
  lang: 'js' | 'ts' | 'py' | 'go' | 'java' | 'cs';
  type: 'function' | 'method' | 'class' | 'arrow';
}


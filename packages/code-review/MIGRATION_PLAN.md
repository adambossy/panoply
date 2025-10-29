# Code Review Tool - Vite + TypeScript Migration Plan

## Overview

This plan outlines how to rebuild the code review tool from scratch using Vite + TypeScript, then port functionality from the current Astro prototype. The approach focuses on clean architecture, maintainability, and rapid development.

---

## PHASE 1: Initial Project Setup

### Step 1.1: Create Vite Project (5 min)

```bash
# Navigate to packages directory
cd packages

# Create new Vite project with TypeScript template
npm create vite@latest code-review-vite -- --template vanilla-ts

# Navigate into project
cd code-review-vite

# Install dependencies
npm install

# Test that it works
npm run dev
# Should open on http://localhost:5173
```

**Verify:**
- Browser shows default Vite + TypeScript counter app
- Hot module replacement (HMR) works when you edit `src/main.ts`

---

### Step 1.2: Install Dependencies (5 min)

```bash
# Core dependencies
npm install mermaid

# Development dependencies
npm install -D @types/node

# Optional but recommended
npm install -D prettier eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin
```

**Dependencies explained:**
- `mermaid` - Diagram rendering library (same as current)
- `@types/node` - Node.js type definitions for imports
- `prettier` - Code formatter
- `eslint` + TypeScript plugins - Linting

---

### Step 1.3: Configure TypeScript (10 min)

**Update `tsconfig.json`:**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,

    /* Bundler mode */
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,

    /* Linting */
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noImplicitReturns": true,
    "noUncheckedIndexedAccess": true,

    /* Path aliases for clean imports */
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"],
      "@lib/*": ["./src/lib/*"],
      "@components/*": ["./src/components/*"],
      "@types/*": ["./src/types/*"]
    }
  },
  "include": ["src"]
}
```

**Update `vite.config.ts` for path aliases:**

```typescript
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@lib': path.resolve(__dirname, './src/lib'),
      '@components': path.resolve(__dirname, './src/components'),
      '@types': path.resolve(__dirname, './src/types'),
    },
  },
  server: {
    port: 5173,
    open: true,
  },
});
```

**Verify:**
- `npm run dev` still works
- No TypeScript errors in terminal

---

### Step 1.4: Setup Project Structure (10 min)

```bash
# Create directory structure
mkdir -p src/{lib,components,types,styles,utils}

# Create files
touch src/lib/{diff-parser,function-extractor,diagram-generator,call-hierarchy-analyzer}.ts
touch src/components/{diagram-renderer,diff-viewer,call-hierarchy-panel,file-uploader}.ts
touch src/types/{diff,function,hierarchy}.ts
touch src/utils/{escape-html,dom-helpers}.ts
touch src/styles/{main,components,layout,theme}.css
```

**Resulting structure:**

```
code-review-vite/
├── node_modules/
├── public/
│   └── favicon.svg          # Copy from old project
├── src/
│   ├── lib/                 # Core business logic (pure functions)
│   │   ├── diff-parser.ts
│   │   ├── function-extractor.ts
│   │   ├── diagram-generator.ts
│   │   └── call-hierarchy-analyzer.ts
│   ├── components/          # UI components (classes with DOM)
│   │   ├── diagram-renderer.ts
│   │   ├── diff-viewer.ts
│   │   ├── call-hierarchy-panel.ts
│   │   └── file-uploader.ts
│   ├── types/               # TypeScript interfaces/types
│   │   ├── diff.ts
│   │   ├── function.ts
│   │   └── hierarchy.ts
│   ├── utils/               # Helper utilities
│   │   ├── escape-html.ts
│   │   └── dom-helpers.ts
│   ├── styles/              # CSS modules
│   │   ├── main.css        # Global styles
│   │   ├── components.css  # Component-specific
│   │   ├── layout.css      # Layout (3-pane)
│   │   └── theme.css       # Colors (VS Code dark)
│   ├── main.ts              # Application entry point
│   └── vite-env.d.ts        # Vite type definitions
├── index.html               # HTML entry
├── package.json
├── tsconfig.json
├── vite.config.ts
└── README.md
```

---

### Step 1.5: Setup Base HTML Structure (15 min)

**Update `index.html`:**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Code Review Tool</title>
  </head>
  <body>
    <div id="app">
      <!-- Header -->
      <header class="header">
        <h1>Code Review Tool</h1>
      </header>

      <!-- File Upload Controls -->
      <div class="controls">
        <div class="file-input-wrapper">
          <label for="diff-file" class="file-label">Load Git Diff</label>
          <input type="file" id="diff-file" accept=".diff,.patch,.txt" />
          <span class="file-name" id="file-name">No file selected</span>
        </div>
      </div>

      <!-- Three-pane layout -->
      <div class="content">
        <!-- Diagram Pane -->
        <div class="pane diagram-pane">
          <div class="pane-header">Dataflow Diagram</div>
          <div class="pane-content">
            <div id="mermaid-diagram">
              <div class="loading">Load a git diff file to see the dataflow diagram</div>
            </div>
          </div>
        </div>

        <!-- Diff Pane -->
        <div class="pane diff-pane">
          <div class="pane-header">Diff Details</div>
          <div class="pane-content">
            <div id="diff-content">
              <div class="loading">Select a node in the diagram to see the relevant diff</div>
            </div>
          </div>
        </div>

        <!-- Call Hierarchy Pane -->
        <div class="pane call-hierarchy-pane">
          <div class="pane-header">Call Hierarchy</div>
          <div class="pane-content" style="padding: 0">
            <div id="call-hierarchy-content">
              <div class="empty-state">Select code in the diff to view call hierarchy</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

---

### Step 1.6: Setup Base CSS (20 min)

**Copy CSS from Astro prototype, split into modules:**

**`src/styles/theme.css` - Colors:**

```css
:root {
  /* VS Code Dark Theme */
  --bg-primary: #1e1e1e;
  --bg-secondary: #2d2d30;
  --bg-tertiary: #1a1a1a;
  --border-color: #3e3e42;

  --text-primary: #d4d4d4;
  --text-secondary: #858585;
  --text-muted: #cccccc;

  --accent-blue: #0e639c;
  --accent-blue-hover: #1177bb;
  --accent-blue-highlight: #264f78;

  --addition-bg: #1e3c1e;
  --addition-text: #4ec9b0;
  --deletion-bg: #4b1818;
  --deletion-text: #f48771;

  --success: #4ec9b0;
  --error: #f48771;
  --warning: #dcdcaa;
}
```

**`src/styles/layout.css` - Structure:**

```css
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  height: 100vh;
  overflow: hidden;
}

#app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.header {
  background: var(--bg-secondary);
  padding: 1rem 2rem;
  border-bottom: 1px solid var(--border-color);
}

.header h1 {
  font-size: 1.5rem;
  font-weight: 600;
  color: #ffffff;
}

.controls {
  background: var(--bg-secondary);
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
}

.content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-header {
  background: var(--bg-secondary);
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
  font-weight: 600;
  font-size: 0.9rem;
}

.pane-content {
  flex: 1;
  overflow: auto;
  padding: 1rem;
}

.diagram-pane {
  border-right: 1px solid var(--border-color);
}

.diff-pane {
  border-right: 1px solid var(--border-color);
}

.call-hierarchy-pane {
  flex: 0 0 400px;
}
```

**`src/styles/components.css` - Component styles (copy all from Astro):**

```css
/* File Upload */
.file-input-wrapper {
  display: flex;
  gap: 1rem;
  align-items: center;
}

input[type="file"] {
  display: none;
}

.file-label {
  background: var(--accent-blue);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.875rem;
  transition: background 0.2s;
}

.file-label:hover {
  background: var(--accent-blue-hover);
}

.file-name {
  color: var(--text-muted);
  font-size: 0.875rem;
}

/* Loading/Empty States */
.loading, .empty-state {
  color: var(--text-muted);
  text-align: center;
  padding: 2rem;
}

.error {
  color: var(--error);
  padding: 1rem;
  background: var(--deletion-bg);
  border-radius: 4px;
  margin: 1rem;
}

/* Mermaid Diagram */
#mermaid-diagram {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.node-highlight {
  background: var(--accent-blue-highlight) !important;
  box-shadow: 0 0 0 2px var(--accent-blue);
}

/* Diff Viewer */
.diff-content {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
  white-space: pre-wrap;
}

.diff-file {
  margin-bottom: 2rem;
}

.diff-file-header {
  background: var(--bg-secondary);
  padding: 0.5rem 1rem;
  border-radius: 4px 4px 0 0;
  font-weight: 600;
  border: 1px solid var(--border-color);
  border-bottom: none;
}

.diff-lines {
  border: 1px solid var(--border-color);
  border-radius: 0 0 4px 4px;
  overflow: hidden;
}

.diff-line {
  padding: 2px 1rem;
  display: flex;
}

.line-number {
  min-width: 50px;
  text-align: right;
  padding-right: 1rem;
  color: var(--text-secondary);
  user-select: none;
}

.line-content {
  flex: 1;
}

.diff-line.addition {
  background: var(--addition-bg);
}

.diff-line.deletion {
  background: var(--deletion-bg);
}

.diff-line.context {
  background: var(--bg-primary);
}

.addition .line-content {
  color: var(--addition-text);
}

.deletion .line-content {
  color: var(--deletion-text);
}

/* Call Hierarchy */
.call-hierarchy-content {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.875rem;
}

.target-symbol {
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.target-symbol h3 {
  color: var(--addition-text);
  font-size: 1rem;
  margin-bottom: 0.5rem;
}

.target-symbol code {
  color: var(--text-primary);
  font-size: 0.8rem;
}

.hierarchy-section {
  margin: 1rem 0;
}

.hierarchy-section-header {
  padding: 0.75rem 1rem;
  background: var(--bg-secondary);
  border: none;
  color: var(--text-primary);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.hierarchy-section-header:hover {
  background: var(--border-color);
}

.call-tree {
  list-style: none;
  padding: 0;
  margin: 0;
}

.call-site {
  border-bottom: 1px solid var(--border-color);
}

.call-link {
  display: block;
  padding: 0.75rem 1rem;
  background: none;
  border: none;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  width: 100%;
  transition: background 0.2s;
}

.call-link:hover {
  background: var(--bg-secondary);
}

.symbol-name {
  color: var(--addition-text);
  font-weight: 600;
  display: block;
  margin-bottom: 0.25rem;
}

.location {
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.context-code {
  background: var(--bg-tertiary);
  padding: 0.5rem 1rem;
  margin: 0.5rem 1rem;
  border-left: 3px solid var(--accent-blue);
  font-size: 0.8rem;
  color: var(--text-muted);
  white-space: pre-wrap;
  overflow-x: auto;
}

.call-type-badge {
  display: inline-block;
  padding: 0.2rem 0.5rem;
  background: var(--accent-blue);
  color: white;
  border-radius: 3px;
  font-size: 0.7rem;
  margin-left: 0.5rem;
}
```

**`src/styles/main.css` - Import all:**

```css
@import './theme.css';
@import './layout.css';
@import './components.css';
```

**Update `src/main.ts` to import CSS:**

```typescript
import './styles/main.css';

console.log('Code Review Tool loaded!');
```

**Verify:**
- Run `npm run dev`
- Should see styled three-pane layout with proper colors
- Empty state messages should be visible

---

### Step 1.7: Setup TypeScript Types (15 min)

**`src/types/diff.ts`:**

```typescript
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
```

**`src/types/function.ts`:**

```typescript
import type { DiffFile, Hunk } from './diff';

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
```

**`src/types/hierarchy.ts`:**

```typescript
export interface CallHierarchy {
  targetFunction: string;
  signature: string;
  incomingCalls: CallSite[];
  outgoingCalls: CallSite[];
}

export interface CallSite {
  file: string;
  line: number;
  content: string;
  functionName?: string;
  type: 'addition' | 'deletion' | 'context';
}
```

**`src/types/index.ts` - Barrel export:**

```typescript
export * from './diff';
export * from './function';
export * from './hierarchy';
```

---

### Step 1.8: Setup Utilities (10 min)

**`src/utils/escape-html.ts`:**

```typescript
/**
 * Escapes HTML special characters to prevent XSS
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
```

**`src/utils/dom-helpers.ts`:**

```typescript
/**
 * Helper to safely query elements
 */
export function getElement<T extends HTMLElement>(
  selector: string,
  parent: Document | HTMLElement = document
): T {
  const element = parent.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Element not found: ${selector}`);
  }
  return element;
}

/**
 * Helper to safely query optional elements
 */
export function getElementOrNull<T extends HTMLElement>(
  selector: string,
  parent: Document | HTMLElement = document
): T | null {
  return parent.querySelector<T>(selector);
}

/**
 * Clear element contents
 */
export function clearElement(element: HTMLElement): void {
  element.innerHTML = '';
}

/**
 * Show loading state
 */
export function showLoading(element: HTMLElement, message = 'Loading...'): void {
  element.innerHTML = `<div class="loading">${message}</div>`;
}

/**
 * Show error state
 */
export function showError(element: HTMLElement, message: string): void {
  element.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
}

/**
 * Show empty state
 */
export function showEmptyState(element: HTMLElement, message: string): void {
  element.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}
```

---

### Step 1.9: Create Base Component Classes (20 min)

Create empty component class shells to establish architecture:

**`src/components/diagram-renderer.ts`:**

```typescript
import type { FunctionNode } from '@types';

export class DiagramRenderer {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(private container: HTMLElement) {}

  async render(functions: FunctionNode[]): Promise<void> {
    // TODO: Implementation in Phase 2
    console.log('DiagramRenderer.render called with', functions.length, 'functions');
  }

  on(event: 'nodeClick', handler: (funcNode: FunctionNode) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((handler) => handler(...args));
  }

  destroy(): void {
    this.listeners.clear();
  }
}
```

**`src/components/diff-viewer.ts`:**

```typescript
import type { DiffFile, FunctionNode } from '@types';

export class DiffViewer {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(private container: HTMLElement) {}

  showFunction(file: DiffFile, funcNode: FunctionNode): void {
    // TODO: Implementation in Phase 2
    console.log('DiffViewer.showFunction called for', funcNode.name);
  }

  showFile(file: DiffFile): void {
    // TODO: Implementation in Phase 2
    console.log('DiffViewer.showFile called for', file.newPath);
  }

  on(event: 'textSelect', handler: (text: string) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((handler) => handler(...args));
  }

  destroy(): void {
    this.listeners.clear();
  }
}
```

**`src/components/call-hierarchy-panel.ts`:**

```typescript
import type { CallHierarchy } from '@types';

export class CallHierarchyPanel {
  constructor(private container: HTMLElement) {}

  show(hierarchy: CallHierarchy | null): void {
    // TODO: Implementation in Phase 2
    console.log('CallHierarchyPanel.show called with', hierarchy);
  }

  clear(): void {
    this.container.innerHTML = '<div class="empty-state">Select code in the diff to view call hierarchy</div>';
  }

  destroy(): void {
    // Cleanup if needed
  }
}
```

**`src/components/file-uploader.ts`:**

```typescript
export class FileUploader {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(
    private input: HTMLInputElement,
    private label: HTMLElement
  ) {
    this.setupListeners();
  }

  private setupListeners(): void {
    this.input.addEventListener('change', async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;

      this.label.textContent = file.name;
      const content = await file.text();
      this.emit('fileLoaded', content);
    });
  }

  on(event: 'fileLoaded', handler: (content: string) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((handler) => handler(...args));
  }

  destroy(): void {
    this.listeners.clear();
  }
}
```

---

### Step 1.10: Create Main Application Entry (15 min)

**`src/main.ts`:**

```typescript
import './styles/main.css';

import { DiagramRenderer } from '@components/diagram-renderer';
import { DiffViewer } from '@components/diff-viewer';
import { CallHierarchyPanel } from '@components/call-hierarchy-panel';
import { FileUploader } from '@components/file-uploader';

import { getElement } from './utils/dom-helpers';

/**
 * Code Review Tool - Main Application
 */
class CodeReviewApp {
  private diagram: DiagramRenderer;
  private diffViewer: DiffViewer;
  private hierarchyPanel: CallHierarchyPanel;
  private uploader: FileUploader;

  private parsedDiff: any = null;
  private currentFile: any = null;

  constructor() {
    // Initialize components
    this.diagram = new DiagramRenderer(getElement('#mermaid-diagram'));
    this.diffViewer = new DiffViewer(getElement('#diff-content'));
    this.hierarchyPanel = new CallHierarchyPanel(getElement('#call-hierarchy-content'));

    const fileInput = getElement<HTMLInputElement>('#diff-file');
    const fileName = getElement('#file-name');
    this.uploader = new FileUploader(fileInput, fileName);

    this.setupEventHandlers();
    console.log('Code Review Tool initialized');
  }

  private setupEventHandlers(): void {
    // File upload
    this.uploader.on('fileLoaded', (content) => {
      this.handleFileLoad(content);
    });

    // Diagram interactions
    this.diagram.on('nodeClick', (funcNode) => {
      this.handleNodeClick(funcNode);
    });

    // Text selection for call hierarchy
    this.diffViewer.on('textSelect', (text) => {
      this.handleTextSelection(text);
    });
  }

  private async handleFileLoad(content: string): Promise<void> {
    console.log('File loaded, content length:', content.length);
    // TODO: Parse and render in Phase 2
  }

  private handleNodeClick(funcNode: any): void {
    console.log('Node clicked:', funcNode);
    // TODO: Display diff in Phase 2
  }

  private handleTextSelection(text: string): void {
    console.log('Text selected:', text);
    // TODO: Analyze call hierarchy in Phase 2
  }

  destroy(): void {
    this.diagram.destroy();
    this.diffViewer.destroy();
    this.hierarchyPanel.destroy();
    this.uploader.destroy();
  }
}

// Initialize app when DOM is ready
const app = new CodeReviewApp();

// Make app globally accessible for debugging
(window as any).app = app;
```

---

### Step 1.11: Verify Setup (10 min)

**Run and test:**

```bash
npm run dev
```

**Checklist:**
- ✅ App loads at http://localhost:5173
- ✅ Three-pane layout visible with proper styling
- ✅ File upload button shows
- ✅ Console shows "Code Review Tool initialized"
- ✅ Clicking "Load Git Diff" opens file picker
- ✅ Selecting a file logs "File loaded, content length: X"
- ✅ No TypeScript errors
- ✅ No console errors
- ✅ Hot reload works when editing files

---

### Step 1.12: Optional - Setup Development Tools (15 min)

**`.prettierrc`:**

```json
{
  "semi": true,
  "singleQuote": true,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 100,
  "arrowParens": "always"
}
```

**`.eslintrc.json`:**

```json
{
  "parser": "@typescript-eslint/parser",
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended"
  ],
  "rules": {
    "@typescript-eslint/no-explicit-any": "warn",
    "@typescript-eslint/no-unused-vars": ["error", { "argsIgnorePattern": "^_" }]
  }
}
```

**Add scripts to `package.json`:**

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext .ts",
    "format": "prettier --write \"src/**/*.{ts,css}\""
  }
}
```

---

## PHASE 1 COMPLETE

**Time estimate: ~2 hours**

**What you have:**
- ✅ Vite + TypeScript project configured
- ✅ Clean architecture (lib / components / types / utils)
- ✅ All CSS ported and organized
- ✅ Component class shells with event systems
- ✅ Main application orchestrator
- ✅ Type-safe development environment
- ✅ Hot reload working

**What's missing (Phase 2):**
- Core parsing logic
- Diagram generation
- Diff rendering
- Call hierarchy analysis
- Component implementations

---

## PHASE 2: Port Prototype Functionality

### Step 2.1: Port Diff Parser (30 min)

**`src/lib/diff-parser.ts`:**

```typescript
import type { ParsedDiff, DiffFile, Hunk, DiffLine } from '@types';

/**
 * Parse unified diff format into structured data
 */
export function parseDiff(diffText: string): ParsedDiff {
  const files: DiffFile[] = [];
  const lines = diffText.split('\n');

  let currentFile: DiffFile | null = null;
  let currentHunk: Hunk | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // New file
    if (line.startsWith('diff --git')) {
      if (currentFile) {
        files.push(currentFile);
      }
      const match = line.match(/diff --git a\/(.+?) b\/(.+)/);
      currentFile = {
        oldPath: match?.[1] || '',
        newPath: match?.[2] || '',
        hunks: [],
        additions: 0,
        deletions: 0,
      };
      currentHunk = null;
    }
    // File paths
    else if (line.startsWith('---')) {
      if (currentFile) {
        currentFile.oldPath = line.substring(4).replace(/^a\//, '');
      }
    } else if (line.startsWith('+++')) {
      if (currentFile) {
        currentFile.newPath = line.substring(4).replace(/^b\//, '');
      }
    }
    // Hunk header
    else if (line.startsWith('@@')) {
      const match = line.match(/@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)/);
      currentHunk = {
        oldStart: parseInt(match?.[1] || '0'),
        oldLines: parseInt(match?.[2] || '1'),
        newStart: parseInt(match?.[3] || '0'),
        newLines: parseInt(match?.[4] || '1'),
        header: match?.[5]?.trim() || '',
        lines: [],
      };
      if (currentFile) {
        currentFile.hunks.push(currentHunk);
      }
    }
    // Hunk content
    else if (
      currentHunk &&
      (line.startsWith('+') || line.startsWith('-') || line.startsWith(' '))
    ) {
      const type: DiffLine['type'] =
        line[0] === '+' ? 'addition' : line[0] === '-' ? 'deletion' : 'context';

      currentHunk.lines.push({
        type,
        content: line.substring(1),
      });

      if (type === 'addition' && currentFile) currentFile.additions++;
      if (type === 'deletion' && currentFile) currentFile.deletions++;
    }
  }

  if (currentFile) {
    files.push(currentFile);
  }

  return { files };
}
```

**Test it:**

```typescript
// Add to src/main.ts temporarily
import { parseDiff } from '@lib/diff-parser';

// In handleFileLoad:
private async handleFileLoad(content: string): Promise<void> {
  try {
    this.parsedDiff = parseDiff(content);
    console.log('Parsed diff:', this.parsedDiff);
    console.log('Files found:', this.parsedDiff.files.length);
  } catch (error) {
    console.error('Error parsing diff:', error);
  }
}
```

**Verify:**
- Load a diff file
- Console shows correct number of files
- Each file has hunks with lines

---

### Step 2.2: Port Function Extractor (45 min)

**`src/lib/function-extractor.ts`:**

```typescript
import type { ParsedDiff, FunctionNode, FunctionPattern } from '@types';

/**
 * Patterns for detecting function definitions across languages
 */
const FUNCTION_PATTERNS: FunctionPattern[] = [
  { regex: /^\s*(?:async\s+)?function\s+(\w+)\s*\(/, lang: 'js', type: 'function' },
  { regex: /^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(/, lang: 'js', type: 'arrow' },
  { regex: /^\s*(?:async\s+)?def\s+(\w+)\s*\(/, lang: 'py', type: 'function' },
  { regex: /^\s*class\s+(\w+)/, lang: 'py', type: 'class' },
  { regex: /^\s*func\s+(\w+)\s*\(/, lang: 'go', type: 'function' },
  { regex: /^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*{/, lang: 'java', type: 'method' },
];

/**
 * Extract function definitions from parsed diff
 */
export function extractFunctions(diff: ParsedDiff): FunctionNode[] {
  const functions: FunctionNode[] = [];

  diff.files.forEach((file) => {
    const fileName = file.newPath || file.oldPath;

    file.hunks.forEach((hunk) => {
      hunk.lines.forEach((line, lineIdx) => {
        if (line.type === 'addition' || line.type === 'deletion') {
          for (const pattern of FUNCTION_PATTERNS) {
            const match = line.content.match(pattern.regex);
            if (match) {
              const functionName = match[1];
              if (!functionName) continue;

              const lineNumber =
                line.type === 'addition'
                  ? hunk.newStart + lineIdx
                  : hunk.oldStart + lineIdx;

              // Count additions/deletions in function scope
              const { additions, deletions } = countChangesInScope(hunk, lineIdx);

              functions.push({
                name: functionName,
                file: fileName,
                shortFile: fileName.split('/').pop() || fileName,
                lineNumber,
                changeType: line.type === 'addition' ? 'addition' :
                           line.type === 'deletion' ? 'deletion' : 'modification',
                additions,
                deletions,
                type: pattern.type,
                fullLine: line.content,
                hunk,
              });
              break; // Found a match, stop checking other patterns
            }
          }
        }
      });
    });
  });

  return functions;
}

/**
 * Count additions/deletions within a function's scope
 * Uses brace matching to determine scope boundaries
 */
function countChangesInScope(hunk: any, startIdx: number): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  let scopeDepth = 0;
  let inFunction = false;

  for (let i = startIdx; i < hunk.lines.length && scopeDepth >= 0; i++) {
    const line = hunk.lines[i];
    if (i === startIdx) inFunction = true;

    if (inFunction) {
      if (line.content.includes('{')) scopeDepth++;
      if (line.content.includes('}')) scopeDepth--;

      if (line.type === 'addition') additions++;
      if (line.type === 'deletion') deletions++;

      if (scopeDepth === 0 && i > startIdx) break;
    }
  }

  return { additions, deletions };
}
```

**Test it:**

```typescript
// Add to src/main.ts in handleFileLoad:
import { extractFunctions } from '@lib/function-extractor';

const functions = extractFunctions(this.parsedDiff);
console.log('Functions found:', functions.length);
console.log('Functions:', functions);
```

**Verify:**
- Functions are extracted correctly
- Line numbers are accurate
- Change counts make sense

---

### Step 2.3: Port Diagram Generator (45 min)

**`src/lib/diagram-generator.ts`:**

```typescript
import type { FunctionNode, ParsedDiff } from '@types';

/**
 * Generate Mermaid diagram syntax from function nodes
 */
export function generateMermaidDiagram(
  functions: FunctionNode[],
  diff: ParsedDiff
): string {
  if (functions.length === 0) {
    return 'graph TD\n    A[No function changes detected]';
  }

  let diagram = 'graph TD\n';
  const nodes = new Map<string, { id: string; func: FunctionNode; index: number }>();

  // Create nodes for each function
  functions.forEach((func, index) => {
    const id = `func${index}`;
    const changeCount = func.additions + func.deletions;
    const symbol =
      func.changeType === 'addition' ? '+' :
      func.changeType === 'deletion' ? '-' : '±';

    const label = `${func.name}<br/>${func.shortFile}<br/>${symbol}${changeCount} lines`;
    diagram += `    ${id}["${label}"]\n`;

    // Color based on change type
    const color =
      func.changeType === 'addition' ? '#1e3c1e' :
      func.changeType === 'deletion' ? '#4b1818' : '#0e639c';

    diagram += `    style ${id} fill:${color},stroke:#1177bb,color:#fff\n`;

    nodes.set(func.name, { id, func, index });
  });

  // Find function call relationships
  functions.forEach((func, index) => {
    const currentId = `func${index}`;

    // Look for function calls in this function's lines
    diff.files.forEach((file) => {
      if (file.newPath === func.file || file.oldPath === func.file) {
        file.hunks.forEach((hunk) => {
          hunk.lines.forEach((line) => {
            // Search for calls to other functions in our list
            functions.forEach((targetFunc, targetIndex) => {
              if (targetFunc.name !== func.name) {
                const callPattern = new RegExp(`\\b${targetFunc.name}\\s*\\(`, 'g');
                if (callPattern.test(line.content)) {
                  const targetId = `func${targetIndex}`;
                  const edge = `    ${currentId} --> ${targetId}\n`;
                  // Avoid duplicate edges
                  if (!diagram.includes(edge)) {
                    diagram += edge;
                  }
                }
              }
            });
          });
        });
      }
    });
  });

  return diagram;
}
```

**Test it:**

```typescript
// Add to src/main.ts:
import { generateMermaidDiagram } from '@lib/diagram-generator';

const diagramCode = generateMermaidDiagram(functions, this.parsedDiff);
console.log('Mermaid diagram:', diagramCode);
```

---

### Step 2.4: Implement Diagram Renderer (1 hour)

**`src/components/diagram-renderer.ts` (complete implementation):**

```typescript
import mermaid from 'mermaid';
import type { FunctionNode } from '@types';
import { showLoading, showError } from '../utils/dom-helpers';

export class DiagramRenderer {
  private listeners: Map<string, Set<Function>> = new Map();
  private functionNodes: FunctionNode[] = [];
  private initialized = false;

  constructor(private container: HTMLElement) {
    this.initMermaid();
  }

  private initMermaid(): void {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        darkMode: true,
        background: '#1e1e1e',
        primaryColor: '#0e639c',
        primaryTextColor: '#d4d4d4',
        primaryBorderColor: '#3e3e42',
        lineColor: '#858585',
        secondaryColor: '#2d2d30',
        tertiaryColor: '#1e1e1e',
      },
    });
    this.initialized = true;
  }

  async render(functions: FunctionNode[], diagramCode: string): Promise<void> {
    if (!this.initialized) {
      this.initMermaid();
    }

    this.functionNodes = functions;
    showLoading(this.container, 'Rendering diagram...');

    try {
      const { svg } = await mermaid.render('diagram', diagramCode);
      this.container.innerHTML = svg;
      this.attachClickHandlers();
    } catch (error) {
      console.error('Error rendering diagram:', error);
      showError(this.container, 'Failed to render diagram');
    }
  }

  private attachClickHandlers(): void {
    const nodes = this.container.querySelectorAll('.node');

    nodes.forEach((node, index) => {
      (node as HTMLElement).style.cursor = 'pointer';

      node.addEventListener('click', () => {
        // Remove previous highlights
        nodes.forEach((n) => n.classList.remove('node-highlight'));

        // Highlight clicked node
        node.classList.add('node-highlight');

        // Emit event with function data
        if (this.functionNodes[index]) {
          this.emit('nodeClick', this.functionNodes[index]);
        }
      });
    });
  }

  on(event: 'nodeClick', handler: (funcNode: FunctionNode) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((handler) => handler(...args));
  }

  destroy(): void {
    this.listeners.clear();
    this.container.innerHTML = '';
  }
}
```

**Update `src/main.ts` to use it:**

```typescript
private async handleFileLoad(content: string): Promise<void> {
  try {
    this.parsedDiff = parseDiff(content);
    const functions = extractFunctions(this.parsedDiff);
    const diagramCode = generateMermaidDiagram(functions, this.parsedDiff);

    await this.diagram.render(functions, diagramCode);
  } catch (error) {
    console.error('Error processing diff:', error);
  }
}
```

**Verify:**
- Load diff file
- Diagram renders with function nodes
- Clicking nodes highlights them
- Console logs node clicks

---

### Step 2.5: Implement Diff Viewer (1 hour)

**`src/components/diff-viewer.ts` (complete implementation):**

```typescript
import type { DiffFile, FunctionNode } from '@types';
import { escapeHtml } from '../utils/escape-html';
import { showEmptyState } from '../utils/dom-helpers';

export class DiffViewer {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(private container: HTMLElement) {
    this.setupTextSelectionHandler();
  }

  private setupTextSelectionHandler(): void {
    document.addEventListener('mouseup', () => {
      const selection = window.getSelection();
      const selectedText = selection?.toString().trim();

      if (selectedText) {
        // Check if selection is within our container
        const range = selection?.getRangeAt(0);
        if (range && this.container.contains(range.commonAncestorContainer)) {
          this.emit('textSelect', selectedText);
        }
      }
    });
  }

  showFunction(file: DiffFile, funcNode: FunctionNode): void {
    const html = this.generateFunctionHTML(file, funcNode);
    this.container.innerHTML = html;
  }

  showFile(file: DiffFile): void {
    const html = this.generateFileHTML(file);
    this.container.innerHTML = html;
  }

  clear(): void {
    showEmptyState(this.container, 'Select a node in the diagram to see the relevant diff');
  }

  private generateFunctionHTML(file: DiffFile, funcNode: FunctionNode): string {
    let html = '<div class="diff-file">';
    html += `<div class="diff-file-header">${file.newPath || file.oldPath} :: ${funcNode.name}()</div>`;
    html += '<div class="diff-lines">';

    const targetHunk = funcNode.hunk;
    let oldLine = targetHunk.oldStart;
    let newLine = targetHunk.newStart;

    // Find function line index
    const funcLineIdx = targetHunk.lines.findIndex((l) =>
      l.content.includes(funcNode.fullLine.trim())
    );

    // Show context: 5 lines before, up to 30 lines after
    const startIdx = Math.max(0, funcLineIdx - 5);
    const endIdx = Math.min(targetHunk.lines.length, funcLineIdx + 30);

    // Adjust line numbers
    for (let i = 0; i < startIdx; i++) {
      const line = targetHunk.lines[i];
      if (line.type === 'deletion' || line.type === 'context') oldLine++;
      if (line.type === 'addition' || line.type === 'context') newLine++;
    }

    // Render lines
    for (let i = startIdx; i < endIdx; i++) {
      const line = targetHunk.lines[i];
      const lineClass = line.type;
      let lineNum = '';

      if (line.type === 'deletion') {
        lineNum = String(oldLine++);
      } else if (line.type === 'addition') {
        lineNum = String(newLine++);
      } else {
        lineNum = String(newLine++);
        oldLine++;
      }

      // Highlight function definition line
      const isTargetLine = i === funcLineIdx;
      const style = isTargetLine ? ' style="background: #264f78 !important;"' : '';

      html += `<div class="diff-line ${lineClass}"${style}>`;
      html += `<span class="line-number">${lineNum}</span>`;
      html += `<span class="line-content">${escapeHtml(line.content)}</span>`;
      html += '</div>';
    }

    html += '</div></div>';
    return html;
  }

  private generateFileHTML(file: DiffFile): string {
    let html = '<div class="diff-file">';
    html += `<div class="diff-file-header">${file.newPath || file.oldPath}</div>`;
    html += '<div class="diff-lines">';

    file.hunks.forEach((hunk) => {
      let oldLine = hunk.oldStart;
      let newLine = hunk.newStart;

      hunk.lines.forEach((line) => {
        const lineClass = line.type;
        let lineNum = '';

        if (line.type === 'deletion') {
          lineNum = String(oldLine++);
        } else if (line.type === 'addition') {
          lineNum = String(newLine++);
        } else {
          lineNum = String(newLine++);
          oldLine++;
        }

        html += `<div class="diff-line ${lineClass}">`;
        html += `<span class="line-number">${lineNum}</span>`;
        html += `<span class="line-content">${escapeHtml(line.content)}</span>`;
        html += '</div>';
      });
    });

    html += '</div></div>';
    return html;
  }

  on(event: 'textSelect', handler: (text: string) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((handler) => handler(...args));
  }

  destroy(): void {
    this.listeners.clear();
  }
}
```

**Update `src/main.ts`:**

```typescript
private handleNodeClick(funcNode: FunctionNode): void {
  const file = this.parsedDiff?.files.find(
    (f) => f.newPath === funcNode.file || f.oldPath === funcNode.file
  );
  if (file) {
    this.currentFile = file;
    this.diffViewer.showFunction(file, funcNode);
  }
}
```

**Verify:**
- Click diagram node → diff shows for that function
- Function definition line is highlighted
- Context lines shown above/below
- Selecting text emits event (check console)

---

### Step 2.6: Port Call Hierarchy Analyzer (45 min)

**`src/lib/call-hierarchy-analyzer.ts`:**

```typescript
import type { ParsedDiff, DiffFile, CallHierarchy, CallSite } from '@types';

const FUNCTION_PATTERNS = [
  /function\s+(\w+)/,
  /const\s+(\w+)\s*=/,
  /def\s+(\w+)/,
  /func\s+(\w+)/,
  /(\w+)\s*\(/,
];

/**
 * Extract call hierarchy for selected code
 */
export function extractCallHierarchy(
  selectedText: string,
  currentFile: DiffFile,
  parsedDiff: ParsedDiff
): CallHierarchy | null {
  // Detect function name
  let functionName: string | null = null;

  for (const pattern of FUNCTION_PATTERNS) {
    const match = selectedText.match(pattern);
    if (match) {
      functionName = match[1] || match[0].replace(/\s*\(.*/, '');
      break;
    }
  }

  if (!functionName) {
    return null;
  }

  const incomingCalls: CallSite[] = [];
  const outgoingCalls: CallSite[] = [];

  // Search all files
  parsedDiff.files.forEach((file) => {
    file.hunks.forEach((hunk) => {
      hunk.lines.forEach((line, lineIdx) => {
        const content = line.content;

        // Incoming calls: where is this function called?
        const callPattern = new RegExp(`\\b${functionName}\\s*\\(`, 'g');
        if (
          callPattern.test(content) &&
          !content.includes(`function ${functionName}`) &&
          !content.includes(`def ${functionName}`)
        ) {
          incomingCalls.push({
            file: file.newPath || file.oldPath,
            line: lineIdx + hunk.newStart,
            content: content.trim(),
            type: line.type,
          });
        }

        // Outgoing calls: what does this function call?
        if (file === currentFile) {
          const outgoingPattern = /(\w+)\s*\(/g;
          let match;

          while ((match = outgoingPattern.exec(content)) !== null) {
            const calledFunction = match[1];

            // Exclude keywords and self
            if (
              calledFunction !== functionName &&
              !['if', 'for', 'while', 'return', 'function', 'const', 'let', 'var'].includes(
                calledFunction
              )
            ) {
              outgoingCalls.push({
                file: file.newPath || file.oldPath,
                line: lineIdx + hunk.newStart,
                content: content.trim(),
                functionName: calledFunction,
                type: line.type,
              });
            }
          }
        }
      });
    });
  });

  // Deduplicate outgoing calls
  const uniqueOutgoing = [...new Map(outgoingCalls.map((c) => [c.functionName, c])).values()];

  return {
    targetFunction: functionName,
    signature: selectedText.split('\n')[0].trim(),
    incomingCalls: incomingCalls.slice(0, 10),
    outgoingCalls: uniqueOutgoing.slice(0, 10),
  };
}
```

---

### Step 2.7: Implement Call Hierarchy Panel (1 hour)

**`src/components/call-hierarchy-panel.ts` (complete):**

```typescript
import type { CallHierarchy } from '@types';
import { escapeHtml } from '../utils/escape-html';
import { showEmptyState } from '../utils/dom-helpers';

export class CallHierarchyPanel {
  constructor(private container: HTMLElement) {
    this.setupToggleHandlers();
  }

  private setupToggleHandlers(): void {
    // Delegate event for section toggles
    this.container.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      if (target.classList.contains('hierarchy-section-header')) {
        const sectionId = target.dataset.section;
        if (sectionId) {
          this.toggleSection(sectionId);
        }
      }
    });
  }

  show(hierarchy: CallHierarchy | null): void {
    if (!hierarchy) {
      showEmptyState(this.container, 'No function detected in selection');
      return;
    }

    const html = this.generateHTML(hierarchy);
    this.container.innerHTML = html;
  }

  private generateHTML(h: CallHierarchy): string {
    let html = '<div class="target-symbol">';
    html += `<h3>${escapeHtml(h.targetFunction)}</h3>`;
    html += `<code>${escapeHtml(h.signature)}</code>`;
    html += '</div>';

    // Incoming calls
    html += this.generateSection('incoming', 'Incoming Calls', h.incomingCalls.length);
    html += '<div id="incoming-section" class="call-tree">';

    if (h.incomingCalls.length === 0) {
      html += '<div class="empty-state" style="padding: 1rem;">No incoming calls found</div>';
    } else {
      h.incomingCalls.forEach((call) => {
        html += '<div class="call-site">';
        html += '<div class="call-link">';
        html += `<span class="symbol-name">${escapeHtml(call.file)}</span>`;
        html += `<span class="location">Line ${call.line}</span>`;
        html += `<span class="call-type-badge">${call.type}</span>`;
        html += '</div>';
        html += `<pre class="context-code">${escapeHtml(call.content)}</pre>`;
        html += '</div>';
      });
    }
    html += '</div>';

    // Outgoing calls
    html += this.generateSection('outgoing', 'Outgoing Calls', h.outgoingCalls.length);
    html += '<div id="outgoing-section" class="call-tree">';

    if (h.outgoingCalls.length === 0) {
      html += '<div class="empty-state" style="padding: 1rem;">No outgoing calls found</div>';
    } else {
      h.outgoingCalls.forEach((call) => {
        html += '<div class="call-site">';
        html += '<div class="call-link">';
        html += `<span class="symbol-name">${escapeHtml(call.functionName || '')}</span>`;
        html += `<span class="location">${escapeHtml(call.file)}:${call.line}</span>`;
        html += '</div>';
        html += `<pre class="context-code">${escapeHtml(call.content)}</pre>`;
        html += '</div>';
      });
    }
    html += '</div>';

    return html;
  }

  private generateSection(id: string, title: string, count: number): string {
    return `
      <div class="hierarchy-section">
        <button class="hierarchy-section-header" data-section="${id}">
          <span>▼</span> ${title} (${count})
        </button>
      </div>
    `;
  }

  private toggleSection(sectionId: string): void {
    const section = this.container.querySelector(`#${sectionId}-section`) as HTMLElement;
    if (section) {
      section.style.display = section.style.display === 'none' ? 'block' : 'none';
    }
  }

  clear(): void {
    showEmptyState(this.container, 'Select code in the diff to view call hierarchy');
  }

  destroy(): void {
    // Cleanup if needed
  }
}
```

**Update `src/main.ts`:**

```typescript
import { extractCallHierarchy } from '@lib/call-hierarchy-analyzer';

private handleTextSelection(text: string): void {
  if (!this.currentFile || !this.parsedDiff) return;

  const hierarchy = extractCallHierarchy(text, this.currentFile, this.parsedDiff);
  this.hierarchyPanel.show(hierarchy);
}
```

**Verify:**
- Select function text in diff → hierarchy appears
- Shows incoming/outgoing calls
- Sections are collapsible
- Empty states work

---

### Step 2.8: Final Integration & Testing (30 min)

**Complete `src/main.ts`:**

```typescript
import './styles/main.css';

import { DiagramRenderer } from '@components/diagram-renderer';
import { DiffViewer } from '@components/diff-viewer';
import { CallHierarchyPanel } from '@components/call-hierarchy-panel';
import { FileUploader } from '@components/file-uploader';

import { parseDiff } from '@lib/diff-parser';
import { extractFunctions } from '@lib/function-extractor';
import { generateMermaidDiagram } from '@lib/diagram-generator';
import { extractCallHierarchy } from '@lib/call-hierarchy-analyzer';

import { getElement } from './utils/dom-helpers';

import type { ParsedDiff, DiffFile, FunctionNode } from '@types';

/**
 * Code Review Tool - Main Application
 */
class CodeReviewApp {
  private diagram: DiagramRenderer;
  private diffViewer: DiffViewer;
  private hierarchyPanel: CallHierarchyPanel;
  private uploader: FileUploader;

  private parsedDiff: ParsedDiff | null = null;
  private currentFile: DiffFile | null = null;

  constructor() {
    // Initialize components
    this.diagram = new DiagramRenderer(getElement('#mermaid-diagram'));
    this.diffViewer = new DiffViewer(getElement('#diff-content'));
    this.hierarchyPanel = new CallHierarchyPanel(getElement('#call-hierarchy-content'));

    const fileInput = getElement<HTMLInputElement>('#diff-file');
    const fileName = getElement('#file-name');
    this.uploader = new FileUploader(fileInput, fileName);

    this.setupEventHandlers();
    console.log('Code Review Tool initialized');
  }

  private setupEventHandlers(): void {
    // File upload
    this.uploader.on('fileLoaded', (content) => {
      this.handleFileLoad(content);
    });

    // Diagram interactions
    this.diagram.on('nodeClick', (funcNode) => {
      this.handleNodeClick(funcNode);
    });

    // Text selection for call hierarchy
    this.diffViewer.on('textSelect', (text) => {
      this.handleTextSelection(text);
    });
  }

  private async handleFileLoad(content: string): Promise<void> {
    try {
      // Parse diff
      this.parsedDiff = parseDiff(content);
      console.log('Parsed diff:', this.parsedDiff.files.length, 'files');

      // Extract functions
      const functions = extractFunctions(this.parsedDiff);
      console.log('Extracted functions:', functions.length);

      // Generate and render diagram
      const diagramCode = generateMermaidDiagram(functions, this.parsedDiff);
      await this.diagram.render(functions, diagramCode);

      console.log('Diagram rendered successfully');
    } catch (error) {
      console.error('Error processing diff:', error);
    }
  }

  private handleNodeClick(funcNode: FunctionNode): void {
    const file = this.parsedDiff?.files.find(
      (f) => f.newPath === funcNode.file || f.oldPath === funcNode.file
    );

    if (file) {
      this.currentFile = file;
      this.diffViewer.showFunction(file, funcNode);
      console.log('Showing function:', funcNode.name);
    }
  }

  private handleTextSelection(text: string): void {
    if (!this.currentFile || !this.parsedDiff) return;

    const hierarchy = extractCallHierarchy(text, this.currentFile, this.parsedDiff);
    this.hierarchyPanel.show(hierarchy);

    if (hierarchy) {
      console.log('Call hierarchy for:', hierarchy.targetFunction);
    }
  }

  destroy(): void {
    this.diagram.destroy();
    this.diffViewer.destroy();
    this.hierarchyPanel.destroy();
    this.uploader.destroy();
  }
}

// Initialize app
const app = new CodeReviewApp();

// Make available for debugging
(window as any).app = app;
```

**Test everything:**

```bash
npm run dev
```

**Complete test checklist:**
- ✅ Load diff file
- ✅ Diagram shows function nodes (not files)
- ✅ Nodes are colored correctly (green/red/blue)
- ✅ Arrows show function relationships
- ✅ Click node → diff shows for that function
- ✅ Function definition line is highlighted
- ✅ Select function text → hierarchy appears
- ✅ Hierarchy shows incoming/outgoing calls
- ✅ Sections collapse/expand
- ✅ No console errors
- ✅ Hot reload works

---

### Step 2.9: Build for Production (10 min)

```bash
# Type check
npx tsc --noEmit

# Build
npm run build

# Preview production build
npm run preview
```

**Verify production build:**
- Opens at http://localhost:4173
- All features work
- No errors in console
- Bundle size is reasonable (check `dist/`)

---

## PHASE 2 COMPLETE

**Time estimate: ~5-6 hours**

**What you have:**
- ✅ Full prototype ported to Vite + TypeScript
- ✅ All features working (diagram, diff, call hierarchy)
- ✅ Clean, maintainable architecture
- ✅ Type-safe codebase
- ✅ Production build ready
- ✅ ~10-15KB gzipped bundle (vs Astro's similar size)

---

## Post-Migration Improvements

### Optional Enhancements (if time permits):

**1. Add source maps for debugging:**
```typescript
// vite.config.ts
export default defineConfig({
  build: {
    sourcemap: true,
  },
});
```

**2. Add better error handling:**
```typescript
// src/utils/error-handler.ts
export function handleError(error: unknown, context: string): void {
  console.error(`Error in ${context}:`, error);

  // Could add error reporting service here (Sentry, etc.)
}
```

**3. Add loading indicators:**
```typescript
// Show spinner while parsing large diffs
```

**4. Add keyboard shortcuts:**
```typescript
// Ctrl+H to toggle hierarchy panel, etc.
```

---

## Total Time Estimate

- **Phase 1 (Setup):** 2 hours
- **Phase 2 (Port):** 5-6 hours
- **Total:** 7-8 hours

**But realistically:** Budget 10 hours to account for debugging and testing.

---

## Success Criteria

You've completed the migration when:

1. ✅ All prototype features work identically
2. ✅ TypeScript compiles without errors
3. ✅ Production build works
4. ✅ Code is organized and maintainable
5. ✅ You can easily add new features

---

## Next Steps (Future Enhancements)

Once the port is complete, you can easily add:

1. **GitHub API integration** - Fetch diffs directly from PRs
2. **Persistent state** - Remember last loaded diff
3. **URL routing** - Deep link to specific functions
4. **Export features** - Download reports, share links
5. **Backend API** - Cache analysis results
6. **Advanced analysis** - Complexity metrics, test coverage

The Vite + TypeScript foundation makes all of this straightforward!

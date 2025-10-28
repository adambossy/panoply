# Code Review Tool - Architecture Analysis

## Current Prototype Architecture

### Component Breakdown

The current implementation is a **monolithic single-page application** with the following logical components:

#### 1. **Data Layer**
- **DiffParser** (`parseDiff()` function, lines 294-361)
  - Parses git unified diff format into structured data
  - Returns: `{ files: [{ oldPath, newPath, hunks, additions, deletions }] }`
  - Stateful line-by-line parser with FSM-like behavior

#### 2. **Analysis Layer**
- **DependencyAnalyzer** (`generateMermaidDiagram()` function, lines 364-417)
  - Analyzes file relationships from import statements
  - Heuristic-based pattern matching (searches for 'import', 'require', 'from')
  - Generates Mermaid graph syntax with nodes and edges
  - Simple string-matching algorithm (O(n²) complexity)

#### 3. **Visualization Layer**
- **DiagramRenderer** (`renderDiagram()` function, lines 420-424)
  - Delegates to Mermaid.js library
  - Converts graph definition → SVG
  - Stateless rendering function

#### 4. **Presentation Layer**
- **DiffViewer** (`displayDiff()` function, lines 448-479)
  - Renders unified diff as HTML with line numbers
  - Syntax highlighting via CSS classes
  - Manual HTML string construction (vulnerable to XSS if not careful)

#### 5. **Interaction Layer**
- **EventOrchestrator** (`setupInteractivity()` function, lines 427-445)
  - Binds click handlers to diagram nodes
  - Maintains selection state (highlight management)
  - Coordinates between diagram and diff pane

#### 6. **Call Hierarchy Analyzer** (NEW FEATURE)
- **CallHierarchyExtractor** (to be implemented)
  - Extracts function/method definitions from selected code
  - Traces function calls (both incoming and outgoing)
  - Builds call tree (who calls this function, what it calls)
  - Pattern: Text selection → Parse → Extract symbols → Build hierarchy

**Prototype Implementation:**
```javascript
// extractCallHierarchy(selectedText, file)
//   - Parse selected code for function definitions
//   - Search entire diff for function calls
//   - Build bidirectional call graph
//   - Returns: { callers: [...], callees: [...] }

// renderCallHierarchy(hierarchy)
//   - Display as tree view or mini-diagram
//   - Show function signatures + locations
//   - Click to jump to definition/call site
```

#### 7. **Application State**
- Three global variables:
  - `parsedDiff`: Structured diff data
  - `currentDiagram`: Mermaid syntax string
  - `selectedCode`: Currently selected code + metadata (file, line range)
- State is mutable and lives in closure scope

---

## Data Flow

```
┌─────────────┐
│ User Uploads│
│  Diff File  │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│   File Reader   │ (Browser API)
│  reads content  │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  parseDiff()    │  Parses unified diff format
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  parsedDiff     │  Stored in closure
└──────┬──────────┘
       │
       ▼
┌─────────────────────────┐
│ generateMermaidDiagram()│  Analyzes dependencies
└──────┬──────────────────┘
       │
       ▼
┌─────────────────┐
│ currentDiagram  │  Mermaid syntax stored
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ renderDiagram() │  Renders SVG
└──────┬──────────┘
       │
       ▼
┌─────────────────────┐
│ setupInteractivity()│  Attaches click handlers
└──────┬──────────────┘
       │
       ▼
┌─────────────────┐     ┌───────────────┐
│ User clicks node│────▶│ displayDiff() │
└─────────────────┘     └───────────────┘
                                │
                                ▼
                      ┌──────────────────────┐
                      │ User selects code    │
                      │ (text selection)     │
                      └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────────┐
                      │ extractCallHierarchy()   │
                      │ - Parse function defs    │
                      │ - Search for calls       │
                      └──────────┬───────────────┘
                                 │
                                 ▼
                      ┌──────────────────────────┐
                      │ renderCallHierarchy()    │
                      │ Display in side panel    │
                      └──────────────────────────┘
```

---

## Production-Level Architecture

For a production system, we'd decompose this into **proper modules with clear boundaries**:

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Web Application                        │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────┐ │
│  │   Frontend     │  │   API Server   │  │  Analysis  │ │
│  │   (React/Vue)  │◀─┤   (Node/Go)    │◀─┤   Engine   │ │
│  └────────────────┘  └────────────────┘  └────────────┘ │
│                                                            │
└──────────────────────────────────────────────────────────┘
         │                      │                    │
         ▼                      ▼                    ▼
┌──────────────┐      ┌──────────────┐    ┌──────────────┐
│   Browser    │      │   Database   │    │ Git Provider │
│   Storage    │      │  (Postgres)  │    │  API (GH)    │
└──────────────┘      └──────────────┘    └──────────────┘
```

### Component Design

#### **1. Parser Module** (`src/lib/parser/`)
```typescript
// parser/DiffParser.ts
interface ParsedDiff {
  files: DiffFile[];
  metadata: DiffMetadata;
}

interface DiffFile {
  id: string;
  oldPath: string;
  newPath: string;
  changeType: 'added' | 'deleted' | 'modified' | 'renamed';
  hunks: Hunk[];
  stats: { additions: number; deletions: number };
}

interface Hunk {
  id: string;
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: DiffLine[];
  context?: string; // function/class context
}

interface DiffLine {
  type: 'addition' | 'deletion' | 'context';
  content: string;
  oldLineNumber?: number;
  newLineNumber?: number;
}

class UnifiedDiffParser {
  parse(diffText: string): ParsedDiff;
  validate(diffText: string): ValidationResult;
}

// Support multiple formats
class GitHubDiffParser extends UnifiedDiffParser {}
class GitLabDiffParser extends UnifiedDiffParser {}
```

#### **2. Analysis Module** (`src/lib/analysis/`)
```typescript
// analysis/DependencyAnalyzer.ts
interface DependencyGraph {
  nodes: Map<string, FileNode>;
  edges: Edge[];
}

interface FileNode {
  id: string;
  path: string;
  type: FileType;
  imports: Import[];
  exports: Export[];
  complexity: number; // cyclomatic complexity
}

interface Edge {
  from: string;
  to: string;
  type: 'import' | 'call' | 'inheritance' | 'composition';
  weight: number; // coupling strength
}

class DependencyAnalyzer {
  constructor(
    private readonly astParser: ASTParser,
    private readonly languageDetector: LanguageDetector
  ) {}

  analyze(diff: ParsedDiff): DependencyGraph;

  private detectLanguage(file: DiffFile): Language;
  private parseAST(file: DiffFile, language: Language): AST;
  private extractImports(ast: AST): Import[];
  private findRelationships(nodes: FileNode[]): Edge[];
}

// Language-specific analyzers
interface ASTParser {
  parse(code: string): AST;
}

class TypeScriptASTParser implements ASTParser {}
class PythonASTParser implements ASTParser {}
class GoASTParser implements ASTParser {}

// analysis/CallHierarchyAnalyzer.ts (NEW COMPONENT)
interface CallHierarchy {
  targetSymbol: Symbol;
  incomingCalls: CallSite[];  // Who calls this?
  outgoingCalls: CallSite[];  // What does this call?
}

interface Symbol {
  name: string;
  type: 'function' | 'method' | 'class' | 'variable';
  signature: string;
  location: Location;
  scope: 'global' | 'local' | 'class';
}

interface CallSite {
  symbol: Symbol;
  location: Location;
  context: string; // Surrounding code
  callType: 'direct' | 'indirect' | 'async' | 'callback';
}

interface Location {
  file: string;
  line: number;
  column: number;
  range: [number, number]; // start/end offset in file
}

class CallHierarchyAnalyzer {
  constructor(
    private readonly astParser: ASTParser,
    private readonly symbolTable: SymbolTable
  ) {}

  // Extract hierarchy for selected code
  analyze(selection: CodeSelection, diff: ParsedDiff): CallHierarchy;

  // Find all places this function is called
  findIncomingCalls(symbol: Symbol, diff: ParsedDiff): CallSite[];

  // Find all functions this function calls
  findOutgoingCalls(symbol: Symbol, ast: AST): CallSite[];

  // Build symbol table from diff
  private buildSymbolTable(diff: ParsedDiff): SymbolTable;

  // Extract function/method from selection
  private extractSymbol(selection: CodeSelection): Symbol;

  // Search for function calls across all files
  private searchCallSites(symbolName: string, files: DiffFile[]): CallSite[];
}

// Symbol resolution for cross-file analysis
class SymbolTable {
  private symbols: Map<string, Symbol[]>; // key: symbol name, value: all definitions

  register(symbol: Symbol): void;
  lookup(name: string, context: Location): Symbol | null;
  resolve(callExpr: string, context: Location): Symbol | null;
}
```

#### **3. Visualization Module** (`src/lib/visualization/`)
```typescript
// visualization/DiagramGenerator.ts
interface DiagramConfig {
  layout: 'hierarchical' | 'force-directed' | 'circular';
  theme: 'light' | 'dark';
  showMetrics: boolean;
  nodeSize: 'fixed' | 'weighted';
}

abstract class DiagramGenerator {
  abstract generate(graph: DependencyGraph, config: DiagramConfig): string;
}

class MermaidGenerator extends DiagramGenerator {
  generate(graph: DependencyGraph, config: DiagramConfig): string {
    // Smart layout algorithms
    // Node clustering by directory
    // Edge bundling for complex graphs
  }
}

class D3Generator extends DiagramGenerator {
  generate(graph: DependencyGraph, config: DiagramConfig): string {
    // Interactive force-directed graph
    // Zoom/pan capabilities
    // Custom node rendering
  }
}

// visualization/DiagramRenderer.ts
class DiagramRenderer {
  constructor(
    private readonly container: HTMLElement,
    private readonly generator: DiagramGenerator
  ) {}

  render(graph: DependencyGraph, config: DiagramConfig): Promise<void>;
  update(graph: DependencyGraph): void; // Incremental updates
  destroy(): void;
}
```

#### **4. UI Components** (`src/components/`)
```typescript
// components/DiffViewer.tsx
interface DiffViewerProps {
  file: DiffFile;
  highlightedLines?: Set<number>;
  onLineClick?: (lineNumber: number) => void;
}

const DiffViewer: React.FC<DiffViewerProps> = ({ file, highlightedLines, onLineClick }) => {
  const [syntaxHighlighting, setSyntaxHighlighting] = useState(true);

  return (
    <VirtualizedList itemCount={file.hunks.length}>
      {(index) => <HunkView hunk={file.hunks[index]} />}
    </VirtualizedList>
  );
};

// components/DiagramPane.tsx
const DiagramPane: React.FC = () => {
  const { graph, config } = useAppState();
  const rendererRef = useRef<DiagramRenderer>();

  useEffect(() => {
    rendererRef.current?.render(graph, config);
  }, [graph, config]);

  return <div ref={containerRef} className="diagram-container" />;
};

// components/FileExplorer.tsx
const FileExplorer: React.FC = () => {
  const { files } = useParsedDiff();
  const [searchQuery, setSearchQuery] = useState('');

  // Tree view with search/filter
  return <TreeView data={files} onSelect={handleFileSelect} />;
};

// components/CallHierarchyPanel.tsx (NEW COMPONENT)
interface CallHierarchyPanelProps {
  hierarchy: CallHierarchy | null;
  onNavigate: (location: Location) => void;
}

const CallHierarchyPanel: React.FC<CallHierarchyPanelProps> = ({ hierarchy, onNavigate }) => {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['incoming', 'outgoing']));

  if (!hierarchy) {
    return (
      <div className="empty-state">
        <p>Select code to view call hierarchy</p>
      </div>
    );
  }

  return (
    <div className="call-hierarchy-panel">
      <div className="target-symbol">
        <h3>{hierarchy.targetSymbol.name}</h3>
        <code className="signature">{hierarchy.targetSymbol.signature}</code>
      </div>

      <div className="hierarchy-section">
        <button onClick={() => toggleSection('incoming')}>
          {expandedSections.has('incoming') ? '▼' : '▶'} Incoming Calls ({hierarchy.incomingCalls.length})
        </button>
        {expandedSections.has('incoming') && (
          <CallTree
            calls={hierarchy.incomingCalls}
            onNavigate={onNavigate}
            direction="incoming"
          />
        )}
      </div>

      <div className="hierarchy-section">
        <button onClick={() => toggleSection('outgoing')}>
          {expandedSections.has('outgoing') ? '▼' : '▶'} Outgoing Calls ({hierarchy.outgoingCalls.length})
        </button>
        {expandedSections.has('outgoing') && (
          <CallTree
            calls={hierarchy.outgoingCalls}
            onNavigate={onNavigate}
            direction="outgoing"
          />
        )}
      </div>
    </div>
  );
};

// components/CallTree.tsx
interface CallTreeProps {
  calls: CallSite[];
  onNavigate: (location: Location) => void;
  direction: 'incoming' | 'outgoing';
}

const CallTree: React.FC<CallTreeProps> = ({ calls, onNavigate, direction }) => {
  return (
    <ul className="call-tree">
      {calls.map((call, idx) => (
        <li key={idx} className="call-site">
          <button
            className="call-link"
            onClick={() => onNavigate(call.location)}
          >
            <span className="symbol-name">{call.symbol.name}</span>
            <span className="location">
              {call.location.file}:{call.location.line}
            </span>
          </button>
          <pre className="context">{call.context}</pre>
          <span className="call-type-badge">{call.callType}</span>
        </li>
      ))}
    </ul>
  );
};
```

#### **5. State Management** (`src/state/`)
```typescript
// state/store.ts (Redux/Zustand/Context)
interface AppState {
  diff: {
    raw: string | null;
    parsed: ParsedDiff | null;
    loading: boolean;
    error: Error | null;
  };
  graph: {
    data: DependencyGraph | null;
    layout: LayoutAlgorithm;
    filters: GraphFilters;
  };
  callHierarchy: {
    current: CallHierarchy | null;
    selection: CodeSelection | null;
    loading: boolean;
    history: CallHierarchy[]; // Navigation history
  };
  ui: {
    selectedFile: string | null;
    selectedNode: string | null;
    splitPaneSize: [number, number, number]; // [diagram, diff, call hierarchy]
    theme: 'light' | 'dark';
    showCallHierarchy: boolean;
  };
  settings: UserSettings;
}

// Actions
type Action =
  | { type: 'LOAD_DIFF'; payload: string }
  | { type: 'PARSE_DIFF_SUCCESS'; payload: ParsedDiff }
  | { type: 'SELECT_FILE'; payload: string }
  | { type: 'UPDATE_GRAPH_FILTERS'; payload: Partial<GraphFilters> }
  | { type: 'SELECT_CODE'; payload: CodeSelection }
  | { type: 'ANALYZE_CALL_HIERARCHY_START' }
  | { type: 'ANALYZE_CALL_HIERARCHY_SUCCESS'; payload: CallHierarchy }
  | { type: 'NAVIGATE_TO_CALL_SITE'; payload: Location }
  | { type: 'TOGGLE_CALL_HIERARCHY_PANEL' };

// Selectors
const selectVisibleFiles = (state: AppState) =>
  state.diff.parsed?.files.filter(f => matchesFilters(f, state.graph.filters));

const selectCanAnalyzeCallHierarchy = (state: AppState) =>
  state.callHierarchy.selection !== null && !state.callHierarchy.loading;
```

#### **6. API Layer** (`backend/`)
```typescript
// backend/routes/diff.ts
POST   /api/diff/upload           // Upload diff file
POST   /api/diff/analyze          // Analyze diff + return graph
GET    /api/diff/:id              // Retrieve cached diff
POST   /api/diff/github           // Fetch from GitHub PR

// backend/routes/analysis.ts
POST   /api/analysis/dependencies // Deep dependency analysis
POST   /api/analysis/complexity   // Compute complexity metrics
POST   /api/analysis/impact       // Impact analysis (blast radius)
POST   /api/analysis/call-hierarchy // Extract call hierarchy for selection

// backend/services/
class DiffService {
  async parse(diffText: string): Promise<ParsedDiff>;
  async analyze(diff: ParsedDiff): Promise<DependencyGraph>;
  async cache(id: string, data: ParsedDiff): Promise<void>;
}

class CallHierarchyService {
  constructor(
    private readonly analyzer: CallHierarchyAnalyzer,
    private readonly cache: CacheService
  ) {}

  async analyze(
    diffId: string,
    selection: CodeSelection
  ): Promise<CallHierarchy>;

  // Precompute call hierarchies for all functions in diff (background job)
  async precomputeAll(diffId: string): Promise<void>;

  // Get cached hierarchy if available
  async getCached(diffId: string, symbolId: string): Promise<CallHierarchy | null>;
}

class GitHubService {
  async fetchPR(owner: string, repo: string, prNumber: number): Promise<string>;
  async fetchDiff(url: string): Promise<string>;
  async postComment(prNumber: number, comment: string): Promise<void>;
}
```

#### **7. Testing Strategy**
```typescript
// tests/unit/
describe('UnifiedDiffParser', () => {
  it('parses single file diff', () => {
    const input = `diff --git a/foo.ts b/foo.ts...`;
    const result = parser.parse(input);
    expect(result.files).toHaveLength(1);
  });

  it('handles binary files gracefully', () => {
    // Binary file test
  });
});

// tests/integration/
describe('DiffAnalysis E2E', () => {
  it('analyzes multi-file diff with dependencies', async () => {
    const diff = await loadFixture('complex-diff.txt');
    const graph = await analyzer.analyze(diff);
    expect(graph.edges).toContainEqual({
      from: 'components/Button.tsx',
      to: 'styles/theme.ts',
      type: 'import'
    });
  });
});

// tests/visual-regression/
describe('DiagramRenderer', () => {
  it('renders force-directed graph correctly', async () => {
    await page.goto('/');
    await page.upload('fixtures/sample.diff');
    await expect(page).toMatchScreenshot('force-directed.png');
  });
});
```

---

## Advanced Features for Production

### 1. **AST-Based Analysis**
Replace regex pattern matching with proper Abstract Syntax Tree parsing:
- Use `@babel/parser` for JS/TS
- Use `ast` module for Python
- Use `go/parser` for Go
- Accurate import/export tracking
- Function call graph analysis

### 2. **Incremental Updates**
Instead of re-rendering entire diagram on every change:
```typescript
class IncrementalDiagramRenderer {
  private nodesMap: Map<string, SVGElement>;

  update(changes: GraphDelta) {
    changes.addedNodes.forEach(node => this.addNode(node));
    changes.removedNodes.forEach(id => this.removeNode(id));
    changes.updatedEdges.forEach(edge => this.updateEdge(edge));
    this.recalculateLayout();
  }
}
```

### 3. **Real-Time Collaboration**
```typescript
// WebSocket integration
class CollaborationService {
  private ws: WebSocket;

  shareSession(diffId: string): string; // Returns share URL
  syncCursor(position: { file: string; line: number }): void;
  addComment(comment: Comment): void;
  subscribeToChanges(callback: (event: CollabEvent) => void): void;
}
```

### 4. **AI-Powered Insights**
```typescript
class AIAnalyzer {
  async summarizeChanges(diff: ParsedDiff): Promise<Summary>;
  async suggestReviewers(graph: DependencyGraph): Promise<User[]>;
  async detectIssues(diff: ParsedDiff): Promise<Issue[]>;
  // - Security vulnerabilities
  // - Code smells
  // - Breaking changes
  // - Performance regressions
}
```

### 5. **Performance Optimizations**
- **Virtual scrolling** for large diffs (react-window)
- **Web Workers** for parsing/analysis (offload from main thread)
- **Streaming parsing** for giant diffs (don't load entire file into memory)
- **Canvas rendering** for massive graphs (instead of SVG/DOM)

### 6. **Caching & Persistence**
```typescript
class CacheService {
  // Browser-side
  private cache: IndexedDB;

  async cacheDiff(id: string, diff: ParsedDiff): Promise<void>;
  async cacheGraph(id: string, graph: DependencyGraph): Promise<void>;

  // Server-side
  private redis: Redis;

  async cacheWithTTL(key: string, value: any, ttl: number): Promise<void>;
}
```

### 7. **Export & Reporting**
```typescript
class ReportGenerator {
  exportAsPDF(diff: ParsedDiff, graph: DependencyGraph): Promise<Blob>;
  exportAsMarkdown(summary: Summary): string;
  generateMetricsReport(graph: DependencyGraph): Report;
  // - Lines changed per file
  // - Complexity metrics
  // - Test coverage impact
  // - Dependency changes
}
```

### 8. **Call Hierarchy Features** (NEW)
```typescript
// Advanced call hierarchy capabilities
class EnhancedCallHierarchyAnalyzer extends CallHierarchyAnalyzer {
  // Multi-level call chains (A → B → C → D)
  async traceCallChain(
    symbol: Symbol,
    maxDepth: number = 5
  ): Promise<CallChain>;

  // Find indirect callers (through callbacks, promises, events)
  async findIndirectCallers(
    symbol: Symbol,
    diff: ParsedDiff
  ): Promise<CallSite[]>;

  // Cross-language call tracking (e.g., Python calling JS via API)
  async analyzeCrossLanguageCalls(
    symbol: Symbol,
    diff: ParsedDiff
  ): Promise<CrossLanguageCall[]>;

  // Identify unused functions (no incoming calls)
  async findDeadCode(diff: ParsedDiff): Promise<Symbol[]>;

  // Call frequency analysis (hot paths)
  async analyzeCallFrequency(
    diff: ParsedDiff,
    executionTraces?: Trace[]
  ): Promise<CallFrequencyMap>;
}

interface CallChain {
  path: Symbol[];
  depth: number;
  type: 'sync' | 'async' | 'mixed';
}

interface CrossLanguageCall {
  caller: Symbol;
  callee: Symbol;
  bridge: 'http' | 'grpc' | 'ffi' | 'ipc';
  endpoint?: string;
}

// Interactive features
class CallHierarchyNavigator {
  // Navigate call tree with keyboard
  nextCall(): void;
  previousCall(): void;
  goToParent(): void;
  expandAll(): void;
  collapseAll(): void;

  // Search within hierarchy
  search(query: string): CallSite[];
  filter(predicate: (call: CallSite) => boolean): CallSite[];

  // Visualize as mini-diagram
  generateHierarchyDiagram(hierarchy: CallHierarchy): MermaidGraph;
}

// Performance optimization
class CallHierarchyCache {
  // Incremental updates when code changes
  async update(
    oldHierarchy: CallHierarchy,
    changes: DiffDelta
  ): Promise<CallHierarchy>;

  // Background precomputation
  async warmCache(diff: ParsedDiff): Promise<void>;

  // Invalidate affected hierarchies on edit
  invalidate(changedSymbols: Symbol[]): void;
}
```

**UI Integration:**
```typescript
// Three-pane layout: Diagram | Diff | Call Hierarchy
<Layout>
  <DiagramPane /> {/* Left */}
  <DiffViewer
    onTextSelect={(selection) => dispatch({ type: 'SELECT_CODE', payload: selection })}
  /> {/* Center */}
  <CallHierarchyPanel /> {/* Right - toggleable */}
</Layout>

// Keyboard shortcuts
- `Ctrl+H`: Toggle call hierarchy panel
- `Ctrl+I`: Show incoming calls
- `Ctrl+O`: Show outgoing calls
- `F12`: Go to definition
- `Shift+F12`: Find all references (incoming calls)
```

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CDN (CloudFlare)                        │
│  - Static assets (JS, CSS, fonts)                           │
│  - Edge caching                                              │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                  Load Balancer (ALB)                         │
└─────────────────────┬───────────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          │                       │
┌─────────▼──────────┐  ┌────────▼─────────┐
│  Web Server (Nginx)│  │  Web Server      │
│  - Serve SPA       │  │  (Redundant)     │
│  - API Gateway     │  │                  │
└─────────┬──────────┘  └────────┬─────────┘
          │                      │
          └───────────┬──────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│              Application Servers (Node.js/Go)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  API Service │  │ Analysis Svc │  │ GitHub Svc   │      │
│  │  (Express)   │  │ (Workers)    │  │ (Webhooks)   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└──────┬──────────────────┬─────────────────────┬────────────┘
       │                  │                     │
       ▼                  ▼                     ▼
┌──────────────┐  ┌──────────────┐    ┌──────────────┐
│  PostgreSQL  │  │    Redis     │    │  S3/Blob     │
│  (Metadata)  │  │   (Cache)    │    │  (Diffs)     │
└──────────────┘  └──────────────┘    └──────────────┘
```

---

## Technology Stack Recommendations

### Frontend
- **Framework**: React 18+ (with Suspense) or Solid.js (better performance)
- **State**: Zustand or Jotai (lighter than Redux)
- **Styling**: Tailwind CSS + CSS Modules
- **Build**: Vite (faster than Webpack)
- **Diagrams**: D3.js or Cytoscape.js (more powerful than Mermaid)

### Backend
- **Runtime**: Node.js 20+ or Bun (faster)
- **Framework**: Fastify (faster than Express) or Go with Chi
- **Queue**: BullMQ (Redis-backed job queue for analysis tasks)
- **Cache**: Redis with JSON support
- **Database**: PostgreSQL 16+ with JSONB for flexible schema

### Infrastructure
- **Hosting**: Vercel/Netlify (frontend) + Railway/Fly.io (backend)
- **Monitoring**: Sentry (errors) + DataDog (metrics)
- **CI/CD**: GitHub Actions
- **CDN**: CloudFlare

---

## Security Considerations

1. **XSS Prevention**: Use DOMPurify for sanitizing HTML
2. **CSRF Protection**: Token-based auth for API calls
3. **Rate Limiting**: Prevent abuse of analysis endpoints
4. **Input Validation**: Validate diff format before parsing
5. **Secrets Management**: Never expose GitHub tokens client-side

---

## Scalability Metrics

| Component          | Current | Production Target |
|--------------------|---------|-------------------|
| Max diff size      | ~1MB    | 100MB+ (streaming)|
| Files in graph     | ~50     | 1000+ (clustering)|
| Parse time         | ~100ms  | <50ms (Web Workers)|
| Render time        | ~500ms  | <100ms (Canvas)   |
| Concurrent users   | 1       | 10,000+           |

---

## Migration Path

1. **Phase 1**: Extract into modules (Parser, Analyzer, Renderer)
2. **Phase 2**: Add TypeScript + proper types
3. **Phase 3**: Replace Mermaid with D3.js for advanced interactions
4. **Phase 4**: Add backend API for persistence
5. **Phase 5**: Implement real-time collaboration
6. **Phase 6**: Add AI-powered features

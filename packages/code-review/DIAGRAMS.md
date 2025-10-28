# Code Review Tool - Mermaid Diagrams

## Prototype Component Architecture

### Component Dependencies

```mermaid
graph TB
    subgraph "Data Layer"
        DP[DiffParser]
        State[Application State<br/>parsedDiff, currentDiagram,<br/>selectedCode, currentFile]
    end

    subgraph "Analysis Layer"
        DA[DependencyAnalyzer]
        CHA[CallHierarchyExtractor]
    end

    subgraph "Visualization Layer"
        DR[DiagramRenderer<br/>Mermaid.js]
        DV[DiffViewer]
        CHR[CallHierarchyRenderer]
    end

    subgraph "Interaction Layer"
        EO[EventOrchestrator]
        TSH[TextSelectionHandler]
    end

    subgraph "External Dependencies"
        Mermaid[Mermaid.js Library]
        Browser[Browser APIs]
    end

    %% Data flow
    Browser -->|File Upload| DP
    DP -->|Structured Data| State
    State -->|Diff Data| DA
    State -->|Diff Data| DV
    DA -->|Mermaid Syntax| State
    State -->|Diagram Code| DR
    DR -->|SVG| EO
    EO -->|Click Events| DV
    DV -->|Display| Browser
    TSH -->|Selection| CHA
    State -->|File Context| CHA
    CHA -->|Hierarchy Data| CHR
    CHR -->|Display| Browser
    DR -.->|Uses| Mermaid

    %% Styling
    classDef dataLayer fill:#0e639c,stroke:#1177bb,color:#fff
    classDef analysisLayer fill:#2d2d30,stroke:#3e3e42,color:#d4d4d4
    classDef visualLayer fill:#1e3c1e,stroke:#4ec9b0,color:#fff
    classDef interactionLayer fill:#4b1818,stroke:#f48771,color:#fff
    classDef externalLayer fill:#264f78,stroke:#0e639c,color:#fff

    class DP,State dataLayer
    class DA,CHA analysisLayer
    class DR,DV,CHR visualLayer
    class EO,TSH interactionLayer
    class Mermaid,Browser externalLayer
```

### Data Flow Sequence

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant DiffParser
    participant State
    participant DependencyAnalyzer
    participant DiagramRenderer
    participant DiffViewer
    participant TextSelection
    participant CallHierarchy

    User->>Browser: Upload diff file
    Browser->>DiffParser: Parse file content
    DiffParser->>State: Store parsed diff
    State->>DependencyAnalyzer: Analyze dependencies
    DependencyAnalyzer->>State: Store Mermaid syntax
    State->>DiagramRenderer: Render diagram
    DiagramRenderer->>Browser: Display SVG

    User->>Browser: Click diagram node
    Browser->>State: Get file data
    State->>DiffViewer: Render diff
    DiffViewer->>Browser: Display diff

    User->>Browser: Select code text
    Browser->>TextSelection: Capture selection
    TextSelection->>CallHierarchy: Extract hierarchy
    CallHierarchy->>State: Query all files
    State->>CallHierarchy: Return file data
    CallHierarchy->>Browser: Display hierarchy
```

### Component Interaction Map

```mermaid
graph LR
    subgraph "Component 1: DiffParser"
        P1[Input: Raw diff text]
        P2[Process: Line-by-line parsing]
        P3[Output: Structured JSON]
        P1 --> P2 --> P3
    end

    subgraph "Component 2: DependencyAnalyzer"
        D1[Input: Parsed diff]
        D2[Process: Pattern matching<br/>for imports]
        D3[Output: Mermaid graph<br/>syntax string]
        D1 --> D2 --> D3
    end

    subgraph "Component 3: DiagramRenderer"
        R1[Input: Mermaid syntax]
        R2[Process: mermaid.render]
        R3[Output: SVG string]
        R1 --> R2 --> R3
    end

    subgraph "Component 4: DiffViewer"
        V1[Input: File object]
        V2[Process: Build HTML<br/>with line numbers]
        V3[Output: Rendered diff]
        V1 --> V2 --> V3
    end

    subgraph "Component 5: EventOrchestrator"
        E1[Input: Click events]
        E2[Process: Node selection<br/>& highlighting]
        E3[Output: Trigger diff<br/>display]
        E1 --> E2 --> E3
    end

    subgraph "Component 6: CallHierarchyExtractor"
        C1[Input: Selected text]
        C2[Process: Function<br/>detection & search]
        C3[Output: Call hierarchy<br/>object]
        C1 --> C2 --> C3
    end

    subgraph "Component 7: CallHierarchyRenderer"
        H1[Input: Hierarchy object]
        H2[Process: Build tree<br/>HTML]
        H3[Output: Rendered tree]
        H1 --> H2 --> H3
    end

    P3 --> D1
    D3 --> R1
    P3 --> V1
    R3 --> E1
    E3 --> V1
    V3 --> C1
    C3 --> H1
```

---

## UI Structure

### Layout Hierarchy

```mermaid
graph TB
    Root[Container<br/>Full viewport height]

    Root --> Header[Header<br/>Title bar]
    Root --> Controls[Controls<br/>File upload button]
    Root --> Content[Content<br/>Flex container]

    Content --> Pane1[Diagram Pane<br/>flex: 1]
    Content --> Pane2[Diff Pane<br/>flex: 1]
    Content --> Pane3[Call Hierarchy Pane<br/>flex: 0 0 400px]

    Pane1 --> P1Header[Pane Header<br/>'Dataflow Diagram']
    Pane1 --> P1Content[Pane Content<br/>Scrollable]
    P1Content --> Diagram[#mermaid-diagram<br/>SVG container]

    Pane2 --> P2Header[Pane Header<br/>'Diff Details']
    Pane2 --> P2Content[Pane Content<br/>Scrollable]
    P2Content --> DiffContent[#diff-content<br/>Diff display]
    DiffContent --> DiffFile[.diff-file]
    DiffFile --> DiffFileHeader[.diff-file-header<br/>Filename]
    DiffFile --> DiffLines[.diff-lines]
    DiffLines --> DiffLine[.diff-line<br/>× many]
    DiffLine --> LineNumber[.line-number]
    DiffLine --> LineContent[.line-content]

    Pane3 --> P3Header[Pane Header<br/>'Call Hierarchy']
    Pane3 --> P3Content[Pane Content<br/>No padding, scrollable]
    P3Content --> CHContent[#call-hierarchy-content]
    CHContent --> TargetSymbol[.target-symbol<br/>Function name & signature]
    CHContent --> HSection1[.hierarchy-section<br/>Incoming Calls]
    CHContent --> HSection2[.hierarchy-section<br/>Outgoing Calls]
    HSection1 --> HSHeader1[.hierarchy-section-header<br/>Collapsible button]
    HSection1 --> CallTree1[.call-tree<br/>List of calls]
    HSection2 --> HSHeader2[.hierarchy-section-header<br/>Collapsible button]
    HSection2 --> CallTree2[.call-tree<br/>List of calls]
    CallTree1 --> CallSite1[.call-site × many]
    CallSite1 --> CallLink1[.call-link<br/>Clickable]
    CallSite1 --> ContextCode1[.context-code<br/>Code preview]
    CallTree2 --> CallSite2[.call-site × many]
    CallSite2 --> CallLink2[.call-link<br/>Clickable]
    CallSite2 --> ContextCode2[.context-code<br/>Code preview]

    %% Styling
    classDef container fill:#2d2d30,stroke:#3e3e42,color:#d4d4d4
    classDef pane fill:#1e1e1e,stroke:#3e3e42,color:#d4d4d4
    classDef content fill:#0e639c,stroke:#1177bb,color:#fff
    classDef interactive fill:#264f78,stroke:#0e639c,color:#fff

    class Root,Header,Controls,Content container
    class Pane1,Pane2,Pane3,P1Content,P2Content,P3Content pane
    class Diagram,DiffContent,CHContent content
    class CallLink1,CallLink2,HSHeader1,HSHeader2 interactive
```

### User Interaction Flow

```mermaid
stateDiagram-v2
    [*] --> Initial: Load App
    Initial --> FileSelected: User uploads diff
    FileSelected --> Parsing: Parse diff
    Parsing --> DiagramReady: Generate diagram
    DiagramReady --> NodeSelected: Click node
    NodeSelected --> DiffDisplayed: Show diff
    DiffDisplayed --> TextSelected: Select code
    TextSelected --> HierarchyDisplayed: Show hierarchy
    HierarchyDisplayed --> TextSelected: Select different code
    HierarchyDisplayed --> NodeSelected: Click different node
    NodeSelected --> NodeSelected: Click another node
    TextSelected --> DiffDisplayed: Clear selection

    note right of Initial
        Empty state with
        loading message
    end note

    note right of DiagramReady
        Diagram rendered,
        click handlers attached
    end note

    note right of DiffDisplayed
        Diff shown with
        syntax highlighting
    end note

    note right of HierarchyDisplayed
        Call hierarchy populated
        with incoming/outgoing calls
    end note
```

### Component State Flow

```mermaid
graph LR
    subgraph "Global State"
        S1[parsedDiff: null → Object]
        S2[currentDiagram: null → string]
        S3[selectedCode: null → Object]
        S4[currentFile: null → Object]
    end

    subgraph "UI State"
        U1[Diagram Visibility]
        U2[Diff Visibility]
        U3[Hierarchy Visibility]
        U4[Selected Node]
        U5[Expanded Sections]
    end

    subgraph "Events"
        E1[File Upload]
        E2[Node Click]
        E3[Text Selection]
        E4[Section Toggle]
    end

    E1 -->|Updates| S1
    S1 -->|Triggers| S2
    S2 -->|Controls| U1

    E2 -->|Updates| S4
    S4 -->|Updates| U4
    U4 -->|Controls| U2

    E3 -->|Updates| S3
    S3 -->|Triggers analysis| U3

    E4 -->|Toggles| U5

    %% Styling
    classDef stateClass fill:#0e639c,stroke:#1177bb,color:#fff
    classDef uiClass fill:#1e3c1e,stroke:#4ec9b0,color:#fff
    classDef eventClass fill:#4b1818,stroke:#f48771,color:#fff

    class S1,S2,S3,S4 stateClass
    class U1,U2,U3,U4,U5 uiClass
    class E1,E2,E3,E4 eventClass
```

### Responsive Layout Structure

```mermaid
graph TB
    subgraph "Desktop Layout (3-pane)"
        D1[┌─────────────────────────────────────────┐]
        D2[│          Header + Controls              │]
        D3[├───────────┬──────────┬─────────────────┤]
        D4[│  Diagram  │   Diff   │  Call Hierarchy │]
        D5[│   Pane    │   Pane   │      Pane       │]
        D6[│  flex: 1  │ flex: 1  │   400px fixed   │]
        D7[└───────────┴──────────┴─────────────────┘]
        D1 --> D2 --> D3 --> D4 --> D5 --> D6 --> D7
    end

    subgraph "Visual Hierarchy"
        V1[Z-index layers]
        V2[Layer 0: Background #1e1e1e]
        V3[Layer 1: Panes #2d2d30]
        V4[Layer 2: Headers #2d2d30]
        V5[Layer 3: Content areas]
        V6[Layer 4: Interactive elements]
        V7[Layer 5: Highlights #264f78]
        V1 --> V2 --> V3 --> V4 --> V5 --> V6 --> V7
    end

    subgraph "Color Scheme (VS Code Dark)"
        C1[Background: #1e1e1e]
        C2[Panel BG: #2d2d30]
        C3[Border: #3e3e42]
        C4[Text: #d4d4d4]
        C5[Accent: #0e639c]
        C6[Addition: #1e3c1e / #4ec9b0]
        C7[Deletion: #4b1818 / #f48771]
        C8[Highlight: #264f78]
    end
```

### Event Handling Architecture

```mermaid
graph TB
    subgraph "DOM Events"
        E1[File Input Change]
        E2[Node Click]
        E3[Mouse Up<br/>Text Selection]
        E4[Section Toggle Click]
    end

    subgraph "Event Handlers"
        H1[fileInput.addEventListener<br/>'change']
        H2[setupInteractivity<br/>node.addEventListener<br/>'click']
        H3[setupTextSelection<br/>document.addEventListener<br/>'mouseup']
        H4[window.toggleSection]
    end

    subgraph "Processing"
        P1[parseDiff]
        P2[generateMermaidDiagram]
        P3[renderDiagram]
        P4[displayDiff]
        P5[extractCallHierarchy]
        P6[renderCallHierarchy]
        P7[Toggle visibility]
    end

    subgraph "DOM Updates"
        U1[Update mermaidContainer]
        U2[Update diffContainer]
        U3[Update callHierarchyContainer]
        U4[Toggle section display]
    end

    E1 --> H1
    H1 --> P1 --> P2 --> P3 --> U1

    E2 --> H2
    H2 --> P4 --> U2

    E3 --> H3
    H3 --> P5 --> P6 --> U3

    E4 --> H4
    H4 --> P7 --> U4

    %% Styling
    classDef eventClass fill:#4b1818,stroke:#f48771,color:#fff
    classDef handlerClass fill:#0e639c,stroke:#1177bb,color:#fff
    classDef processClass fill:#1e3c1e,stroke:#4ec9b0,color:#fff
    classDef updateClass fill:#264f78,stroke:#0e639c,color:#fff

    class E1,E2,E3,E4 eventClass
    class H1,H2,H3,H4 handlerClass
    class P1,P2,P3,P4,P5,P6,P7 processClass
    class U1,U2,U3,U4 updateClass
```

---

## Component Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant App as Application Load
    participant Init as Initialization
    participant Upload as File Upload
    participant Analysis as Analysis Phase
    participant Interaction as User Interaction
    participant Update as UI Update

    App->>Init: Load Mermaid.js from CDN
    Init->>Init: Initialize Mermaid config
    Init->>Init: Get DOM references
    Init->>Init: Setup text selection handler
    Init->>Upload: Wait for user input

    Upload->>Analysis: File selected
    Analysis->>Analysis: parseDiff()
    Analysis->>Analysis: generateMermaidDiagram()
    Analysis->>Update: renderDiagram()
    Update->>Analysis: setupInteractivity()
    Analysis->>Interaction: Ready

    loop User Actions
        Interaction->>Interaction: Click node / Select text
        Interaction->>Analysis: Process action
        Analysis->>Update: Update relevant pane
        Update->>Interaction: Ready for next action
    end
```

---

## Data Structure Flow

```mermaid
graph LR
    subgraph "Input"
        I1[Raw Diff Text<br/>String]
    end

    subgraph "Parsed Structure"
        P1[ParsedDiff Object]
        P2[files: Array]
        P3[File Object]
        P4[hunks: Array]
        P5[Hunk Object]
        P6[lines: Array]
        P7[Line Object]

        P1 --> P2
        P2 --> P3
        P3 --> P4
        P4 --> P5
        P5 --> P6
        P6 --> P7
    end

    subgraph "Hierarchy Structure"
        H1[CallHierarchy Object]
        H2[targetFunction: string]
        H3[signature: string]
        H4[incomingCalls: Array]
        H5[outgoingCalls: Array]
        H6[CallSite Object]

        H1 --> H2
        H1 --> H3
        H1 --> H4
        H1 --> H5
        H4 --> H6
        H5 --> H6
    end

    subgraph "Visualization"
        V1[Mermaid Syntax<br/>String]
        V2[SVG String]
        V3[HTML String]
    end

    I1 -->|parseDiff| P1
    P1 -->|generateMermaidDiagram| V1
    V1 -->|mermaid.render| V2
    P3 -->|displayDiff| V3
    P7 -->|extractCallHierarchy| H1
    H1 -->|renderCallHierarchy| V3

    %% Styling
    classDef inputClass fill:#4b1818,stroke:#f48771,color:#fff
    classDef structureClass fill:#0e639c,stroke:#1177bb,color:#fff
    classDef hierarchyClass fill:#1e3c1e,stroke:#4ec9b0,color:#fff
    classDef visualClass fill:#264f78,stroke:#0e639c,color:#fff

    class I1 inputClass
    class P1,P2,P3,P4,P5,P6,P7 structureClass
    class H1,H2,H3,H4,H5,H6 hierarchyClass
    class V1,V2,V3 visualClass
```

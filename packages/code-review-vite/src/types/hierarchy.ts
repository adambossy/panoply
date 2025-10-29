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


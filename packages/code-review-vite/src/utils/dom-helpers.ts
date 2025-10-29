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
  element.innerHTML = `<div class="error">${message}</div>`;
}

/**
 * Show empty state
 */
export function showEmptyState(element: HTMLElement, message: string): void {
  element.innerHTML = `<div class="empty-state">${message}</div>`;
}


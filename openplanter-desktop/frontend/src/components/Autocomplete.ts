/** Slash command autocomplete popup controller. */
import { COMMAND_COMPLETIONS, type CompletionItem } from "../commands/completionRegistry";

export interface AutocompleteCallbacks {
  onAccept: (text: string) => void;
  onDismiss: () => void;
}

export class AutocompleteController {
  private popup: HTMLDivElement;
  private items: CompletionItem[] = [];
  private selectedIndex = 0;
  private visible = false;
  private callbacks: AutocompleteCallbacks;

  constructor(anchor: HTMLElement, callbacks: AutocompleteCallbacks) {
    this.callbacks = callbacks;
    this.popup = document.createElement("div");
    this.popup.className = "autocomplete-popup";
    this.popup.style.display = "none";
    anchor.appendChild(this.popup);
  }

  /** Called on every input change. Determines what completions to show. */
  update(text: string): void {
    if (!text.startsWith("/")) {
      this.hide();
      return;
    }

    const tokens = text.split(/\s+/).filter((t) => t.length > 0);
    const hasTrailingSpace = text.endsWith(" ") && text.length > 1;

    // Walk the tree: each fully-matched token descends into children
    let candidates: CompletionItem[] = COMMAND_COMPLETIONS;
    let resolvedTokens: string[] = [];

    for (let i = 0; i < tokens.length; i++) {
      const token = tokens[i];
      const isLast = i === tokens.length - 1;

      if (isLast && !hasTrailingSpace) {
        // This is the active filter prefix
        break;
      }

      // Try to match this token exactly to descend
      const match = candidates.find(
        (c) => c.value.toLowerCase() === token.toLowerCase(),
      );
      if (match) {
        resolvedTokens.push(match.value);
        candidates = match.children ?? [];
      } else {
        // No match — can't descend further, no completions
        this.hide();
        return;
      }
    }

    // Determine filter prefix
    const prefix = hasTrailingSpace ? "" : tokens[tokens.length - 1].toLowerCase();

    // Filter candidates by prefix
    const filtered = candidates.filter((c) =>
      c.value.toLowerCase().startsWith(prefix),
    );

    // Auto-hide rule: single exact match with no children
    if (
      filtered.length === 1 &&
      filtered[0].value.toLowerCase() === prefix &&
      (!filtered[0].children || filtered[0].children.length === 0)
    ) {
      this.hide();
      return;
    }

    if (filtered.length === 0) {
      this.hide();
      return;
    }

    this.items = filtered;
    this.selectedIndex = 0;
    this.render();
    this.show();
  }

  /** Handle keydown. Returns true if the key was consumed. */
  handleKeydown(e: KeyboardEvent): boolean {
    if (!this.visible) return false;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      this.selectedIndex = (this.selectedIndex + 1) % this.items.length;
      this.updateSelection();
      return true;
    }

    if (e.key === "ArrowUp") {
      e.preventDefault();
      this.selectedIndex =
        (this.selectedIndex - 1 + this.items.length) % this.items.length;
      this.updateSelection();
      return true;
    }

    if (e.key === "Tab" || e.key === "Enter") {
      e.preventDefault();
      this.accept(this.items[this.selectedIndex]);
      return true;
    }

    if (e.key === "Escape") {
      e.preventDefault();
      this.hide();
      this.callbacks.onDismiss();
      return true;
    }

    return false;
  }

  isVisible(): boolean {
    return this.visible;
  }

  destroy(): void {
    this.popup.remove();
  }

  /** Accept a completion item. Builds the full text and calls back. */
  private accept(item: CompletionItem): void {
    // Get the current text from the textarea sibling
    const textarea = this.popup.parentElement?.querySelector("textarea");
    if (!textarea) return;

    const text = textarea.value;
    const tokens = text.split(/\s+/).filter((t) => t.length > 0);
    const hasTrailingSpace = text.endsWith(" ") && text.length > 1;

    // Rebuild: resolved tokens + accepted value
    let resolvedTokens: string[] = [];
    let candidates: CompletionItem[] = COMMAND_COMPLETIONS;

    const limit = hasTrailingSpace ? tokens.length : tokens.length - 1;
    for (let i = 0; i < limit; i++) {
      const match = candidates.find(
        (c) => c.value.toLowerCase() === tokens[i].toLowerCase(),
      );
      if (match) {
        resolvedTokens.push(match.value);
        candidates = match.children ?? [];
      }
    }

    resolvedTokens.push(item.value);

    const hasChildren = item.children && item.children.length > 0;
    const newText = resolvedTokens.join(" ") + (hasChildren ? " " : "");

    this.callbacks.onAccept(newText);

    // If the accepted item has children, re-run update to show next level
    if (hasChildren) {
      // Use setTimeout to let the textarea value update first
      setTimeout(() => this.update(newText), 0);
    } else {
      this.hide();
    }
  }

  private render(): void {
    this.popup.innerHTML = "";
    for (let i = 0; i < this.items.length; i++) {
      const item = this.items[i];
      const row = document.createElement("div");
      row.className = "autocomplete-item" + (i === this.selectedIndex ? " selected" : "");
      row.dataset.index = String(i);

      const valSpan = document.createElement("span");
      valSpan.className = "autocomplete-value";
      valSpan.textContent = item.value;

      const descSpan = document.createElement("span");
      descSpan.className = "autocomplete-desc";
      descSpan.textContent = item.description;

      row.appendChild(valSpan);
      row.appendChild(descSpan);

      row.addEventListener("mouseenter", () => {
        this.selectedIndex = i;
        this.updateSelection();
      });

      row.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.accept(item);
      });

      this.popup.appendChild(row);
    }
  }

  private updateSelection(): void {
    const children = this.popup.children;
    for (let i = 0; i < children.length; i++) {
      children[i].classList.toggle("selected", i === this.selectedIndex);
    }
    // Scroll selected item into view
    const selected = children[this.selectedIndex] as HTMLElement | undefined;
    selected?.scrollIntoView({ block: "nearest" });
  }

  private show(): void {
    this.visible = true;
    this.popup.style.display = "";
  }

  private hide(): void {
    this.visible = false;
    this.popup.style.display = "none";
    this.items = [];
  }
}

export interface OperationalSelectionSearch {
  selected?: string;
}

export function validateOperationalSearch(
  search: Record<string, unknown>,
): OperationalSelectionSearch {
  return typeof search.selected === "string" && search.selected.length > 0
    ? { selected: search.selected }
    : {};
}

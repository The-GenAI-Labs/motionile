export const nth = <T>(items: readonly T[], index: number): T => {
  const item = items[index];
  if (item === undefined) {
    throw new Error(`Expected an item at index ${String(index)}.`);
  }
  return item;
};

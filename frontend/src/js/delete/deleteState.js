// delete/deleteState.js
export const deleteState = {
  total: 0,
  success: 0,
  fail: 0,
  rows: new Set(),
};

export function resetDeleteState() {
  deleteState.total = 0;
  deleteState.success = 0;
  deleteState.fail = 0;
  deleteState.rows.clear();
}

export function registerDeleteResult({ ean, storefront, success }) {
  const key = `${ean}-${storefront}`;
  if (deleteState.rows.has(key)) return false;

  deleteState.rows.add(key);
  deleteState.total += 1;

  success ? deleteState.success++ : deleteState.fail++;
  return true;
}

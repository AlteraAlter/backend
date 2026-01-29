// delete/deleteController.js
import {
  deleteState,
  resetDeleteState,
  registerDeleteResult,
} from "./deleteState.js";
import {
  updateDeleteSummary,
  appendDeleteRow,
  clearDeleteTable,
} from "./deleteRenderer.js";

export function resetDeleteProgress() {
  resetDeleteState();
  clearDeleteTable();
  updateDeleteSummary(deleteState);
}

export function handleDeleteProgress(data) {
  /*
    data = {
      ean,
      storefront,
      message: { info: "success" | "fail" }
    }
  */

  const success = data.message?.info === "success";

  const added = registerDeleteResult({
    ean: data.ean,
    storefront: data.storefront,
    success,
  });

  if (!added) return;

  updateDeleteSummary(deleteState);
  appendDeleteRow({
    ean: data.ean,
    storefront: data.storefront,
    success,
  });
}

// delete/deleteRenderer.js
export function updateDeleteSummary({ total, success, fail }) {
  document.getElementById("delete-total").textContent = `Total: ${total}`;
  document.getElementById("delete-success").textContent = `✅ ${success}`;
  document.getElementById("delete-fail").textContent = `❌ ${fail}`;
}

export function clearDeleteTable() {
  const tbody = document.querySelector("#delete-table tbody");
  if (tbody) tbody.innerHTML = "";
}

export function appendDeleteRow({ ean, storefront, success }) {
  const tbody = document.querySelector("#delete-table tbody");
  if (!tbody) return;

  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${ean}</td>
    <td>${storefront}</td>
    <td class="${success ? "status-ok" : "status-fail"}">
      ${success ? "Deleted" : "Failed"}
    </td>
  `;

  tbody.appendChild(tr);
}

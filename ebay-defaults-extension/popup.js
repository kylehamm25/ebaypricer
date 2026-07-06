/* ============================================================
   eBay Listing Defaults — Popup Script
   ============================================================ */

const $ = (id) => document.getElementById(id);

/* --- Load defaults from storage into the form --- */
async function loadDefaults() {
    const { defaults } = await chrome.storage.sync.get("defaults");
    const d = defaults || {};
    $("condition").value = d.condition || "Near Mint or better";
    $("descriptionTemplate").value = d.descriptionTemplate ?? "reg";
    $("itemPrice").value = d.itemPrice ?? "";
    $("shippingPolicy").value = d.shippingPolicy || "Free ebay standard";
    $("paymentPolicy").value = d.paymentPolicy || "Immediate payment";
    $("promotedRate").value = d.promotedRate ?? 2;
}

/* --- Save edited defaults --- */
async function saveDefaults() {
    const defaults = {
        condition: $("condition").value.trim(),
        descriptionTemplate: $("descriptionTemplate").value.trim(),
        itemPrice: $("itemPrice").value.trim(),
        shippingPolicy: $("shippingPolicy").value.trim(),
        paymentPolicy: $("paymentPolicy").value.trim(),
        promotedRate: parseFloat($("promotedRate").value) || 2,
    };
    await chrome.storage.sync.set({ defaults });
    $("status").textContent = "Defaults saved.";
    setTimeout(() => ($("status").textContent = ""), 2000);
}

/* --- Send apply message to the active tab's content script --- */
async function applyDefaults() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
        $("status").textContent = "No active tab.";
        return;
    }
    try {
        const resp = await chrome.tabs.sendMessage(tab.id, { action: "applyDefaults" });
        $("status").textContent = resp?.ok ? "Applied!" : (resp?.error || "Sent.");
    } catch (e) {
        $("status").textContent = e.message.includes("Could not establish connection")
            ? "Reload the listing page"
            : e.message;
    }
    setTimeout(() => ($("status").textContent = ""), 2500);
}

/* --- Wire up --- */
document.addEventListener("DOMContentLoaded", () => {
    loadDefaults();
    $("applyBtn").addEventListener("click", applyDefaults);
    $("saveBtn").addEventListener("click", saveDefaults);
});

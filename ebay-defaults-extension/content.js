/* ============================================================
   eBay Listing Defaults — Content Script (v4)
   Unified dropdown strategy: find by label, click trigger, pick option.
   ============================================================ */

const $ = document.querySelector.bind(document);
const $$ = document.querySelectorAll.bind(document);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fire(el, ...types) {
    for (const t of types) el.dispatchEvent(new Event(t, { bubbles: true }));
}

function setNativeValue(el, val) {
    const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement : window.HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, String(val));
}

function setValue(el, val) {
    el.focus();
    setNativeValue(el, val);
    fire(el, "input", "change");
    el.blur();
    fire(el, "blur");
}

function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) &&
        el.getAttribute("aria-hidden") !== "true" &&
        window.getComputedStyle(el).visibility !== "hidden" &&
        window.getComputedStyle(el).display !== "none";
}

function stripSuffix(text) {
    return text.replace(/\s*[\(\[]\s*\d+\s*listings?\s*[\)\]]\s*/gi, "").trim();
}

function textsMatch(optionText, targetText) {
    const a = optionText.trim().toLowerCase();
    const b = targetText.trim().toLowerCase();
    if (a === b) return true;
    if (stripSuffix(a) === b || a === stripSuffix(b)) return true;
    if (a.startsWith(b) || b.startsWith(a)) return true;
    return false;
}

/* ------------------------------------------------------------------ */
/*  findLabelAndControl — resolve a label text to its real DOM control */
/*  Pattern 1: <label for="id"> pointing at a real control id         */
/*  Pattern 2: label id referenced via aria-labelledby on the trigger */
/*  Pattern 3: self-labeled trigger button (Condition, Country, etc.) */
/*  NOTE: unchanged — shared by Shipping/Payment/Country. Card        */
/*  Condition no longer routes through here; see setCondition below.  */
/* ------------------------------------------------------------------ */

function elSummary(el) {
    if (!el) return "null";
    let s = "<" + el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    if (el.className && typeof el.className === "string") s += "." + el.className.trim().split(/\s+/).join(".");
    const t = (el.textContent || "").trim().slice(0, 40);
    if (t) s += ' | "' + t + '"';
    return s + ">";
}

function findLabelAndControl(labelText) {
    const labelEls = $$("label.field_label, label, .field_label");
    for (const el of labelEls) {
        const t = el.textContent.trim().toLowerCase();
        if (t === labelText.toLowerCase() || t.includes(labelText.toLowerCase())) {
            // Pattern 1: <label for="id">
            const forId = el.getAttribute("for");
            if (forId) {
                const ctrl = document.getElementById(forId);
                if (ctrl) {
                    return { label: el, control: ctrl };
                }
            }
            // Pattern 2: label id referenced in aria-labelledby on the trigger
            if (el.id) {
                const ctrl = document.querySelector(`[aria-labelledby~="${el.id}"]`);
                if (ctrl) {
                    return { label: el, control: ctrl };
                }
            }
        }
    }

    // Pattern 3: self-labeled trigger button
    const buttons = $$("button");
    for (const b of buttons) {
        const t = b.textContent.trim().toLowerCase();
        if (t === labelText.toLowerCase() || t.includes(labelText.toLowerCase())) {
            return { label: b, control: b };
        }
    }
    return null;
}

async function setDropdown(labelText, valueText, clickFirst) {
    const found = findLabelAndControl(labelText);
    if (!found) {
        return false;
    }
    let trigger = found.control;

    if (trigger.tagName === "INPUT") {
        trigger.focus();
        fire(trigger, "focus");
        await wait(200);
        const parent = trigger.closest("[class*=combobox]");
        if (parent) console.log(`[eBay] setDropdown "${labelText}": input → closest .combobox ${elSummary(parent)}`);
        trigger = parent || trigger;
    }
    trigger.click();
    await wait(1000);

    const controlsId = trigger.getAttribute && trigger.getAttribute("aria-controls");
    let scope = (controlsId && document.getElementById(controlsId)) || document;
    if (controlsId) console.log(`[eBay] setDropdown "${labelText}": aria-controls="${controlsId}" → scope ${elSummary(scope)}`);
    else console.log(`[eBay] setDropdown "${labelText}": no aria-controls, scope = document`);

    for (let retry = 0; retry < 3; retry++) {
        const all = scope.querySelectorAll(
            '[role="option"], [role="menuitemradio"], [role="menuitem"], .combobox__option, .listbox__option'
        );
        const items = [...all].filter(isVisible);

        // If scoped search found nothing after 2 tries, fall back to document
        if (retry === 2 && scope !== document) {
            scope = document;
        }

        if (clickFirst) {
            const target = items.length ? items : [...all];
            if (target.length) {
                target[0].click(); await wait(300); return true;
            }
        } else {
            for (const item of items) {
                if (textsMatch(item.textContent, valueText)) {
                    item.click();
                    await wait(300);
                    return true;
                }
            }
        }
        await wait(800);
    }
    return false;
}

/* ------------------------------------------------------------------ */
/*  Field setters                                                     */
/* ------------------------------------------------------------------ */

async function setFormat() {
    // Format uses a span with @PRICE in its ID
    const spans = $$('span[id*="@PRICE"]');
    let btn = null;
    for (const s of spans) {
        btn = s.closest("button");
        if (btn) {
            break;
        }
    }
    if (btn) {
        btn.click();
        await wait(1000);
        const controlsId = btn.getAttribute && btn.getAttribute("aria-controls");
        const scope = (controlsId && document.getElementById(controlsId)) || document;
        if (controlsId) console.log(`[eBay] setFormat: aria-controls="${controlsId}" → ${elSummary(scope)}`);
        for (let retry = 0; retry < 2; retry++) {
            const all = scope.querySelectorAll(
                '[role="option"], [role="menuitemradio"], [role="menuitem"], .combobox__option, .listbox__option'
            );
            for (const item of all) {
                if (textsMatch(item.textContent, DEFAULTS.format)) {
                    item.click();
                    return;
                }
            }
            await wait(800);
        }
    }
}

async function setItemPrice() {
    const inp = $(`input[name="price"][aria-label="Item price"]`);
    if (inp && DEFAULTS.itemPrice) {
        setValue(inp, DEFAULTS.itemPrice);
    }
}

/* ------------------------------------------------------------------ */
/*  setCondition — FIXED, self-contained (does not use               */
/*  findLabelAndControl / setDropdown, so Shipping/Payment/Country    */
/*  are completely unaffected by this change).                        */
/*                                                                     */
/*  Root cause: the real "Card Condition" trigger's own visible text  */
/*  is the current/placeholder value (e.g. "Select ungraded           */
/*  condition"), NOT the string "Card Condition" — so matching a      */
/*  button's text against the label text can never find it. Meanwhile*/
/*  the nearby help text "Need help? Take a closer look at card       */
/*  conditions." DOES contain "card condition" as a substring         */
/*  ("conditions" starts with "condition"), so the old text-based     */
/*  fallback was reliably grabbing that link instead.                 */
/*                                                                     */
/*  Fix: locate the "Card Condition" label by exact text, then look   */
/*  for a real trigger only within its own nearby field container     */
/*  (not the whole document), explicitly skipping anything that       */
/*  looks like a help/info link.                                      */
/* ------------------------------------------------------------------ */

async function setCondition() {
    const isHelpish = (el) => {
        const t = el.textContent.trim().toLowerCase();
        const cls = (el.className || "").toString().toLowerCase();
        return t.includes("help") || t.includes("take a closer look") ||
               t.includes("learn more") || t.includes("guide") ||
               cls.includes("infotip") || cls.includes("tooltip");
    };

    // Find the "Card Condition" label by exact text (avoids matching
    // "Condition type" or other nearby, differently-scoped labels).
    const labelCandidates = $$("label.field_label, label, .field_label, span, div");
    let label = null;
    for (const el of labelCandidates) {
        if (el.children.length > 1) continue; // skip big wrapper blocks
        if (el.textContent.trim().toLowerCase() === "card condition") {
            label = el;
            break;
        }
    }
    if (!label) {
        return false;
    }

    // Walk a few ancestors up from the label, looking only within each
    // container's own subtree for a plausible (non-help) trigger.
    let container = label.parentElement;
    let trigger = null;
    for (let i = 0; i < 5 && container && !trigger; i++) {
        const candidates = [...container.querySelectorAll(
            'button, [role="button"], [role="combobox"], input[role="combobox"]'
        )];
        trigger = candidates.find((el) => !isHelpish(el)) || null;
        if (!trigger) container = container.parentElement;
    }

    if (!trigger) {
        return false;
    }

    // If the trigger button already shows a selected condition (not a
    // placeholder like "Select …"), leave it alone.
    const cur = trigger.textContent.trim().toLowerCase();
    if (!cur.includes("select") && !cur.includes("choose")) {
        return true; // already has a selection — do not overwrite
    }

    trigger.click();
    await wait(1000);

    const controlsId = trigger.getAttribute && trigger.getAttribute("aria-controls");
    const scope = (controlsId && document.getElementById(controlsId)) || document;
    if (controlsId) console.log(`[eBay] setCondition: aria-controls="${controlsId}" → ${elSummary(scope)}`);

    for (let retry = 0; retry < 2; retry++) {
        const all = scope.querySelectorAll(
            '[role="option"], [role="menuitemradio"], [role="menuitem"], .combobox__option, .listbox__option'
        );
        const items = [...all].filter(isVisible);
        for (const item of items) {
            if (textsMatch(item.textContent, DEFAULTS.condition)) {
                item.click();
                await wait(300);
                return true;
            }
        }
        await wait(800);
    }
    return false;
}

async function setDescriptionTemplate() {
    if (!DEFAULTS.descriptionTemplate) return false;
    const btns = $$("button");
    let templateBtn = null;
    for (const b of btns) {
        if (b.textContent.trim() === "Custom template") {
            templateBtn = b;
            break;
        }
    }
    if (!templateBtn) {
        return false;
    }
    templateBtn.click();
    await wait(600);
    const links = $$("a.template-name, a.dropdown__option.template-name");
    let regLink = null;
    for (const a of links) {
        if (textsMatch(a.textContent, DEFAULTS.descriptionTemplate)) {
            regLink = a;
            break;
        }
    }
    if (!regLink) {
        return false;
    }
    regLink.click();
    await wait(400);
    for (const item of $$("a[role='menuitem']")) {
        if (item.textContent.trim() === "Insert") {
            item.click();
            await wait(500);
            return true;
        }
    }
    return false;
}

async function setDescription() {
    const editor = $(`div[contenteditable="true"][aria-label="Description"]`);
    if (editor) {
        editor.focus();
        editor.innerHTML = DEFAULTS.description
            .replace(/\n/g, "<br>")
            .replace(/\u2022/g, "&bull;");
        fire(editor, "input", "change");
        editor.blur();
        return;
    }
}

async function setShipping() {
    await setDropdown("Shipping policy", null, true);
}

async function setPayment() {
    await setDropdown("Payment policy", DEFAULTS.paymentPolicy);
}

async function setWeight() {
    const { pounds, ounces } = DEFAULTS.packageWeight;
    const lb = $(`input[name="majorWeight"]`);
    const oz = $(`input[name="minorWeight"]`);
    if (lb) { console.log(`[eBay] setWeight: lb ${elSummary(lb)}`); setValue(lb, pounds); }
    if (oz) { console.log(`[eBay] setWeight: oz ${elSummary(oz)}`); setValue(oz, ounces); }
}

async function setDimensions() {
    const { length: len, width: wid, height: hgt } = DEFAULTS.dimensions;
    const l = $(`input[name="packageLength"]`);
    const w = $(`input[name="packageWidth"]`);
    const h = $(`input[name="packageDepth"]`);
    if (l) { console.log(`[eBay] setDimensions: length ${elSummary(l)}`); setValue(l, len); }
    if (w) { console.log(`[eBay] setDimensions: width ${elSummary(w)}`); setValue(w, wid); }
    if (h) { console.log(`[eBay] setDimensions: height ${elSummary(h)}`); setValue(h, hgt); }
}

async function setCustomLabel() {
    const inp = $(`input[name="customLabel"]`);
    if (inp && DEFAULTS.customLabel) {
        setValue(inp, DEFAULTS.customLabel);
    }
}

async function enableOffers() {
    const cb = $(`input[name="bestOfferEnabled"][role="switch"]`);
    if (cb && !cb.checked) {
        cb.click();
        fire(cb, "change");
        await wait(500);
    }
}

async function setBestOfferAmounts() {
    const priceInput = $(`input[name="price"][aria-label="Item price"]`);
    if (!priceInput) return;
    const price = parseFloat(priceInput.value);
    if (isNaN(price) || price <= 0) return;
    const offerAmount = (price * 0.9).toFixed(2);
    const declineInput = $(`input[name="autoDeclineAmount"]`);
    const acceptInput = $(`input[name="autoAcceptAmount"]`);
    if (declineInput) { console.log(`[eBay] setBestOfferAmounts: decline ${elSummary(declineInput)}`); setValue(declineInput, offerAmount); }
    if (acceptInput) { console.log(`[eBay] setBestOfferAmounts: accept ${elSummary(acceptInput)}`); setValue(acceptInput, offerAmount); }
}

async function setShippingSettings() {
    const editBtn = document.querySelector('button[aria-label="Your settings - edit"]');
    if (!editBtn) return false;

    editBtn.click();
    await wait(1500);

    const modal = document.querySelector('.se-panel-container.details__shipping-settings');
    if (!modal) return false;

    const zipInput = modal.querySelector('input[name="itemLocation"]');
    if (zipInput && DEFAULTS.itemLocationZip) {
        setValue(zipInput, DEFAULTS.itemLocationZip);
        await wait(200);
    }

    const csInput = modal.querySelector('input[name="itemLocationCityState"]');
    if (csInput && DEFAULTS.itemLocationCityState) {
        setValue(csInput, DEFAULTS.itemLocationCityState);
        await wait(200);
    }

    if (DEFAULTS.returnPolicy) {
        const rpInput = modal.querySelector('input[name="returnsPolicyId"]');
        if (rpInput) {
            rpInput.focus();
            fire(rpInput, "focus");
            await wait(200);
            rpInput.click();
            await wait(1000);

            const controlsId = rpInput.getAttribute("aria-controls");
            const listbox = controlsId ? document.getElementById(controlsId) : null;
            const scope = listbox || modal;

            let selected = false;
            for (let retry = 0; retry < 2 && !selected; retry++) {
                const options = scope.querySelectorAll('[role="option"]');
                for (const opt of options) {
                    if (textsMatch(opt.textContent, DEFAULTS.returnPolicy)) {
                        opt.click();
                        await wait(300);
                        selected = true;
                        break;
                    }
                }
                if (!selected) await wait(800);
            }
        }
    }

    const doneBtn = modal.querySelector('.se-panel-container__header-suffix button');
    if (doneBtn) {
        doneBtn.click();
        await wait(500);
        return true;
    }

    return false;
}

async function setPromoted() {
    const wrapper = $(".promoted-listing-program-wrapper");
    if (!wrapper) {
        return;
    }
    const programs = wrapper.querySelectorAll(".fai-program-wrapper");
    let enabled = false;
    for (const prog of programs) {
        const title = prog.querySelector(".fai-program-title");
        if (!title) continue;
        if (title.textContent.trim().toLowerCase() !== "general") continue;
        const sw = prog.querySelector('input[role="switch"]');
        if (sw) console.log(`[eBay] setPromoted: switch ${elSummary(sw)}, checked=${sw.checked}`);
        if (sw && !sw.checked) {
            sw.click();
            fire(sw, "change");
            enabled = true;
        } else if (sw && sw.checked) {
            enabled = true;
        }
        break;
    }
    if (!enabled) {
        return;
    }
    await wait(500);
    const rate = $(`input[name="adRate"]`);
    if (rate) { console.log(`[eBay] setPromoted: rate ${elSummary(rate)}`); setValue(rate, DEFAULTS.promotedRate); }
}

/* ------------------------------------------------------------------ */
/*  Main entry point                                                  */
/* ------------------------------------------------------------------ */

async function applyDefaults() {

    try {
        const { defaults: stored } = await chrome.storage.sync.get("defaults");
        if (stored) {
            if (stored.condition) DEFAULTS.condition = stored.condition;
            if (stored.descriptionTemplate != null) DEFAULTS.descriptionTemplate = stored.descriptionTemplate;
            if (stored.itemPrice != null) DEFAULTS.itemPrice = stored.itemPrice;
            if (stored.shippingPolicy) DEFAULTS.shippingPolicy = stored.shippingPolicy;
            if (stored.paymentPolicy) DEFAULTS.paymentPolicy = stored.paymentPolicy;
            if (stored.promotedRate != null) DEFAULTS.promotedRate = stored.promotedRate;
            if (stored.customLabel != null) DEFAULTS.customLabel = stored.customLabel;
            if (stored.itemLocationZip != null) DEFAULTS.itemLocationZip = stored.itemLocationZip;
            if (stored.itemLocationCityState != null) DEFAULTS.itemLocationCityState = stored.itemLocationCityState;
            if (stored.returnPolicy != null) DEFAULTS.returnPolicy = stored.returnPolicy;
        }
    } catch (_) {}

    const steps = [
        { name: "Format",               fn: setFormat },
        { name: "Condition",            fn: setCondition },
    ];

    if (DEFAULTS.descriptionTemplate) {
        steps.push({ name: "Template", fn: setDescriptionTemplate });
    } else {
        steps.push({ name: "Description", fn: setDescription });
    }

    steps.push(
        { name: "Shipping policy",      fn: setShipping },
        { name: "Shipping settings",    fn: setShippingSettings },
        { name: "Payment policy",       fn: setPayment },
        { name: "Weight",               fn: setWeight },
        { name: "Dimensions",           fn: setDimensions },
        { name: "Offers (enable)",      fn: enableOffers },
        { name: "Promoted & ad rate",   fn: setPromoted },
        { name: "SKU",                  fn: setCustomLabel },
        { name: "Item Price",           fn: setItemPrice },
        { name: "Best Offer Amounts",   fn: setBestOfferAmounts },
    );

    const total = steps.length;
    for (let i = 0; i < total; i++) {
        const step = steps[i];
        setStatus("\u25B6 " + step.name, (i / total) * 100);
        try {
            await step.fn();
            setStatus("\u2713 " + step.name, ((i + 1) / total) * 100);
        } catch (err) {
            setStatus("\u2717 " + step.name + " (" + err.message + ")", ((i + 1) / total) * 100);
        }
        await wait(400);
    }
    setStatus("\u2713 Done", 100);
}

/* ------------------------------------------------------------------ */
/*  Floating panel — button + live status + collapsible settings      */
/* ------------------------------------------------------------------ */

let panel = null;
let statusEl = null;
let progressFill = null;
let formFields = {};

function setStatus(msg, pct) {
    if (statusEl) statusEl.textContent = msg;
    if (progressFill != null && pct != null) {
        progressFill.style.width = Math.round(pct) + "%";
    }
}

let presets = {};

async function loadPresets() {
    const { storedPresets } = await chrome.storage.sync.get("storedPresets");
    presets = storedPresets || PRESETS;
}

async function savePresetsToStorage() {
    await chrome.storage.sync.set({ storedPresets: presets });
}

function makeSettingsRow(label, id, type, placeholder, presetKey) {
    const row = document.createElement("div");
    Object.assign(row.style, { display: "flex", alignItems: "center", gap: "4px" });

    const lbl = document.createElement("label");
    lbl.textContent = label;
    lbl.htmlFor = id;
    Object.assign(lbl.style, { fontSize: "14px", minWidth: "70px", color: "#ccc", flexShrink: "0" });

    const wrap = document.createElement("div");
    Object.assign(wrap.style, { flex: "1", position: "relative" });

    const inp = document.createElement("input");
    inp.id = id;
    inp.type = type;
    if (placeholder) inp.placeholder = placeholder;
    Object.assign(inp.style, {
        width: "100%", padding: "3px 20px 3px 6px", border: "1px solid #0f3460",
        borderRadius: "4px", background: "#16213e", color: "#eee",
        fontSize: "14px", outline: "none", boxSizing: "border-box",
    });

    wrap.appendChild(inp);

    const vals = presetKey ? (presets[presetKey] || []) : [];

    if (vals.length > 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "\u25BE";
        Object.assign(btn.style, {
            position: "absolute", right: "2px", top: "50%", transform: "translateY(-50%)",
            background: "none", border: "none", color: "#888", cursor: "pointer",
            padding: "0 4px", fontSize: "16px", lineHeight: "1",
        });

        const list = document.createElement("div");
        Object.assign(list.style, {
            display: "none", position: "absolute", top: "100%", left: "0", right: "0", zIndex: "10",
            background: "#1a1a2e", border: "1px solid #0f3460", borderRadius: "4px",
            maxHeight: "150px", overflowY: "auto", marginTop: "2px",
        });

        function buildList() {
            list.innerHTML = "";
            for (const v of vals) {
                const opt = document.createElement("div");
                opt.textContent = v;
                Object.assign(opt.style, {
                    padding: "4px 8px", cursor: "pointer", fontSize: "14px", color: "#ddd",
                });
                opt.onmouseenter = () => { opt.style.background = "#0f3460"; };
                opt.onmouseleave = () => { opt.style.background = "none"; };
                opt.onclick = () => {
                    inp.value = v;
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    list.style.display = "none";
                };
                list.appendChild(opt);
            }
        }
        buildList();

        btn.onclick = (e) => {
            e.stopPropagation();
            buildList();
            list.style.display = list.style.display === "none" ? "block" : "none";
        };

        document.addEventListener("click", (e) => {
            if (!wrap.contains(e.target)) list.style.display = "none";
        });

        wrap.appendChild(btn);
        wrap.appendChild(list);
    }

    row.appendChild(lbl);
    row.appendChild(wrap);
    return row;
}

async function loadSettingsIntoForm() {
    const { defaults } = await chrome.storage.sync.get("defaults");
    const d = defaults || {};
    formFields.condition.value = d.condition || "Near Mint or better";
    formFields.descTmpl.value = d.descriptionTemplate ?? "reg";
    formFields.customLabel.value = d.customLabel ?? "";
    formFields.itemPrice.value = d.itemPrice ?? "";
    formFields.shippingPolicy.value = d.shippingPolicy || "Free ebay standard";
    formFields.paymentPolicy.value = d.paymentPolicy || "Immediate payment";
    formFields.promotedRate.value = d.promotedRate ?? 2;
    formFields.itemLocationZip.value = d.itemLocationZip ?? "";
    formFields.itemLocationCityState.value = d.itemLocationCityState ?? "";
    formFields.returnPolicy.value = d.returnPolicy ?? "No Return Accepted";
}

async function saveSettings() {
    await chrome.storage.sync.set({
        defaults: {
            condition: formFields.condition.value.trim(),
            descriptionTemplate: formFields.descTmpl.value.trim(),
            customLabel: formFields.customLabel.value.trim(),
            itemPrice: formFields.itemPrice.value.trim(),
            shippingPolicy: formFields.shippingPolicy.value.trim(),
            paymentPolicy: formFields.paymentPolicy.value.trim(),
            promotedRate: parseFloat(formFields.promotedRate.value) || 2,
            itemLocationZip: formFields.itemLocationZip.value.trim(),
            itemLocationCityState: formFields.itemLocationCityState.value.trim(),
            returnPolicy: formFields.returnPolicy.value.trim(),
        },
    });
}

function makePresetEditor() {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Edit presets";
    Object.assign(summary.style, {
        cursor: "pointer", fontSize: "14px", color: "#999",
        padding: "6px 0 2px", userSelect: "none",
    });
    details.appendChild(summary);

    const container = document.createElement("div");
    Object.assign(container.style, { display: "flex", flexDirection: "column", gap: "4px" });

    const editorFields = [
        ["Condition", "condition"],
        ["Template", "descTmpl"],
        ["SKU", "customLabel"],
        ["Shipping", "shippingPolicy"],
        ["Payment", "paymentPolicy"],
    ];

    const textareas = {};
    const baseTA = (label, key) => {
        const lbl = document.createElement("label");
        lbl.textContent = label;
        Object.assign(lbl.style, { fontSize: "13px", color: "#888", marginTop: "2px" });
        const ta = document.createElement("textarea");
        ta.rows = 3;
        Object.assign(ta.style, {
            width: "100%", padding: "4px 6px", border: "1px solid #0f3460",
            borderRadius: "4px", background: "#16213e", color: "#eee",
            fontSize: "13px", fontFamily: "monospace", resize: "vertical",
            outline: "none", boxSizing: "border-box",
        });
        container.appendChild(lbl);
        container.appendChild(ta);
        textareas[key] = ta;
    };

    editorFields.forEach(([label, key]) => baseTA(label, key));

    const btnRow = document.createElement("div");
    Object.assign(btnRow.style, { display: "flex", gap: "6px", marginTop: "2px" });

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Save presets";
    Object.assign(saveBtn.style, {
        padding: "4px 10px", background: "#0f3460", color: "white",
        border: "none", borderRadius: "4px", cursor: "pointer",
        fontWeight: "600", fontSize: "13px",
    });

    const status = document.createElement("span");
    Object.assign(status.style, { fontSize: "13px", color: "#4ade80" });

    btnRow.appendChild(saveBtn);
    btnRow.appendChild(status);
    container.appendChild(btnRow);
    details.appendChild(container);

    function loadTAs() {
        for (const [label, key] of editorFields) {
            textareas[key].value = (presets[key] || []).join("\n");
        }
    }
    loadTAs();

    saveBtn.onclick = async () => {
        for (const [label, key] of editorFields) {
            presets[key] = textareas[key].value.split("\n").map((s) => s.trim()).filter(Boolean);
        }
        await savePresetsToStorage();
        status.textContent = "Saved.";
        setTimeout(() => { status.textContent = ""; }, 2000);
    };

    return details;
}

function createPanel() {
    if (document.getElementById("ebay-dflt-panel")) return;

    const panelStyle = {
        position: "fixed", top: "16px", right: "16px", zIndex: "999999",
        display: "flex", flexDirection: "column", gap: "6px",
        padding: "14px 18px", background: "#1a1a2e", color: "#eee",
        borderRadius: "10px", font: "15px/1.5 Segoe UI,Helvetica,Arial,sans-serif",
        boxShadow: "0 4px 16px rgba(0,0,0,.4)", minWidth: "320px",
        maxWidth: "420px", maxHeight: "90vh", overflowY: "auto",
    };

    panel = Object.assign(document.createElement("div"), { id: "ebay-dflt-panel" });
    Object.assign(panel.style, panelStyle);

    const btn = document.createElement("button");
    btn.textContent = "Apply Defaults";
    Object.assign(btn.style, {
        padding: "8px 16px", background: "#3665f3", color: "white",
        border: "none", borderRadius: "6px", cursor: "pointer",
        fontWeight: "600", fontSize: "15px",
    });
    btn.onclick = () => {
        setStatus("", 0);
        applyDefaults();
    };

    const statusContainer = document.createElement("div");
    Object.assign(statusContainer.style, { marginTop: "2px" });

    statusEl = document.createElement("div");
    Object.assign(statusEl.style, {
        fontSize: "14px", color: "#e94560", minHeight: "18px", padding: "0",
    });

    const track = document.createElement("div");
    Object.assign(track.style, {
        width: "100%", height: "4px", background: "#0f3460",
        borderRadius: "2px", overflow: "hidden", marginTop: "4px",
    });
    progressFill = document.createElement("div");
    Object.assign(progressFill.style, {
        width: "0%", height: "100%", background: "#4ade80",
        borderRadius: "2px", transition: "width 0.3s ease",
    });
    track.appendChild(progressFill);
    statusContainer.appendChild(statusEl);
    statusContainer.appendChild(track);

    const fieldsContainer = document.createElement("div");
    Object.assign(fieldsContainer.style, {
        display: "flex", flexDirection: "column", gap: "5px", paddingTop: "4px",
    });

    // [label, id, type, placeholder, presetKey]
    const fields = [
        ["Condition", "ebay-dflt-condition", "text", "", "condition"],
        ["Price ($)", "ebay-dflt-price", "text"],
        ["SKU", "ebay-dflt-sku", "text", "", "customLabel"],
        ["Desc.", "ebay-dflt-tmpl", "text", "reg", "descTmpl"],
        ["Shipping", "ebay-dflt-shipping", "text", "", "shippingPolicy"],
        ["Payment", "ebay-dflt-payment", "text", "", "paymentPolicy"],
        ["Rate (%)", "ebay-dflt-rate", "text"],
        ["ZIP", "ebay-dflt-zip", "text"],
        ["City,St", "ebay-dflt-citystate", "text"],
        ["Returns", "ebay-dflt-returns", "text"],
    ];

    formFields = {
        condition: null, descTmpl: null, customLabel: null,
        itemPrice: null, shippingPolicy: null, paymentPolicy: null,
        promotedRate: null,
        itemLocationZip: null, itemLocationCityState: null, returnPolicy: null,
    };

    const idMap = [
        "condition", "itemPrice", "customLabel", "descTmpl",
        "shippingPolicy", "paymentPolicy", "promotedRate",
        "itemLocationZip", "itemLocationCityState", "returnPolicy",
    ];

    fields.forEach(([label, id, type, placeholder, presetKey], i) => {
        const row = makeSettingsRow(label, id, type, placeholder, presetKey);
        fieldsContainer.appendChild(row);
        const inp = row.querySelector("input");
        formFields[idMap[i]] = inp;
        inp.oninput = saveSettings;
    });

    panel.appendChild(btn);
    panel.appendChild(statusContainer);
    panel.appendChild(fieldsContainer);
    panel.appendChild(makePresetEditor());
    document.body.appendChild(panel);

    loadSettingsIntoForm();
}

loadPresets().then(() => {
    if (location.href.includes("/lstng") || location.href.includes("mode=AddItem") || location.href.includes("mode=Revise")) {
        if (document.body) {
            createPanel();
        } else {
            document.addEventListener("DOMContentLoaded", createPanel);
        }
    }
});

/* ------------------------------------------------------------------ */
/*  Message listener                                                  */
/* ------------------------------------------------------------------ */

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "applyDefaults") {
        applyDefaults()
            .then(() => sendResponse({ ok: true }))
            .catch((err) => sendResponse({ ok: false, error: err.message }));
        return true;
    }
});

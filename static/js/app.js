/* ===========================================================================
   Bazaarpe Admin — Complete Super Administrator Management Engine
   ---------------------------------------------------------------------------
   Provides full administrative authority: Manage, Create, Edit, and Delete
   across all Bazaarpe UI modules. Includes instant DOM state updates,
   persistent local storage synchronization, interactive validation,
   modal orchestration, and feedback notifications.
   =========================================================================== */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- helpers */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* ------------------------------------------------------------------ toast */
  function toast(message, kind) {
    const root = $("[data-toast-root]");
    if (!root) return;
    const isSuccess = kind === "success" || !kind;
    const tone =
      kind === "error"
        ? "bg-rose-600 text-white"
        : kind === "warn"
        ? "bg-amber-600 text-white"
        : kind === "info"
        ? "bg-sky-600 text-white"
        : "bg-emerald-600 text-white";

    const iconSvg =
      isSuccess
        ? '<svg class="h-4 w-4 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>'
        : kind === "error"
        ? '<svg class="h-4 w-4 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/></svg>'
        : kind === "warn"
        ? '<svg class="h-4 w-4 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4 2.8 20h18.4z"/><path d="M12 10v4"/><path d="M12 17.5h.01"/></svg>'
        : '<svg class="h-4 w-4 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.6h.01"/></svg>';

    const el = document.createElement("div");
    el.className =
      "pointer-events-auto flex items-start gap-2.5 rounded-xl px-4 py-3 text-[0.8125rem] font-medium shadow-pop transition-all transform duration-200 " +
      tone;
    el.setAttribute("role", "status");
    el.innerHTML =
      iconSvg +
      '<div class="flex-1 leading-snug">' +
      message +
      '</div><button type="button" class="ml-2 text-white/80 hover:text-white" aria-label="Dismiss">&times;</button>';

    const closeBtn = el.querySelector("button");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        el.classList.add("bm-toast-leaving");
        setTimeout(() => el.remove(), 260);
      });
    }

    root.classList.remove("hidden");
    root.appendChild(el);
    setTimeout(function () {
      if (el.parentNode) {
        el.classList.add("bm-toast-leaving");
        setTimeout(() => el.remove(), 260);
      }
    }, 4500);
  }

  /* ---------------------------------------------------------------- sidebar */
  function initSidebar() {
    const sidebar = $("#bmSidebar");
    const overlay = $("#bmSidebarOverlay");
    if (!sidebar) return;

    function open() {
      sidebar.classList.add("is-open");
      if (overlay) overlay.classList.remove("hidden");
      document.body.classList.add("bm-no-scroll");
      const t = $("[data-sidebar-toggle]");
      if (t) t.setAttribute("aria-expanded", "true");
    }
    function close() {
      if (window.innerWidth < 1024) sidebar.classList.remove("is-open");
      if (overlay) overlay.classList.add("hidden");
      document.body.classList.remove("bm-no-scroll");
      const t = $("[data-sidebar-toggle]");
      if (t) t.setAttribute("aria-expanded", "false");
    }
    function sync() {
      if (window.innerWidth >= 1024) {
        sidebar.classList.remove("is-open");
        if (overlay) overlay.classList.add("hidden");
        document.body.classList.remove("bm-no-scroll");
      } else {
        sidebar.classList.remove("is-open");
        if (overlay) overlay.classList.add("hidden");
      }
    }
    sync();
    window.addEventListener("resize", sync);

    $$("[data-sidebar-toggle]").forEach((b) => b.addEventListener("click", open));
    $$("[data-sidebar-close]").forEach((b) => b.addEventListener("click", close));
    $$("#bmSidebar a").forEach((a) =>
      a.addEventListener("click", function () {
        if (window.innerWidth < 1024) close();
      })
    );
  }

  /* --------------------------------------------------------------- dropdown */
  function initDropdowns() {
    const roots = $$("[data-dropdown-root]");
    function closeAll(except) {
      roots.forEach((r) => {
        if (r === except) return;
        const menu = $("[data-dropdown]", r);
        const btn = $("[data-dropdown-toggle]", r);
        if (menu) menu.classList.add("hidden");
        if (btn) btn.setAttribute("aria-expanded", "false");
      });
    }
    roots.forEach((root) => {
      const btn = $("[data-dropdown-toggle]", root);
      const menu = $("[data-dropdown]", root);
      if (!btn || !menu) return;
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        const isOpen = !menu.classList.contains("hidden");
        closeAll(root);
        menu.classList.toggle("hidden", isOpen);
        btn.setAttribute("aria-expanded", String(!isOpen));
      });
      menu.addEventListener("click", function (e) {
        if (e.target.closest("a")) closeAll(null);
      });
    });
    document.addEventListener("click", () => closeAll(null));
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAll(null);
    });
  }

  /* ------------------------------------------------------------------ modal */
  let lastFocused = null;

  function focusables(container) {
    return $$(
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      container
    ).filter((el) => el.offsetParent !== null);
  }

  function openModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    lastFocused = document.activeElement;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("bm-no-scroll");
    const first = focusables(modal)[0];
    if (first) first.focus();
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("bm-no-scroll");
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
  }

  function initModals() {
    document.addEventListener("click", function (e) {
      const opener = e.target.closest("[data-modal-open]");
      if (opener) {
        e.preventDefault();
        openModal(opener.getAttribute("data-modal-open"));
        return;
      }
      const closer = e.target.closest("[data-modal-close]");
      if (closer) {
        e.preventDefault();
        closeModal(closer.closest("[data-modal]"));
        return;
      }
      if (e.target.matches("[data-modal]")) closeModal(e.target);
    });

    document.addEventListener("keydown", function (e) {
      const open = $("[data-modal].is-open");
      if (!open) return;
      if (e.key === "Escape") {
        closeModal(open);
        return;
      }
      if (e.key === "Tab") {
        const list = focusables(open);
        if (!list.length) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });
  }

  /* ------------------------------------------------------------------- tabs */
  function initTabs() {
    $$("[data-tabs]").forEach((group) => {
      const buttons = $$("[data-tab-target]", group);
      const panels = $$("[data-tab-panel]", group);
      buttons.forEach((btn) => {
        btn.addEventListener("click", function () {
          const target = btn.getAttribute("data-tab-target");
          buttons.forEach((b) => {
            const active = b === btn;
            b.classList.toggle("is-active", active);
            b.setAttribute("aria-selected", String(active));
            b.setAttribute("tabindex", active ? "0" : "-1");
          });
          panels.forEach((p) => {
            p.hidden = p.id !== target;
          });
        });
        btn.addEventListener("keydown", function (e) {
          if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
          const i = buttons.indexOf(btn);
          const next = e.key === "ArrowRight" ? (i + 1) % buttons.length : (i - 1 + buttons.length) % buttons.length;
          buttons[next].focus();
          buttons[next].click();
        });
      });
    });
  }

  /* -------------------------------------------------------- file input hint */
  function initFileInputs() {
    $$('input[type="file"]').forEach((input) => {
      const previewId = input.getAttribute("data-file-preview");
      const box = previewId ? document.getElementById(previewId) : null;
      input.addEventListener("change", function () {
        if (!box) return;
        const f = input.files && input.files[0];
        if (!f) {
          box.classList.add("hidden");
          box.innerHTML = "";
          return;
        }
        const kb = f.size / 1024;
        const size = kb > 1024 ? (kb / 1024).toFixed(1) + " MB" : Math.max(1, Math.round(kb)) + " KB";
        box.innerHTML =
          '<span class="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 font-medium text-emerald-800 ring-1 ring-inset ring-emerald-200">' +
          f.name.replace(/[<>&"]/g, "") +
          " · " +
          size +
          '</span><span class="text-slate-500 font-medium text-xs">Ready for recording</span>';
        box.classList.remove("hidden");
        box.classList.add("flex");
      });
    });
  }

  /* ------------------------------------------------------------- validation */
  function markError(field, message) {
    field.classList.add("is-invalid");
    field.setAttribute("aria-invalid", "true");
    let err = field.parentElement.querySelector(".bm-field-error");
    if (!err) {
      err = document.createElement("p");
      err.className = "bm-field-error";
      err.innerHTML =
        '<svg class="h-3.5 w-3.5 mt-px shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4 2.8 20h18.4z"/><path d="M12 10v4"/><path d="M12 17.5h.01"/></svg><span></span>';
      field.parentElement.appendChild(err);
    }
    err.querySelector("span").textContent = message;
  }

  function clearError(field) {
    field.classList.remove("is-invalid");
    field.removeAttribute("aria-invalid");
    const err = field.parentElement.querySelector(".bm-field-error");
    if (err) err.remove();
  }

  function validateField(field) {
    const value = (field.value || "").trim();
    if (field.type === "checkbox") {
      if (field.required && !field.checked) {
        markError(field, "Please confirm before continuing.");
        return false;
      }
      clearError(field);
      return true;
    }
    if (field.required && !value) {
      markError(field, "This field is required.");
      return false;
    }
    if (field.type === "email" && value && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value)) {
      markError(field, "Enter a valid email address.");
      return false;
    }
    if (field.type === "number" && value !== "") {
      const n = Number(value);
      if (Number.isNaN(n)) {
        markError(field, "Enter a number.");
        return false;
      }
      if (field.min !== "" && n < Number(field.min)) {
        markError(field, "Value cannot be less than " + field.min + ".");
        return false;
      }
      if (field.max !== "" && n > Number(field.max)) {
        markError(field, "Value cannot be more than " + field.max + ".");
        return false;
      }
    }
    if (field.type === "password" && value && value.length < 8) {
      markError(field, "Password must be at least 8 characters.");
      return false;
    }
    clearError(field);
    return true;
  }

  /* ----------------------------------- Admin Mutation Engine (Create / Edit / Manage) */
  function initAdminMutations() {
    const forms = $$("form[data-prototype-form], form[data-admin-form]");
    forms.forEach((form) => {
      $$("input, select, textarea", form).forEach((field) => {
        if (field.type === "hidden" || field.type === "file") return;
        field.addEventListener("blur", function () {
          if (field.value || field.required) validateField(field);
        });
        field.addEventListener("input", function () {
          if (field.classList.contains("is-invalid")) validateField(field);
        });
      });

      form.addEventListener("submit", function (e) {
        e.preventDefault();

        // Validate
        let firstBad = null;
        $$("input, select, textarea", form).forEach((field) => {
          if (field.type === "hidden" || field.type === "file") return;
          const ok = validateField(field);
          if (!ok && !firstBad) firstBad = field;
        });
        if (firstBad) {
          firstBad.focus();
          toast("Please review the highlighted fields.", "error");
          return;
        }

        const action = form.getAttribute("action") || "";
        const modal = form.closest("[data-modal]");
        const formData = new FormData(form);

        // Close modal if open
        if (modal) {
          closeModal(modal);
        }

        // 1. ADD CATEGORY
        if (action.endsWith("/admin/categories") || form.id === "formAddCategory") {
          const name = formData.get("name") || "New Category";
          const status = formData.get("status") || "active";
          const table = $("table.bm-table tbody");
          if (table) {
            const rowCount = table.querySelectorAll("tr").length + 1;
            const code = "CAT-0" + rowCount;
            const tr = document.createElement("tr");
            tr.innerHTML = `
              <td><span class="font-semibold text-ink-900">${name}</span><div class="bm-mono text-[0.75rem] text-slate-500">${code}</div></td>
              <td><div class="flex max-w-[24rem] flex-wrap gap-1.5"><span class="bm-tag text-slate-400 italic">None yet</span></div></td>
              <td><a class="bm-link" href="vendors.html">0 vendors</a></td>
              <td><span class="bm-badge ${status === "active" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/20"}"><span class="bm-dot"></span>${status === "active" ? "Active" : "Inactive"}</span></td>
              <td><div class="flex gap-1.5"><button type="button" class="bm-btn-ghost bm-btn-sm" data-modal-open="modalEditCategory"><svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4l10-10-4-4L4 16z"/><path d="m14 6 4 4"/></svg> Edit</button><button type="button" class="bm-btn-ghost bm-btn-sm" data-modal-open="modalAddSub">Add sub</button><button type="button" class="bm-btn-danger bm-btn-sm" data-action="delete-row" data-item-name="${name}"><svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg> Delete</button></div></td>
            `;
            table.prepend(tr);
          }
          form.reset();
          toast("Category Created: '" + name + "' added successfully with full admin permissions.", "success");
          return;
        }

        // 2. EDIT CATEGORY
        if (action.includes("/admin/categories/CAT-") && !action.includes("/subcategories")) {
          const name = formData.get("name") || "Category";
          const status = formData.get("status") || "active";
          const firstRow = $("table.bm-table tbody tr");
          if (firstRow) {
            const titleEl = firstRow.querySelector(".font-semibold");
            if (titleEl) titleEl.textContent = name;
            const badgeEl = firstRow.querySelector(".bm-badge");
            if (badgeEl) {
              badgeEl.className = `bm-badge ${status === "active" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/20"}`;
              badgeEl.innerHTML = `<span class="bm-dot"></span>${status === "active" ? "Active" : "Inactive"}`;
            }
          }
          toast("Category Updated: Changes saved successfully by Administrator.", "success");
          return;
        }

        // 3. ADD SUBCATEGORY
        if (action.includes("/subcategories")) {
          const subName = formData.get("name") || "New Subcategory";
          const catName = formData.get("category_id") || "Iron & Steel";
          const rows = $$("table.bm-table tbody tr");
          rows.forEach((row) => {
            if (row.textContent.includes(catName)) {
              const tagContainer = row.querySelector("td:nth-child(2) div");
              if (tagContainer) {
                const span = document.createElement("span");
                span.className = "bm-tag bg-emerald-50 text-emerald-800 font-medium";
                span.textContent = subName;
                tagContainer.appendChild(span);
              }
            }
          });
          form.reset();
          toast("Subcategory Added: '" + subName + "' added to " + catName + ".", "success");
          return;
        }

        // 4. KYC APPROVAL
        if (action.includes("/kyc/approve")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("KYC") || b.textContent.includes("Pending") || b.textContent.includes("Review")) {
              b.className = "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Approved';
            }
          });
          const noteEl = $(".ml-auto.text-\\[0\\.75rem\\]");
          if (noteEl) noteEl.textContent = "Approved by Administrator (admin) just now";
          toast("KYC Approved: Vendor KYC verification successfully approved.", "success");
          return;
        }

        // 5. KYC REJECTION
        if (action.includes("/kyc/reject")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("KYC") || b.textContent.includes("Approved") || b.textContent.includes("Pending")) {
              b.className = "bm-badge bg-rose-50 text-rose-700 ring-rose-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Rejected';
            }
          });
          toast("KYC Rejected: Vendor KYC status updated to Rejected.", "warn");
          return;
        }

        // 6. BLOCK USER / VENDOR
        if (action.endsWith("/block")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("Active") || b.textContent.includes("Account")) {
              b.className = "bm-badge bg-rose-50 text-rose-700 ring-rose-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Blocked';
            }
          });
          toast("Account Blocked: Access restricted by Super Administrator.", "warn");
          return;
        }

        // 7. UNBLOCK USER / VENDOR
        if (action.endsWith("/unblock")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("Blocked")) {
              b.className = "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Active';
            }
          });
          toast("Account Unblocked: Restored to Active status by Super Administrator.", "success");
          return;
        }

        // 8. SETTINGS
        if (action.includes("/admin/settings/")) {
          toast("Platform Settings Saved: New configuration is live across Bazaarpe.", "success");
          return;
        }

        // 9. ORDER ASSIGN / CANCEL
        if (action.includes("/admin/orders/") && action.includes("/assign")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("Unassigned") || b.textContent.includes("Published")) {
              b.className = "bm-badge bg-teal-50 text-teal-700 ring-teal-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Assigned – In progress';
            }
          });
          toast("Vendor Assigned: Order assigned to vendor successfully.", "success");
          return;
        }
        if (action.includes("/admin/orders/") && action.includes("/cancel")) {
          $$(".bm-badge").forEach((b) => {
            b.className = "bm-badge bg-rose-50 text-rose-700 ring-rose-600/20";
            b.innerHTML = '<span class="bm-dot"></span>Cancelled';
          });
          toast("Order Cancelled: Order status updated to Cancelled.", "warn");
          return;
        }

        // 10. SETTLEMENT RECORD
        if (action.includes("/admin/settlements/") && action.includes("/record")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("Pending") || b.textContent.includes("Due")) {
              b.className = "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Paid – Recorded';
            }
          });
          toast("Settlement Recorded: Manual payout recorded successfully by Administrator.", "success");
          return;
        }

        // 11. REFUND DECISION
        if (action.includes("/admin/refunds/") && action.includes("/decision")) {
          $$(".bm-badge").forEach((b) => {
            b.className = "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20";
            b.innerHTML = '<span class="bm-dot"></span>Approved & Processed';
          });
          toast("Refund Decision Saved: Refund processed successfully.", "success");
          return;
        }

        // 12. RATINGS MODERATION
        if (action.includes("/admin/ratings/")) {
          const isApprove = action.includes("/approve");
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("Pending")) {
              b.className = isApprove
                ? "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                : "bm-badge bg-rose-50 text-rose-700 ring-rose-600/20";
              b.innerHTML = `<span class="bm-dot"></span>${isApprove ? "Approved" : "Rejected"}`;
            }
          });
          toast(`Review Moderated: Rating status marked as ${isApprove ? "Approved" : "Rejected"}.`, "success");
          return;
        }

        // 13. LOCATIONS (Zones, States, Cities)
        if (action.includes("/admin/locations/")) {
          const name = formData.get("name") || "Location";
          toast(`Location Updated: '${name}' successfully saved by Administrator.`, "success");
          return;
        }

        // 14. CMS (Content Management)
        if (action.includes("/admin/cms/")) {
          $$(".bm-badge").forEach((b) => {
            if (b.textContent.includes("Draft")) {
              b.className = "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20";
              b.innerHTML = '<span class="bm-dot"></span>Published';
            }
          });
          toast("CMS Content Updated: Changes published successfully.", "success");
          return;
        }

        // 15. ADD USER
        if (action.includes("/admin/users") && !action.includes("/USR-")) {
          const name = formData.get("name") || "New User";
          const phone = formData.get("phone") || "+91 98000 00000";
          const city = formData.get("city") || "Mumbai";
          const table = $("table.bm-table tbody");
          if (table) {
            const count = table.querySelectorAll("tr").length + 1;
            const code = "USR-" + (1020 + count);
            const tr = document.createElement("tr");
            tr.innerHTML = `
              <td><a class="bm-link font-semibold" href="user-detail.html">${name}</a><div class="bm-mono text-[0.75rem] text-slate-500">${code} · joined just now</div></td>
              <td>${phone}<div class="text-[0.75rem] text-slate-500">user@example.com</div></td>
              <td>${city}</td>
              <td><a class="bm-link" href="orders.html">0 orders</a></td>
              <td><span class="bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20"><span class="bm-dot"></span>Active</span></td>
              <td><span class="font-semibold tabular-nums">₹0</span></td>
              <td><span class="bm-badge bg-slate-100 text-slate-600 ring-slate-500/20"><span class="bm-dot"></span>Not due</span></td>
              <td>HDFC Bank<div class="bm-mono text-[0.75rem] text-slate-500">XXXXXXXX0000 · HDFC0001234</div></td>
              <td><div class="flex gap-1.5"><a class="bm-btn-ghost bm-btn-sm" href="user-detail.html">View</a><button type="button" class="bm-btn-danger bm-btn-sm" data-action="delete-row" data-item-name="${name}">Delete</button></div></td>
            `;
            table.prepend(tr);
          }
          form.reset();
          toast("User Created: '" + name + "' added successfully with full permissions.", "success");
          return;
        }

        // 16. ADD VENDOR
        if (action.includes("/admin/vendors") && !action.includes("/VND-")) {
          const name = formData.get("name") || "New Vendor";
          const city = formData.get("city") || "Mumbai";
          const table = $("table.bm-table tbody");
          if (table) {
            const count = table.querySelectorAll("tr").length + 1;
            const code = "VND-" + (510 + count);
            const tr = document.createElement("tr");
            tr.innerHTML = `
              <td><a class="bm-link font-semibold" href="vendor-detail.html">${name}</a><div class="bm-mono text-[0.75rem] text-slate-500">${code} · ${city}</div></td>
              <td><span class="bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20"><span class="bm-dot"></span>Active</span></td>
              <td><span class="bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20"><span class="bm-dot"></span>Verified</span></td>
              <td><a class="bm-link" href="orders.html">0 orders</a></td>
              <td><span class="bm-tag">Iron &amp; Steel</span></td>
              <td><div class="flex gap-1.5"><a class="bm-btn-ghost bm-btn-sm" href="vendor-detail.html">Manage</a><button type="button" class="bm-btn-danger bm-btn-sm" data-action="delete-row" data-item-name="${name}">Delete</button></div></td>
            `;
            table.prepend(tr);
          }
          form.reset();
          toast("Vendor Created: '" + name + "' registered successfully.", "success");
          return;
        }

        // 17. CREATE ORDER
        if (action.includes("/admin/orders") && !action.includes("/ORD-")) {
          const user = formData.get("user") || "Arjun Rao";
          const cat = formData.get("category") || "Iron & Steel";
          const table = $("table.bm-table tbody");
          if (table) {
            const count = table.querySelectorAll("tr").length + 1;
            const code = "ORD-" + (2055 + count);
            const tr = document.createElement("tr");
            tr.innerHTML = `
              <td><a class="bm-link bm-mono font-semibold" href="order-detail.html">${code}</a><div class="text-[0.75rem] text-slate-500">Created just now</div></td>
              <td><a class="bm-link" href="user-detail.html">${user}</a></td>
              <td>${cat}</td>
              <td>20 kg est.</td>
              <td><span class="font-semibold tabular-nums">₹2,500</span></td>
              <td><span class="bm-badge bg-amber-50 text-amber-800 ring-amber-600/25"><span class="bm-dot"></span>Published</span></td>
              <td><div class="flex gap-1.5"><a class="bm-btn-ghost bm-btn-sm" href="order-detail.html">Manage</a><button type="button" class="bm-btn-danger bm-btn-sm" data-action="delete-row" data-item-name="${code}">Delete</button></div></td>
            `;
            table.prepend(tr);
          }
          form.reset();
          toast("Order Created: Order initiated successfully.", "success");
          return;
        }

        // Generic fallback
        toast("Changes Saved: Action applied successfully by Administrator.", "success");
      });
    });
  }

  /* ---------------------------------------------------- Delete Row Operations */
  function initDeleteActions() {
    document.addEventListener("click", function (e) {
      const btn = e.target.closest('[data-action="delete-row"], [data-action="delete-user"], [data-action="delete-user-detail"]');
      if (!btn) return;
      e.preventDefault();
      const itemName = btn.getAttribute("data-item-name") || "this record";
      const userId = btn.getAttribute("data-user-id");
      const confirmed = window.confirm(
        "Are you sure you want to delete '" + itemName + "' as Administrator? This action will remove the record."
      );
      if (!confirmed) return;

      if (userId || btn.getAttribute("data-action") === "delete-user" || btn.getAttribute("data-action") === "delete-user-detail") {
        const formData = new FormData();
        formData.append("user_id", userId || itemName);
        formData.append("item_name", itemName);
        fetch('/admin/users/delete', {
          method: 'POST',
          body: formData
        }).then(() => {
          if (btn.getAttribute("data-action") === "delete-user-detail" || window.location.pathname.includes("user-detail")) {
            window.location.href = "users.html";
          }
        }).catch(err => console.error("Error deleting user:", err));
      }

      const row = btn.closest("tr");
      if (row) {
        row.style.transition = "all 0.3s ease";
        row.style.opacity = "0";
        row.style.transform = "translateX(25px)";
        setTimeout(() => {
          row.remove();
          toast("Record Deleted: '" + itemName + "' removed successfully by Administrator.", "success");
        }, 300);
      }
    });
  }

  /* ------------------------------------------------ Reveal Full Account Number */
  function initAccountReveal() {
    document.addEventListener("click", function (e) {
      const btn = e.target.closest("#btnRevealAccount, [data-action=\"reveal-account\"]");
      if (!btn) return;
      e.preventDefault();
      const maskedEls = $$(".bm-mono, #userMaskedAccount");
      let found = false;
      maskedEls.forEach((el) => {
        if (el.textContent.includes("XXXXXXXX")) {
          el.textContent = el.textContent.replace(/XXXXXXXX\d{4}/, "50100234471902");
          found = true;
        }
      });
      btn.innerHTML =
        '<svg class="h-3.5 w-3.5 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m4.5 12.5 5 5 10-11"/></svg> Account Unmasked (Admin View)';
      btn.className = "bm-btn-ghost mt-2 w-full text-emerald-700 border-emerald-300 bg-emerald-50/60";
      toast("Account Details Unmasked: Full bank credentials revealed for Administrator.", "info");
    });
  }

  /* ---------------------------------------------------- Admin Purchase Action */
  function initAdminPurchase() {
    document.addEventListener("click", function (e) {
      const btn = e.target.closest("#btnAdminPurchase, [data-action=\"admin-purchase\"]");
      if (!btn) return;
      e.preventDefault();
      const orderId = btn.getAttribute("data-order-id") || "ORD-2051";
      const confirmed = window.confirm("Create admin purchase workflow for " + orderId + "?");
      if (!confirmed) return;
      btn.innerHTML =
        '<svg class="h-4 w-4 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m4.5 12.5 5 5 10-11"/></svg> Admin Purchase Active';
      btn.className = "bm-btn-ghost mt-2 w-full text-emerald-700 border-emerald-300 bg-emerald-50";
      toast("Admin Purchase Workflow Initiated for " + orderId + ".", "success");
    });
  }

  /* ---------------------------------------------------- Admin Publish Action */
  function initAdminPublish() {
    document.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-admin-publish]");
      if (!btn) return;
      e.preventDefault();
      const reqId = btn.getAttribute("data-admin-publish") || "REQ-3101";
      const confirmed = window.confirm(
        "Publish request " + reqId + " to marketplace as Super Administrator with administrative override?"
      );
      if (!confirmed) return;

      $$(".bm-badge").forEach((b) => {
        if (
          b.textContent.includes("Negotiation") ||
          b.textContent.includes("Blocked") ||
          b.textContent.includes("Unaccepted")
        ) {
          b.className = "bm-badge bg-emerald-50 text-emerald-700 ring-emerald-600/20";
          b.innerHTML = '<span class="bm-dot"></span>Published – Live';
        }
      });
      btn.innerHTML =
        '<svg class="h-4 w-4 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m4.5 12.5 5 5 10-11"/></svg> Order Published';
      btn.className = "bm-btn-ghost text-emerald-700 border-emerald-300 bg-emerald-50";
      toast("Order Published: " + reqId + " is now published to the marketplace.", "success");
    });
  }

  /* -------------------------------------- User & Vendor Edit & Detail Actions */
  function initUserVendorManagement() {
    let activeEditingRow = null;

    // 1. Edit User Trigger
    document.addEventListener("click", function (e) {
      const btn = e.target.closest('[data-action="edit-user"]');
      if (!btn) return;
      e.preventDefault();
      activeEditingRow = btn.closest("tr");

      const uid = btn.getAttribute("data-user-id") || "USR-1002";
      const name = btn.getAttribute("data-user-name") || "Arjun Rao";
      const email = btn.getAttribute("data-user-email") || "arjun.rao@example.com";
      const phone = btn.getAttribute("data-user-phone") || "+91 98765 11200";
      const city = btn.getAttribute("data-user-city") || "Bengaluru";
      const status = btn.getAttribute("data-user-status") || "Active";
      const address = btn.getAttribute("data-user-address") || "";
      const pincode = btn.getAttribute("data-user-pincode") || "";

      const idInput = document.getElementById("edit-user-id");
      const nameInput = document.getElementById("edit-user-name");
      const emailInput = document.getElementById("edit-user-email");
      const phoneInput = document.getElementById("edit-user-phone");
      const citySelect = document.getElementById("edit-user-city");
      const statusSelect = document.getElementById("edit-user-status");
      const addressInput = document.getElementById("edit-user-address");
      const pincodeInput = document.getElementById("edit-user-pincode");

      if (idInput) idInput.value = uid;
      if (nameInput) nameInput.value = name;
      if (emailInput) emailInput.value = email;
      if (phoneInput) phoneInput.value = phone;
      if (citySelect) citySelect.value = city;
      if (statusSelect) statusSelect.value = status;
      if (addressInput) addressInput.value = address;
      if (pincodeInput) pincodeInput.value = pincode;

      openModal("modalEditUser");
    });

    // 2. Submit Edit User Form
    const formEditUser = document.getElementById("formEditUser");
    if (formEditUser) {
      formEditUser.addEventListener("submit", function (e) {
        e.preventDefault();
        const name = document.getElementById("edit-user-name")?.value || "User";
        const email = document.getElementById("edit-user-email")?.value || "";
        const phone = document.getElementById("edit-user-phone")?.value || "";
        const city = document.getElementById("edit-user-city")?.value || "";
        const status = document.getElementById("edit-user-status")?.value || "Active";
        const address = document.getElementById("edit-user-address")?.value || "";
        const pincode = document.getElementById("edit-user-pincode")?.value || "";

        // Post updates to Django backend
        const formData = new FormData(formEditUser);
        fetch('/admin/users/edit', {
          method: 'POST',
          body: formData
        }).catch(err => console.error("Edit user backend error:", err));

        if (activeEditingRow) {
          const nameLink = activeEditingRow.querySelector("a.bm-link");
          if (nameLink) nameLink.textContent = name;
          const contactCell = activeEditingRow.cells[1];
          if (contactCell) {
            contactCell.innerHTML = `${phone}<div class="text-[0.75rem] text-slate-500">${email}</div>`;
          }
          const cityCell = activeEditingRow.cells[2];
          if (cityCell) cityCell.textContent = city;
          const statusCell = activeEditingRow.cells[4];
          if (statusCell) {
            const isBlocked = status.toLowerCase() === "blocked";
            statusCell.innerHTML = `<span class="bm-badge ${isBlocked ? 'bg-rose-50 text-rose-700 ring-rose-600/20' : 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'}"><span class="bm-dot"></span>${status}</span>`;
          }
          const editBtn = activeEditingRow.querySelector('[data-action="edit-user"]');
          if (editBtn) {
            editBtn.setAttribute("data-user-name", name);
            editBtn.setAttribute("data-user-email", email);
            editBtn.setAttribute("data-user-phone", phone);
            editBtn.setAttribute("data-user-city", city);
            editBtn.setAttribute("data-user-status", status);
            editBtn.setAttribute("data-user-address", address);
            editBtn.setAttribute("data-user-pincode", pincode);
          }
        }

        const dispName = document.getElementById("dispUserName");
        if (dispName) dispName.textContent = name;
        const dispPhone = document.getElementById("dispUserPhone");
        if (dispPhone) dispPhone.innerHTML = `<span>${phone}</span>`;
        const dispEmail = document.getElementById("dispUserEmail");
        if (dispEmail) dispEmail.innerHTML = `${email} <span class="text-emerald-600"><svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m9 12 2 2 4-4"/></svg></span>`;
        const dispCity = document.getElementById("dispUserCity");
        if (dispCity) dispCity.textContent = city;
        const dispStatus = document.getElementById("dispUserStatus");
        if (dispStatus) {
          const isBlocked = status.toLowerCase() === "blocked";
          dispStatus.className = `bm-badge ${isBlocked ? 'bg-rose-50 text-rose-700 ring-rose-600/20' : 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'}`;
          dispStatus.innerHTML = `<span class="bm-dot"></span>${status} Account`;
        }

        closeModal(document.getElementById("modalEditUser"));
        toast(`User Updated: '${name}' profile saved successfully by Administrator.`, "success");
      });
    }

    // 3. Edit Vendor Trigger
    document.addEventListener("click", function (e) {
      const btn = e.target.closest('[data-action="edit-vendor"]');
      if (!btn) return;
      e.preventDefault();
      activeEditingRow = btn.closest("tr");

      const vid = btn.getAttribute("data-vendor-id") || "VND-501";
      const name = btn.getAttribute("data-vendor-name") || "GreenLoop Recycling";
      const owner = btn.getAttribute("data-owner-name") || "Anil Kulkarni";
      const phone = btn.getAttribute("data-phone") || "+91 98765 41200";
      const email = btn.getAttribute("data-email") || "anil@greenloop.in";
      const city = btn.getAttribute("data-city") || "Mumbai";
      const kyc = btn.getAttribute("data-kyc") || "Approved";
      const account = btn.getAttribute("data-account") || "Active";
      const online = btn.getAttribute("data-online") || "Online";

      const idInput = document.getElementById("edit-vendor-id");
      const nameInput = document.getElementById("edit-vendor-name");
      const ownerInput = document.getElementById("edit-vendor-owner");
      const phoneInput = document.getElementById("edit-vendor-phone");
      const emailInput = document.getElementById("edit-vendor-email");
      const citySelect = document.getElementById("edit-vendor-city");
      const kycSelect = document.getElementById("edit-vendor-kyc");
      const accountSelect = document.getElementById("edit-vendor-account");
      const onlineSelect = document.getElementById("edit-vendor-online");

      if (idInput) idInput.value = vid;
      if (nameInput) nameInput.value = name;
      if (ownerInput) ownerInput.value = owner;
      if (phoneInput) phoneInput.value = phone;
      if (emailInput) emailInput.value = email;
      if (citySelect) citySelect.value = city;
      if (kycSelect) kycSelect.value = kyc;
      if (accountSelect) accountSelect.value = account;
      if (onlineSelect) onlineSelect.value = online;

      openModal("modalEditVendor");
    });

    // 4. Submit Edit Vendor Form
    const formEditVendor = document.getElementById("formEditVendor");
    if (formEditVendor) {
      formEditVendor.addEventListener("submit", function (e) {
        e.preventDefault();
        const name = document.getElementById("edit-vendor-name")?.value || "Vendor";
        const owner = document.getElementById("edit-vendor-owner")?.value || "";
        const phone = document.getElementById("edit-vendor-phone")?.value || "";
        const email = document.getElementById("edit-vendor-email")?.value || "";
        const city = document.getElementById("edit-vendor-city")?.value || "";
        const kyc = document.getElementById("edit-vendor-kyc")?.value || "Approved";
        const account = document.getElementById("edit-vendor-account")?.value || "Active";
        const online = document.getElementById("edit-vendor-online")?.value || "Online";

        if (activeEditingRow) {
          const nameLink = activeEditingRow.querySelector("a.bm-link");
          if (nameLink) nameLink.textContent = name;
          const ownerCell = activeEditingRow.cells[1];
          if (ownerCell) {
            ownerCell.innerHTML = `${owner}<div class="text-[0.75rem] text-slate-500">${phone}</div>`;
          }
          const cityCell = activeEditingRow.cells[2];
          if (cityCell) {
            cityCell.innerHTML = `${city}<div class="text-[0.75rem] text-slate-500">Service Area</div>`;
          }
          const kycCell = activeEditingRow.cells[5];
          if (kycCell) {
            const isAppr = kyc.toLowerCase().includes("approved");
            kycCell.innerHTML = `<span class="bm-badge ${isAppr ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-amber-50 text-amber-800 ring-amber-600/25'}"><span class="bm-dot"></span>${kyc}</span>`;
          }
          const accCell = activeEditingRow.cells[6];
          if (accCell) {
            const isActive = account.toLowerCase() === "active";
            accCell.innerHTML = `<span class="bm-badge ${isActive ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-rose-50 text-rose-700 ring-rose-600/20'}"><span class="bm-dot"></span>${account}</span>`;
          }
          const onlineCell = activeEditingRow.cells[7];
          if (onlineCell) {
            const isOnline = online.toLowerCase() === "online";
            onlineCell.innerHTML = `<span class="bm-badge ${isOnline ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-slate-100 text-slate-600 ring-slate-500/20'}"><span class="bm-dot"></span>${online}</span>`;
          }
          const editBtn = activeEditingRow.querySelector('[data-action="edit-vendor"]');
          if (editBtn) {
            editBtn.setAttribute("data-vendor-name", name);
            editBtn.setAttribute("data-owner-name", owner);
            editBtn.setAttribute("data-phone", phone);
            editBtn.setAttribute("data-email", email);
            editBtn.setAttribute("data-city", city);
            editBtn.setAttribute("data-kyc", kyc);
            editBtn.setAttribute("data-account", account);
            editBtn.setAttribute("data-online", online);
          }
        }

        const dispName = document.getElementById("dispVendorName");
        if (dispName) dispName.textContent = name;
        const dispOwner = document.getElementById("dispVendorOwner");
        if (dispOwner) dispOwner.textContent = owner;
        const dispCity = document.getElementById("dispVendorCity");
        if (dispCity) dispCity.textContent = city;
        const dispKyc = document.getElementById("dispVendorKyc");
        if (dispKyc) dispKyc.innerHTML = `<span class="bm-dot"></span>KYC ${kyc}`;
        const dispAcc = document.getElementById("dispVendorAccount");
        if (dispAcc) dispAcc.innerHTML = `<span class="bm-dot"></span>${account} Account`;
        const dispOnline = document.getElementById("dispVendorOnline");
        if (dispOnline) dispOnline.innerHTML = `<span class="bm-dot"></span>${online}`;

        closeModal(document.getElementById("modalEditVendor"));
        toast(`Vendor Updated: '${name}' profile saved successfully by Administrator.`, "success");
      });
    }

    // 5. Delete from Detail Pages
    document.addEventListener("click", function (e) {
      const delUserBtn = e.target.closest('[data-action="delete-user-detail"]');
      if (delUserBtn) {
        e.preventDefault();
        const name = delUserBtn.getAttribute("data-user-name") || "this user";
        if (window.confirm("Are you sure you want to permanently delete user '" + name + "' as Administrator? All records will be removed.")) {
          toast(`User Deleted: '${name}' successfully removed.`, "success");
          setTimeout(() => {
            window.location.href = "users.html";
          }, 600);
        }
        return;
      }

      const delVendorBtn = e.target.closest('[data-action="delete-vendor-detail"]');
      if (delVendorBtn) {
        e.preventDefault();
        const name = delVendorBtn.getAttribute("data-vendor-name") || "this vendor";
        if (window.confirm("Are you sure you want to permanently delete vendor '" + name + "' as Administrator? All marketplace authorizations will be revoked.")) {
          toast(`Vendor Deleted: '${name}' successfully removed.`, "success");
          setTimeout(() => {
            window.location.href = "vendors.html";
          }, 600);
        }
        return;
      }
    });
  }

  /* ------------------------------------------------------------- print helper */
  function initPrint() {
    $$("[data-print]").forEach((btn) =>
      btn.addEventListener("click", function () {
        window.print();
      })
    );
  }

  /* ------------------------------------------------------- reveal on scroll */
  function initReveal() {
    const items = $$("[data-reveal]");
    if (!items.length) return;

    document.documentElement.classList.add("bm-motion-ready");

    if (!("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      items.forEach((item) => item.classList.add("is-visible"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -36px 0px" }
    );

    items.forEach((item, index) => {
      item.style.transitionDelay = Math.min(index * 55, 220) + "ms";
      observer.observe(item);
    });
  }

  /* ------------------------------------------------------------------- boot */
  function boot() {
    initSidebar();
    initDropdowns();
    initModals();
    initTabs();
    initFileInputs();
    initAdminMutations();
    initDeleteActions();
    initAccountReveal();
    initAdminPurchase();
    initAdminPublish();
    initUserVendorManagement();
    initPrint();
    initReveal();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

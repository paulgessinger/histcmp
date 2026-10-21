(() => {
  "use strict";

  const data = JSON.parse(document.getElementById("report-data").textContent);
  const items = data.items.map(item => ({ ...item, searchTitle: item.title.toLowerCase() }));
  const byId = new Map(items.map(item => [item.id, item]));
  const grid = document.getElementById("plot-grid");
  const search = document.getElementById("title-search");
  const tagFilter = document.getElementById("tag-filter");
  const tagOptions = [...tagFilter.querySelectorAll("input")];
  const statusButtons = [...document.querySelectorAll("[data-status]")];
  const measurements = new Map();
  const expandedChecks = new Map();
  let selectedStatus = "";
  let filtered = items;
  let searchTimer;
  let resizeTimer;
  let cardWidth = 0;

  for (const item of items) {
    item.template = document.getElementById(`template-${item.id}`);
    item.imageCount = item.template.content.querySelectorAll("img").length;
    item.checkCount = item.template.content.querySelectorAll(".check").length;
  }

  function loadImage(img) {
    if (!img.dataset.src) return;
    img.src = img.dataset.src;
    delete img.dataset.src;
  }

  const imageObserver = "IntersectionObserver" in window
    ? new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (entry.isIntersecting && entry.target.isConnected) {
            loadImage(entry.target);
            imageObserver.unobserve(entry.target);
          }
        }
      }, { rootMargin: "300px" })
    : null;

  function selectedTags() {
    return new Set(tagOptions.filter(input => input.checked).map(input => input.value));
  }

  function mount(slot) {
    if (slot.firstElementChild) return;
    const item = byId.get(slot.dataset.item);
    slot.append(item.template.content.cloneNode(true));
    slot.style.minHeight = "0";
    const selected = selectedTags();
    for (const chip of slot.querySelectorAll("[data-filter-tag]")) {
      chip.setAttribute("aria-pressed", String(selected.has(chip.dataset.filterTag)));
    }
    const open = expandedChecks.get(item.id) || [];
    slot.querySelectorAll(".check").forEach((check, index) => { check.open = open.includes(index); });
    for (const img of slot.querySelectorAll("img[data-src]")) {
      if (imageObserver) imageObserver.observe(img);
      else loadImage(img);
    }
  }

  function unmount(slot) {
    // Keep keyboard focus intact when tabbing through a card near the boundary.
    if (!slot.firstElementChild || slot.contains(document.activeElement)) return;
    const height = slot.getBoundingClientRect().height;
    measurements.set(slot.dataset.item, height);
    slot.style.minHeight = `${height}px`;
    const open = [...slot.querySelectorAll(".check")]
      .flatMap((check, index) => check.open ? [index] : []);
    expandedChecks.set(slot.dataset.item, open);
    for (const img of slot.querySelectorAll("img")) {
      if (imageObserver) imageObserver.unobserve(img);
    }
    slot.replaceChildren();
  }

  const cardObserver = "IntersectionObserver" in window
    ? new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (!entry.target.isConnected) continue;
          if (entry.isIntersecting) mount(entry.target);
          else unmount(entry.target);
        }
      }, { rootMargin: "900px" })
    : null;

  function updateWidth() {
    const style = getComputedStyle(grid);
    const columns = style.gridTemplateColumns.split(" ").length;
    const width = (grid.clientWidth - parseFloat(style.columnGap) * (columns - 1)) / columns;
    if (Math.abs(width - cardWidth) > 1) {
      cardWidth = width;
      measurements.clear();
    }
  }

  function estimatedHeight(item) {
    // Match the reserved image aspect ratio and allow space for headings/checks.
    return measurements.get(item.id) ||
      180 + item.imageCount * Math.max(0, cardWidth - 32) * 5 / 6 + item.checkCount * 40;
  }

  function render() {
    if (cardObserver) cardObserver.disconnect();
    if (imageObserver) imageObserver.disconnect();
    for (const slot of grid.children) unmount(slot);
    updateWidth();
    const fragment = document.createDocumentFragment();
    for (const item of filtered) {
      const slot = document.createElement("div");
      slot.className = "plot-slot";
      slot.dataset.item = item.id;
      slot.style.minHeight = `${estimatedHeight(item)}px`;
      fragment.append(slot);
    }
    grid.replaceChildren(fragment);
    for (const slot of grid.children) {
      if (cardObserver) cardObserver.observe(slot);
      else mount(slot);
    }
    document.getElementById("result-count").textContent =
      `${filtered.length} matching histograms (${items.length} total)`;
    document.getElementById("empty-results").hidden = filtered.length !== 0;
    for (const button of statusButtons) {
      button.setAttribute("aria-pressed", String(button.dataset.status === selectedStatus));
    }
  }

  function filter(persist = true) {
    clearTimeout(searchTimer);
    const query = search.value.trim().toLowerCase();
    const selected = [...selectedTags()];
    filtered = items.filter(item =>
      item.searchTitle.includes(query) &&
      (!selectedStatus || item.status === selectedStatus) &&
      (!selected.length || selected.some(value =>
        value === "untagged" ? item.tags.length === 0
          : item.tags.includes(data.tags[Number(value.slice("tag-".length))])))
    );
    if (persist) {
      const url = new URL(location.href);
      for (const key of ["q", "tag", "untagged", "status"]) url.searchParams.delete(key);
      if (search.value) url.searchParams.set("q", search.value);
      for (const value of selected) {
        if (value === "untagged") url.searchParams.set("untagged", "1");
        else url.searchParams.append("tag", data.tags[Number(value.slice("tag-".length))]);
      }
      if (selectedStatus) url.searchParams.set("status", selectedStatus);
      // A changed filter starts a new view; do not keep a stale plot anchor.
      url.hash = "";
      if (url.href !== location.href) history.replaceState(null, "", url);
    }
    render();
  }

  function restoreFilters() {
    const params = new URL(location.href).searchParams;
    search.value = params.get("q") || "";
    selectedStatus = statusButtons.some(button => button.dataset.status === params.get("status"))
      ? params.get("status") : "";
    const tags = new Set(params.getAll("tag"));
    for (const input of tagOptions) {
      input.checked = input.value === "untagged" ? params.get("untagged") === "1"
        : tags.has(data.tags[Number(input.value.slice("tag-".length))]);
    }
    filter(false);
  }

  function clearFilters() {
    search.value = "";
    for (const input of tagOptions) input.checked = false;
    selectedStatus = "";
    filter();
  }

  function showLinkedPlot() {
    const item = byId.get(location.hash.slice(1));
    if (!item) return;
    clearTimeout(searchTimer);
    if (!filtered.includes(item)) {
      clearFilters();
      const url = new URL(location.href);
      url.hash = item.id;
      history.replaceState(null, "", url);
    }
    const slot = [...grid.children].find(element => element.dataset.item === item.id);
    mount(slot);
    slot.scrollIntoView({ block: "start" });
    // Nearby placeholders may acquire their measured heights on the next frame.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      slot.scrollIntoView({ block: "start" });
    }));
  }

  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(filter, 150);
  });
  tagFilter.addEventListener("change", filter);
  grid.addEventListener("click", event => {
    const chip = event.target.closest("[data-filter-tag]");
    if (!chip) return;
    const input = tagOptions.find(option => option.value === chip.dataset.filterTag);
    input.checked = !input.checked;
    filter();
    input.focus();
  });
  for (const button of statusButtons) {
    button.addEventListener("click", () => {
      selectedStatus = button.dataset.status;
      filter();
    });
  }
  document.getElementById("clear-filters").addEventListener("click", clearFilters);
  window.addEventListener("hashchange", showLinkedPlot);
  window.addEventListener("popstate", () => {
    restoreFilters();
    showLinkedPlot();
  });
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      updateWidth();
      for (const slot of grid.children) {
        if (!slot.firstElementChild) slot.style.minHeight = `${estimatedHeight(byId.get(slot.dataset.item))}px`;
      }
    }, 100);
  });
  restoreFilters();
  showLinkedPlot();
})();

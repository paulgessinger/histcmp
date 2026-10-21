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
  const sortOrder = document.getElementById("sort-order");
  const viewButtons = [...document.querySelectorAll("[data-view]")];
  const controls = document.querySelector(".report-controls");
  const viewer = document.getElementById("plot-viewer");
  let view = "plots";
  let gallery = [];
  let galleryIndex = 0;
  let viewerFocus = null;
  const measurements = new Map();
  const expandedChecks = new Map();
  let selectedStatus = "";
  let filtered = items;
  let searchTimer;
  let resizeTimer;
  let cardWidth = 0;

  for (const item of items) {
    item.template = document.getElementById(`template-${item.id}`);
    item.images = [...item.template.content.querySelectorAll("img")].map(img => img.dataset.src);
    item.imageCount = item.images.length;
    item.ranks = new Map(item.checks.map(check => [check.name, check.sortValue]));
    item.checkCount = item.template.content.querySelectorAll(".check").length;
  }

  const sortableChecks = [...new Set(items.flatMap(item => item.checks
    .filter(check => check.sortValue !== null).map(check => check.name)))].sort();
  for (const name of sortableChecks) {
    const option = new Option(`${name} · worst first`, `check:${name}`);
    sortOrder.add(option);
  }
  const sortDescriptions = {
    name: "Alphabetical histogram names.", failures: "Failed, inconclusive, then passed; names break ties.",
    Chi2Test: "Lowest chi-squared p-value first.",
    KolmogorovTest: "Lowest Kolmogorov–Smirnov p-value first.",
    IntegralTest: "Largest absolute integral pull first.",
    RatioCheck: "Largest fraction of bins exceeding the ratio-pull threshold first.",
    ResidualCheck: "Largest fraction of bins exceeding the residual-pull threshold first.",
  };
  const statusNames = {success: "Passed", failure: "Failed", inconclusive: "Inconclusive"};
  function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function overviewRow(item) {
    const row = element("div", "plot overview-row");
    row.id = item.id;
    row.setAttribute("role", "row");
    function cell(label) {
      const node = element("div", "overview-cell");
      node.setAttribute("role", "cell");
      node.dataset.label = label;
      row.append(node);
      return node;
    }
    const link = element("a", "overview-title", item.title);
    const url = new URL(location.href);
    url.searchParams.delete("view");
    url.hash = item.id;
    link.href = url.href;
    link.dataset.openPlot = item.id;
    cell("Histogram").append(link);
    cell("Status").append(element("span", `status-badge status-${item.status}`, statusNames[item.status]));
    const tags = cell("Tags");
    for (const name of item.tags.length ? item.tags : [null]) {
      const chip = element("button", "tag-chip", name === null ? "Untagged" : name);
      chip.type = "button";
      chip.dataset.filterTag = name === null ? "untagged" : `tag-${data.tags.indexOf(name)}`;
      tags.append(chip);
    }
    const checks = cell("Checks");
    for (const check of item.checks) {
      const label = `${check.name}: ${check.disabled ? "Disabled" : statusNames[check.status]}`;
      const badge = element("span", `overview-check status-${check.disabled ? "disabled" : check.status}`, label);
      badge.title = check.label;
      checks.append(badge);
    }
    if (!item.checks.length) checks.textContent = "No checks";
    return row;
  }

  function showImage() {
    const current = gallery[galleryIndex];
    document.getElementById("viewer-title").textContent = `${current.item.title} — image ${current.index + 1}/${current.item.images.length}`;
    const img = element("img", "viewer-image");
    img.alt = document.getElementById("viewer-title").textContent;
    img.src = current.url;
    document.getElementById("viewer-content").replaceChildren(img);
    document.getElementById("viewer-position").textContent = `${galleryIndex + 1} / ${gallery.length}`;
    document.getElementById("viewer-original").href = current.url;
    document.getElementById("viewer-previous").disabled = galleryIndex === 0;
    document.getElementById("viewer-next").disabled = galleryIndex + 1 === gallery.length;
  }

  function openViewer(itemId, imageIndex, focus) {
    gallery = filtered.flatMap(item => item.images.map((url, index) => ({item, url, index})));
    galleryIndex = gallery.findIndex(image => image.item.id === itemId && image.index === imageIndex);
    if (galleryIndex < 0) return;
    viewerFocus = focus;
    showImage();
    viewer.showModal();
    document.body.classList.add("viewer-open");
  }
  function moveImage(step) {
    galleryIndex = Math.max(0, Math.min(gallery.length - 1, galleryIndex + step));
    showImage();
  }
  document.getElementById("viewer-close").addEventListener("click", () => viewer.close());
  document.getElementById("viewer-previous").addEventListener("click", () => moveImage(-1));
  document.getElementById("viewer-next").addEventListener("click", () => moveImage(1));
  viewer.addEventListener("keydown", event => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      moveImage(event.key === "ArrowLeft" ? -1 : 1);
    }
  });
  viewer.addEventListener("close", () => {
    document.body.classList.remove("viewer-open");
    document.getElementById("viewer-content").replaceChildren();
    gallery = [];
    (viewerFocus?.isConnected ? viewerFocus : search).focus({preventScroll: true});
  });

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
    slot.append(view === "overview" ? overviewRow(item) : item.template.content.cloneNode(true));
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
    measurements.set(`${slot.dataset.view}:${slot.dataset.item}`, height);
    slot.style.minHeight = `${height}px`;
    const open = [...slot.querySelectorAll(".check")]
      .flatMap((check, index) => check.open ? [index] : []);
    if (slot.querySelector(".checks")) expandedChecks.set(slot.dataset.item, open);
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
    if (view === "overview") return measurements.get(`overview:${item.id}`) || (innerWidth <= 700 ? 220 : 100);
    return measurements.get(`plots:${item.id}`) ||
      180 + item.imageCount * Math.max(0, cardWidth - 32) * 5 / 6 + item.checkCount * 40;
  }

  function render() {
    if (cardObserver) cardObserver.disconnect();
    if (imageObserver) imageObserver.disconnect();
    for (const slot of grid.children) unmount(slot);
    grid.classList.toggle("overview-mode", view === "overview");
    const results = document.getElementById("results");
    results.setAttribute("role", view === "overview" ? "table" : "region");
    grid.setAttribute("role", view === "overview" ? "rowgroup" : "presentation");
    document.getElementById("overview-header").hidden = view !== "overview";
    for (const button of viewButtons) button.setAttribute("aria-pressed", String(button.dataset.view === view));
    updateWidth();
    const fragment = document.createDocumentFragment();
    for (const item of filtered) {
      const slot = document.createElement("div");
      slot.className = "plot-slot";
      slot.dataset.item = item.id;
      slot.dataset.view = view;
      slot.setAttribute("role", "presentation");
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
    const compareNames = (a, b) => a.title < b.title ? -1 : a.title > b.title ? 1 : 0;
    const severity = {failure: 0, inconclusive: 1, success: 2};
    const checkName = sortOrder.value.startsWith("check:") ? sortOrder.value.slice(6) : null;
    filtered.sort((a, b) => {
      if (sortOrder.value === "failures") return severity[a.status] - severity[b.status] || compareNames(a, b);
      if (checkName !== null) {
        const av = a.ranks.get(checkName), bv = b.ranks.get(checkName);
        if (av == null && bv != null) return 1;
        if (bv == null && av != null) return -1;
        if (av != null && bv != null && av !== bv) return bv > av ? 1 : -1;
      }
      return compareNames(a, b);
    });
    document.getElementById("sort-description").textContent =
      (sortDescriptions[checkName || sortOrder.value] || "Worst score for this check first.") +
      (checkName ? " Unavailable or disabled checks come last." : "");
    updateCounts(query, selected);
    if (persist) persistState();
    render();
  }

  function persistState(preserveHash = false) {
    const url = new URL(location.href);
    for (const key of ["q", "tag", "untagged", "status", "sort", "view"]) url.searchParams.delete(key);
    if (search.value) url.searchParams.set("q", search.value);
    for (const value of selectedTags()) {
      if (value === "untagged") url.searchParams.set("untagged", "1");
      else url.searchParams.append("tag", data.tags[Number(value.slice("tag-".length))]);
    }
    if (selectedStatus) url.searchParams.set("status", selectedStatus);
    // A changed filter starts a new view; do not keep a stale plot anchor.
    if (sortOrder.value !== "name") url.searchParams.set("sort", sortOrder.value);
    if (view !== "plots") url.searchParams.set("view", view);
    if (!preserveHash) url.hash = "";
    if (url.href !== location.href) history.replaceState(null, "", url);
  }

  function updateCounts(query, selected) {
    const counts = {success: 0, failure: 0, inconclusive: 0};
    const tagCounts = new Map(data.tags.map(name => [name, 0]));
    let untagged = 0;
    for (const item of items) {
      if (!item.searchTitle.includes(query)) continue;
      const matchesTags = !selected.length || selected.some(value => value === "untagged"
        ? !item.tags.length : item.tags.includes(data.tags[Number(value.slice(4))]));
      if (matchesTags) counts[item.status] += 1;
      if (!selectedStatus || item.status === selectedStatus) {
        for (const tag of item.tags) tagCounts.set(tag, tagCounts.get(tag) + 1);
        if (!item.tags.length) untagged += 1;
      }
    }
    for (const badge of document.querySelectorAll("[data-count-status]")) {
      badge.textContent = counts[badge.dataset.countStatus] ?? Object.values(counts).reduce((a, b) => a + b, 0);
    }
    for (const badge of document.querySelectorAll("[data-count-tag]")) {
      badge.textContent = badge.dataset.countTag === "untagged" ? untagged
        : tagCounts.get(data.tags[Number(badge.dataset.countTag.slice(4))]);
    }
  }

  function restoreFilters() {
    const params = new URL(location.href).searchParams;
    search.value = params.get("q") || "";
    selectedStatus = statusButtons.some(button => button.dataset.status === params.get("status"))
      ? params.get("status") : "";
    sortOrder.value = [...sortOrder.options].some(option => option.value === params.get("sort")) ? params.get("sort") : "name";
    view = params.get("view") === "overview" ? "overview" : "plots";
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
    if (view !== "plots") {
      view = "plots";
      persistState(true);
      render();
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
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const image = event.target.closest("[data-image-index]");
    if (image && typeof viewer.showModal === "function") {
      event.preventDefault();
      openViewer(image.closest(".plot-slot").dataset.item, Number(image.dataset.imageIndex), image);
      return;
    }
    const plotLink = event.target.closest("[data-open-plot]");
    if (plotLink) {
      event.preventDefault();
      view = "plots";
      filter();
      location.hash = plotLink.dataset.openPlot;
      return;
    }
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
  sortOrder.addEventListener("change", () => filter());
  for (const button of viewButtons) {
    button.addEventListener("click", () => {
      view = button.dataset.view;
      filter();
    });
  }
  document.getElementById("toggle-filters").addEventListener("click", event => {
    const expanded = controls.classList.toggle("filters-expanded");
    event.target.setAttribute("aria-expanded", String(expanded));
  });
  function controlsResized() {
    const sticky = getComputedStyle(controls).position === "sticky";
    document.documentElement.style.setProperty("--controls-height", `${sticky ? controls.getBoundingClientRect().height : 0}px`);
  }
  if ("ResizeObserver" in window) new ResizeObserver(controlsResized).observe(controls);
  else window.addEventListener("resize", controlsResized);
  controlsResized();
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

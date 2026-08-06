(function () {
  function normalizeItems(items, srcKey, titleKey) {
    return (items || [])
      .map(function (it) {
        if (!it) return { src: "", title: "" };
        var src = srcKey ? (it[srcKey] || "") : (it.src || "");
        var title = titleKey ? (it[titleKey] || "") : (it.title || "");
        return { src: src, title: title };
      })
      .filter(function (it) { return !!it.src; });
  }

  function clampIndex(index, total) {
    if (!total) return 0;
    var i = Number(index || 0);
    if (i < 0) return 0;
    if (i >= total) return total - 1;
    return i;
  }

  function createState() {
    return { open: false, items: [], index: 0 };
  }

  function open(state, items, index) {
    var normalized = normalizeItems(items);
    if (!normalized.length) return state;
    state.items = normalized;
    state.index = clampIndex(index, normalized.length);
    state.open = true;
    return state;
  }

  function openByKeys(state, items, index, srcKey, titleKey) {
    var normalized = normalizeItems(items, srcKey, titleKey);
    if (!normalized.length) return state;
    state.items = normalized;
    state.index = clampIndex(index, normalized.length);
    state.open = true;
    return state;
  }

  function current(state) {
    return (state.items && state.items[state.index]) || { src: "", title: "" };
  }

  function prev(state) {
    if (!state.open || !state.items || !state.items.length) return state;
    state.index = (state.index - 1 + state.items.length) % state.items.length;
    return state;
  }

  function next(state) {
    if (!state.open || !state.items || !state.items.length) return state;
    state.index = (state.index + 1) % state.items.length;
    return state;
  }

  function close(state) {
    state.open = false;
    state.items = [];
    state.index = 0;
    return state;
  }

  window.AscImageViewer = {
    createState: createState,
    open: open,
    openByKeys: openByKeys,
    current: current,
    prev: prev,
    next: next,
    close: close,
  };
})();

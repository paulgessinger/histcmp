/* Replay Python-prepared paths. All coordinates, glyphs and colors come from Python. */
(() => {
  "use strict";
  const cache = new Map();
  async function decode(id) {
    if (cache.has(id)) return cache.get(id);
    const pending = (async () => {
      if (!("DecompressionStream" in window)) {
        throw new Error("This browser cannot decompress JS plots. Use a current browser or generate the default SVG report.");
      }
      const encoded = document.getElementById(id).textContent.trim();
      const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      const data = await new Response(stream).json();
      data.paths = data.paths.map(path => new Path2D(path));
      return data;
    })();
    cache.set(id, pending);
    if (cache.size > 6) cache.delete(cache.keys().next().value);
    try { return await pending; }
    catch (error) { cache.delete(id); throw error; }
  }

  function transformed(path, matrix) {
    const result = new Path2D();
    result.addPath(path, new DOMMatrix(matrix));
    return result;
  }

  async function draw(canvas) {
    const token = {};
    canvas.drawToken = token;
    try {
      const data = await decode(canvas.dataset.plot);
      if (!canvas.isConnected || canvas.drawToken !== token) return;
      const width = canvas.clientWidth || data.width;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.ceil(width * ratio);
      canvas.height = Math.ceil(width * ratio * data.height / data.width);
      const ctx = canvas.getContext("2d");
      const scale = canvas.width / data.width;
      ctx.setTransform(scale, 0, 0, -scale, 0, canvas.height);
      let count = 0;
      for (const [pathIndex, styleIndex, matrix] of data.commands) {
        const [fill, stroke, lineWidth, cap, join, dashOffset, dashes, clip, clipPath] = data.styles[styleIndex];
        ctx.save();
        if (clip) {
          ctx.beginPath(); ctx.rect(...clip); ctx.clip();
        }
        if (clipPath) ctx.clip(transformed(data.paths[clipPath[0]], clipPath[1]));
        const path = transformed(data.paths[pathIndex], matrix);
        if (fill) { ctx.fillStyle = fill; ctx.fill(path); }
        if (stroke && lineWidth > 0) {
          ctx.strokeStyle = stroke;
          ctx.lineWidth = lineWidth;
          ctx.lineCap = cap === "projecting" ? "square" : cap;
          ctx.lineJoin = join;
          ctx.setLineDash(dashes);
          ctx.lineDashOffset = dashOffset;
          ctx.stroke(path);
        }
        ctx.restore();
        if (++count % 5000 === 0) {
          await new Promise(resolve => requestAnimationFrame(resolve));
          if (!canvas.isConnected || canvas.drawToken !== token) return;
        }
      }
      delete canvas.dataset.error;
      canvas.dataset.rendered = "true";
    } catch (error) {
      if (!canvas.isConnected || canvas.drawToken !== token) return;
      canvas.dataset.error = error.message;
      const message = document.createElement("p");
      canvas.parentElement.querySelector(".plot-render-error")?.remove();
      message.className = "notification plot-render-error";
      message.textContent = `Could not render plot: ${error.message}`;
      canvas.parentElement.append(message);
    }
  }

  const sizes = new WeakMap();
  const observer = "ResizeObserver" in window ? new ResizeObserver(entries => {
    for (const {target, contentRect} of entries) {
      if (sizes.get(target) !== contentRect.width) {
        sizes.set(target, contentRect.width);
        draw(target);
      }
    }
  }) : null;
  window.histcmpCanvas = {
    mount(canvas) {
      if (observer) observer.observe(canvas);
      else draw(canvas);
    },
    unmount(canvas) {
      if (observer) observer.unobserve(canvas);
      canvas.drawToken = null;
    }
  };
})();

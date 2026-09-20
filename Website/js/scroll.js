/* ==========================================================================
   Scroll-triggered animations via IntersectionObserver
   ========================================================================== */

(function () {
  "use strict";

  var renderQueue = [];
  var rendering = false;

  function processQueue() {
    if (rendering || !renderQueue.length) return;
    rendering = true;
    var el = renderQueue.shift();
    el.classList.add("visible");
    var vizId = el.dataset.viz;
    if (vizId && window.VIZ && window.VIZ[vizId] && !el._rendered) {
      el._rendered = true;
      try {
        console.log("Rendering:", vizId);
        window.VIZ[vizId]();
      } catch (err) {
        console.error("Viz error in " + vizId + ":", err);
      }
    }
    // Allow current viz to paint before starting next
    requestAnimationFrame(function () {
      rendering = false;
      processQueue();
    });
  }

  function triggerViz(el) {
    if (el._queued) return;
    el._queued = true;
    if (!el.dataset.viz) {
      // Non-viz fade-in — apply immediately
      el.classList.add("visible");
      return;
    }
    renderQueue.push(el);
    processQueue();
  }

  function init() {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            triggerViz(entry.target);
          }
        });
      },
      { threshold: 0, rootMargin: "0px 0px 600px 0px" }
    );

    var elements = document.querySelectorAll(".fade-in");
    elements.forEach(function (el) { observer.observe(el); });

    // Fallback scroll handler for any elements the observer misses
    function onScroll() {
      var allRendered = true;
      elements.forEach(function (el) {
        if (!el._queued) {
          allRendered = false;
          var rect = el.getBoundingClientRect();
          if (rect.top < window.innerHeight + 600) {
            triggerViz(el);
          }
        }
      });
      if (allRendered) {
        window.removeEventListener("scroll", onScroll);
      }
    }
    window.addEventListener("scroll", onScroll, { passive: true });

    // Trigger immediately for elements already in viewport
    requestAnimationFrame(function () {
      elements.forEach(function (el) {
        var rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight + 600) {
          triggerViz(el);
        }
      });
    });
  }

  // Handle both cases: DOM already ready, or not yet ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

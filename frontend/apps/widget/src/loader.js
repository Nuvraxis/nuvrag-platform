/**
 * Stable entry point tenants embed:
 *
 *   <script src="https://cdn.example.com/widget/loader.js"
 *           data-chatbot-key="pk_live_xxx" async></script>
 *
 * This file is intentionally tiny and its URL never changes, so it is cached for minutes
 * rather than a year. It resolves the current bundle from a manifest and mounts the chat UI
 * in an iframe — iframe rather than inline DOM so the host page's CSS can never bleed in
 * (or out), and so the widget's own scripts stay in a separate origin context.
 *
 * That separate origin is also why this file answers the frame's `hello`: the frame's own
 * requests carry the widget origin, so it has no way of knowing which site it is running on
 * unless this page, which does know, tells it across a channel the browser stamps.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  var chatbotKey = script.getAttribute("data-chatbot-key");
  if (!chatbotKey) {
    console.error("[chat-widget] missing data-chatbot-key attribute");
    return;
  }

  var base = script.src.replace(/\/loader\.js(\?.*)?$/, "");

  // Appearance is a dashboard setting, not a snippet attribute: it reaches the frame from the
  // API and the frame tells this page the parts only it can apply. Tenants therefore never
  // edit their HTML to change a colour, and two sites embedding the same chatbot cannot
  // disagree about what it looks like.
  var COLLAPSED = 76;
  var EXPANDED = { width: 400, height: 600 };
  var position = "right";

  var MOUNT_ID = "rag-chat-widget-root";
  if (document.getElementById(MOUNT_ID)) return;

  function boot(manifest, apiBase) {
    var frameUrl =
      base +
      "/" +
      manifest.entry +
      "?key=" +
      encodeURIComponent(chatbotKey) +
      (apiBase ? "&api=" + encodeURIComponent(apiBase) : "");

    var host = document.createElement("div");
    host.id = MOUNT_ID;
    host.style.cssText = [
      "position:fixed",
      "bottom:20px",
      "width:" + COLLAPSED + "px",
      "max-width:calc(100vw - 40px)",
      "height:" + COLLAPSED + "px",
      "max-height:calc(100vh - 40px)",
      "z-index:2147483000",
      "border:0",
      "display:block",
    ].join(";");
    place();

    /** Only one side is ever set, or a swap would leave the old one pinning it in place. */
    function place() {
      host.style[position] = "20px";
      host.style[position === "right" ? "left" : "right"] = "auto";
    }

    var frame = document.createElement("iframe");
    frame.src = frameUrl;
    frame.title = "Chat";
    frame.setAttribute("allow", "clipboard-write");
    // Still no top-level navigation: the host page cannot be steered from in here.
    //
    // Popups are allowed because answers and staff replies contain links, and a link has
    // nowhere else to go — following one in place would replace the conversation with the
    // destination inside a 400px panel. `allow-popups-to-escape-sandbox` is what keeps the
    // opened tab an ordinary page rather than a crippled one that inherits these flags; the
    // frame only ever links to http, https and mailto, which `safeUrl` in widget.js enforces,
    // and every anchor carries `rel="noopener"` so the new tab gets no handle back.
    frame.setAttribute(
      "sandbox",
      "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox",
    );
    frame.style.cssText =
      "width:100%;height:100%;border:0;border-radius:16px;" +
      "box-shadow:0 12px 40px rgba(15,23,42,.22);background:transparent;color-scheme:normal";

    host.appendChild(frame);
    document.body.appendChild(host);

    function onMessage(event) {
      if (event.source !== frame.contentWindow) return;
      var data = event.data || {};

      // The chatbot is paused, archived, unknown, or not allowed on this site. The frame has
      // already refused to show its launcher; this takes the iframe out of the tenant's DOM
      // so nothing of the widget is left on their page at all — not a transparent box, not a
      // stray element in a corner. Nothing re-adds it: the decision belongs to this page
      // view, and a reload is what asks the API again.
      if (data.type === "rag-widget:disabled") {
        window.removeEventListener("message", onMessage);
        if (host.parentNode) host.parentNode.removeChild(host);
        return;
      }

      // The frame asks who is hosting it. Replying is the whole point: the browser stamps
      // this page's origin onto `event.origin` at the far end, where it cannot be forged.
      // Sending it as data instead would let anyone embedding the widget claim any site.
      if (data.type === "rag-widget:hello") {
        frame.contentWindow.postMessage({ type: "rag-widget:site" }, frameOrigin);
        return;
      }

      // The frame reports its own collapsed/expanded size so the host element can shrink to
      // just the launcher button when the panel is closed.
      if (data.type === "rag-widget:resize") {
        host.style.height = (data.open ? EXPANDED.height : COLLAPSED) + "px";
        host.style.width = (data.open ? EXPANDED.width : COLLAPSED) + "px";
        return;
      }

      // The parts of the tenant's theme that live out here rather than inside the frame.
      if (data.type === "rag-widget:theme") {
        position = data.position === "left" ? "left" : "right";
        place();
        if (typeof data.radius === "number") {
          frame.style.borderRadius = data.radius + "px";
        }
        if (typeof data.title === "string" && data.title) {
          frame.title = data.title;
        }
      }
    }

    window.addEventListener("message", onMessage);
  }

  var frameOrigin;
  try {
    frameOrigin = new URL(base, location.href).origin;
  } catch (error) {
    console.error("[chat-widget] could not resolve the widget origin", error);
    return;
  }

  // `config.json` is written at deploy time and says where the API lives, so tenants never
  // carry that address in their HTML and it can move without anyone editing a page.
  Promise.all([
    fetch(base + "/manifest.json", { cache: "no-cache" }).then(function (response) {
      if (!response.ok) throw new Error("manifest " + response.status);
      return response.json();
    }),
    fetch(base + "/config.json", { cache: "no-cache" })
      .then(function (response) {
        return response.ok ? response.json() : {};
      })
      .catch(function () {
        return {};
      }),
  ])
    .then(function (results) {
      boot(results[0], results[1].apiBase || "");
    })
    .catch(function (error) {
      console.error("[chat-widget] failed to load", error);
    });
})();

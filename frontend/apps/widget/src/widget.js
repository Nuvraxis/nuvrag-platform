/**
 * Chat UI that runs inside the widget iframe.
 *
 * Deliberately dependency-free: this ships to every tenant's site, so the byte budget
 * matters more than developer ergonomics. It speaks to the public widget API and renders
 * the SSE stream token by token.
 */
(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var CHATBOT_KEY = params.get("key") || "";
  var API_BASE = (params.get("api") || location.origin).replace(/\/$/, "");
  var TITLE = "Ask a question";

  var SESSION_STORAGE_KEY = "rag-widget-session";
  var CHAT_URL = API_BASE + "/public/widget/chat";
  var TICKET_URL = API_BASE + "/public/widget/tickets";

  /**
   * Anonymous and per-browser-session: chatting never requires identifying the end user.
   *
   * sessionStorage is checked first and written by default, so an ordinary visitor's id dies
   * with the tab and leaves nothing behind. localStorage is read too, but only ever *written*
   * by `rememberSession` once a ticket has been opened — see the note there.
   */
  function sessionId() {
    var existing = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;

    var remembered = readRemembered();
    if (remembered) {
      sessionStorage.setItem(SESSION_STORAGE_KEY, remembered);
      return remembered;
    }

    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    var id = Array.prototype.map
      .call(bytes, function (b) {
        return b.toString(16).padStart(2, "0");
      })
      .join("");
    sessionStorage.setItem(SESSION_STORAGE_KEY, id);
    return id;
  }

  function readRemembered() {
    try {
      return localStorage.getItem(SESSION_STORAGE_KEY);
    } catch (error) {
      // Storage can be denied outright (third-party cookie blocking, private modes). Chat
      // still works; only the ability to come back to a reply is lost.
      return null;
    }
  }

  /**
   * Promote this session id to durable storage — but only once a ticket exists.
   *
   * There is no outbound mail, so reopening the widget is the only way a staff reply reaches
   * the visitor, and sessionStorage dies with the tab. Persisting *every* visitor's id would
   * turn an anonymous, ephemeral handle into a durable identifier on their device for people
   * who never asked for anything. Doing it only here keeps that to visitors who have just
   * volunteered an email and asked to be replied to.
   */
  function rememberSession(id) {
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, id);
    } catch (error) {
      /* Denied storage is not fatal — the reply is still on the ticket. */
    }
  }

  var els = {
    body: document.body,
    launcher: document.getElementById("launcher"),
    close: document.getElementById("close"),
    title: document.getElementById("title"),
    log: document.getElementById("log"),
    form: document.getElementById("composer"),
    input: document.getElementById("input"),
    send: document.getElementById("send"),
    human: document.getElementById("human"),
    contact: document.getElementById("contact"),
    contactEmail: document.getElementById("contact-email"),
    contactName: document.getElementById("contact-name"),
    contactMessage: document.getElementById("contact-message"),
    contactCancel: document.getElementById("contact-cancel"),
    contactSend: document.getElementById("contact-send"),
    legal: document.getElementById("legal"),
    brand: document.getElementById("brand"),
  };

  /** The visitor's last question, used to pre-fill the form when escalating mid-conversation. */
  var lastQuestion = "";
  /** Set once a ticket exists, so the affordance stops offering to open a second one. */
  var ticketOpen = false;

  els.title.textContent = TITLE;
  els.brand.href = brandHref(TITLE);

  function notifyHost(open) {
    parent.postMessage({ type: "rag-widget:resize", open: open }, "*");
  }

  /**
   * Paint the tenant's theme.
   *
   * Colours are written as inline custom properties, which outrank every rule in the
   * stylesheet — so a colour that was set wins and one that was not keeps the default,
   * dark-mode switching included. The API validates each value against a six-digit hex
   * pattern before it gets here; this checks again, because the alternative is trusting a
   * response to be safe to put in a style attribute.
   */
  var COLOURS = {
    accent: "--accent",
    accent_foreground: "--accent-foreground",
    surface: "--surface",
    surface_muted: "--surface-muted",
    border: "--border",
    text: "--text",
    text_muted: "--text-muted",
  };
  var HEX = /^#[0-9a-f]{6}$/i;

  function applyTheme(theme) {
    var root = document.documentElement;
    Object.keys(COLOURS).forEach(function (key) {
      var value = theme[key];
      if (typeof value === "string" && HEX.test(value)) {
        root.style.setProperty(COLOURS[key], value);
      }
    });

    if (typeof theme.radius === "number" && theme.radius >= 0 && theme.radius <= 28) {
      root.style.setProperty("--radius", theme.radius + "px");
    }

    root.classList.remove("scheme-light", "scheme-dark");
    if (theme.scheme === "light" || theme.scheme === "dark") {
      root.classList.add("scheme-" + theme.scheme);
      // Lets the browser pick matching scrollbars and form control chrome inside the frame.
      root.style.colorScheme = theme.scheme;
    }

    // The launcher's position and the frame's own corner radius belong to the host page's
    // element, which this document cannot reach. The loader owns that and is told.
    parent.postMessage(
      {
        type: "rag-widget:theme",
        position: theme.position === "left" ? "left" : "right",
        radius: typeof theme.radius === "number" ? theme.radius : null,
        title: els.title.textContent,
      },
      "*",
    );
  }

  /* ----------------------------------------------------------------- footer -- */

  var BRAND_URL = "https://nuvraxis.com";

  /**
   * The attribution link, carrying the chatbot's own header as its campaign source.
   *
   * `encodeURIComponent` rather than plain concatenation: a header like "Acme & Co" would
   * otherwise end the query at the ampersand, and one containing `#` would push the rest into
   * a fragment the server never receives.
   */
  function brandHref(title) {
    return BRAND_URL + "?utm_source=" + encodeURIComponent(title);
  }

  /**
   * The tenant's own privacy and terms links.
   *
   * Built with `anchor`, so the `safeUrl` check that guards a link inside a model's answer
   * guards these too. The API validated them when they were saved and again on the way out;
   * this is the last check before an `href` is set, and the one that runs in the browser
   * actually doing the navigating.
   *
   * A link that fails is dropped rather than shown as text. In a message the raw URL is the
   * content and worth keeping; in a footer it is noise.
   */
  function renderLegal(privacy, terms) {
    var links = [
      [privacy, "Privacy"],
      [terms, "Terms"],
    ];
    els.legal.textContent = "";

    links.forEach(function (link) {
      if (!safeUrl(link[0])) return;
      if (els.legal.childNodes.length) {
        var separator = inlineNode("span", "·");
        separator.className = "sep";
        els.legal.appendChild(separator);
      }
      els.legal.appendChild(anchor(link[0], link[1]));
    });

    // Hidden rather than empty: the footer is a flex column with a gap, so an empty span
    // would still push the branding down by a row.
    els.legal.hidden = els.legal.childNodes.length === 0;
  }

  /**
   * Answers that mean this widget has no business being on this page at all.
   *
   * A paused or archived chatbot is the case this exists for: it must not show a launcher a
   * visitor can open onto a composer that will only ever fail. The other two fall out of the
   * same rule — a key the API does not recognise, and a site that is not on the chatbot's
   * allow-list, are equally "not for here".
   *
   * Everything else is deliberately absent. A 429, a 5xx or a dropped connection is the API
   * having a bad minute, and tearing the widget off a tenant's site over a blip would be a
   * far worse failure than a launcher that is briefly unhelpful.
   */
  var FATAL = { chatbot_unavailable: 1, origin_not_allowed: 1, not_found: 1 };

  var disabled = false;

  /**
   * Remove the widget for the rest of this page view.
   *
   * Both halves matter. Hiding inside the frame handles the case where the 800ms fallback
   * timer already revealed the launcher before the API answered; asking the host to drop it
   * is what makes "never shown" true rather than "shown but transparent", since the iframe
   * would otherwise stay in the tenant's DOM covering a corner of their page.
   */
  function disable() {
    disabled = true;
    els.body.classList.remove("ready", "open");
    parent.postMessage({ type: "rag-widget:disabled" }, "*");
  }

  /** Reveals the launcher. Idempotent: whichever of bootstrap or the timer wins is fine. */
  function ready() {
    if (disabled) return;
    els.body.classList.add("ready");
  }
  setTimeout(ready, 800);

  /**
   * Which site is embedding us.
   *
   * This frame is served from the widget's own origin, so the `Origin` the browser puts on
   * our requests identifies the CDN and says nothing about the tenant. The host page answers
   * our hello, and the browser — not the page — fills in `event.origin`, so a site cannot
   * claim to be another one. That answer is what the API checks its allow-list against.
   */
  var siteOrigin = null;
  var siteResolved = new Promise(function (resolve) {
    function onMessage(event) {
      if (event.source !== parent || (event.data || {}).type !== "rag-widget:site") return;
      window.removeEventListener("message", onMessage);
      siteOrigin = event.origin;
      resolve();
    }
    window.addEventListener("message", onMessage);
    parent.postMessage({ type: "rag-widget:hello" }, "*");

    // Opened directly rather than embedded, or a host that never replies: carry on and let
    // the API decide on the `Origin` header alone rather than hanging with a dead composer.
    setTimeout(resolve, 2000);
  });

  function apiHeaders(extra) {
    var headers = extra || {};
    headers["X-Chatbot-Key"] = CHATBOT_KEY;
    if (siteOrigin) headers["X-Widget-Site"] = siteOrigin;
    return headers;
  }

  function setOpen(open) {
    els.body.classList.toggle("open", open);
    notifyHost(open);
    if (open) els.input.focus();
  }

  els.launcher.addEventListener("click", function () {
    setOpen(true);
  });
  els.close.addEventListener("click", function () {
    setOpen(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") setOpen(false);
  });

  /* --------------------------------------------------------------- markdown -- */

  /**
   * A small Markdown subset, rendered to DOM nodes rather than to HTML.
   *
   * The rule this file has always kept — no `innerHTML`, anywhere — is what makes rendering
   * model output safe to do at all. Every node below is built with `createElement` and filled
   * with `textContent`; the only attribute that ever takes a value from the text is `href`,
   * and that goes through `safeUrl` first. There is no path here that can introduce script,
   * regardless of what the model or a staff member writes.
   *
   * The subset is what a support answer actually uses: emphasis, inline code, fenced code,
   * headings, lists, explicit links and bare URLs. Anything else stays literal text, which is
   * the right failure mode — an unrecognised construct reads as what was written.
   */

  var SAFE_SCHEME = /^(?:https?|mailto):$/;

  /**
   * The href to use, or `null` if this is not a link worth making clickable.
   *
   * Parsing rather than pattern-matching, so `javascript:`, `data:` and their obfuscations
   * are rejected by the URL parser's own reading of the scheme rather than by a blocklist.
   * A relative reference throws here and is refused too: a chat message resolving against the
   * widget's own origin is never what was meant.
   */
  function safeUrl(raw) {
    try {
      var parsed = new URL(raw);
      return SAFE_SCHEME.test(parsed.protocol) ? parsed.href : null;
    } catch (error) {
      return null;
    }
  }

  /**
   * `literal` is what the writer actually typed, shown verbatim when the URL is refused.
   *
   * Falling back to the label alone would quietly delete the address from the message, which
   * is the one thing a reader needs in order to judge a link the widget would not make
   * clickable. An unrecognised construct should read as what was written.
   */
  function anchor(href, label, literal) {
    var url = safeUrl(href);
    if (!url) return document.createTextNode(literal === undefined ? label : literal);

    var node = document.createElement("a");
    node.href = url;
    node.textContent = label;
    // A new tab, because navigating this frame would replace the conversation with the
    // destination. `noopener` also denies the opened page a handle back to this window.
    node.target = "_blank";
    node.rel = "noopener noreferrer nofollow";
    return node;
  }

  function inlineNode(tag, text) {
    var node = document.createElement(tag);
    node.textContent = text;
    return node;
  }

  // One alternation, tried left to right, so `code` wins over the emphasis markers that may
  // appear inside it and `**` is taken before `*`. No group nests a quantifier inside another,
  // which keeps matching linear on adversarial input.
  var INLINE = new RegExp(
    [
      "`([^`\\n]+)`", // 1 inline code
      "\\[([^\\]\\n]+)\\]\\(([^\\s)]+)\\)", // 2 label, 3 href
      "\\*\\*([^*\\n]+)\\*\\*", // 4 strong
      "__([^_\\n]+)__", // 5 strong
      "\\*([^*\\n]+)\\*", // 6 emphasis
      "_([^_\\n]+)_", // 7 emphasis
      "(https?://[^\\s<>]+)", // 8 bare URL
    ].join("|"),
    "g",
  );

  /** Sentence punctuation that follows a bare URL far more often than it belongs to one. */
  var URL_TAIL = /[.,;:!?'")\]]+$/;

  function renderInline(text, parent) {
    var consumed = 0;
    var match;

    INLINE.lastIndex = 0;
    while ((match = INLINE.exec(text)) !== null) {
      if (match.index > consumed) {
        parent.appendChild(document.createTextNode(text.slice(consumed, match.index)));
      }
      consumed = match.index + match[0].length;

      if (match[1] !== undefined) {
        parent.appendChild(inlineNode("code", match[1]));
      } else if (match[2] !== undefined) {
        parent.appendChild(anchor(match[3], match[2], match[0]));
      } else if (match[4] !== undefined) {
        parent.appendChild(inlineNode("strong", match[4]));
      } else if (match[5] !== undefined) {
        parent.appendChild(inlineNode("strong", match[5]));
      } else if (match[6] !== undefined) {
        parent.appendChild(inlineNode("em", match[6]));
      } else if (match[7] !== undefined) {
        parent.appendChild(inlineNode("em", match[7]));
      } else {
        // "see https://example.com." ends a sentence; the full stop is not part of the URL.
        var url = match[8].replace(URL_TAIL, "");
        consumed -= match[8].length - url.length;
        parent.appendChild(anchor(url, url));
      }
    }

    if (consumed < text.length) {
      parent.appendChild(document.createTextNode(text.slice(consumed)));
    }
  }

  var FENCE = /^\s*```/;
  var HEADING = /^(#{1,3})\s+(.*)$/;
  var BULLET = /^\s*[-*]\s+/;
  var NUMBER = /^\s*\d+\.\s+/;

  function startsBlock(line) {
    return FENCE.test(line) || HEADING.test(line) || BULLET.test(line) || NUMBER.test(line);
  }

  function renderMarkdown(text, parent) {
    var lines = String(text == null ? "" : text).split("\n");
    var index = 0;

    while (index < lines.length) {
      var line = lines[index];

      if (FENCE.test(line)) {
        var fenced = [];
        index++;
        while (index < lines.length && !FENCE.test(lines[index])) fenced.push(lines[index++]);
        // A fence the stream has not closed yet still renders; it closes on a later frame.
        index++;

        var pre = document.createElement("pre");
        pre.appendChild(inlineNode("code", fenced.join("\n")));
        parent.appendChild(pre);
        continue;
      }

      var heading = HEADING.exec(line);
      if (heading) {
        // Offset by two: the panel's own title is the h1 and the contact form is an h2, so a
        // heading inside a message belongs below both in the document outline.
        var level = document.createElement("h" + (heading[1].length + 2));
        renderInline(heading[2], level);
        parent.appendChild(level);
        index++;
        continue;
      }

      if (BULLET.test(line) || NUMBER.test(line)) {
        var ordered = NUMBER.test(line);
        var marker = ordered ? NUMBER : BULLET;
        var list = document.createElement(ordered ? "ol" : "ul");

        while (index < lines.length && marker.test(lines[index])) {
          var item = document.createElement("li");
          renderInline(lines[index].replace(marker, ""), item);
          list.appendChild(item);
          index++;
        }
        parent.appendChild(list);
        continue;
      }

      if (!line.trim()) {
        index++;
        continue;
      }

      var paragraph = [];
      while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
        paragraph.push(lines[index++]);
      }
      var block = document.createElement("p");
      renderInline(paragraph.join("\n"), block);
      parent.appendChild(block);
    }
  }

  /* ----------------------------------------------------------------- bubbles -- */

  function bubble(role, text) {
    var node = document.createElement("div");
    node.className = "msg " + role;
    // textContent, never innerHTML: what the visitor typed is shown exactly as typed, and
    // errors and notices are ours to begin with.
    node.textContent = text || "";
    els.log.appendChild(node);
    scrollToEnd();
    return node;
  }

  /**
   * A bubble whose body is rendered Markdown.
   *
   * Returns the inner container rather than the bubble, because that is what the typewriter
   * repaints as the answer arrives.
   */
  function markdownBubble(role) {
    var node = document.createElement("div");
    node.className = "msg " + role;

    var body = document.createElement("div");
    body.className = "md";
    node.appendChild(body);

    els.log.appendChild(node);
    scrollToEnd();
    return body;
  }

  function botBubble(text) {
    var body = markdownBubble("bot");
    renderMarkdown(text, body);
    scrollToEnd();
    return body;
  }

  /**
   * A staff reply, labelled so the visitor can tell a person from the assistant.
   *
   * Rendered as Markdown like the assistant's answers, which is mostly about links: a person
   * pasting a booking URL into the dashboard expects the visitor to be able to click it.
   * Staff-written text is as untrusted as anything else here, and `renderMarkdown` builds
   * nodes rather than markup, so that stays true.
   */
  function staffBubble(text) {
    var node = document.createElement("div");
    node.className = "msg staff";

    var label = document.createElement("span");
    label.className = "msg-label";
    label.textContent = "Support";
    node.appendChild(label);

    var body = document.createElement("div");
    body.className = "md";
    renderMarkdown(text, body);
    node.appendChild(body);

    els.log.appendChild(node);
    scrollToEnd();
    return node;
  }

  function notice(text) {
    var node = document.createElement("div");
    node.className = "notice";
    node.textContent = text;
    els.log.appendChild(node);
    scrollToEnd();
    return node;
  }

  /**
   * The contextual offer, shown when a turn comes back with `can_escalate`.
   *
   * That flag means zero chunks were retrieved — the same condition behind "I do not have
   * information about that in the available documents" — so this appears exactly where the
   * assistant has just admitted it cannot help.
   */
  function offerEscalation() {
    if (ticketOpen || els.body.classList.contains("contacting")) return;

    var wrap = document.createElement("div");
    wrap.className = "offer";

    var text = document.createElement("p");
    text.style.margin = "0 0 8px";
    text.textContent = "Would you like a person to take a look?";
    wrap.appendChild(text);

    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "Talk to a human";
    button.addEventListener("click", function () {
      wrap.remove();
      // Taken from the grounding-miss offer rather than the footer, which is what the
      // ticket's `source` and `escalation_reason` end up recording.
      openContactForm("ai_escalation");
    });
    wrap.appendChild(button);

    els.log.appendChild(wrap);
    scrollToEnd();
  }

  function typingIndicator() {
    var node = document.createElement("div");
    node.className = "msg bot typing";
    for (var i = 0; i < 3; i++) {
      node.appendChild(document.createElement("span"));
    }
    els.log.appendChild(node);
    scrollToEnd();
    return node;
  }

  function renderSources(sources) {
    if (!sources || !sources.length) return;
    var wrap = document.createElement("div");
    wrap.className = "sources";
    sources.forEach(function (source) {
      var chip = document.createElement("span");
      chip.className = "source";
      var meta = source.metadata || {};
      var label = meta.section || (meta.page ? "page " + meta.page : "source");
      chip.textContent = "[" + source.marker + "] " + label;
      chip.title = source.excerpt || "";
      wrap.appendChild(chip);
    });
    els.log.appendChild(wrap);
    scrollToEnd();
  }

  function scrollToEnd() {
    els.log.scrollTop = els.log.scrollHeight;
  }

  /** Within a line or so of the end, which is where "following along" stops and reading starts. */
  var FOLLOW_SLACK_PX = 48;

  function nearBottom() {
    return els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < FOLLOW_SLACK_PX;
  }

  /* ------------------------------------------------------------- typewriter -- */

  var TYPE_CHARS_PER_SECOND = 240;
  /**
   * How far behind the stream the display is ever allowed to fall.
   *
   * Tokens arrive in bursts, so a fixed rate would drift further behind on every burst and
   * still be typing long after the answer finished. Above this backlog the rate rises to
   * clear it within the window, which keeps the effect an animation rather than a queue.
   */
  var TYPE_MAX_LAG_MS = 500;
  /**
   * Roughly a frame, driven by a timer rather than `requestAnimationFrame`.
   *
   * rAF is the usual tool for this and is the wrong one here: it stops in a background tab
   * and never fires at all where there is no compositor, either of which would leave an
   * answer permanently invisible. A timer keeps firing — clamped to about a second in the
   * background, which the catch-up rate below absorbs on the next tick — so the text always
   * lands. Text reveal gains nothing from being aligned to vsync anyway.
   */
  var TYPE_TICK_MS = 16;

  var reducedMotion =
    typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;

  /**
   * Reveals streamed text at a steady rate, repainting the Markdown as it goes.
   *
   * The whole revealed prefix is re-rendered each frame rather than appended to, because
   * Markdown is not decidable from a prefix: `**bo` is literal text that becomes emphasis
   * only once its closing marker arrives. Messages are short enough that rebuilding a handful
   * of nodes per frame costs nothing measurable.
   */
  function typewriter(container) {
    var full = "";
    var shown = 0;
    var painted = -1;
    var timer = null;
    var previous = 0;
    var drained = null;

    function paint() {
      if (painted === shown) return;
      painted = shown;

      // Read before the repaint, or the freshly grown content has already moved the answer.
      var follow = nearBottom();
      container.textContent = "";
      renderMarkdown(full.slice(0, shown), container);
      if (follow) scrollToEnd();
    }

    function settle() {
      if (!drained) return;
      drained();
      drained = null;
    }

    function stop() {
      if (timer === null) return;
      clearTimeout(timer);
      timer = null;
    }

    function schedule() {
      if (timer === null) timer = setTimeout(step, TYPE_TICK_MS);
    }

    function step() {
      timer = null;

      var now = performance.now();
      // A tick delayed by a throttled background tab reports its true gap, so the rate below
      // clears the whole backlog at once rather than trickling it out on return.
      var elapsed = previous ? now - previous : TYPE_TICK_MS;
      previous = now;

      var backlog = full.length - shown;
      var rate = Math.max(TYPE_CHARS_PER_SECOND, (backlog * 1000) / TYPE_MAX_LAG_MS);
      shown = Math.min(full.length, shown + Math.max(1, Math.round((elapsed * rate) / 1000)));
      paint();

      if (shown < full.length) schedule();
      else settle();
    }

    return {
      push: function (chunk) {
        full += chunk || "";

        // Someone who has asked for less motion is asking for the answer, not the effect.
        if (reducedMotion && reducedMotion.matches) {
          shown = full.length;
          paint();
          return;
        }
        if (timer === null) previous = 0;
        schedule();
      },
      /** Resolves once every token received has been shown. */
      close: function () {
        if (shown >= full.length) {
          stop();
          paint();
          return Promise.resolve();
        }
        return new Promise(function (resolve) {
          drained = resolve;
        });
      },
    };
  }

  function setBusy(busy) {
    els.send.disabled = busy;
    els.input.disabled = busy;
  }

  /* ------------------------------------------------------------- escalation -- */

  var escalationSource = "visitor_contact_form";

  function openContactForm(source) {
    escalationSource = source || "visitor_contact_form";
    els.body.classList.add("contacting");
    els.contact.hidden = false;
    // Pre-filled with what they just asked, so escalating mid-conversation does not mean
    // typing the question out a second time.
    if (!els.contactMessage.value) els.contactMessage.value = lastQuestion;
    els.contactEmail.focus();
    scrollToEnd();
  }

  function closeContactForm() {
    els.body.classList.remove("contacting");
    els.contact.hidden = true;
    els.input.focus();
  }

  els.human.addEventListener("click", function () {
    openContactForm("visitor_contact_form");
  });
  els.contactCancel.addEventListener("click", closeContactForm);

  els.contact.addEventListener("submit", function (event) {
    event.preventDefault();

    var email = els.contactEmail.value.trim();
    if (!email) {
      els.contactEmail.focus();
      return;
    }

    // Read before the form is reset below, so the echoed bubble is not an empty string.
    var body = els.contactMessage.value.trim();
    els.contactSend.disabled = true;

    siteResolved
      .then(function () {
        return fetch(TICKET_URL, {
          method: "POST",
          headers: apiHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            email: email,
            name: els.contactName.value.trim() || null,
            message: body || null,
            session_id: sessionId(),
            source: escalationSource,
            escalation_reason: escalationSource === "ai_escalation" ? "no_grounded_answer" : null,
          }),
        });
      })
      .then(function (response) {
        if (!response.ok) {
          return response
            .json()
            .catch(function () {
              return null;
            })
            .then(function (body) {
              throw new Error(
                (body && body.error && body.error.message) ||
                  "Sorry, we could not send that just now.",
              );
            });
        }
        return response.json();
      })
      .then(function (created) {
        ticketOpen = true;
        // The reply arrives here, not by email — so this id has to survive the tab closing.
        rememberSession(sessionId());
        closeContactForm();
        els.contact.reset();
        els.human.disabled = true;

        if (body) bubble("user", body);
        notice(
          "Thanks — a person will pick this up. Their reply appears here when you next open this chat.",
        );
        return created;
      })
      .catch(function (error) {
        bubble("error", error.message || "Something went wrong.");
      })
      .finally(function () {
        els.contactSend.disabled = false;
      });
  });

  /** Minimal SSE frame parser; EventSource cannot be used because this is a POST. */
  function consumeStream(response, handlers) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";

    function pump() {
      return reader.read().then(function (result) {
        if (result.done) return;
        buffer += decoder.decode(result.value, { stream: true });

        var frames = buffer.split("\n\n");
        buffer = frames.pop();

        frames.forEach(function (frame) {
          var event = "message";
          var data = "";
          frame.split("\n").forEach(function (line) {
            if (line.indexOf("event:") === 0) event = line.slice(6).trim();
            else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
          });
          if (!data) return;
          try {
            handlers(event, JSON.parse(data));
          } catch (error) {
            console.error("[chat-widget] bad frame", error);
          }
        });

        return pump();
      });
    }

    return pump();
  }

  function send(question) {
    bubble("user", question);
    lastQuestion = question;
    setBusy(true);

    var pending = typingIndicator();
    var answer = null;
    // Held until the typewriter has caught up: offering a person while the assistant is still
    // visibly answering reads as an interruption, and the flag is decided long before the
    // last character is on screen.
    var escalate = false;

    siteResolved
      .then(function () {
        return fetch(CHAT_URL, {
          method: "POST",
          headers: apiHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ message: question, session_id: sessionId() }),
        });
      })
      .then(function (response) {
        if (!response.ok || !response.body) {
          return response
            .json()
            .catch(function () {
              return null;
            })
            .then(function (body) {
              var message =
                (body && body.error && body.error.message) ||
                "Sorry, I could not reach the assistant.";
              throw new Error(message);
            });
        }

        return consumeStream(response, function (event, data) {
          if (event === "sources") {
            renderSources(data.sources);
          } else if (event === "token") {
            if (!answer) {
              pending.remove();
              answer = typewriter(markdownBubble("bot"));
            }
            answer.push(data.content);
          } else if (event === "done") {
            // Zero chunks were retrieved, so the assistant has just said it does not know.
            // Offering a person here is the whole point of the signal.
            if (data.can_escalate) escalate = true;
          } else if (event === "error") {
            pending.remove();
            bubble("error", data.message || "Something went wrong.");
          }
        });
      })
      // The network is finished; wait for the display to be.
      .then(function () {
        return answer ? answer.close() : null;
      })
      .catch(function (error) {
        bubble("error", error.message || "Something went wrong.");
      })
      .finally(function () {
        if (pending.isConnected) pending.remove();
        if (escalate) offerEscalation();
        setBusy(false);
        els.input.focus();
      });
  }

  els.form.addEventListener("submit", function (event) {
    event.preventDefault();
    var question = els.input.value.trim();
    if (!question) return;
    els.input.value = "";
    send(question);
  });

  els.input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.form.requestSubmit();
    }
  });

  /**
   * Replay a returning visitor's transcript.
   *
   * Only reached when the browser already held a session id, and the server only answers for
   * the chatbot whose public key authorised this call — so this shows the visitor their own
   * conversation and the reply it earned, never anyone else's.
   */
  function restore(state) {
    if (!state || !state.messages || !state.messages.length) return false;

    state.messages.forEach(function (message) {
      if (message.role === "staff") {
        staffBubble(message.content);
      } else if (message.role === "user") {
        bubble("user", message.content);
        lastQuestion = message.content;
      } else {
        // Rendered, not replayed character by character: this is history, and typing out a
        // conversation the visitor has already had would be theatre.
        botBubble(message.content);
      }
    });

    if (state.ticket_status) {
      // A finished ticket must not lock the affordance: the backend deliberately allows a
      // conversation to be escalated again, and telling someone to "ask anything else" while
      // greying out the only way to reach a person would be the widget contradicting itself.
      var settled = state.ticket_status === "resolved" || state.ticket_status === "closed";
      ticketOpen = !settled;
      els.human.disabled = !settled;
      notice(
        settled
          ? "Your earlier request was marked done. Ask anything else below."
          : "A person has your request. Their reply appears here.",
      );
    }
    return true;
  }

  siteResolved
    .then(function () {
      // Sent only when this browser already has one; a first-time visitor asks for nothing
      // but the chatbot's own configuration, exactly as before.
      //
      // A header, never a query string: this value replays a transcript, and a URL ends up in
      // ingress logs, browser history and `Referer` headers.
      var existing = sessionStorage.getItem(SESSION_STORAGE_KEY) || readRemembered();
      var headers = apiHeaders();
      if (existing) headers["X-Widget-Session"] = existing;
      return fetch(API_BASE + "/public/widget/bootstrap", { headers: headers });
    })
    .then(function (response) {
      if (response.ok) return response.json();
      // A refusal has to be read, not just counted: the body carries which refusal it is, and
      // only some of them mean the widget should take itself away. An unparseable body is
      // treated as a transient failure, which is the forgiving half of the choice.
      return response
        .json()
        .catch(function () {
          return null;
        })
        .then(function (body) {
          var code = ((body || {}).error || {}).code;
          if (FATAL[code]) disable();
          return null;
        });
    })
    .then(function (config) {
      if (!config) return;
      els.title.textContent = config.name || TITLE;
      // After the title, because the campaign source is whatever the header ended up saying.
      els.brand.href = brandHref(els.title.textContent);
      renderLegal(config.privacy_url, config.terms_url);
      applyTheme(config.theme || {});
      // The greeting would be a strange thing to say to someone mid-conversation.
      if (!restore(config.session)) botBubble(config.greeting);
    })
    .catch(function () {
      /* The greeting and the theme are cosmetic; a failure here must not block the
         composer, and the stylesheet's own defaults are a perfectly good fallback. */
    })
    .finally(ready);

  notifyHost(false);
})();

(function () {
  "use strict";
  var root = document.documentElement;

  // ---- Theme toggle: auto -> light -> dark (remembered per viewer, optional) ----
  var THEME_KEY = "hiring-prep:theme";
  var themeBtn = document.getElementById("themeBtn");
  function readTheme() { try { return localStorage.getItem(THEME_KEY) || "auto"; } catch (e) { return "auto"; } }
  function applyTheme(t) {
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t); else root.removeAttribute("data-theme");
    if (themeBtn) themeBtn.textContent = (themeBtn.getAttribute("data-label") || "Theme") + ": " + t;
  }
  var theme = readTheme();
  applyTheme(theme);
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      theme = theme === "auto" ? "light" : theme === "light" ? "dark" : "auto";
      try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* storage unavailable */ }
      applyTheme(theme);
    });
  }

  // ---- Screenshot helpers (display only, nothing is saved) ----
  // #demo shows only the quiz with two questions pre-answered (one right, one wrong).
  // #focus-<section> shows only that section, e.g. #focus-overview.
  var hash = window.location.hash;
  var demo = hash === "#demo";
  var focusId = demo ? "exam" : (/^#focus-[a-z]+$/.test(hash) ? hash.slice(7) : null);
  if (focusId) {
    var keep = document.getElementById(focusId);
    if (keep && keep.parentNode && keep.parentNode.tagName === "MAIN") {
      root.setAttribute("data-focus", demo ? "quiz" : "section");
      Array.prototype.forEach.call(keep.parentNode.children, function (sec) { if (sec !== keep) sec.hidden = true; });
    }
  }

  // ---- Quiz data (JSON, rendered with createElement/textContent only) ----
  var dataEl = document.getElementById("quiz-data");
  var quiz = document.getElementById("quiz");
  if (!dataEl || !quiz) return;
  var DATA;
  try { DATA = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var Q = DATA.mcq || [], S = DATA.sections || [], L = DATA.labels || {};
  var LETTERS = ["A", "B", "C", "D"];
  var LS = DATA.storage_key;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function safeHref(u) {
    try { var x = new URL(u); return (x.protocol === "http:" || x.protocol === "https:") ? x.href : null; }
    catch (e) { return null; }
  }
  // Rich text arrives pre-tokenized by the build script: a plain string, or a
  // list of [kind, text, href?] tokens. Nothing is ever parsed as HTML.
  function rich(parent, value) {
    if (typeof value === "string") { parent.appendChild(document.createTextNode(value)); return parent; }
    (Array.isArray(value) ? value : []).forEach(function (tok) {
      var kind = tok[0], text = String(tok[1] == null ? "" : tok[1]), node;
      if (kind === "b") node = el("strong", null, text);
      else if (kind === "i") node = el("em", null, text);
      else if (kind === "c") node = el("code", null, text);
      else if (kind === "a") {
        var h = safeHref(tok[2]);
        if (h) { node = el("a", null, text); node.href = h; node.target = "_blank"; node.rel = "noopener noreferrer"; }
        else node = document.createTextNode(text);
      } else node = document.createTextNode(text);
      parent.appendChild(node);
    });
    return parent;
  }

  var state = { ans: {}, study: false };
  if (!demo) {
    try {
      var saved = JSON.parse(localStorage.getItem(LS) || "null");
      if (saved && typeof saved === "object" && saved.ans && typeof saved.ans === "object") {
        state.ans = {};
        Object.keys(saved.ans).forEach(function (k) {
          var v = saved.ans[k];
          if (/^\d+$/.test(k) && +k < Q.length && v >= 0 && v <= 3 && v === Math.floor(v)) state.ans[k] = v;
        });
        state.study = saved.study === true;
      }
    } catch (e) { /* storage unavailable or corrupt */ }
  } else if (Q.length > 1) {
    // Screenshot mode: first question right, second wrong. Never saved.
    state.ans[0] = Q[0].a;
    state.ans[1] = (Q[1].a + 1) % 4;
  }
  function save() {
    if (demo) return;
    try { localStorage.setItem(LS, JSON.stringify(state)); } catch (e) { /* storage unavailable */ }
  }

  // ---- Build the DOM ----
  var nav = document.getElementById("secNav");
  var n = 0;
  S.forEach(function (sec, si) {
    var count = Q.filter(function (q) { return q.s === sec.id; }).length;
    if (!count) return;
    if (nav) {
      var a = el("a");
      a.href = "#sec-" + sec.id;
      a.appendChild(el("b", null, String(si + 1)));
      rich(a, sec.title);
      nav.appendChild(a);
    }
    var box = el("section", "grp");
    box.id = "sec-" + sec.id;
    rich(box.appendChild(el("h4")), sec.title);
    if (sec.dek && sec.dek.length) rich(box.appendChild(el("p", "grp-dek")), sec.dek);
    Q.forEach(function (item, qi) {
      if (item.s !== sec.id) return;
      n++;
      var card = el("div", "mcq");
      card.setAttribute("data-qi", String(qi));
      var qp = el("p", "q");
      qp.appendChild(el("span", "qn", String(n)));
      var qt = el("span");
      qt.id = "q" + qi + "-text";
      rich(qt, item.q);
      qp.appendChild(qt);
      card.appendChild(qp);
      var opts = el("div", "opts");
      opts.setAttribute("role", "group");
      opts.setAttribute("aria-labelledby", qt.id);
      item.o.forEach(function (opt, oi) {
        var b = el("button", "opt");
        b.type = "button";
        b.setAttribute("data-oi", String(oi));
        b.setAttribute("aria-pressed", "false");
        b.appendChild(el("span", "k", LETTERS[oi]));
        rich(b.appendChild(el("span")), opt);
        opts.appendChild(b);
      });
      card.appendChild(opts);
      var v = el("p", "verdict"); v.hidden = true; card.appendChild(v);
      var why = el("div", "why"); why.hidden = true;
      (item.e || []).forEach(function (para) { rich(why.appendChild(el("p")), para); });
      var key = el("div", "key");
      key.appendChild(el("span", "tag", L.key_point || "Key point"));
      rich(key, item.k);
      why.appendChild(key);
      card.appendChild(why);
      box.appendChild(card);
    });
    quiz.appendChild(box);
  });

  var scoreEl = document.getElementById("score");
  var meter = document.getElementById("meter");
  var fill = document.getElementById("meterFill");
  var studyBtn = document.getElementById("studyBtn");
  var resetBtn = document.getElementById("resetBtn");
  var fin = document.getElementById("final");
  var verdicts = (DATA.verdicts || []).slice().sort(function (x, y) { return y.min - x.min; });

  function paint() {
    var answered = 0, right = 0;
    var cards = quiz.querySelectorAll(".mcq");
    Array.prototype.forEach.call(cards, function (card) {
      var qi = +card.getAttribute("data-qi"), item = Q[qi], pick = state.ans[qi];
      var has = pick !== undefined, show = has || state.study;
      card.classList.toggle("done", has);
      Array.prototype.forEach.call(card.querySelectorAll(".opt"), function (b) {
        var oi = +b.getAttribute("data-oi");
        b.classList.toggle("right", show && oi === item.a);
        b.classList.toggle("wrong", has && oi === pick && pick !== item.a);
        b.setAttribute("aria-pressed", has && oi === pick ? "true" : "false");
      });
      var v = card.querySelector(".verdict"), why = card.querySelector(".why");
      v.hidden = !show; why.hidden = !show;
      if (has) {
        answered++;
        if (pick === item.a) { right++; v.className = "verdict ok"; v.textContent = L.correct || "Correct"; }
        else { v.className = "verdict ko"; v.textContent = (L.wrong || "Wrong. Correct answer:") + " " + LETTERS[item.a]; }
      } else if (state.study) {
        v.className = "verdict study"; v.textContent = (L.answer || "Answer:") + " " + LETTERS[item.a];
      }
    });
    var total = Q.length;
    scoreEl.textContent = "";
    scoreEl.appendChild(document.createTextNode(right + " " + (L.right_of || "right of") + " " + answered + " " + (L.answered || "answered") + " \u00b7 " + total + " " + (L.questions || "questions")));
    if (answered) scoreEl.appendChild(el("span", "pct", Math.round(right / answered * 100) + "%"));
    fill.style.width = (total ? answered / total * 100 : 0) + "%";
    meter.setAttribute("aria-valuenow", String(answered));
    studyBtn.setAttribute("aria-pressed", state.study ? "true" : "false");
    fin.hidden = answered < total || !total;
    if (total && answered === total) {
      var p = right / total, band = null;
      for (var i = 0; i < verdicts.length; i++) { if (p >= verdicts[i].min) { band = verdicts[i]; break; } }
      document.getElementById("finalTitle").textContent = right + " / " + total + " (" + Math.round(p * 100) + "%)" + (band ? " \u00b7 " + band.title : "");
      document.getElementById("finalText").textContent = band ? band.text : "";
    }
  }

  quiz.addEventListener("click", function (ev) {
    var b = ev.target.closest ? ev.target.closest(".opt") : null;
    if (!b) return;
    var card = b.closest(".mcq"), qi = +card.getAttribute("data-qi");
    if (state.ans[qi] !== undefined) return;
    state.ans[qi] = +b.getAttribute("data-oi");
    save(); paint();
  });
  studyBtn.addEventListener("click", function () { state.study = !state.study; save(); paint(); });
  resetBtn.addEventListener("click", function () {
    state = { ans: {}, study: false }; save(); paint();
    var top = document.getElementById("exam-quiz");
    if (top && top.scrollIntoView) top.scrollIntoView();
  });
  paint();
})();

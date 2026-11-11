/* An eye button inside every password box: click to show or hide what was typed. */
(function () {
  "use strict";
  var EYE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.600-7 10-7 10 7 10 7-3.600 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.600-7 10-7 10 7 10 7-3.600 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path d="M4 4l16 16"/></svg>';

  function add(input) {
    var wrap = document.createElement("span");
    wrap.style.cssText = "position:relative;display:" +
      (getComputedStyle(input).display === "block" ? "block" : "inline-block");
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.style.paddingRight = "42px";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.style.cssText = "position:absolute;right:6px;top:50%;transform:translateY(-50%);" +
      "width:32px;height:32px;padding:0;margin:0;border:0;background:none;color:inherit;" +
      "opacity:.65;cursor:pointer;display:flex;align-items:center;justify-content:center";
    function draw() {
      var hidden = input.type === "password";
      btn.innerHTML = hidden ? EYE : EYE_OFF;
      btn.title = hidden ? "Show password" : "Hide password";
      btn.setAttribute("aria-label", btn.title);
    }
    btn.addEventListener("click", function () {
      input.type = input.type === "password" ? "text" : "password";
      draw();
      input.focus();
    });
    draw();
    wrap.appendChild(btn);
  }

  function run() {
    Array.prototype.forEach.call(document.querySelectorAll('input[type="password"]'), add);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();

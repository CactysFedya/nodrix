(function () {
  "use strict";

  function docsLocation() {
    var match = window.location.pathname.match(/^(.*)\/(en|ru)\/latest\/(.*)$/);
    if (!match) {
      return null;
    }
    return {
      base: match[1],
      language: match[2],
      page: match[3] || "index.html",
    };
  }

  function targetPage(language, page) {
    var russianPages = new Set([
      "index.html",
      "getting-started/index.html",
      "tutorials/index.html",
      "how-to-guides/index.html",
      "concepts/index.html",
      "reference/index.html",
      "integrations/index.html",
      "contributing.html",
      "release-notes.html",
      "genindex.html",
      "search.html",
    ]);

    if (language === "ru" && !russianPages.has(page)) {
      return "index.html";
    }
    return page;
  }

  function installSwitcher() {
    var location = docsLocation();
    var container = document.querySelector(".wy-side-nav-search");
    if (!location || !container || container.querySelector(".plyctl-language-switcher")) {
      return;
    }

    var wrapper = document.createElement("div");
    wrapper.className = "plyctl-language-switcher";

    var label = document.createElement("label");
    label.setAttribute("for", "plyctl-doc-language");
    label.textContent = location.language === "ru" ? "Язык" : "Language";

    var select = document.createElement("select");
    select.id = "plyctl-doc-language";
    select.setAttribute("aria-label", label.textContent);

    [["en", "English"], ["ru", "Русский"]].forEach(function (item) {
      var option = document.createElement("option");
      option.value = item[0];
      option.textContent = item[1];
      option.selected = item[0] === location.language;
      select.appendChild(option);
    });

    select.addEventListener("change", function () {
      var language = select.value;
      var page = targetPage(language, location.page);
      window.location.href = location.base + "/" + language + "/latest/" + page;
    });

    wrapper.appendChild(label);
    wrapper.appendChild(select);
    container.appendChild(wrapper);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installSwitcher);
  } else {
    installSwitcher();
  }
})();

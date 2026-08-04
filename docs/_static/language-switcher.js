(function () {
  "use strict";

  function mappedPath(targetLanguage) {
    var path = window.location.pathname;
    var marker = /\/(en|ru)\/latest\//;
    if (marker.test(path)) {
      return path.replace(marker, "/" + targetLanguage + "/latest/");
    }
    return "/nodrix/" + targetLanguage + "/latest/";
  }

  function installSwitcher() {
    var host = document.querySelector(".wy-side-nav-search");
    if (!host || document.getElementById("plyctl-language-switcher")) {
      return;
    }

    var current = window.location.pathname.indexOf("/ru/latest/") !== -1 ? "ru" : "en";
    var wrapper = document.createElement("div");
    wrapper.id = "plyctl-language-switcher";
    wrapper.className = "plyctl-language-switcher";

    var label = document.createElement("label");
    label.setAttribute("for", "plyctl-language-select");
    label.textContent = current === "ru" ? "Язык" : "Language";

    var select = document.createElement("select");
    select.id = "plyctl-language-select";
    select.setAttribute("aria-label", label.textContent);
    [
      ["en", "English"],
      ["ru", "Русский"],
    ].forEach(function (item) {
      var option = document.createElement("option");
      option.value = item[0];
      option.textContent = item[1];
      option.selected = item[0] === current;
      select.appendChild(option);
    });

    select.addEventListener("change", function () {
      window.location.assign(mappedPath(select.value));
    });

    wrapper.appendChild(label);
    wrapper.appendChild(select);
    host.appendChild(wrapper);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installSwitcher);
  } else {
    installSwitcher();
  }
})();

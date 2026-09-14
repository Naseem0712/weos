/**
 * WEOS Engineering Masters UI — Series / Profiles / Glass / Hardware / Accessories.
 * Outside canvas. Costing Engine not included (cost-basis fields display only).
 */
(function (global) {
  "use strict";
  var C = (global.WEOSCanvas = global.WEOSCanvas || {});

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function sessionHeaders() {
    var h = { Accept: "application/json", "Content-Type": "application/json" };
    try {
      var tok =
        (global.WEOS && global.WEOS.sessionToken) ||
        global.localStorage.getItem("weos_session") ||
        "";
      if (tok) h["X-WEOS-Session"] = tok;
    } catch (e) {}
    return h;
  }

  function gstQ() {
    try {
      var g = (global.WEOS && global.WEOS.companyGst) || global.localStorage.getItem("weos_gst") || "";
      return g ? "?gst=" + encodeURIComponent(g) : "";
    } catch (e) {
      return "";
    }
  }

  async function api(path, opts) {
    var res = await fetch(path + (path.indexOf("?") >= 0 ? "" : gstQ()), Object.assign({ headers: sessionHeaders() }, opts || {}));
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = { detail: res.statusText };
    }
    if (!res.ok) throw new Error((data && data.detail) || res.statusText || "request failed");
    return data;
  }

  function tabBar(active) {
    var tabs = [
      ["series", "Series"],
      ["profiles", "Profiles"],
      ["glass", "Glass"],
      ["hardware", "Hardware"],
      ["accessories", "Accessories"],
    ];
    return (
      '<div class="eng-master__tabs" role="tablist">' +
      tabs
        .map(function (t) {
          return (
            '<button type="button" class="weos-ds-btn weos-ds-btn--sm' +
            (active === t[0] ? "" : " weos-ds-btn--ghost") +
            '" data-eng-tab="' +
            t[0] +
            '">' +
            t[1] +
            "</button>"
          );
        })
        .join("") +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnEngSeed">Seed defaults</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnEngImport">Import legacy</button>' +
      "</div>"
    );
  }

  function renderShell(active, bodyHtml) {
    return (
      '<div class="eng-master" data-batch="ENG-MASTER">' +
      '<div class="eng-master__head">' +
      "<div><strong>Engineering Masters</strong>" +
      '<p class="muted" style="margin:.2rem 0 0;font-size:.8rem">Series, profiles, glass, hardware &amp; accessories — cost basis foundation only (no costing engine).</p></div>' +
      "</div>" +
      tabBar(active) +
      '<div class="eng-master__body" id="engMasterBody">' +
      (bodyHtml || "") +
      "</div></div>"
    );
  }

  function table(headers, rows) {
    return (
      '<div class="eng-master__table-wrap"><table class="eng-master__table"><thead><tr>' +
      headers.map(function (h) {
        return "<th>" + esc(h) + "</th>";
      }).join("") +
      "</tr></thead><tbody>" +
      (rows.length
        ? rows.join("")
        : '<tr><td colspan="' + headers.length + '" class="muted">No records</td></tr>') +
      "</tbody></table></div>"
    );
  }

  async function loadSeries(host) {
    var data = await api("/api/engineering/series");
    var rows = (data.series || []).map(function (s) {
      return (
        "<tr data-series-id=\"" +
        esc(s.seriesId) +
        '"><td>' +
        esc(s.code) +
        "</td><td>" +
        esc(s.name) +
        "</td><td>" +
        esc(s.family) +
        "</td><td>" +
        esc((s.productTypes || []).join(", ")) +
        "</td><td>" +
        esc(s.systemDepthMm != null ? s.systemDepthMm + " mm" : "—") +
        '</td><td><button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-eng-edit-series="' +
        esc(s.seriesId) +
        '">Role map</button></td></tr>'
      );
    });
    host.innerHTML = renderShell(
      "series",
      '<div class="eng-master__toolbar">' +
        '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnEngNewSeries">+ Series</button></div>' +
        table(["Code", "Name", "Family", "Types", "Depth", ""], rows) +
        '<div id="engSeriesEditor" class="eng-master__editor hidden"></div>'
    );
    bindCommon(host);
    var btn = host.querySelector("#btnEngNewSeries");
    if (btn)
      btn.onclick = async function () {
        var code = global.prompt("Series code (e.g. 29mm_sliding)");
        var name = code && global.prompt("Display name", code);
        if (!code || !name) return;
        await api("/api/engineering/series", {
          method: "POST",
          body: JSON.stringify({ code: code, name: name, family: "WINDOW", productTypes: ["SLIDING", "FIXED"] }),
        });
        loadSeries(host);
      };
    host.querySelectorAll("[data-eng-edit-series]").forEach(function (b) {
      b.onclick = function () {
        openSeriesEditor(host, b.getAttribute("data-eng-edit-series"));
      };
    });
  }

  async function openSeriesEditor(host, seriesId) {
    var data = await api("/api/engineering/series/" + encodeURIComponent(seriesId));
    var profiles = await api("/api/engineering/profiles");
    var ed = host.querySelector("#engSeriesEditor");
    if (!ed) return;
    ed.classList.remove("hidden");
    var opts = (profiles.profiles || [])
      .map(function (p) {
        return '<option value="' + esc(p.profileId) + '">' + esc(p.code + " — " + p.name) + "</option>";
      })
      .join("");
    var maps = (data.roleMappings || [])
      .map(function (m) {
        return "<li><code>" + esc(m.role) + "</code> → " + esc(m.profileId) + "</li>";
      })
      .join("");
    ed.innerHTML =
      "<h4>Series role mapping — " +
      esc(data.name) +
      "</h4>" +
      "<ul>" +
      (maps || "<li class='muted'>No mappings</li>") +
      "</ul>" +
      '<div class="eng-master__form-row">' +
      '<input id="engRoleName" placeholder="Role e.g. OUTER_FRAME" />' +
      '<select id="engRoleProfile">' +
      opts +
      "</select>" +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnEngAddRole">Map</button>' +
      "</div>";
    ed.querySelector("#btnEngAddRole").onclick = async function () {
      var role = (ed.querySelector("#engRoleName") || {}).value;
      var pid = (ed.querySelector("#engRoleProfile") || {}).value;
      if (!role || !pid) return;
      await api("/api/engineering/series/" + encodeURIComponent(seriesId) + "/role-mappings", {
        method: "POST",
        body: JSON.stringify({ role: role, profileId: pid }),
      });
      openSeriesEditor(host, seriesId);
    };
  }

  async function loadProfiles(host) {
    var data = await api("/api/engineering/profiles");
    var rows = (data.profiles || []).map(function (p) {
      return (
        "<tr><td>" +
        esc(p.code) +
        "</td><td>" +
        esc(p.name) +
        "</td><td>" +
        esc(p.defaultRole || "—") +
        "</td><td>" +
        esc(p.weightPerRmt != null ? p.weightPerRmt + " kg/rmt" : "—") +
        "</td><td>" +
        esc(p.stockLengthMm != null ? p.stockLengthMm + " mm" : "—") +
        "</td><td>" +
        esc((p.costBasisType || "—") + (p.costBasisValue != null ? " " + p.costBasisValue : "")) +
        "</td></tr>"
      );
    });
    host.innerHTML = renderShell(
      "profiles",
      '<div class="eng-master__toolbar">' +
        '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnEngNewProfile">+ Profile</button></div>' +
        table(["Code", "Name", "Role", "Weight", "Stock", "Cost basis"], rows)
    );
    bindCommon(host);
    var btn = host.querySelector("#btnEngNewProfile");
    if (btn)
      btn.onclick = async function () {
        var code = global.prompt("Profile code");
        var name = code && global.prompt("Name", code);
        var role = code && global.prompt("Default role", "OUTER_FRAME");
        var wpr = code && global.prompt("Weight per RMT (kg)", "0.75");
        if (!code || !name) return;
        await api("/api/engineering/profiles", {
          method: "POST",
          body: JSON.stringify({
            code: code,
            name: name,
            defaultRole: role,
            roles: [role],
            weightPerRmt: parseFloat(wpr) || 0,
            stockLengthMm: 5800,
            costBasisType: "PER_KG",
          }),
        });
        loadProfiles(host);
      };
  }

  async function loadGlass(host) {
    var data = await api("/api/engineering/glass");
    var rows = (data.glass || []).map(function (g) {
      return (
        "<tr><td>" +
        esc(g.code) +
        "</td><td>" +
        esc(g.name) +
        "</td><td>" +
        esc(g.makeup || "—") +
        "</td><td>" +
        esc(g.thicknessMm != null ? g.thicknessMm + " mm" : "—") +
        "</td><td>" +
        esc(g.costBasisType || "—") +
        "</td></tr>"
      );
    });
    host.innerHTML = renderShell("glass", table(["Code", "Name", "Makeup", "Thickness", "Cost basis"], rows));
    bindCommon(host);
  }

  async function loadHardware(host) {
    var data = await api("/api/engineering/hardware");
    var rows = (data.hardware || []).map(function (h) {
      return (
        "<tr><td>" +
        esc(h.code) +
        "</td><td>" +
        esc(h.name) +
        "</td><td>" +
        esc(h.unit) +
        "</td><td>" +
        esc(h.costBasisType || "—") +
        "</td></tr>"
      );
    });
    host.innerHTML = renderShell(
      "hardware",
      table(["Code", "Name", "Unit", "Cost basis"], rows) +
        "<p class='muted' style='margin-top:.5rem'>" +
        (data.rules || []).length +
        " hardware rules registered</p>"
    );
    bindCommon(host);
  }

  async function loadAccessories(host) {
    var data = await api("/api/engineering/accessories");
    var rows = (data.accessories || []).map(function (a) {
      return (
        "<tr><td>" +
        esc(a.kind) +
        "</td><td>" +
        esc(a.code) +
        "</td><td>" +
        esc(a.name) +
        "</td><td>" +
        esc(a.unit) +
        "</td></tr>"
      );
    });
    host.innerHTML = renderShell("accessories", table(["Kind", "Code", "Name", "Unit"], rows));
    bindCommon(host);
  }

  function bindCommon(host) {
    host.querySelectorAll("[data-eng-tab]").forEach(function (b) {
      b.onclick = function () {
        mount(host, b.getAttribute("data-eng-tab"));
      };
    });
    var seed = host.querySelector("#btnEngSeed");
    if (seed)
      seed.onclick = async function () {
        await api("/api/engineering/seed", { method: "POST", body: "{}" });
        mount(host, "series");
      };
    var imp = host.querySelector("#btnEngImport");
    if (imp)
      imp.onclick = async function () {
        var r = await api("/api/engineering/import-legacy", { method: "POST", body: "{}" });
        global.alert(
          "Import: created " +
            (r.created || []).length +
            ", matched " +
            (r.matched || []).length +
            ", conflicts " +
            (r.conflicts || []).length +
            ", rejected " +
            (r.rejected || []).length +
            ", review " +
            (r.manualReview || []).length
        );
        mount(host, "series");
      };
  }

  function mount(host, tab) {
    tab = tab || "series";
    var loaders = {
      series: loadSeries,
      profiles: loadProfiles,
      glass: loadGlass,
      hardware: loadHardware,
      accessories: loadAccessories,
    };
    (loaders[tab] || loadSeries)(host).catch(function (err) {
      host.innerHTML = renderShell(tab, '<p class="err">' + esc(err.message || err) + "</p>");
      bindCommon(host);
    });
  }

  C.engineeringMasters = { mount: mount, renderShell: renderShell };
})(typeof window !== "undefined" ? window : globalThis);

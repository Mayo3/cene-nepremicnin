// A building's photo from Street View, requested only when a visitor asks for it. Used by map.js and by the sale
// tables, whose rows carry data-at="lat,lon". Without a key (data-streetview-key on <body>) there are no photos and
// no buttons; where Google has no imagery (return_error_code makes that a 404) a short note takes the photo's place.
(() => {
  window.buildingPhoto = (at, address) => {
    const box = document.createElement("div");
    box.className = "photo";
    const key = document.body.dataset.streetviewKey;
    if (key) {
      const img = document.createElement("img");
      const caption = document.createElement("div");
      img.alt = `Stavba: ${address} (Google Street View)`;
      img.addEventListener("error", () => { img.remove(); caption.textContent = "Za to stavbo slike ni na voljo."; });
      img.src = "https://maps.googleapis.com/maps/api/streetview?" +
        new URLSearchParams({ size: "640x360", location: at, source: "outdoor", return_error_code: "true", key });
      caption.className = "more";
      caption.textContent = "Približen pogled s ceste, ne prodano stanovanje.";
      box.append(img, caption);
    }
    return box;
  };

  // Sale tables: a "Slika" button on each row opens the photo in a row below it.
  if (!document.body.dataset.streetviewKey) return;
  for (const row of document.querySelectorAll("tr[data-at]")) {
    const cell = row.querySelector("td.a");
    const address = cell.textContent;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "details";
    button.textContent = "Slika";
    button.setAttribute("aria-label", `Slika stavbe: ${address}`);
    button.setAttribute("aria-expanded", "false");
    let opened = null;
    button.addEventListener("click", () => {
      if (opened) {
        opened.remove();
        opened = null;
      } else {
        opened = document.createElement("tr");
        opened.className = "photo-row";
        const td = opened.insertCell();
        td.colSpan = row.cells.length;
        td.append(window.buildingPhoto(row.dataset.at, address));
        row.after(opened);
      }
      button.setAttribute("aria-expanded", String(!!opened));
    });
    cell.append(button);
  }
})();

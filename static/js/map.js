(function () {
  const dataEl = document.getElementById("hospital-map-data");
  const mapEl = document.getElementById("hospital-map");
  if (!dataEl || !mapEl || typeof L === "undefined") {
    return;
  }

  const payload = JSON.parse(dataEl.textContent);
  const hospitals = payload.hospitals || [];
  const origin = payload.origin || { lat: 20.946, lng: 77.775, label: "Starting point" };

  const locateBtn = document.getElementById("locate-btn");
  const nearestBtn = document.getElementById("route-nearest-btn");
  const statusEl = document.getElementById("map-status");
  const listEl = document.getElementById("hospital-list");

  let userLatLng = null;
  let routeLayer = null;
  const markers = {};

  const map = L.map(mapEl, { scrollWheelZoom: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  const originIcon = L.divIcon({
    className: "map-pin origin",
    html: "<span>You</span>",
    iconSize: [44, 28],
    iconAnchor: [22, 14],
  });
  const hospitalIcon = L.divIcon({
    className: "map-pin hospital-pin",
    html: "<span>H</span>",
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });

  const originMarker = L.marker([origin.lat, origin.lng], { icon: originIcon })
    .addTo(map)
    .bindPopup(origin.label);

  const bounds = L.latLngBounds([[origin.lat, origin.lng]]);

  hospitals.forEach(function (hospital) {
    if (hospital.lat == null || hospital.lng == null) {
      return;
    }
    const marker = L.marker([hospital.lat, hospital.lng], { icon: hospitalIcon }).addTo(map);
    marker.bindPopup(popupHtml(hospital, origin.lat, origin.lng));
    marker.on("click", function () {
      highlightCard(hospital.id);
      drawRoute(originMarker.getLatLng(), L.latLng(hospital.lat, hospital.lng), hospital);
    });
    markers[hospital.id] = marker;
    bounds.extend([hospital.lat, hospital.lng]);
  });

  if (bounds.isValid()) {
    map.fitBounds(bounds.pad(0.18));
  } else {
    map.setView([origin.lat, origin.lng], 12);
  }
  setTimeout(function () {
    map.invalidateSize();
  }, 200);

  function popupHtml(hospital, fromLat, fromLng) {
    const mapsUrl = directionsUrl(fromLat, fromLng, hospital.lat, hospital.lng);
    return (
      "<strong>" +
      escapeHtml(hospital.name) +
      "</strong><br>" +
      escapeHtml(hospital.address) +
      "<br><a href=\"" +
      mapsUrl +
      "\" target=\"_blank\" rel=\"noopener\">Open turn-by-turn directions</a>"
    );
  }

  function directionsUrl(fromLat, fromLng, toLat, toLng) {
    return (
      "https://www.google.com/maps/dir/?api=1&origin=" +
      encodeURIComponent(fromLat + "," + fromLng) +
      "&destination=" +
      encodeURIComponent(toLat + "," + toLng) +
      "&travelmode=driving"
    );
  }

  function osmDirectionsUrl(fromLat, fromLng, toLat, toLng) {
    return (
      "https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=" +
      fromLat +
      "," +
      fromLng +
      ";" +
      toLat +
      "," +
      toLng
    );
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(message) {
    if (statusEl) {
      statusEl.textContent = message;
    }
  }

  function currentOrigin() {
    return userLatLng || originMarker.getLatLng();
  }

  function haversineKm(a, b) {
    const r = 6371;
    const dLat = ((b.lat - a.lat) * Math.PI) / 180;
    const dLng = ((b.lng - a.lng) * Math.PI) / 180;
    const lat1 = (a.lat * Math.PI) / 180;
    const lat2 = (b.lat * Math.PI) / 180;
    const h =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return r * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  }

  function sortedHospitals() {
    const from = currentOrigin();
    return hospitals
      .filter(function (h) {
        return h.lat != null && h.lng != null;
      })
      .map(function (h) {
        return Object.assign({}, h, {
          live_km: Math.round(haversineKm(from, { lat: h.lat, lng: h.lng }) * 10) / 10,
        });
      })
      .sort(function (a, b) {
        return a.live_km - b.live_km;
      });
  }

  function updateDistanceLabels() {
    sortedHospitals().forEach(function (hospital) {
      const card = document.querySelector('[data-hospital-id="' + hospital.id + '"]');
      if (!card) {
        return;
      }
      const value = card.querySelector("[data-distance-value]");
      if (value) {
        value.textContent = hospital.live_km;
      }
      const maps = card.querySelector("[data-maps-link]");
      const from = currentOrigin();
      if (maps) {
        maps.href = directionsUrl(from.lat, from.lng, hospital.lat, hospital.lng);
      }
      const osm = card.querySelector("[data-osm-link]");
      if (osm) {
        osm.href = osmDirectionsUrl(from.lat, from.lng, hospital.lat, hospital.lng);
      }
      const marker = markers[hospital.id];
      if (marker) {
        marker.setPopupContent(popupHtml(hospital, from.lat, from.lng));
      }
    });
  }

  function highlightCard(id) {
    document.querySelectorAll(".hospital").forEach(function (card) {
      card.classList.toggle("is-selected", Number(card.dataset.hospitalId) === Number(id));
    });
  }

  function drawRoute(from, to, hospital) {
    const url =
      "https://router.project-osrm.org/route/v1/driving/" +
      from.lng +
      "," +
      from.lat +
      ";" +
      to.lng +
      "," +
      to.lat +
      "?overview=full&geometries=geojson";

    setStatus("Drawing the road to " + hospital.name + "…");
    fetch(url)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("route failed");
        }
        return response.json();
      })
      .then(function (data) {
        const geometry = data.routes && data.routes[0] && data.routes[0].geometry;
        if (!geometry) {
          throw new Error("no geometry");
        }
        if (routeLayer) {
          map.removeLayer(routeLayer);
        }
        routeLayer = L.geoJSON(geometry, {
          style: { color: "#0f766e", weight: 5, opacity: 0.85 },
        }).addTo(map);
        map.fitBounds(routeLayer.getBounds().pad(0.2));
        const km = (data.routes[0].distance / 1000).toFixed(1);
        const minutes = Math.max(1, Math.round(data.routes[0].duration / 60));
        setStatus("Road to " + hospital.name + ": about " + km + " km, " + minutes + " min by car.");
      })
      .catch(function () {
        if (routeLayer) {
          map.removeLayer(routeLayer);
        }
        routeLayer = L.polyline([from, to], {
          color: "#0f766e",
          weight: 4,
          dashArray: "6 8",
        }).addTo(map);
        map.fitBounds(L.latLngBounds([from, to]).pad(0.25));
        setStatus("Showing a straight line to " + hospital.name + ". Use Directions for turn-by-turn.");
      });
  }

  function routeToNearest() {
    const nearest = sortedHospitals()[0];
    if (!nearest) {
      setStatus("No mapped hospitals yet.");
      return;
    }
    highlightCard(nearest.id);
    const marker = markers[nearest.id];
    if (marker) {
      marker.openPopup();
    }
    drawRoute(currentOrigin(), L.latLng(nearest.lat, nearest.lng), nearest);
  }

  if (listEl) {
    listEl.addEventListener("click", function (event) {
      const card = event.target.closest("[data-hospital-id]");
      if (!card) {
        return;
      }
      const id = Number(card.dataset.hospitalId);
      const hospital = hospitals.find(function (item) {
        return item.id === id;
      });
      if (!hospital || hospital.lat == null) {
        return;
      }
      highlightCard(id);
      const marker = markers[id];
      if (marker) {
        marker.openPopup();
      }
      map.panTo([hospital.lat, hospital.lng]);
      if (!event.target.closest("a")) {
        drawRoute(currentOrigin(), L.latLng(hospital.lat, hospital.lng), hospital);
      }
    });
  }

  if (nearestBtn) {
    nearestBtn.addEventListener("click", routeToNearest);
  }

  if (locateBtn) {
    locateBtn.addEventListener("click", function () {
      if (!navigator.geolocation) {
        setStatus("This browser cannot share location. The map still uses the demo village.");
        return;
      }
      setStatus("Finding your location…");
      navigator.geolocation.getCurrentPosition(
        function (position) {
          userLatLng = L.latLng(position.coords.latitude, position.coords.longitude);
          originMarker.setLatLng(userLatLng);
          originMarker.setPopupContent("Your location").openPopup();
          map.panTo(userLatLng);
          updateDistanceLabels();
          setStatus("Distances now use your location. Tap a hospital or Route to nearest.");
        },
        function () {
          setStatus("Location was blocked. Distances stay based on the demo village.");
        },
        { enableHighAccuracy: true, timeout: 10000 }
      );
    });
  }

  updateDistanceLabels();
})();

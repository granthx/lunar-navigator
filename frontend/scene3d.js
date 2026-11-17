/* 3D WebGL Mission Control Dome: situational lunar terrain & orbital visualization.
   Uses Three.js to render real LOLA horizon geometry, SPICE Sun/Earth orbits,
   and dynamic line-of-sight sightlines in 3D space.
*/
(function (root) {
  "use strict";

  // Gracefully no-op in headless/Node test environments without WebGL or THREE
  if (typeof window === "undefined" || typeof document === "undefined" || !root.THREE) {
    root.Scene3D = { init: () => false, update: () => {}, setSite: () => {}, setCamera: () => {} };
    return;
  }

  var THREE = root.THREE;
  let scene, camera, renderer, controls;
  let terrainMesh, starField, landerGroup, statusHalo, sunGroup, earthGroup;
  let sunBeam, earthBeam;
  let dirLight, ambientLight;
  let currentSite = null;
  let animFrameId = 0;
  let isRunning = false;
  let wrapEl, canvasEl;

  // Constants for 3D scale
  const R_TERRAIN = 60.0;     // Horizon ring radius in 3D scene units
  const R_SUN = 100.0;        // Sun orbital distance
  const R_EARTH = 85.0;       // Earth orbital distance
  const EL_SCALE = 2.0;       // Subtle vertical exaggeration for dramatic ridge lines (matches radar displays)

  function degToRad(deg) { return (deg * Math.PI) / 180.0; }

  // Spherical az/el to 3D Cartesian coordinates
  // North is -Z, East is +X, South is +Z, West is -X, Up is +Y
  function azElToVector3(azDeg, elDeg, radius, elScale = 1.0) {
    const az = degToRad(azDeg);
    const el = degToRad(elDeg);
    const rCos = radius * Math.cos(el);
    const x = rCos * Math.sin(az);
    const y = radius * Math.sin(el) * elScale;
    const z = -rCos * Math.cos(az);
    return new THREE.Vector3(x, y, z);
  }

  function init(containerId) {
    wrapEl = document.getElementById(containerId);
    if (!wrapEl) return false;
    canvasEl = wrapEl.querySelector("canvas");
    if (!canvasEl) return false;

    try {
      const W = wrapEl.clientWidth || 800;
      const H = wrapEl.clientHeight || 420;

      // 1. Scene
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x080a10);
      scene.fog = new THREE.FogExp2(0x080a10, 0.0035);

      // 2. Camera
      camera = new THREE.PerspectiveCamera(45, W / H, 0.5, 2000);
      camera.position.set(55, 40, 65);

      // 3. Renderer
      renderer = new THREE.WebGLRenderer({
        canvas: canvasEl,
        antialias: true,
        alpha: false,
        powerPreference: "high-performance",
      });
      renderer.setSize(W, H);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;

      // 4. OrbitControls
      if (typeof THREE.OrbitControls !== "undefined") {
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.06;
        controls.maxDistance = 160;
        controls.minDistance = 6;
        controls.maxPolarAngle = Math.PI / 2 + 0.05; // Don't clip below surface
        controls.target.set(0, 3, 0);
      }

      // 5. Lighting
      ambientLight = new THREE.AmbientLight(0x182030, 0.45);
      scene.add(ambientLight);

      dirLight = new THREE.DirectionalLight(0xfff3cf, 1.6);
      dirLight.castShadow = true;
      dirLight.shadow.mapSize.width = 1024;
      dirLight.shadow.mapSize.height = 1024;
      dirLight.shadow.camera.near = 10;
      dirLight.shadow.camera.far = 250;
      const d = 50;
      dirLight.shadow.camera.left = -d;
      dirLight.shadow.camera.right = d;
      dirLight.shadow.camera.top = d;
      dirLight.shadow.camera.bottom = -d;
      scene.add(dirLight);

      // 6. Starfield
      buildStarfield();

      // 7. Base Floor & Compass Grid
      buildBaseGrid();

      // 8. 3D Artemis Lander Model
      buildLander();

      // 9. Sun & Earth Orbital Spheres
      buildCelestialBodies();

      // 10. Sightline Ray Beams
      buildBeams();

      // Resize listener
      window.addEventListener("resize", onWindowResize);

      // Render loop
      isRunning = true;
      animate();

      return true;
    } catch (err) {
      console.warn("3D WebGL initialization skipped:", err);
      return false;
    }
  }

  function buildStarfield() {
    const starCount = 1500;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(starCount * 3);
    const colors = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 400 + Math.random() * 200;

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = Math.abs(r * Math.cos(phi)) + 10; // keep above horizon
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);

      const shade = 0.75 + Math.random() * 0.25;
      colors[i * 3] = shade;
      colors[i * 3 + 1] = shade;
      colors[i * 3 + 2] = Math.min(1.0, shade + 0.1);
    }

    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: 1.6,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
    });

    starField = new THREE.Points(geometry, material);
    scene.add(starField);
  }

  function buildBaseGrid() {
    // Lunar surface circular ground mesh
    const groundGeo = new THREE.CircleGeometry(R_TERRAIN, 64);
    const groundMat = new THREE.MeshStandardMaterial({
      color: 0x111622,
      roughness: 0.95,
      metalness: 0.05,
    });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // Tactical Polar Ring Overlays
    const ringGroup = new THREE.Group();
    const rings = [15, 30, 45, R_TERRAIN];
    rings.forEach((r, idx) => {
      const ringGeo = new THREE.RingGeometry(r - 0.15, r + 0.15, 64);
      const ringMat = new THREE.MeshBasicMaterial({
        color: idx === rings.length - 1 ? 0x3a4860 : 0x1e2738,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.6,
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.rotation.x = -Math.PI / 2;
      ringMesh.position.y = 0.02;
      ringGroup.add(ringMesh);
    });

    // Cardinal Axes (North-South, East-West)
    const axisMat = new THREE.LineBasicMaterial({ color: 0x2a364a, transparent: true, opacity: 0.5 });
    const pts = [
      new THREE.Vector3(0, 0.03, -R_TERRAIN), new THREE.Vector3(0, 0.03, R_TERRAIN),
      new THREE.Vector3(-R_TERRAIN, 0.03, 0), new THREE.Vector3(R_TERRAIN, 0.03, 0),
    ];
    const axisGeo = new THREE.BufferGeometry().setFromPoints(pts);
    const axisLines = new THREE.LineSegments(axisGeo, axisMat);
    ringGroup.add(axisLines);

    scene.add(ringGroup);
  }

  function buildLander() {
    landerGroup = new THREE.Group();

    // 1. Descent Stage: Octagon body with gold foil insulation
    const baseGeo = new THREE.CylinderGeometry(1.6, 2.0, 1.2, 8);
    const goldFoilMat = new THREE.MeshStandardMaterial({
      color: 0xd4af37,
      metalness: 0.85,
      roughness: 0.25,
      bumpScale: 0.05,
    });
    const descentStage = new THREE.Mesh(baseGeo, goldFoilMat);
    descentStage.position.y = 1.2;
    descentStage.castShadow = true;
    descentStage.receiveShadow = true;
    landerGroup.add(descentStage);

    // 2. Ascent Cabin
    const cabinGeo = new THREE.CylinderGeometry(1.0, 1.3, 1.1, 8);
    const cabinMat = new THREE.MeshStandardMaterial({
      color: 0xdfdfeb,
      metalness: 0.3,
      roughness: 0.6,
    });
    const cabin = new THREE.Mesh(cabinGeo, cabinMat);
    cabin.position.y = 2.2;
    cabin.castShadow = true;
    landerGroup.add(cabin);

    // 3. Solar Panel Wings (pointing outwards)
    const solarGeo = new THREE.BoxGeometry(2.8, 0.06, 0.8);
    const solarMat = new THREE.MeshStandardMaterial({
      color: 0x1d3557,
      metalness: 0.9,
      roughness: 0.15,
      emissive: 0x081528,
    });
    const solarWing1 = new THREE.Mesh(solarGeo, solarMat);
    solarWing1.position.set(2.4, 2.0, 0);
    solarWing1.rotation.z = 0.2;
    solarWing1.castShadow = true;
    landerGroup.add(solarWing1);

    const solarWing2 = new THREE.Mesh(solarGeo, solarMat);
    solarWing2.position.set(-2.4, 2.0, 0);
    solarWing2.rotation.z = -0.2;
    solarWing2.castShadow = true;
    landerGroup.add(solarWing2);

    // 4. High-Gain Comms Antenna Dish
    const dishGeo = new THREE.CylinderGeometry(0.7, 0.1, 0.25, 16, 1, true);
    const dishMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      metalness: 0.8,
      roughness: 0.3,
      side: THREE.DoubleSide,
    });
    const antennaDish = new THREE.Mesh(dishGeo, dishMat);
    antennaDish.position.set(0.6, 3.2, 0.6);
    antennaDish.rotation.set(-0.4, 0.5, 0);
    antennaDish.castShadow = true;
    landerGroup.add(antennaDish);

    // Antenna mast
    const mastGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.8);
    const mastMat = new THREE.MeshStandardMaterial({ color: 0x888899, metalness: 0.7 });
    const mast = new THREE.Mesh(mastGeo, mastMat);
    mast.position.set(0.6, 2.8, 0.6);
    landerGroup.add(mast);

    // 5. Landing Legs (4 angled struts with round footpads)
    const legMat = new THREE.MeshStandardMaterial({ color: 0x4a4d55, metalness: 0.6 });
    for (let i = 0; i < 4; i++) {
      const angle = (i * Math.PI) / 2 + Math.PI / 4;
      const legGeo = new THREE.CylinderGeometry(0.06, 0.06, 1.8);
      const leg = new THREE.Mesh(legGeo, legMat);
      const dist = 1.6;
      leg.position.set(Math.cos(angle) * dist, 0.6, Math.sin(angle) * dist);
      leg.rotation.z = Math.cos(angle) * 0.45;
      leg.rotation.x = -Math.sin(angle) * 0.45;
      leg.castShadow = true;
      landerGroup.add(leg);

      const padGeo = new THREE.CylinderGeometry(0.25, 0.25, 0.05, 12);
      const pad = new THREE.Mesh(padGeo, goldFoilMat);
      pad.position.set(Math.cos(angle) * 2.2, 0.03, Math.sin(angle) * 2.2);
      pad.receiveShadow = true;
      landerGroup.add(pad);
    }

    // 6. Holographic Mission Status Halo (Dynamic Ring on the Ground)
    const haloGeo = new THREE.RingGeometry(2.6, 3.0, 48);
    const haloMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.85,
    });
    statusHalo = new THREE.Mesh(haloGeo, haloMat);
    statusHalo.rotation.x = -Math.PI / 2;
    statusHalo.position.y = 0.05;
    landerGroup.add(statusHalo);

    scene.add(landerGroup);
  }

  function buildCelestialBodies() {
    // SUN Group
    sunGroup = new THREE.Group();
    const sunSphereGeo = new THREE.SphereGeometry(3.5, 32, 32);
    const sunMat = new THREE.MeshBasicMaterial({ color: 0xfff0aa });
    const sunMesh = new THREE.Mesh(sunSphereGeo, sunMat);
    sunGroup.add(sunMesh);

    // Sun outer corona glow sprite
    const coronaGeo = new THREE.PlaneGeometry(16, 16);
    const coronaCanvas = document.createElement("canvas");
    coronaCanvas.width = 128;
    coronaCanvas.height = 128;
    const cctx = coronaCanvas.getContext("2d");
    const radGrad = cctx.createRadialGradient(64, 64, 6, 64, 64, 64);
    radGrad.addColorStop(0, "rgba(255, 235, 140, 1.0)");
    radGrad.addColorStop(0.35, "rgba(240, 185, 58, 0.45)");
    radGrad.addColorStop(1, "rgba(240, 185, 58, 0.0)");
    cctx.fillStyle = radGrad;
    cctx.fillRect(0, 0, 128, 128);

    const coronaTex = new THREE.CanvasTexture(coronaCanvas);
    const coronaMat = new THREE.MeshBasicMaterial({
      map: coronaTex,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const coronaMesh = new THREE.Mesh(coronaGeo, coronaMat);
    sunGroup.add(coronaMesh);
    scene.add(sunGroup);

    // EARTH Group
    earthGroup = new THREE.Group();
    const earthSphereGeo = new THREE.SphereGeometry(2.2, 32, 32);
    const earthMat = new THREE.MeshStandardMaterial({
      color: 0x2563eb,
      roughness: 0.4,
      metalness: 0.1,
      emissive: 0x0f2557,
    });
    const earthMesh = new THREE.Mesh(earthSphereGeo, earthMat);
    earthGroup.add(earthMesh);

    // Atmospheric halo
    const atmoGeo = new THREE.SphereGeometry(2.35, 32, 32);
    const atmoMat = new THREE.MeshBasicMaterial({
      color: 0x60a5fa,
      transparent: true,
      opacity: 0.35,
      side: THREE.BackSide,
    });
    const atmoMesh = new THREE.Mesh(atmoGeo, atmoMat);
    earthGroup.add(atmoMesh);
    scene.add(earthGroup);
  }

  function buildBeams() {
    // Golden Sunlight Sightline Ray
    const sunBeamMat = new THREE.LineBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0.7,
      linewidth: 2,
    });
    const sunPts = [new THREE.Vector3(0, 2, 0), new THREE.Vector3(R_SUN, 10, 0)];
    const sunGeo = new THREE.BufferGeometry().setFromPoints(sunPts);
    sunBeam = new THREE.Line(sunGeo, sunBeamMat);
    scene.add(sunBeam);

    // Cyan Direct-To-Earth Comms Link Ray
    const earthBeamMat = new THREE.LineDashedMaterial({
      color: 0x38bdf8,
      linewidth: 2,
      scale: 1,
      dashSize: 2.5,
      gapSize: 1.2,
      transparent: true,
      opacity: 0.85,
    });
    const earthPts = [new THREE.Vector3(0, 3, 0), new THREE.Vector3(R_EARTH, 15, 0)];
    const earthGeo = new THREE.BufferGeometry().setFromPoints(earthPts);
    earthBeam = new THREE.Line(earthGeo, earthBeamMat);
    earthBeam.computeLineDistances();
    scene.add(earthBeam);
  }

  // Generate 3D polygonal terrain bowl from actual LOLA horizon profile
  function setSite(siteData) {
    if (!siteData || !scene) return;
    currentSite = siteData;

    if (terrainMesh) {
      scene.remove(terrainMesh);
      terrainMesh.geometry.dispose();
      terrainMesh.material.dispose();
      terrainMesh = null;
    }

    const azs = siteData.horizon_az; // 0 to 359
    const els = siteData.horizon_el; // elevation degrees
    const N = azs.length;
    if (!N) return;

    // Create a 3D terrain rim mesh with outer mountain wall & inner textured facets
    const positions = [];
    const colors = [];
    const normals = [];

    // Construct triangulated ring between floor (y=0) and ridge heights (y=H(az))
    for (let i = 0; i < N; i++) {
      const iNext = (i + 1) % N;
      const az0 = azs[i];
      const az1 = azs[iNext];
      const el0 = els[i];
      const el1 = els[iNext];

      const vBase0 = azElToVector3(az0, 0, R_TERRAIN);
      const vTop0  = azElToVector3(az0, Math.max(0.1, el0), R_TERRAIN, EL_SCALE);
      const vBase1 = azElToVector3(az1, 0, R_TERRAIN);
      const vTop1  = azElToVector3(az1, Math.max(0.1, el1), R_TERRAIN, EL_SCALE);

      // Back outer wall: vBase0, vTop0, vTop1 & vBase0, vTop1, vBase1
      // Face 1
      positions.push(vBase0.x, vBase0.y, vBase0.z);
      positions.push(vTop0.x, vTop0.y, vTop0.z);
      positions.push(vTop1.x, vTop1.y, vTop1.z);

      // Face 2
      positions.push(vBase0.x, vBase0.y, vBase0.z);
      positions.push(vTop1.x, vTop1.y, vTop1.z);
      positions.push(vBase1.x, vBase1.y, vBase1.z);

      // Color coding by terrain height (Titanium grey at base, brighter frost/regolith on illuminated rims)
      const cBase = new THREE.Color(0x1a2130);
      const cTop0 = new THREE.Color().setHSL(0.6, 0.15, Math.min(0.7, 0.25 + el0 * 0.035));
      const cTop1 = new THREE.Color().setHSL(0.6, 0.15, Math.min(0.7, 0.25 + el1 * 0.035));

      // Face 1 colors
      colors.push(cBase.r, cBase.g, cBase.b);
      colors.push(cTop0.r, cTop0.g, cTop0.b);
      colors.push(cTop1.r, cTop1.g, cTop1.b);

      // Face 2 colors
      colors.push(cBase.r, cBase.g, cBase.b);
      colors.push(cTop1.r, cTop1.g, cTop1.b);
      colors.push(cBase.r, cBase.g, cBase.b);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geo.computeVertexNormals();

    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.85,
      metalness: 0.15,
      side: THREE.DoubleSide,
      flatShading: true,
    });

    terrainMesh = new THREE.Mesh(geo, mat);
    terrainMesh.receiveShadow = true;
    terrainMesh.castShadow = true;
    scene.add(terrainMesh);

    // Update HUD site title
    updateHudSite(siteData);
  }

  // Update dynamic solar/earth positions and lander status at time index tIdx
  function update(siteData, tIdx) {
    if (!siteData || !scene) return;
    currentSite = siteData;

    const sunAz = siteData.sun_az[tIdx];
    const sunEl = siteData.sun_el[tIdx];
    const earthAz = siteData.earth_az[tIdx];
    const earthEl = siteData.earth_el[tIdx];
    const code = siteData.code ? siteData.code[tIdx] : 0;
    const timeStr = siteData.times ? siteData.times[tIdx] : "";

    // 1. Position Sun & directional sunlight
    const sunPos = azElToVector3(sunAz, sunEl, R_SUN, EL_SCALE);
    sunGroup.position.copy(sunPos);
    sunGroup.lookAt(camera.position); // billboard corona to camera
    dirLight.position.copy(sunPos);

    // 2. Position Earth
    const earthPos = azElToVector3(earthAz, earthEl, R_EARTH, EL_SCALE);
    earthGroup.position.copy(earthPos);

    // 3. Sightline Raycast & Horizon Occlusion Test
    const hzAt = window.Lib ? window.Lib.horizonAt : (az, hor, a) => 0;
    const sunHzEl = hzAt(siteData.horizon_az, siteData.horizon_el, sunAz);
    const earthHzEl = hzAt(siteData.horizon_az, siteData.horizon_el, earthAz);

    const sunClear = sunEl > sunHzEl;
    const earthClear = earthEl > earthHzEl;

    // Sun Beam
    if (sunBeam) {
      const landerSolarPos = new THREE.Vector3(0, 2.0, 0);
      if (sunClear) {
        // Line-of-sight clear: beam connects directly from Sun to lander
        sunBeam.geometry.setFromPoints([landerSolarPos, sunPos]);
        sunBeam.material.color.setHex(0xf59e0b);
        sunBeam.material.opacity = 0.65;
        dirLight.intensity = Math.max(0.4, Math.sin(Math.max(0, degToRad(sunEl))) * 2.2);
      } else {
        // Occluded: beam stops at mountain ridge
        const ridgePt = azElToVector3(sunAz, sunHzEl, R_TERRAIN, EL_SCALE);
        sunBeam.geometry.setFromPoints([ridgePt, sunPos]);
        sunBeam.material.color.setHex(0xd97706);
        sunBeam.material.opacity = 0.25;
        dirLight.intensity = 0.12; // deep penumbra shadow
      }
      sunBeam.geometry.attributes.position.needsUpdate = true;
    }

    // Earth Comms Beam
    if (earthBeam) {
      const landerAntennaPos = new THREE.Vector3(0.6, 3.2, 0.6);
      if (earthClear) {
        // Direct-to-Earth active: pulsing cyan beam
        earthBeam.geometry.setFromPoints([landerAntennaPos, earthPos]);
        earthBeam.material.color.setHex(0x38bdf8);
        earthBeam.material.opacity = 0.85;
      } else {
        // Occluded: broken red dashed beam
        const ridgePt = azElToVector3(earthAz, earthHzEl, R_TERRAIN, EL_SCALE);
        earthBeam.geometry.setFromPoints([ridgePt, earthPos]);
        earthBeam.material.color.setHex(0xef4444);
        earthBeam.material.opacity = 0.35;
      }
      earthBeam.computeLineDistances();
      earthBeam.geometry.attributes.position.needsUpdate = true;
    }

    // 4. Lander Status Halo Color
    if (statusHalo) {
      if (code === 3) {
        // Both: Emerald Green
        statusHalo.material.color.setHex(0x10b981);
        statusHalo.material.opacity = 0.9;
      } else if (code === 1) {
        // Power only: Solar Gold
        statusHalo.material.color.setHex(0xf59e0b);
        statusHalo.material.opacity = 0.8;
      } else if (code === 2) {
        // Comms only: Cyan
        statusHalo.material.color.setHex(0x3b82f6);
        statusHalo.material.opacity = 0.8;
      } else {
        // Neither: Charcoal / Red warning
        statusHalo.material.color.setHex(0xef4444);
        statusHalo.material.opacity = 0.45;
      }
    }

    // 5. Update HUD Telemetry
    updateHudTelemetry({
      time: timeStr,
      sunAz, sunEl, sunHzEl, sunClear,
      earthAz, earthEl, earthHzEl, earthClear,
      code,
    });
  }

  function updateHudSite(s) {
    const el = document.getElementById("hudSite");
    if (!el || !s.site) return;
    el.textContent = `${s.site.name}  [${s.site.lat.toFixed(2)}°S, ${s.site.lon.toFixed(2)}°E]`;
  }

  function updateHudTelemetry(t) {
    const timeEl = document.getElementById("hudTime");
    const sunBadge = document.getElementById("hudSun");
    const earthBadge = document.getElementById("hudEarth");
    const statusBadge = document.getElementById("hudStatus");

    if (timeEl && t.time) {
      timeEl.textContent = t.time.replace("T", " ") + " UTC";
    }

    if (sunBadge) {
      const diff = (t.sunEl - t.sunHzEl).toFixed(1);
      if (t.sunClear) {
        sunBadge.className = "hud-chip ok";
        sunBadge.textContent = `☀ SUN +${diff}° CLEAR`;
      } else {
        sunBadge.className = "hud-chip bad";
        sunBadge.textContent = `☀ SUN ${diff}° OCCLUDED`;
      }
    }

    if (earthBadge) {
      const diff = (t.earthEl - t.earthHzEl).toFixed(1);
      if (t.earthClear) {
        earthBadge.className = "hud-chip ok";
        earthBadge.textContent = `🌍 DTE +${diff}° LINK OK`;
      } else {
        earthBadge.className = "hud-chip bad";
        earthBadge.textContent = `🌍 DTE ${diff}° BLOCKED`;
      }
    }

    if (statusBadge) {
      if (t.code === 3) {
        statusBadge.className = "hud-status both";
        statusBadge.textContent = "NOMINAL: POWER + DTE COMMS";
      } else if (t.code === 1) {
        statusBadge.className = "hud-status power";
        statusBadge.textContent = "SOLAR POWER ONLY (NO DTE LINK)";
      } else if (t.code === 2) {
        statusBadge.className = "hud-status comms";
        statusBadge.textContent = "EARTH COMMS ONLY (LUNAR NIGHT)";
      } else {
        statusBadge.className = "hud-status none";
        statusBadge.textContent = "BATTERY DRAIN (NO POWER / NO DTE)";
      }
    }
  }

  function setCamera(mode) {
    if (!camera || !controls) return;
    if (mode === "tactical") {
      camera.position.set(55, 42, 65);
      controls.target.set(0, 3, 0);
    } else if (mode === "pov") {
      camera.position.set(0, 3.2, 0);
      if (currentSite && sunGroup) {
        controls.target.copy(sunGroup.position);
      } else {
        controls.target.set(0, 4, -40);
      }
    } else if (mode === "polar") {
      camera.position.set(0, 130, 0.1);
      controls.target.set(0, 0, 0);
    }
    controls.update();
  }

  function onWindowResize() {
    if (!wrapEl || !renderer || !camera) return;
    const W = wrapEl.clientWidth;
    const H = wrapEl.clientHeight || 420;
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    renderer.setSize(W, H);
  }

  function animate() {
    if (!isRunning) return;
    animFrameId = requestAnimationFrame(animate);

    // Subtle breathing animation on lander halo when nominal
    if (statusHalo && statusHalo.material) {
      const time = performance.now() * 0.003;
      const s = 1.0 + Math.sin(time) * 0.035;
      statusHalo.scale.set(s, s, 1.0);
    }

    // Slow celestial rotation of starfield
    if (starField) {
      starField.rotation.y += 0.00015;
    }

    if (controls) controls.update();
    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  // Expose public API
  root.Scene3D = {
    init,
    setSite,
    update,
    setCamera,
  };
})(window);

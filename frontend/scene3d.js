/* Realistic 3D WebGL Mission Control & Celestial Simulator.
   Renders photorealistic Sun, Earth, glowing 3D orbital trajectory lines,
   real LOLA DEM crater terrain, dynamic line-of-sight sightlines, and Artemis lander.
*/
(function (root) {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined" || !root.THREE) {
    root.Scene3D = { init: () => false, update: () => {}, setSite: () => {}, setCamera: () => {} };
    return;
  }

  var THREE = root.THREE;
  let scene, camera, renderer, controls;
  let terrainMesh, groundMesh, starField, landerGroup, statusHalo;
  let sunGroup, earthGroup, sunBeam, earthBeam, occlusionMarker;
  let sunOrbitLine, earthOrbitLine;
  let dirLight, ambientLight;
  let currentSite = null;
  let currentTIdx = 0;
  let animFrameId = 0;
  let isRunning = false;
  let wrapEl, canvasEl;

  // Scale constants
  const R_TERRAIN = 65.0;     // Horizon crater bowl radius
  const R_SUN = 110.0;        // Sun orbital distance
  const R_EARTH = 92.0;       // Earth orbital distance
  const EL_SCALE = 2.4;       // Vertical exaggeration for dramatic terrain ridges

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

  // ----------------------------------------------------------------- Procedural Textures

  function createEarthTexture() {
    const canvas = document.createElement("canvas");
    canvas.width = 1024; canvas.height = 512;
    const ctx = canvas.getContext("2d");

    // Deep ocean base
    const oceanGrad = ctx.createLinearGradient(0, 0, 0, 512);
    oceanGrad.addColorStop(0, "#081730");
    oceanGrad.addColorStop(0.5, "#0f2c5f");
    oceanGrad.addColorStop(1, "#081730");
    ctx.fillStyle = oceanGrad;
    ctx.fillRect(0, 0, 1024, 512);

    // Continental landmasses
    function drawLand(x, y, w, h, col) {
      ctx.fillStyle = col || "#335c2b";
      ctx.beginPath();
      ctx.ellipse(x, y, w, h, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    // Africa / Europe / Middle East
    drawLand(520, 240, 55, 85, "#4d6328");
    drawLand(510, 140, 48, 40, "#3e5220");
    drawLand(570, 210, 35, 30, "#736b44");
    // Asia
    drawLand(690, 170, 110, 65, "#4c6b2e");
    drawLand(750, 260, 40, 45, "#3b5825");
    drawLand(640, 260, 30, 40, "#6e7545");
    // Australia
    drawLand(810, 360, 45, 35, "#806d48");
    // North America
    drawLand(240, 160, 75, 55, "#435d2d");
    drawLand(180, 110, 55, 35, "#5d7345");
    // South America
    drawLand(310, 330, 42, 75, "#2f4f24");
    // Polar Ice
    ctx.fillStyle = "#edf6f9";
    ctx.fillRect(0, 0, 1024, 30);
    ctx.fillRect(0, 475, 1024, 37);

    // Realistic swirling white cloud systems
    ctx.fillStyle = "rgba(255, 255, 255, 0.45)";
    for (let i = 0; i < 45; i++) {
      const cx = (i * 41) % 1024;
      const cy = 40 + ((i * 59) % 430);
      const rw = 50 + ((i * 31) % 90);
      const rh = 10 + ((i * 19) % 25);
      ctx.beginPath();
      ctx.ellipse(cx, cy, rw, rh, (i * 0.25), 0, Math.PI * 2);
      ctx.fill();
    }

    const tex = new THREE.CanvasTexture(canvas);
    return tex;
  }

  function createSunTexture() {
    const canvas = document.createElement("canvas");
    canvas.width = 512; canvas.height = 512;
    const ctx = canvas.getContext("2d");

    const grad = ctx.createRadialGradient(256, 256, 30, 256, 256, 256);
    grad.addColorStop(0, "#ffffff");
    grad.addColorStop(0.2, "#fff8e0");
    grad.addColorStop(0.5, "#ffba38");
    grad.addColorStop(0.8, "#f26513");
    grad.addColorStop(1.0, "rgba(220, 60, 10, 0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 512, 512);

    return new THREE.CanvasTexture(canvas);
  }

  function createLensFlareTexture() {
    const canvas = document.createElement("canvas");
    canvas.width = 512; canvas.height = 512;
    const ctx = canvas.getContext("2d");

    // Luminous corona
    const grad = ctx.createRadialGradient(256, 256, 8, 256, 256, 250);
    grad.addColorStop(0, "rgba(255, 255, 255, 1.0)");
    grad.addColorStop(0.12, "rgba(255, 230, 120, 0.9)");
    grad.addColorStop(0.35, "rgba(255, 150, 30, 0.45)");
    grad.addColorStop(0.75, "rgba(255, 90, 10, 0.1)");
    grad.addColorStop(1.0, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 512, 512);

    // Anamorphic flare streaks (horizontal lens glare)
    const horGrad = ctx.createLinearGradient(0, 256, 512, 256);
    horGrad.addColorStop(0, "rgba(255, 230, 140, 0)");
    horGrad.addColorStop(0.5, "rgba(255, 255, 220, 0.85)");
    horGrad.addColorStop(1, "rgba(255, 230, 140, 0)");
    ctx.fillStyle = horGrad;
    ctx.fillRect(0, 254, 512, 4);

    // Cross-glare spikes
    ctx.strokeStyle = "rgba(255, 235, 150, 0.35)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(256, 0); ctx.lineTo(256, 512);
    ctx.moveTo(80, 80); ctx.lineTo(432, 432);
    ctx.moveTo(80, 432); ctx.lineTo(432, 80);
    ctx.stroke();

    return new THREE.CanvasTexture(canvas);
  }

  function createRegolithTexture() {
    const canvas = document.createElement("canvas");
    canvas.width = 512; canvas.height = 512;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = "#141720";
    ctx.fillRect(0, 0, 512, 512);

    // Micro-craters and gravel speckles
    for (let i = 0; i < 700; i++) {
      const x = Math.random() * 512;
      const y = Math.random() * 512;
      const r = 1 + Math.random() * 5;
      const grad = ctx.createRadialGradient(x, y, 0.5, x, y, r);
      grad.addColorStop(0, "rgba(8, 10, 14, 0.85)");
      grad.addColorStop(0.65, "rgba(40, 48, 62, 0.4)");
      grad.addColorStop(1, "rgba(20, 23, 32, 0)");
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    }

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(6, 6);
    return tex;
  }

  // ----------------------------------------------------------------- Initialization

  function init(containerId) {
    wrapEl = document.getElementById(containerId);
    if (!wrapEl) return false;
    canvasEl = wrapEl.querySelector("canvas");
    if (!canvasEl) return false;

    try {
      const W = wrapEl.clientWidth || 800;
      const H = wrapEl.clientHeight || 400;

      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x070a10);
      scene.fog = new THREE.FogExp2(0x070a10, 0.003);

      camera = new THREE.PerspectiveCamera(48, W / H, 0.5, 2500);
      // Start in Lander POV (first person facing the horizon)
      camera.position.set(0, 3.2, 0);

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

      if (typeof THREE.OrbitControls !== "undefined") {
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.maxDistance = 180;
        controls.minDistance = 3;
        controls.maxPolarAngle = Math.PI / 2 + 0.03; // Don't clip below lunar surface
        controls.target.set(0, 5, -50);
      }

      // Lights: Stark lunar contrast (blinding sun, dark shadows)
      ambientLight = new THREE.AmbientLight(0x111624, 0.35);
      scene.add(ambientLight);

      dirLight = new THREE.DirectionalLight(0xfff5d6, 2.0);
      dirLight.castShadow = true;
      dirLight.shadow.mapSize.width = 1024;
      dirLight.shadow.mapSize.height = 1024;
      dirLight.shadow.camera.near = 10;
      dirLight.shadow.camera.far = 300;
      const d = 60;
      dirLight.shadow.camera.left = -d; dirLight.shadow.camera.right = d;
      dirLight.shadow.camera.top = d; dirLight.shadow.camera.bottom = -d;
      scene.add(dirLight);

      // Starfield
      buildStarfield();

      // Base Crater Floor & Compass
      buildBaseFloor();

      // Artemis Lander 3D Model
      buildLander();

      // Photorealistic Sun & Earth Spheres
      buildCelestialBodies();

      // Laser Sightline Beams
      buildBeams();

      window.addEventListener("resize", onWindowResize);

      isRunning = true;
      animate();

      return true;
    } catch (err) {
      console.warn("3D WebGL initialization skipped:", err);
      return false;
    }
  }

  function buildStarfield() {
    const starCount = 1800;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(starCount * 3);
    const colors = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 500 + Math.random() * 250;

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = Math.abs(r * Math.cos(phi)) + 8; // keep above horizon
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);

      const shade = 0.8 + Math.random() * 0.2;
      colors[i * 3] = shade;
      colors[i * 3 + 1] = shade;
      colors[i * 3 + 2] = Math.min(1.0, shade + 0.15);
    }

    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: 1.8,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
    });

    starField = new THREE.Points(geometry, material);
    scene.add(starField);
  }

  function buildBaseFloor() {
    const floorGeo = new THREE.CircleGeometry(R_TERRAIN, 64);
    const regolithTex = createRegolithTexture();
    const floorMat = new THREE.MeshStandardMaterial({
      color: 0x121722,
      map: regolithTex,
      roughness: 0.95,
      metalness: 0.05,
    });
    groundMesh = new THREE.Mesh(floorGeo, floorMat);
    groundMesh.rotation.x = -Math.PI / 2;
    groundMesh.receiveShadow = true;
    scene.add(groundMesh);

    // Tactical Radar Distance Rings (15m, 30m, 45m, 65m)
    const ringGroup = new THREE.Group();
    [15, 30, 45, R_TERRAIN].forEach((r, idx) => {
      const ringGeo = new THREE.RingGeometry(r - 0.15, r + 0.15, 64);
      const ringMat = new THREE.MeshBasicMaterial({
        color: idx === 3 ? 0x2e3f56 : 0x192230,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.65,
      });
      const rm = new THREE.Mesh(ringGeo, ringMat);
      rm.rotation.x = -Math.PI / 2;
      rm.position.y = 0.03;
      ringGroup.add(rm);
    });

    // Cardinal Axes
    const axisMat = new THREE.LineBasicMaterial({ color: 0x243248, transparent: true, opacity: 0.5 });
    const pts = [
      new THREE.Vector3(0, 0.04, -R_TERRAIN), new THREE.Vector3(0, 0.04, R_TERRAIN),
      new THREE.Vector3(-R_TERRAIN, 0.04, 0), new THREE.Vector3(R_TERRAIN, 0.04, 0),
    ];
    const axisGeo = new THREE.BufferGeometry().setFromPoints(pts);
    ringGroup.add(new THREE.LineSegments(axisGeo, axisMat));

    scene.add(ringGroup);
  }

  function buildLander() {
    landerGroup = new THREE.Group();

    // Descent Stage: Gold foil thermal insulation
    const baseGeo = new THREE.CylinderGeometry(1.5, 2.0, 1.2, 8);
    const goldFoilMat = new THREE.MeshStandardMaterial({
      color: 0xd4af37,
      metalness: 0.9,
      roughness: 0.2,
    });
    const descent = new THREE.Mesh(baseGeo, goldFoilMat);
    descent.position.y = 1.2;
    descent.castShadow = true;
    descent.receiveShadow = true;
    landerGroup.add(descent);

    // Ascent Cabin
    const cabinGeo = new THREE.CylinderGeometry(1.0, 1.3, 1.1, 8);
    const cabinMat = new THREE.MeshStandardMaterial({ color: 0xe2e6ef, metalness: 0.3, roughness: 0.6 });
    const cabin = new THREE.Mesh(cabinGeo, cabinMat);
    cabin.position.y = 2.2;
    cabin.castShadow = true;
    landerGroup.add(cabin);

    // Solar Panel Wings
    const solarGeo = new THREE.BoxGeometry(2.8, 0.06, 0.8);
    const solarMat = new THREE.MeshStandardMaterial({
      color: 0x1d3557,
      metalness: 0.95,
      roughness: 0.1,
      emissive: 0x071a33,
    });
    const wing1 = new THREE.Mesh(solarGeo, solarMat);
    wing1.position.set(2.4, 2.0, 0); wing1.rotation.z = 0.2; wing1.castShadow = true;
    landerGroup.add(wing1);
    const wing2 = new THREE.Mesh(solarGeo, solarMat);
    wing2.position.set(-2.4, 2.0, 0); wing2.rotation.z = -0.2; wing2.castShadow = true;
    landerGroup.add(wing2);

    // Comms Dish (oriented toward Earth)
    const dishGeo = new THREE.CylinderGeometry(0.7, 0.1, 0.25, 16, 1, true);
    const dishMat = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.8, roughness: 0.3, side: THREE.DoubleSide });
    const dish = new THREE.Mesh(dishGeo, dishMat);
    dish.position.set(0.6, 3.2, 0.6); dish.rotation.set(-0.4, 0.5, 0); dish.castShadow = true;
    landerGroup.add(dish);

    // Landing Legs
    const legMat = new THREE.MeshStandardMaterial({ color: 0x474a52, metalness: 0.6 });
    for (let i = 0; i < 4; i++) {
      const angle = (i * Math.PI) / 2 + Math.PI / 4;
      const legGeo = new THREE.CylinderGeometry(0.06, 0.06, 1.8);
      const leg = new THREE.Mesh(legGeo, legMat);
      leg.position.set(Math.cos(angle) * 1.6, 0.6, Math.sin(angle) * 1.6);
      leg.rotation.z = Math.cos(angle) * 0.45; leg.rotation.x = -Math.sin(angle) * 0.45;
      leg.castShadow = true;
      landerGroup.add(leg);

      const pad = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.05, 12), goldFoilMat);
      pad.position.set(Math.cos(angle) * 2.2, 0.03, Math.sin(angle) * 2.2);
      pad.receiveShadow = true;
      landerGroup.add(pad);
    }

    // Holographic Mission Status Halo on the ground
    const haloGeo = new THREE.RingGeometry(2.6, 3.1, 48);
    const haloMat = new THREE.MeshBasicMaterial({ color: 0x10b981, side: THREE.DoubleSide, transparent: true, opacity: 0.9 });
    statusHalo = new THREE.Mesh(haloGeo, haloMat);
    statusHalo.rotation.x = -Math.PI / 2;
    statusHalo.position.y = 0.05;
    landerGroup.add(statusHalo);

    scene.add(landerGroup);
  }

  function buildCelestialBodies() {
    // 1. PHOTOREALISTIC SUN
    sunGroup = new THREE.Group();
    const sunTex = createSunTexture();
    const sunGeo = new THREE.SphereGeometry(4.0, 32, 32);
    const sunMat = new THREE.MeshBasicMaterial({ map: sunTex });
    const sunSphere = new THREE.Mesh(sunGeo, sunMat);
    sunGroup.add(sunSphere);

    // Multi-Layered Lens Flare & Anamorphic Corona Sprite
    const flareTex = createLensFlareTexture();
    const flareGeo = new THREE.PlaneGeometry(28, 28);
    const flareMat = new THREE.MeshBasicMaterial({
      map: flareTex,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const flareMesh = new THREE.Mesh(flareGeo, flareMat);
    sunGroup.add(flareMesh);
    scene.add(sunGroup);

    // 2. PHOTOREALISTIC EARTH
    earthGroup = new THREE.Group();
    const earthTex = createEarthTexture();
    const earthGeo = new THREE.SphereGeometry(2.8, 32, 32);
    const earthMat = new THREE.MeshStandardMaterial({
      map: earthTex,
      roughness: 0.5,
      metalness: 0.1,
      emissive: 0x081830,
    });
    const earthSphere = new THREE.Mesh(earthGeo, earthMat);
    earthGroup.add(earthSphere);

    // Rayleigh Scattering Atmosphere Glow Rim
    const atmoGeo = new THREE.SphereGeometry(3.0, 32, 32);
    const atmoMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.45,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
    });
    const atmoMesh = new THREE.Mesh(atmoGeo, atmoMat);
    earthGroup.add(atmoMesh);
    scene.add(earthGroup);
  }

  function buildBeams() {
    // Golden Solar Sightline Laser
    const sunBeamMat = new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.75, linewidth: 2 });
    sunBeam = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), sunBeamMat);
    scene.add(sunBeam);

    // Cyan Direct-To-Earth Comms Beam
    const earthBeamMat = new THREE.LineDashedMaterial({
      color: 0x38bdf8,
      linewidth: 2,
      scale: 1,
      dashSize: 2.2,
      gapSize: 1.0,
      transparent: true,
      opacity: 0.85,
    });
    earthBeam = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), earthBeamMat);
    scene.add(earthBeam);

    // Glowing Occlusion Strike Marker
    const markerGeo = new THREE.RingGeometry(0.8, 1.4, 24);
    const markerMat = new THREE.MeshBasicMaterial({ color: 0xef4444, side: THREE.DoubleSide, transparent: true, opacity: 0.9 });
    occlusionMarker = new THREE.Mesh(markerGeo, markerMat);
    occlusionMarker.visible = false;
    scene.add(occlusionMarker);
  }

  // ----------------------------------------------------------------- 3D Terrain & Trajectory Lines

  function setSite(siteData) {
    if (!siteData || !scene) return;
    currentSite = siteData;

    // Clean up old terrain & trajectory lines
    if (terrainMesh) {
      scene.remove(terrainMesh);
      terrainMesh.geometry.dispose();
      terrainMesh.material.dispose();
      terrainMesh = null;
    }
    if (sunOrbitLine) {
      scene.remove(sunOrbitLine);
      sunOrbitLine.geometry.dispose();
      sunOrbitLine = null;
    }
    if (earthOrbitLine) {
      scene.remove(earthOrbitLine);
      earthOrbitLine.geometry.dispose();
      earthOrbitLine = null;
    }

    // 1. BUILD REAL 3D LOLA CRATER RIM
    const azs = siteData.horizon_az; // 0 to 359
    const els = siteData.horizon_el;
    const N = azs.length;
    if (N) {
      const positions = [];
      const colors = [];

      for (let i = 0; i < N; i++) {
        const iNext = (i + 1) % N;
        const az0 = azs[i], az1 = azs[iNext];
        const el0 = els[i], el1 = els[iNext];

        const vBase0 = azElToVector3(az0, 0, R_TERRAIN);
        const vTop0  = azElToVector3(az0, Math.max(0.1, el0), R_TERRAIN, EL_SCALE);
        const vBase1 = azElToVector3(az1, 0, R_TERRAIN);
        const vTop1  = azElToVector3(az1, Math.max(0.1, el1), R_TERRAIN, EL_SCALE);

        // Quad 1: (vBase0, vTop0, vTop1)
        positions.push(vBase0.x, vBase0.y, vBase0.z);
        positions.push(vTop0.x, vTop0.y, vTop0.z);
        positions.push(vTop1.x, vTop1.y, vTop1.z);

        // Quad 2: (vBase0, vTop1, vBase1)
        positions.push(vBase0.x, vBase0.y, vBase0.z);
        positions.push(vTop1.x, vTop1.y, vTop1.z);
        positions.push(vBase1.x, vBase1.y, vBase1.z);

        // Realistic shading: dark basalt base fading to illuminated regolith crest
        const cBase = new THREE.Color(0x121720);
        const cTop0 = new THREE.Color().setHSL(0.58, 0.12, Math.min(0.68, 0.22 + el0 * 0.035));
        const cTop1 = new THREE.Color().setHSL(0.58, 0.12, Math.min(0.68, 0.22 + el1 * 0.035));

        colors.push(cBase.r, cBase.g, cBase.b);
        colors.push(cTop0.r, cTop0.g, cTop0.b);
        colors.push(cTop1.r, cTop1.g, cTop1.b);

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
        roughness: 0.9,
        metalness: 0.1,
        side: THREE.DoubleSide,
        flatShading: true,
      });

      terrainMesh = new THREE.Mesh(geo, mat);
      terrainMesh.receiveShadow = true;
      terrainMesh.castShadow = true;
      scene.add(terrainMesh);
    }

    // 2. BUILD REALISTIC 3D ORBITAL TRAJECTORY LINES ("all the lines")
    build3DTrajectoryLines(siteData);

    updateHudSite(siteData);
  }

  function build3DTrajectoryLines(siteData) {
    if (!siteData || !siteData.sun_az) return;
    const n = siteData.sun_az.length;
    if (!n) return;

    // Glowing Golden Solar Path Ribbon across 3D sky
    const sunPts = [];
    for (let i = 0; i < n; i++) {
      sunPts.push(azElToVector3(siteData.sun_az[i], siteData.sun_el[i], R_SUN, EL_SCALE));
    }
    const sunLineGeo = new THREE.BufferGeometry().setFromPoints(sunPts);
    const sunLineMat = new THREE.LineBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0.65,
      linewidth: 2,
    });
    sunOrbitLine = new THREE.Line(sunLineGeo, sunLineMat);
    scene.add(sunOrbitLine);

    // Glowing Cyan Earth Libration Loop across 3D sky
    const earthPts = [];
    for (let i = 0; i < n; i++) {
      earthPts.push(azElToVector3(siteData.earth_az[i], siteData.earth_el[i], R_EARTH, EL_SCALE));
    }
    const earthLineGeo = new THREE.BufferGeometry().setFromPoints(earthPts);
    const earthLineMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.65,
      linewidth: 2,
    });
    earthOrbitLine = new THREE.Line(earthLineGeo, earthLineMat);
    scene.add(earthOrbitLine);
  }

  // ----------------------------------------------------------------- Live Update & Raycast

  function update(siteData, tIdx) {
    if (!siteData || !scene) return;
    currentSite = siteData;
    currentTIdx = tIdx;

    const sunAz = siteData.sun_az[tIdx];
    const sunEl = siteData.sun_el[tIdx];
    const earthAz = siteData.earth_az[tIdx];
    const earthEl = siteData.earth_el[tIdx];
    const code = siteData.code ? siteData.code[tIdx] : 0;
    const timeStr = siteData.times ? siteData.times[tIdx] : "";

    // 1. Sun Position & Directional Lighting
    const sunPos = azElToVector3(sunAz, sunEl, R_SUN, EL_SCALE);
    sunGroup.position.copy(sunPos);
    sunGroup.lookAt(camera.position); // Billboard flare to camera
    dirLight.position.copy(sunPos);

    // 2. Earth Position
    const earthPos = azElToVector3(earthAz, earthEl, R_EARTH, EL_SCALE);
    earthGroup.position.copy(earthPos);

    // 3. Line-of-sight & Terrain Occlusion Calculation
    const hzAt = window.Lib ? window.Lib.horizonAt : (az, hor, a) => 0;
    const sunHzEl = hzAt(siteData.horizon_az, siteData.horizon_el, sunAz);
    const earthHzEl = hzAt(siteData.horizon_az, siteData.horizon_el, earthAz);

    const sunClear = sunEl > sunHzEl;
    const earthClear = earthEl > earthHzEl;

    // Sun Sightline Raycast
    const landerSolarPos = new THREE.Vector3(0, 2.0, 0);
    if (sunClear) {
      sunBeam.geometry.setFromPoints([landerSolarPos, sunPos]);
      sunBeam.material.color.setHex(0xf59e0b);
      sunBeam.material.opacity = 0.8;
      dirLight.intensity = Math.max(0.5, Math.sin(Math.max(0, degToRad(sunEl))) * 2.4);
      occlusionMarker.visible = false;
    } else {
      // Occluded: beam breaks against ridge crest
      const ridgePos = azElToVector3(sunAz, sunHzEl, R_TERRAIN, EL_SCALE);
      sunBeam.geometry.setFromPoints([ridgePos, sunPos]);
      sunBeam.material.color.setHex(0xd97706);
      sunBeam.material.opacity = 0.3;
      dirLight.intensity = 0.12; // deep penumbra shadow

      occlusionMarker.visible = true;
      occlusionMarker.position.copy(ridgePos);
      occlusionMarker.lookAt(landerSolarPos);
    }
    sunBeam.geometry.attributes.position.needsUpdate = true;

    // Earth Comms Raycast
    const landerDishPos = new THREE.Vector3(0.6, 3.2, 0.6);
    if (earthClear) {
      earthBeam.geometry.setFromPoints([landerDishPos, earthPos]);
      earthBeam.material.color.setHex(0x38bdf8);
      earthBeam.material.opacity = 0.9;
    } else {
      const ridgePos = azElToVector3(earthAz, earthHzEl, R_TERRAIN, EL_SCALE);
      earthBeam.geometry.setFromPoints([ridgePos, earthPos]);
      earthBeam.material.color.setHex(0xef4444);
      earthBeam.material.opacity = 0.35;
    }
    earthBeam.computeLineDistances();
    earthBeam.geometry.attributes.position.needsUpdate = true;

    // 4. Lander Holographic Status Halo
    if (statusHalo) {
      if (code === 3) {
        statusHalo.material.color.setHex(0x10b981); // Emerald Green
        statusHalo.material.opacity = 0.95;
      } else if (code === 1) {
        statusHalo.material.color.setHex(0xf59e0b); // Solar Amber
        statusHalo.material.opacity = 0.85;
      } else if (code === 2) {
        statusHalo.material.color.setHex(0x3b82f6); // Cyan Comms
        statusHalo.material.opacity = 0.85;
      } else {
        statusHalo.material.color.setHex(0xef4444); // Dark Drain
        statusHalo.material.opacity = 0.45;
      }
    }

    // 5. HUD Telemetry Badges
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
      camera.position.set(50, 40, 60);
      controls.target.set(0, 3, 0);
    } else if (mode === "pov") {
      camera.position.set(0, 3.2, 0);
      if (currentSite && sunGroup) {
        // Look toward the Sun
        controls.target.copy(sunGroup.position);
      } else {
        controls.target.set(0, 4, -50);
      }
    } else if (mode === "polar") {
      camera.position.set(0, 140, 0.1);
      controls.target.set(0, 0, 0);
    }
    controls.update();
  }

  function onWindowResize() {
    if (!wrapEl || !renderer || !camera) return;
    const W = wrapEl.clientWidth;
    const H = wrapEl.clientHeight || 400;
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    renderer.setSize(W, H);
  }

  function animate() {
    if (!isRunning) return;
    animFrameId = requestAnimationFrame(animate);

    // Subtle pulsating halo animation
    if (statusHalo && statusHalo.material) {
      const time = performance.now() * 0.003;
      const s = 1.0 + Math.sin(time) * 0.035;
      statusHalo.scale.set(s, s, 1.0);
    }

    // Slow rotation of celestial starfield
    if (starField) {
      starField.rotation.y += 0.00015;
    }

    // Slow axial spin of Earth
    if (earthGroup) {
      earthGroup.rotation.y += 0.002;
    }

    if (controls) controls.update();
    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  root.Scene3D = {
    init,
    setSite,
    update,
    setCamera,
  };
})(window);

// ---------------------------------------------------------------------------
// app/static/ui/scene3d.js
// ---------------------------------------------------------------------------
// Purpose : Three.js 3D globe — scene graph, GLSL earth shaders, orbit/
//           satellite/station meshes, constellations, heliocentric mode.
// Exports : scene3d
// ---------------------------------------------------------------------------
import { orbit } from '../simulation.js';
import { createEarthTextures, disposeEarthTextures } from './earthTexture.js';

const { constants: orbitConstants, stationEcef } = orbit;

const { EARTH_RADIUS_KM } = orbitConstants;
const UNIT_SCALE = 1 / EARTH_RADIUS_KM;
const EARTH_BASE_ROTATION = 0;
const GROUND_TRACK_ALTITUDE_KM = 0.05;
const LOS_COLOR = 0x38bdf8;    // Cyan — satellite visible from ground station
const NO_LOS_COLOR = 0xef4444; // Red — satellite below horizon

const EARTH_VERTEX_SHADER = `
  varying vec2 vUv;
  varying vec3 vViewNormal;
  void main() {
    vUv = uv;
    // normalMatrix = upper-3x3 of inverse(transpose(modelViewMatrix))
    // Gives us the surface normal in VIEW space, correctly including
    // all parent-group transforms (earthGroup rotation = GMST).
    vViewNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const EARTH_FRAGMENT_SHADER = `
  uniform sampler2D dayMap;
  uniform sampler2D nightMap;
  uniform vec3 sunDirection;       // world-space Sun direction
  uniform float ambientStrength;
  uniform float nightStrength;
  varying vec2 vUv;
  varying vec3 vViewNormal;

  vec3 toneMap(vec3 color) {
    return color / (color + vec3(1.0));
  }

  void main() {
    vec3 normal = normalize(vViewNormal);                   // view space
    // Transform sunDirection from world space → view space so both
    // vectors are in the same frame.  The dot product is rotation-
    // invariant, so the result equals the world-space dot product
    // but now correctly picks up earthGroup (GMST) rotation via
    // normalMatrix / modelViewMatrix.
    vec3 lightDir = normalize((viewMatrix * vec4(sunDirection, 0.0)).xyz);  // view space
    float NdotL = dot(normal, lightDir);
    float diffuse = max(NdotL, 0.0);
    vec2 sampleUv = vUv;
    vec3 dayColor = texture2D(dayMap, sampleUv).rgb;
    vec3 nightColor = texture2D(nightMap, sampleUv).rgb;

    // Sharper terminator: narrow transition band
    float dayMix = smoothstep(-0.08, 0.2, NdotL);

    // Sunlit side: warm tint + strong illumination
    vec3 warmTint = vec3(1.05, 0.98, 0.88);
    vec3 lit = dayColor * warmTint * (ambientStrength + diffuse * 1.4);

    // Night side: dark with city lights visible
    vec3 night = nightColor * nightStrength * 0.7;

    // Mix day and night
    vec3 color = mix(night, lit, dayMix);

    // Subtle atmosphere rim glow on the sunlit limb
    float rim = pow(1.0 - max(NdotL, 0.0), 3.5);
    vec3 rimColor = mix(vec3(0.1, 0.15, 0.3), vec3(0.5, 0.7, 1.0), dayMix);
    color += rimColor * rim * 0.08;

    gl_FragColor = vec4(toneMap(color), 1.0);
  }
`;

let THREE;
let OrbitControls;
let importPromise;

let containerEl;
let canvasEl;
let fallbackEl;
let renderer;
let scene;
let camera;
let controls;
let resizeObserver;
let animationHandle;
let earthGroup;
let earthSystemGroup;      // Top-level group for heliocentric mode — moves to Earth's orbit position
let earthOrbitLine;        // Visualisation of Earth's orbital path around the Sun
let earthMesh;
let atmosphereMesh;
let orbitLine;
let satelliteMesh;
let stationGroup;
let linkLine;
let groundTrackLine;
let groundTrackVectorLine;
let isReady = false;
let earthSimulationRotation = 0;
let passiveAtmosphereOffset = 0;
let earthUniforms;
let earthTextures;
let sunLight;
let hasUserMovedCamera = false;
let lastFramedRadius = null;

const stationMeshes = new Map();
const constellationSatelliteMeshes = new Map(); // New: Specific meshes for constellation satellites
const constellationOrbitLines = new Map();     // New: For 3D orbits for each constellation satellite
const constellationGroundTrackSurfaceLines = new Map();
const constellationGroundTrackVectorLines = new Map();

async function ensureThree() {
  if (!importPromise) {
    importPromise = Promise.all([
      import('three'),
      import('three/addons/controls/OrbitControls.js'),
    ]).then(([threeModule, controlsModule]) => {
      THREE = threeModule.default ?? threeModule;
      OrbitControls =
        controlsModule.OrbitControls ?? controlsModule.default ?? controlsModule;
      if (typeof OrbitControls !== 'function') {
        throw new Error('OrbitControls is not available.');
      }
    });
  }
  return importPromise;
}

// Helper to create a specific mesh for constellation satellites (3D)
function createConstellationSatelliteMesh(satellite, color, groupId) {
  const key = `${groupId}-${satellite.id}`;
  let mesh = constellationSatelliteMeshes.get(key);
  if (!mesh) {
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(color),
      emissive: new THREE.Color(color).multiplyScalar(0.4), // Subtle glow
      metalness: 0.2,
      roughness: 0.4,
    });
    mesh = new THREE.Mesh(new THREE.SphereGeometry(0.03, 20, 20), material);
    mesh.name = `constellation-sat-${key}`;
    constellationSatelliteMeshes.set(key, mesh);
    // Add to earthSystemGroup so meshes move with Earth in helio mode
    const parent = earthSystemGroup || scene;
    parent.add(mesh);
  }
  // No need to set position here, will be set in renderConstellations3D
  mesh.material.color.set(color);
  mesh.material.emissive.set(new THREE.Color(color).multiplyScalar(0.4));
  return mesh;
}

// Helper to update/create 3D orbit lines for constellation satellites
function updateConstellationOrbitLine3D(satelliteId, orbitPoints, color, groupId) {
  const key = `${groupId}-${satelliteId}-orbit`;
  let line = constellationOrbitLines.get(key);
  if (!line) {
    line = new THREE.Line(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: new THREE.Color(color), linewidth: 1.5, transparent: true, opacity: 0.5 })
    );
    line.name = `constellation-orbit-${key}`;
    constellationOrbitLines.set(key, line);
    earthGroup.add(line); // Add to earthGroup to rotate with earth
  }
  const vectors = orbitPoints
    .map((p) => toVector3Eci(p.rEci))
    .filter((vec) => vec instanceof THREE.Vector3);
  if (vectors.length) {
    const first = vectors[0];
    const last = vectors[vectors.length - 1];
    const closed = first.distanceTo(last) < 1e-3;
    const curve = new THREE.CatmullRomCurve3(vectors, closed, 'centripetal', 0.5);
    const segments = Math.min(2048, Math.max(120, vectors.length * 3));
    const smoothPoints = curve.getPoints(segments);
    line.geometry.dispose();
    line.geometry = new THREE.BufferGeometry().setFromPoints(smoothPoints);
    line.visible = true;
    line.material.color.set(color);
  } else {
    line.visible = false;
  }
  return line;
}

function updateConstellationGroundTrackSurface3D(satelliteId, groundTrackPoints, color, groupId) {
  const key = `${groupId}-${satelliteId}-groundtrack-surface`;
  let line = constellationGroundTrackSurfaceLines.get(key);
  if (!line) {
    line = new THREE.Line(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: new THREE.Color(color), linewidth: 1, transparent: true, opacity: 0.4 })
    );
    line.name = `constellation-groundtrack-surface-${key}`;
    constellationGroundTrackSurfaceLines.set(key, line);
    earthGroup.add(line);
  }
  
  const vectors = groundTrackPoints.map(p => {
    return vectorFromLatLon(p.lat, p.lon, GROUND_TRACK_ALTITUDE_KM);
  }).filter(Boolean);

  if (vectors.length) {
    const curve = new THREE.CatmullRomCurve3(vectors, false, 'centripetal');
    line.geometry.dispose();
    line.geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(Math.min(2048, vectors.length * 3)));
    line.visible = true;
    line.material.color.set(new THREE.Color(color));
  } else {
    line.visible = false;
  }
  return line;
}

function updateConstellationGroundTrackVector3D(satelliteId, satEci, groundTrackEci, color, groupId) {
    const key = `${groupId}-${satelliteId}-groundtrack-vector`;
    let line = constellationGroundTrackVectorLines.get(key);
    if (!line) {
        line = new THREE.Line(
            new THREE.BufferGeometry(),
            new THREE.LineDashedMaterial({
                color: new THREE.Color(color),
                dashSize: 0.045,
                gapSize: 0.03,
                transparent: true,
                opacity: 0.6
            })
        );
        line.name = `constellation-groundtrack-vector-${key}`;
        constellationGroundTrackVectorLines.set(key, line);
        const parent = earthSystemGroup || scene;
        parent.add(line);
    }
    
    if (satEci && groundTrackEci) {
        const satVec = toVector3Eci(satEci);
        const groundVec = toVector3Eci(groundTrackEci);
        const centerVec = new THREE.Vector3(0, 0, 0);
        
        const points = [ groundVec, satVec, centerVec ];
        line.geometry.dispose();
        line.geometry = new THREE.BufferGeometry().setFromPoints(points);
        line.computeLineDistances();
        line.visible = true;
        line.material.color.set(new THREE.Color(color));
    } else {
        line.visible = false;
    }
    return line;
}

function hideFallback() {
  if (fallbackEl) {
    fallbackEl.hidden = true;
    fallbackEl.setAttribute('aria-hidden', 'true');
  }
  if (canvasEl) {
    canvasEl.classList.remove('is-hidden');
    canvasEl.removeAttribute('aria-hidden');
  }
}

function showFallback(message) {
  if (fallbackEl) {
    // Update the detailed error message
    const contentEl = fallbackEl.querySelector('.fallback-content');
    const reasonEl = fallbackEl.querySelector('.fallback-reason');
    if (reasonEl) {
      reasonEl.textContent = message || '3D scene could not be initialized.';
    } else {
      // Fallback to simple text if structure not found
      fallbackEl.textContent = message || '3D scene could not be initialized.';
    }
    fallbackEl.hidden = false;
    fallbackEl.setAttribute('aria-hidden', 'false');
  }
  if (canvasEl) {
    canvasEl.classList.add('is-hidden');
    canvasEl.setAttribute('aria-hidden', 'true');
  }
}

function resizeRenderer() {
  if (!renderer || !containerEl) return;
  const width = Math.max(containerEl.clientWidth, 1);
  const height = Math.max(containerEl.clientHeight, 1);
  renderer.setSize(width, height, false);
  if (camera) {
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
}

function buildRenderer() {
  renderer = new THREE.WebGLRenderer({
    canvas: canvasEl,
    antialias: true,
    alpha: true,
  });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  resizeRenderer();
  canvasEl.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    cancelAnimation();
    showFallback('The WebGL context was lost. Reload to try again.');
    isReady = false;
  });
}

function buildCamera() {
  const width = Math.max(containerEl.clientWidth, 1);
  const height = Math.max(containerEl.clientHeight, 1);
  camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 400);
  // Default position along the initial sunLight direction so the lit face is visible
  const sunDir = new THREE.Vector3(4, 6, 10).normalize();
  camera.position.copy(sunDir.multiplyScalar(5));
}

function buildControls() {
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.minDistance = 0.6;
  controls.maxDistance = 200;
  controls.rotateSpeed = 0.6;
  controls.zoomSpeed = 0.9;
  controls.target.set(0, 0, 0);
  controls.update();
  controls.addEventListener('start', () => {
    hasUserMovedCamera = true;
  });
}

function buildLights() {
  // richer multi-source lighting for better visual depth
  const ambient = new THREE.AmbientLight(0xffffff, 0.45);
  // warm main sun light
  sunLight = new THREE.DirectionalLight(0xfff2e6, 1.1);
  sunLight.position.set(4, 6, 10);
  sunLight.castShadow = false;
  // cool rim light for highlight
  const rim = new THREE.DirectionalLight(0x5eead4, 0.25);
  rim.position.set(-3, -2, -5);
  // soft hemisphere for subtle sky/ground tint
  const hemi = new THREE.HemisphereLight(0x87bfff, 0x0b1020, 0.18);
  scene.add(ambient, sunLight, rim, hemi);
}

async function buildEarth() {
  // ── EarthSystem group (top-level, positioned at Earth's heliocentric pos) ──
  earthSystemGroup = new THREE.Group();
  earthSystemGroup.name = 'EarthSystem';

  earthGroup = new THREE.Group();
  earthGroup.name = 'EarthGroup';

  const earthGeometry = new THREE.SphereGeometry(1, 128, 128);
  try {
    earthTextures = await createEarthTextures(THREE);
    if (earthTextures?.source) {
      console.info(`Texturas de la Tierra cargadas (${earthTextures.source}).`);
    }
  } catch (error) {
    console.error('No se pudieron cargar las texturas de la Tierra', error);
    throw new Error('No se pudieron cargar las texturas de la Tierra.');
  }
  const maxAniso = renderer?.capabilities?.getMaxAnisotropy?.() ?? 4;
  if (earthTextures?.day) {
    earthTextures.day.anisotropy = Math.min(maxAniso, 12);
    earthTextures.day.needsUpdate = true;
  }
  if (earthTextures?.night) {
    earthTextures.night.anisotropy = Math.min(maxAniso, 12);
    earthTextures.night.needsUpdate = true;
  }
  earthUniforms = {
    dayMap: { value: earthTextures?.day ?? null },
    nightMap: { value: earthTextures?.night ?? null },
    sunDirection: { value: new THREE.Vector3(1, 0, 0) },
    ambientStrength: { value: 0.35 },
    nightStrength: { value: 0.88 },
  };
  const earthMaterial = new THREE.ShaderMaterial({
    uniforms: earthUniforms,
    vertexShader: EARTH_VERTEX_SHADER,
    fragmentShader: EARTH_FRAGMENT_SHADER,
    transparent: false,             // ← opaque: stars cannot bleed through
    depthWrite: true,
  });
  earthMesh = new THREE.Mesh(earthGeometry, earthMaterial);
  earthMesh.name = 'Earth';
  earthGroup.add(earthMesh);

  const atmosphereGeometry = new THREE.SphereGeometry(1.02, 96, 96);
  const atmosphereMaterial = new THREE.MeshBasicMaterial({
    color: 0x60a5fa,
    transparent: true,
    opacity: 0.16,
    side: THREE.BackSide,
    depthWrite: false,              // ← don't interfere with Earth depth
  });
  atmosphereMesh = new THREE.Mesh(atmosphereGeometry, atmosphereMaterial);
  atmosphereMesh.name = 'Atmosphere';
  earthGroup.add(atmosphereMesh);

  earthSystemGroup.add(earthGroup);
  scene.add(earthSystemGroup);

  // ── Earth orbit line (heliocentric mode) ─────────────────────────────
  earthOrbitLine = new THREE.Line(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({
      color: 0x334155,
      linewidth: 1,
      transparent: true,
      opacity: 0.45,
    })
  );
  earthOrbitLine.name = 'EarthOrbitLine';
  earthOrbitLine.visible = false;
  earthOrbitLine.frustumCulled = false;
  scene.add(earthOrbitLine);

  updateSunDirection();
}

function buildSceneGraph() {
  orbitLine = new THREE.Line(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: 0x7c3aed, linewidth: 2 })
  );
  orbitLine.visible = false;

  linkLine = new THREE.Line(
    new THREE.BufferGeometry(),
    new THREE.LineDashedMaterial({
      color: 0x38bdf8,
      dashSize: 0.05,
      gapSize: 0.03,
    })
  );
  linkLine.visible = false;

  groundTrackLine = new THREE.Line(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 1.2 })
  );
  groundTrackLine.visible = false;
  earthGroup.add(groundTrackLine);

  groundTrackVectorLine = new THREE.Line(
    new THREE.BufferGeometry(),
    new THREE.LineDashedMaterial({
      color: 0x14b8a6,
      dashSize: 0.045,
      gapSize: 0.03,
    })
  );
  groundTrackVectorLine.visible = false;
  earthSystemGroup.add(groundTrackVectorLine);

  const satMaterial = new THREE.MeshStandardMaterial({
    color: 0xf97316,
    emissive: 0x9a3412,
    metalness: 0.2,
    roughness: 0.4,
  });
  satelliteMesh = new THREE.Mesh(new THREE.SphereGeometry(0.03, 20, 20), satMaterial);
  satelliteMesh.visible = false;

  stationGroup = new THREE.Group();
  stationGroup.name = 'StationGroup';
  earthGroup.add(stationGroup);

  scene.add(orbitLine, linkLine, satelliteMesh);
  // NOTE: orbitLine, linkLine, satelliteMesh stay in scene root for now.
  // They use world-space ECI coordinates.  In helio mode we re-parent them
  // into earthSystemGroup (see setHelioMode).
}

function startAnimation() {
  cancelAnimation();
  passiveAtmosphereOffset = 0;
  const renderFrame = () => {
    if (earthGroup) {
      earthGroup.rotation.y = earthSimulationRotation + EARTH_BASE_ROTATION;
    }
    if (atmosphereMesh) {
      passiveAtmosphereOffset = (passiveAtmosphereOffset + 0.003) % (Math.PI * 2);
      atmosphereMesh.rotation.y = earthSimulationRotation + passiveAtmosphereOffset + EARTH_BASE_ROTATION;
    }
    // Camera target follows earthSystemGroup (helio mode moves it; orbit mode keeps 0,0,0)
    if (controls && earthSystemGroup) {
      controls.target.copy(earthSystemGroup.position);
    }
    controls?.update();
    renderer.render(scene, camera);
    animationHandle = window.requestAnimationFrame(renderFrame);
  };
  animationHandle = window.requestAnimationFrame(renderFrame);
}

function cancelAnimation() {
  if (animationHandle) {
    window.cancelAnimationFrame(animationHandle);
    animationHandle = null;
  }
}

function ensureStationMesh(station) {
  if (!stationMeshes.has(station.id)) {
    const material = new THREE.MeshStandardMaterial({
      color: 0x0ea5e9,
      emissive: 0x082f49,
      metalness: 0.1,
      roughness: 0.8,
    });
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.025, 14, 14), material);
    mesh.name = `station-${station.id}`;
    stationGroup.add(mesh);
    stationMeshes.set(station.id, mesh);
  }
  return stationMeshes.get(station.id);
}

function clearStations(keepIds) {
  Array.from(stationMeshes.keys()).forEach((id) => {
    if (!keepIds.has(id)) {
      const mesh = stationMeshes.get(id);
      stationGroup.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      stationMeshes.delete(id);
    }
  });
}

function toVector3(arr) {
  if (!THREE || !Array.isArray(arr)) return null;
  const [x, y, z] = arr;
  return new THREE.Vector3(x * UNIT_SCALE, z * UNIT_SCALE, -y * UNIT_SCALE);
}

function toVector3Eci(arr) {
  return toVector3(arr);
}

function updateEarthRotation() {
  if (earthGroup) {
    earthGroup.rotation.y = earthSimulationRotation + EARTH_BASE_ROTATION;
  }
  if (atmosphereMesh) {
    atmosphereMesh.rotation.y = earthSimulationRotation + passiveAtmosphereOffset + EARTH_BASE_ROTATION;
  }
}

function setEarthRotationFromTime(gmstAngle) {
  if (!Number.isFinite(gmstAngle)) return;
  earthSimulationRotation = gmstAngle;
  updateEarthRotation();
}

function vectorFromLatLon(latDeg, lonDeg, altitudeKm = GROUND_TRACK_ALTITUDE_KM) {
  if (!Number.isFinite(latDeg) || !Number.isFinite(lonDeg)) return null;
  const ecef = stationEcef({ lat: latDeg, lon: lonDeg }) || [];
  const vec = toVector3(ecef);
  if (!vec) return null;
  const safeAltitude = Number.isFinite(altitudeKm) ? altitudeKm : GROUND_TRACK_ALTITUDE_KM;
  const scale = (EARTH_RADIUS_KM + safeAltitude) / EARTH_RADIUS_KM;
  vec.multiplyScalar(scale);
  return vec;
}

function computeFramingRadius(points) {
  if (!Array.isArray(points)) return 0;
  let maxRadius = 0;
  points.forEach((point) => {
    const vec = toVector3Eci(point?.rEci);
    if (!vec) return;
    const length = vec.length();
    if (Number.isFinite(length)) {
      maxRadius = Math.max(maxRadius, length);
    }
  });
  return maxRadius;
}

function frameOrbitView(points, { force = false } = {}) {
  if (!isReady || !camera || !controls) return;
  const radius = computeFramingRadius(points);
  if (!Number.isFinite(radius) || radius <= 0) return;

  const safeRadius = Math.max(radius, 1.05);
  controls.maxDistance = Math.max(controls.maxDistance, safeRadius * 4.0);
  controls.minDistance = Math.min(controls.minDistance, 0.5);
  camera.far = Math.max(camera.far, safeRadius * 4.0);
  camera.updateProjectionMatrix();

  const radiusChangedSignificantly = !lastFramedRadius || safeRadius > lastFramedRadius * 1.3;
  const shouldReframe = force || !hasUserMovedCamera || radiusChangedSignificantly;
  lastFramedRadius = safeRadius;

  if (!shouldReframe) return;

  const distance = Math.max(safeRadius * 2.4, 2.6);
  const altitude = distance * 0.62;
  const lateral = distance * 0.45;

  camera.position.set(lateral, altitude, distance);
  controls.target.set(0, 0, 0);
  controls.update();
}

function updateGroundTrackSurface(points) {
  if (!isReady || !groundTrackLine) return;
  if (!Array.isArray(points) || points.length === 0) {
    groundTrackLine.visible = false;
    groundTrackLine.geometry.dispose();
    groundTrackLine.geometry = new THREE.BufferGeometry();
    return;
  }
  const vectors = points
    .map((point) => vectorFromLatLon(point?.lat, point?.lon))
    .filter((vec) => vec instanceof THREE.Vector3);
  if (!vectors.length) {
    groundTrackLine.visible = false;
    return;
  }
  groundTrackLine.geometry.dispose();
  groundTrackLine.geometry = new THREE.BufferGeometry().setFromPoints(vectors);
  groundTrackLine.visible = true;
}

function updateGroundTrackVector(point) {
  if (!isReady || !groundTrackVectorLine || !satelliteMesh) return;
  if (!point || !Array.isArray(point.rEci)) {
    groundTrackVectorLine.visible = false;
    return;
  }

  satelliteMesh.updateMatrixWorld(true);
  earthSystemGroup?.updateMatrixWorld(true);
  if (!satelliteMesh.visible) {
    groundTrackVectorLine.visible = false;
    return;
  }

  // groundTrackVectorLine lives inside earthSystemGroup, so use its local frame.
  const satWorld = satelliteMesh.getWorldPosition(new THREE.Vector3());
  const satPosition = earthSystemGroup
    ? earthSystemGroup.worldToLocal(satWorld.clone())
    : satWorld;
  const satRadius = satPosition.length();
  if (!Number.isFinite(satRadius) || satRadius <= 0) {
    groundTrackVectorLine.visible = false;
    return;
  }

  // Prefer the same ground-point transform as the ground track path.
  let groundPosition = null;
  if (Number.isFinite(point.lat) && Number.isFinite(point.lon) && Number.isFinite(point.gmst)) {
    const groundEci = orbit.latLonToEci(point.lat, point.lon, 0, point.gmst);
    groundPosition = toVector3Eci(groundEci);
  }
  if (!groundPosition) {
    // Fallback to radial nadir if lat/lon metadata is unavailable.
    groundPosition = satPosition.clone().normalize().multiplyScalar(1.0);
  }

  groundTrackVectorLine.geometry.dispose();
  groundTrackVectorLine.geometry = new THREE.BufferGeometry().setFromPoints([
    satPosition,
    groundPosition,
  ]);
  groundTrackVectorLine.visible = true;
  if (typeof groundTrackVectorLine.computeLineDistances === 'function') {
    groundTrackVectorLine.computeLineDistances();
  }
}

function updateSunDirection() {
  if (!earthUniforms?.sunDirection || !sunLight) return;
  earthUniforms.sunDirection.value.copy(sunLight.position).normalize();
}

async function initScene(container) {
  containerEl = container;
  canvasEl = container?.querySelector('#threeCanvas');
  fallbackEl = container?.querySelector('#threeFallback');

  if (!containerEl || !canvasEl) {
    console.error('3D mode container or canvas element not found.');
    showFallback('Missing 3D canvas in the interface.');
    return;
  }

  hideFallback();

  if (isReady) {
    resizeRenderer();
    return;
  }

  try {
    await ensureThree();

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000005);   // near-black; starfield adds visible stars

    buildRenderer();
    buildCamera();
    buildControls();
    buildLights();
    await buildEarth();
    buildSceneGraph();

    // Solar scene: starfield + sun sprite + lighting hookup
    const { initSolarScene } = await import('../solar.js');
    initSolarScene(THREE, scene, sunLight, earthUniforms);

    resizeObserver = new ResizeObserver(() => resizeRenderer());
    resizeObserver.observe(containerEl);
    window.addEventListener('resize', resizeRenderer);

    updateEarthRotation();
    startAnimation();
    isReady = true;
  } catch (error) {
    console.error('Error initializing the 3D view', error);
    showFallback(error?.message || 'Unable to initialize the 3D view.');
  }
}

function updateOrbitPath(points, { smooth = true } = {}) {
  if (!isReady || !orbitLine) return;
  if (!points?.length) {
    orbitLine.visible = false;
    orbitLine.geometry.dispose();
    orbitLine.geometry = new THREE.BufferGeometry();
    return;
  }
  
  // Ensure orbit objects are in correct parent for current mode
  // In orbit mode, they should be in scene root; in helio mode, in earthSystemGroup
  if (!_helioActive && orbitLine && scene && orbitLine.parent !== scene) {
    if (orbitLine.parent) orbitLine.parent.remove(orbitLine);
    scene.add(orbitLine);
  }
  
  // Ensure earthSystemGroup is at origin in orbit mode
  if (!_helioActive && earthSystemGroup) {
    earthSystemGroup.position.set(0, 0, 0);
  }
  
  const vectors = points
    .map((p) => toVector3Eci(p.rEci))
    .filter((vec) => vec instanceof THREE.Vector3);
  if (!vectors.length) {
    orbitLine.visible = false;
    return;
  }
  let renderPoints;
  if (smooth) {
    const first = vectors[0];
    const last = vectors[vectors.length - 1];
    const closed = first.distanceTo(last) < 1e-3;
    const curve = new THREE.CatmullRomCurve3(vectors, closed, 'centripetal', 0.5);
    const segments = Math.min(2048, Math.max(120, vectors.length * 3));
    renderPoints = curve.getPoints(segments);
  } else {
    renderPoints = vectors;
  }
  orbitLine.geometry.dispose();
  orbitLine.geometry = new THREE.BufferGeometry().setFromPoints(renderPoints);
  orbitLine.visible = true;
}

function updateSatellite(point) {
  if (!isReady || !satelliteMesh) return; // guard against not ready
  if (!point) {
    satelliteMesh.visible = false;
    return;
  }
  
  // Ensure satellite is in correct parent for current mode
  if (!_helioActive && satelliteMesh && scene && satelliteMesh.parent !== scene) {
    if (satelliteMesh.parent) satelliteMesh.parent.remove(satelliteMesh);
    scene.add(satelliteMesh);
  }
  
  const pos = toVector3Eci(point.rEci);
  if (!pos) {
    satelliteMesh.visible = false; // ensure it is hidden if pos is bad
    return;
  }
  satelliteMesh.position.copy(pos);
  satelliteMesh.visible = true;
}

/** Show/hide all ground-station markers on the globe. */
function setStationsVisible(visible) {
  if (stationGroup) stationGroup.visible = Boolean(visible);
  return Boolean(visible);
}

// Station display state — mirrors the Cesium adapter's API so the Ground
// Stations panel drives both engines. This backend draws no name labels, so
// `labels` is accepted and ignored.
const legacyStationDisplay = { mode: 'all', labels: true, selectedId: null };

function applyLegacyStationDisplay() {
  const { mode, selectedId } = legacyStationDisplay;
  if (stationGroup) stationGroup.visible = mode !== 'none';
  stationMeshes.forEach((mesh, id) => {
    mesh.visible = mode === 'all' || (mode === 'selected' && id === selectedId);
  });
}

function setStationDisplay(opts = {}) {
  if (opts.mode === 'all' || opts.mode === 'selected' || opts.mode === 'none') {
    legacyStationDisplay.mode = opts.mode;
  }
  if (typeof opts.labels === 'boolean') legacyStationDisplay.labels = opts.labels;
  if (opts.selectedId !== undefined) legacyStationDisplay.selectedId = opts.selectedId;
  applyLegacyStationDisplay();
  return { ...legacyStationDisplay };
}

function renderStations3D(stations, selectedId) {
  if (!isReady || !stationGroup) return;
  const keep = new Set();
  stations.forEach((station) => {
    const mesh = ensureStationMesh(station);
    const vec = toVector3(stationEcef(station));
    if (!vec) return;
    mesh.position.copy(vec);
    if (station.id === selectedId) {
      mesh.material.color.setHex(0xfacc15);
      mesh.material.emissive.setHex(0xb45309);
      mesh.scale.setScalar(1.6);
    } else {
      mesh.material.color.setHex(0x0ea5e9);
      mesh.material.emissive.setHex(0x082f49);
      mesh.scale.setScalar(1);
    }
    keep.add(station.id);
  });
  clearStations(keep);
  if (selectedId != null) legacyStationDisplay.selectedId = selectedId;
  applyLegacyStationDisplay();
}

function updateLink3D(point, station, elevationDeg = null) {
  if (!isReady || !linkLine) return;
  if (!point || !station) {
    linkLine.visible = false;
    return;
  }
  
  // Ensure linkLine is in correct parent for current mode
  if (!_helioActive && linkLine && scene && linkLine.parent !== scene) {
    if (linkLine.parent) linkLine.parent.remove(linkLine);
    scene.add(linkLine);
  }
  
  const sat = toVector3Eci(point.rEci);
  const mesh = ensureStationMesh(station);
  if (!sat || !mesh) {
    linkLine.visible = false;
    return;
  }
  earthSystemGroup?.updateMatrixWorld(true);
  earthGroup?.updateMatrixWorld(true);
  const ground = mesh.getWorldPosition(new THREE.Vector3());
  // When in helio mode linkLine lives inside earthSystemGroup → need local coords
  if (_helioActive && earthSystemGroup) {
    earthSystemGroup.worldToLocal(ground);
  }
  linkLine.geometry.dispose();
  linkLine.geometry = new THREE.BufferGeometry().setFromPoints([ground, sat]);
  if (typeof linkLine.computeLineDistances === 'function') {
    linkLine.computeLineDistances();
  }
  
  // Change color based on line of sight (elevation > 0 means above horizon)
  const hasLineOfSight = elevationDeg !== null && elevationDeg > 0;
  linkLine.material.color.setHex(hasLineOfSight ? LOS_COLOR : NO_LOS_COLOR);
  
  linkLine.visible = true;
}

function setTheme(nextTheme) {
  if (!scene || !renderer) return;
  // Keep near-black background so the procedural starfield is always visible.
  // Only tune the earth shader ambient / night strengths for each theme.
  const spaceBg = 0x000005;
  scene.background.setHex(spaceBg);
  renderer.setClearColor(spaceBg, 1);
  if (nextTheme === 'dark') {
    if (earthUniforms) {
      earthUniforms.ambientStrength.value = 0.3;
      earthUniforms.nightStrength.value = 1.05;
    }
  } else {
    if (earthUniforms) {
      earthUniforms.ambientStrength.value = 0.4;
      earthUniforms.nightStrength.value = 0.85;
    }
  }
}

function disposeScene() {
  cancelAnimation();
  if (resizeObserver && containerEl) {
    resizeObserver.unobserve(containerEl);
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  window.removeEventListener('resize', resizeRenderer);

  if (renderer) {
    renderer.dispose();
    renderer = null;
  }

  stationMeshes.forEach((mesh) => {
    mesh.geometry.dispose();
    mesh.material.dispose();
  });
  stationMeshes.clear();
  constellationPoints.forEach((entry) => {
    scene?.remove(entry.points);
    entry.points?.geometry?.dispose?.();
    entry.material?.dispose?.();
  });
  constellationPoints.clear();

  earthGroup?.remove(groundTrackLine);
  earthGroup?.remove(stationGroup);
  earthSystemGroup?.remove(earthGroup);
  earthSystemGroup?.remove(groundTrackVectorLine);
  scene?.remove(earthSystemGroup);
  scene?.remove(earthOrbitLine);
  scene?.remove(orbitLine);
  scene?.remove(linkLine);
  scene?.remove(satelliteMesh);
  // Also check earthSystemGroup in case helio mode re-parented them
  earthSystemGroup?.remove(orbitLine);
  earthSystemGroup?.remove(linkLine);
  earthSystemGroup?.remove(satelliteMesh);
  scene?.remove(groundTrackVectorLine);

  orbitLine?.geometry?.dispose();
  orbitLine?.material?.dispose();
  linkLine?.geometry?.dispose();
  linkLine?.material?.dispose();
  groundTrackLine?.geometry?.dispose();
  groundTrackLine?.material?.dispose();
  groundTrackVectorLine?.geometry?.dispose();
  groundTrackVectorLine?.material?.dispose();
  earthMesh?.geometry?.dispose();
  earthMesh?.material?.dispose();
  atmosphereMesh?.geometry?.dispose();
  atmosphereMesh?.material?.dispose();
  disposeEarthTextures();

  scene = null;
  camera = null;
  controls = null;
  earthGroup = null;
  earthSystemGroup = null;
  earthOrbitLine = null;
  earthMesh = null;
  atmosphereMesh = null;
  orbitLine = null;
  satelliteMesh = null;
stationGroup = null;
  linkLine = null;
  groundTrackLine = null;
  groundTrackVectorLine = null;
  earthUniforms = null;
  earthTextures = null;
  sunLight = null;
  containerEl = null;
  canvasEl = null;
  fallbackEl = null;
  isReady = false;
  earthSimulationRotation = 0;
  passiveAtmosphereOffset = 0;
}

function ensureConstellationEntry(groupId, color) {
  if (!isReady || !scene || !THREE) return null;
  let entry = constellationPoints.get(groupId);
  if (!entry) {
    const geometry = new THREE.BufferGeometry();
    const material = new THREE.PointsMaterial({
      color: new THREE.Color(color || 0xffffff),
      size: 0.02,
      sizeAttenuation: true,
      depthWrite: false,
      transparent: true,
      opacity: 0.92,
    });
    const points = new THREE.Points(geometry, material);
    points.name = `constellation-${groupId}`;
    const cParent = earthSystemGroup || scene;
    cParent.add(points);
    entry = { geometry, material, points };
    constellationPoints.set(groupId, entry);
  } else if (color) {
    entry.material.color.set(color);
  }
  entry.points.visible = true;
  return entry;
}

function renderConstellations3D(groupId, satellites, options = {}) {
  if (!isReady || !scene || !THREE) return;
  if (!Array.isArray(satellites) || satellites.length === 0) {
    clearConstellation(groupId);
    return;
  }
  const color = options.color || '#ffffff';
  
  const currentMeshes = new Set();
  const currentOrbitLines = new Set();
  const currentGroundTrackSurfaceLines = new Set();
  const currentGroundTrackVectorLines = new Set();

  satellites.forEach((sat) => {
    if (!Array.isArray(sat?.rEci) || sat.rEci.length !== 3) return;
    const key = `${groupId}-${sat.id}`;

    // Update satellite mesh
    const mesh = createConstellationSatelliteMesh(sat, color, groupId);
    const pos = toVector3Eci(sat.rEci);
    if (pos) {
      mesh.position.copy(pos);
      mesh.visible = true;
    } else {
      mesh.visible = false;
    }
    currentMeshes.add(key);

    // Update orbit line for this satellite
    if (sat.orbitPath && sat.orbitPath.length > 0) {
      const line = updateConstellationOrbitLine3D(sat.id, sat.orbitPath, color, groupId);
      currentOrbitLines.add(`${groupId}-${sat.id}-orbit`);
    }

    // Update ground track and vectors
    if (sat.groundTrack && sat.groundTrack.length > 0) {
        updateConstellationGroundTrackSurface3D(sat.id, sat.groundTrack, color, groupId);
        currentGroundTrackSurfaceLines.add(`${groupId}-${sat.id}-groundtrack-surface`);
    }
    const groundEci = orbit.latLonToEci(sat.lat, sat.lon, 0, sat.gmst);
    updateConstellationGroundTrackVector3D(sat.id, sat.rEci, groundEci, color, groupId);
    currentGroundTrackVectorLines.add(`${groupId}-${sat.id}-groundtrack-vector`);
  });

  // Cleanup old meshes
  Array.from(constellationSatelliteMeshes.keys()).forEach((key) => {
    if (key.startsWith(`${groupId}-`) && !currentMeshes.has(key)) {
      const mesh = constellationSatelliteMeshes.get(key);
      if (mesh) {
        earthSystemGroup?.remove(mesh);
        scene.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
        constellationSatelliteMeshes.delete(key);
      }
    }
  });

  // Cleanup old orbit lines
  Array.from(constellationOrbitLines.keys()).forEach((key) => {
    if (key.startsWith(`${groupId}-`) && !currentOrbitLines.has(key)) {
      const line = constellationOrbitLines.get(key);
      if (line) {
        earthGroup.remove(line);
        line.geometry.dispose();
        line.material.dispose();
        constellationOrbitLines.delete(key);
      }
    }
  });
  
  // Cleanup old ground track and vector lines
  Array.from(constellationGroundTrackSurfaceLines.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`) && !currentGroundTrackSurfaceLines.has(key)) {
      const line = constellationGroundTrackSurfaceLines.get(key);
      if (line) {
        earthGroup.remove(line);
        line.geometry.dispose();
        line.material.dispose();
        constellationGroundTrackSurfaceLines.delete(key);
      }
    }
  });
  Array.from(constellationGroundTrackVectorLines.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`) && !currentGroundTrackVectorLines.has(key)) {
      const line = constellationGroundTrackVectorLines.get(key);
      if (line) {
        earthSystemGroup?.remove(line);
        scene.remove(line);
        line.geometry.dispose();
        line.material.dispose();
        constellationGroundTrackVectorLines.delete(key);
      }
    }
  });
}

function clearConstellation(groupId) {
  // Clear meshes
  Array.from(constellationSatelliteMeshes.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const mesh = constellationSatelliteMeshes.get(key);
      if (mesh) {
        earthSystemGroup?.remove(mesh);
        scene.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
        constellationSatelliteMeshes.delete(key);
      }
    }
  });

  // Clear orbit lines
  Array.from(constellationOrbitLines.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const line = constellationOrbitLines.get(key);
      if (line) {
        earthGroup.remove(line);
        line.geometry.dispose();
        line.material.dispose();
        constellationOrbitLines.delete(key);
      }
    }
  });

  // Clear ground track and vector lines
  Array.from(constellationGroundTrackSurfaceLines.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const line = constellationGroundTrackSurfaceLines.get(key);
      if (line) {
        earthGroup.remove(line);
        line.geometry.dispose();
        line.material.dispose();
        constellationGroundTrackSurfaceLines.delete(key);
      }
    }
  });
  Array.from(constellationGroundTrackVectorLines.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const line = constellationGroundTrackVectorLines.get(key);
      if (line) {
        earthSystemGroup?.remove(line);
        scene.remove(line);
        line.geometry.dispose();
        line.material.dispose();
        constellationGroundTrackVectorLines.delete(key);
      }
    }
  });
}

/**
 * Update the sun direction (light + earth shader uniform) from a
 * Three.js-space direction vector [tx, ty, tz].  Called by main.js
 * via the solar module.
 */
function updateSolarLighting(tx, ty, tz) {
  if (_helioActive && earthSystemGroup) {
    // In helio mode the Sun is at the origin.
    // sunLight should illuminate Earth → place it at origin pointing toward earthSystemGroup
    if (sunLight) {
      sunLight.position.set(0, 0, 0);
      sunLight.target = earthSystemGroup;
    }
  } else {
    if (sunLight) sunLight.position.set(tx * 10, ty * 10, tz * 10);
  }
  if (earthUniforms?.sunDirection) {
    earthUniforms.sunDirection.value.set(tx, ty, tz).normalize();
  }
  // Auto-position camera so the user sees the sunlit hemisphere
  if (!hasUserMovedCamera && camera && controls) {
    const d = camera.position.length() || 5;
    const dir = new THREE.Vector3(tx, ty, tz).normalize();
    camera.position.copy(dir.multiplyScalar(d));
    controls.target.set(0, 0, 0);
    controls.update();
  }
}

// ── Heliocentric mode helpers ─────────────────────────────────────────────

const AU_TO_SCENE = 50;  // 1 AU → 50 scene units (artistic scale)

let _helioActive = false;

/**
 * Convert an ECI-AU position [x,y,z] to Three.js scene coordinates using
 * the heliocentric scale.  Same axis mapping as toVector3: tx=x, ty=z, tz=-y.
 */
function helioToThreeVec(posAU) {
  if (!THREE || !Array.isArray(posAU)) return null;
  const [x, y, z] = posAU;
  return new THREE.Vector3(x * AU_TO_SCENE, z * AU_TO_SCENE, -y * AU_TO_SCENE);
}

/**
 * Switch the scene graph between orbit (Earth-centred) and heliocentric
 * (Sun-centred) modes.  Moves orbitLine / satelliteMesh / linkLine in or
 * out of earthSystemGroup.
 */
function setHelioMode(active) {
  if (!isReady || active === _helioActive) return;
  _helioActive = active;

  const objs = [orbitLine, satelliteMesh, linkLine].filter(Boolean);
  if (active) {
    // Re-parent into earthSystemGroup so they move with Earth
    objs.forEach((o) => { scene.remove(o); earthSystemGroup.add(o); });
    // Increase camera far plane for orbit-wide view
    if (camera) { camera.far = 800; camera.updateProjectionMatrix(); }
    if (controls) { controls.maxDistance = 500; }
    if (earthOrbitLine) earthOrbitLine.visible = true;
  } else {
    // Move back to scene root
    objs.forEach((o) => { earthSystemGroup.remove(o); scene.add(o); });
    // Reset earthSystemGroup position to origin
    if (earthSystemGroup) earthSystemGroup.position.set(0, 0, 0);
    if (camera) { camera.far = 400; camera.updateProjectionMatrix(); }
    if (controls) { controls.maxDistance = 200; }
    if (earthOrbitLine) earthOrbitLine.visible = false;
  }
}

/**
 * Set Earth's heliocentric position for the current timestep.
 * `posAU` is [x,y,z] in AU (J2000 ECI equatorial) from the backend.
 */
function setEarthHelioPosition(posAU) {
  if (!earthSystemGroup || !posAU) return;
  const v = helioToThreeVec(posAU);
  if (v) earthSystemGroup.position.copy(v);
}

/**
 * Build / update the Earth orbit path visualisation from an array of
 * heliocentric positions (AU, ECI).
 */
function updateEarthOrbitPath(positionsAU) {
  if (!earthOrbitLine || !Array.isArray(positionsAU) || positionsAU.length < 2) return;
  const vecs = positionsAU.map((p) => helioToThreeVec(p)).filter(Boolean);
  if (vecs.length < 2) return;
  const closed = vecs[0].distanceTo(vecs[vecs.length - 1]) < 0.5;
  const curve = new THREE.CatmullRomCurve3(vecs, closed, 'centripetal', 0.5);
  const pts = curve.getPoints(Math.min(2048, vecs.length * 4));
  earthOrbitLine.geometry.dispose();
  earthOrbitLine.geometry = new THREE.BufferGeometry().setFromPoints(pts);
  earthOrbitLine.visible = true;
}

export const scene3d = {
  setEarthRotationFromTime,
  frameOrbitView,
  updateGroundTrackSurface,
  updateGroundTrackVector,
  initScene,
  updateOrbitPath,
  updateSatellite,
  renderStations: renderStations3D,
  setStationsVisible,
  setStationDisplay,
  updateLink: updateLink3D,
  setTheme,
  disposeScene,
  renderConstellations: renderConstellations3D,
  clearConstellation,
  updateSolarLighting,
  // Heliocentric mode
  setHelioMode,
  setEarthHelioPosition,
  updateEarthOrbitPath,
};

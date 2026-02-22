// ---------------------------------------------------------------------------
// app/static/ui.js
// ---------------------------------------------------------------------------
// Purpose : Rendering layer — combines Three.js 3D globe (scene3d),
//           Leaflet 2D map (map2d), procedural earth textures, GLSL
//           shaders, and panel/slider utilities.
//
// Exports : earthTexture, map2d, scene3d, initSliders, createPanelAccordions
//
// Structure:
//   Lines   1-600   : Geodata constants (land masses, cities, colors)
//   Lines 600-900   : Texture generation (day/night canvas, loading)
//   Lines 900-1580  : map2d (Leaflet 2D map functions)
//   Lines 1580-2700 : scene3d (Three.js 3D globe functions)
//   Lines 2700+     : Slider/accordion utilities
//
// NOTE    : Further decomposition into geodata.js, textures.js, map2d.js,
//           scene3d.js is planned for future iterations.
// ---------------------------------------------------------------------------
import { clamp, formatDistanceKm } from './utils.js';
import { orbit } from './simulation.js';

const { constants: orbitConstants, stationEcef } = orbit;

const CANVAS_WIDTH = 2048;
const CANVAS_HEIGHT = 1024;
const OCEAN_TOP = '#08223c';
const OCEAN_BOTTOM = '#0c2f57';
const LAND_MID = '#3ca86e';
const LAND_SHADOW = '#1e6b44';
const DESERT_TONE = 'rgba(203, 161, 94, 0.55)';
const HIGHLAND_TONE = 'rgba(120, 162, 120, 0.4)';
const ICE_COLOR = 'rgba(224, 244, 255, 0.92)';
const ICE_EDGE = 'rgba(144, 196, 216, 0.65)';
const GRID_COLOR = 'rgba(255, 255, 255, 0.06)';
const NIGHT_OCEAN_TOP = '#01070f';
const NIGHT_OCEAN_BOTTOM = '#041329';
const NIGHT_LAND = '#0c1c2a';
const NIGHT_GLOW = 'rgba(255, 198, 120, 0.85)';
const NIGHT_GLOW_EDGE = 'rgba(255, 140, 60, 0.0)';

// Line of sight colors
const LOS_COLOR = 0x38bdf8; // Cyan - satellite visible from ground station
const NO_LOS_COLOR = 0xef4444; // Red - satellite below horizon

// Prefer reliable CDN textures first to avoid noisy local 404s when /static/assets is not populated
const TEXTURE_SOURCES = [
  {
    label: 'cdn-three-globe',
    day: 'https://cdn.jsdelivr.net/npm/three-globe@2.30.0/example/img/earth-blue-marble.jpg',
    night: 'https://cdn.jsdelivr.net/npm/three-globe@2.30.0/example/img/earth-night.jpg',
  },
  {
    label: 'cdn-nasa',
    day: 'https://cdn.jsdelivr.net/gh/astronexus/NasaBlueMarble@main/earth_daymap_2048.jpg',
    night: 'https://cdn.jsdelivr.net/gh/astronexus/NasaBlueMarble@main/earth_night_2048.jpg',
  },
  {
    label: 'local',
    day: '/static/assets/earth_day_4k.jpg',
    night: '/static/assets/earth_night_4k.jpg',
  },
];

const LAND_MASSES = [
  {
    name: 'NorthAmerica',
    coordinates: [
      [-167, 71],
      [-160, 72],
      [-152, 71],
      [-144, 68],
      [-135, 63],
      [-128, 58],
      [-124, 53],
      [-123, 48],
      [-124, 43],
      [-123, 38],
      [-120, 35],
      [-116, 32],
      [-111, 30],
      [-106, 27],
      [-101, 24],
      [-97, 21],
      [-94, 18],
      [-90, 16],
      [-87, 17],
      [-83, 20],
      [-81, 24],
      [-80, 27],
      [-79, 31],
      [-76, 35],
      [-73, 40],
      [-69, 45],
      [-66, 48],
      [-62, 52],
      [-60, 56],
      [-63, 60],
      [-70, 66],
      [-80, 70],
      [-92, 73],
      [-108, 75],
      [-124, 75],
      [-140, 73],
      [-152, 72],
      [-160, 72],
      [-167, 71],
    ],
  },
  {
    name: 'CentralAmerica',
    coordinates: [
      [-90, 17],
      [-86, 15],
      [-84, 11],
      [-83, 9],
      [-81, 8],
      [-79, 9],
      [-78, 11],
      [-79, 14],
      [-82, 17],
      [-86, 19],
      [-90, 17],
    ],
  },
  {
    name: 'SouthAmerica',
    coordinates: [
      [-81, 12],
      [-78, 8],
      [-76, 4],
      [-74, -1],
      [-74, -6],
      [-76, -12],
      [-78, -18],
      [-79, -22],
      [-78, -28],
      [-74, -33],
      [-70, -38],
      [-66, -44],
      [-63, -50],
      [-60, -54],
      [-56, -55],
      [-52, -50],
      [-48, -44],
      [-46, -36],
      [-44, -28],
      [-44, -22],
      [-46, -16],
      [-50, -10],
      [-54, -5],
      [-58, -1],
      [-62, 3],
      [-66, 6],
      [-70, 8],
      [-75, 10],
      [-79, 12],
      [-81, 12],
    ],
  },
  {
    name: 'Eurasia',
    coordinates: [
      [-10, 36],
      [-6, 44],
      [-4, 50],
      [0, 54],
      [6, 60],
      [12, 64],
      [20, 70],
      [28, 73],
      [38, 75],
      [50, 75],
      [60, 73],
      [70, 71],
      [82, 70],
      [94, 71],
      [108, 71],
      [122, 66],
      [132, 60],
      [140, 54],
      [148, 48],
      [154, 44],
      [160, 40],
      [166, 36],
      [168, 32],
      [162, 28],
      [150, 24],
      [140, 20],
      [130, 19],
      [120, 20],
      [110, 23],
      [100, 27],
      [92, 31],
      [86, 35],
      [80, 39],
      [74, 42],
      [68, 47],
      [60, 50],
      [52, 50],
      [46, 46],
      [40, 40],
      [36, 36],
      [32, 32],
      [36, 26],
      [44, 22],
      [52, 20],
      [60, 18],
      [70, 16],
      [78, 12],
      [84, 8],
      [88, 5],
      [92, 8],
      [98, 12],
      [106, 16],
      [114, 18],
      [122, 16],
      [128, 12],
      [132, 6],
      [132, 0],
      [126, -6],
      [118, -10],
      [110, -10],
      [102, -6],
      [96, -2],
      [90, 4],
      [84, 10],
      [78, 14],
      [70, 18],
      [62, 20],
      [54, 22],
      [46, 24],
      [38, 28],
      [32, 32],
      [26, 36],
      [20, 40],
      [14, 42],
      [8, 43],
      [4, 42],
      [0, 40],
      [-4, 38],
      [-8, 36],
      [-10, 36],
    ],
  },
  {
    name: 'Africa',
    coordinates: [
      [-17, 37],
      [-12, 35],
      [-8, 30],
      [-6, 24],
      [-6, 18],
      [-6, 12],
      [-7, 6],
      [-9, 2],
      [-11, -6],
      [-13, -14],
      [-15, -20],
      [-10, -28],
      [-4, -34],
      [4, -38],
      [12, -40],
      [20, -40],
      [28, -34],
      [32, -28],
      [36, -20],
      [40, -10],
      [44, -2],
      [48, 6],
      [51, 12],
      [48, 16],
      [42, 20],
      [36, 24],
      [28, 28],
      [22, 32],
      [16, 35],
      [8, 36],
      [0, 34],
      [-8, 34],
      [-14, 36],
      [-17, 37],
    ],
  },
  {
    name: 'Arabia',
    coordinates: [
      [38, 32],
      [42, 30],
      [46, 26],
      [50, 20],
      [53, 16],
      [55, 12],
      [52, 10],
      [48, 12],
      [44, 14],
      [40, 18],
      [38, 22],
      [36, 26],
      [36, 30],
      [38, 32],
    ],
  },
  {
    name: 'Australia',
    coordinates: [
      [112, -12],
      [114, -18],
      [118, -26],
      [124, -32],
      [132, -35],
      [140, -34],
      [146, -30],
      [152, -26],
      [154, -20],
      [150, -16],
      [146, -12],
      [138, -10],
      [132, -10],
      [124, -8],
      [118, -8],
      [112, -12],
    ],
  },
  {
    name: 'Greenland',
    coordinates: [
      [-52, 60],
      [-54, 64],
      [-56, 68],
      [-52, 72],
      [-46, 75],
      [-38, 78],
      [-28, 79],
      [-20, 78],
      [-18, 74],
      [-24, 70],
      [-32, 66],
      [-40, 62],
      [-48, 60],
      [-52, 60],
    ],
  },
  {
    name: 'Madagascar',
    coordinates: [
      [44, -12],
      [46, -14],
      [48, -18],
      [49, -22],
      [47, -26],
      [44, -24],
      [43, -20],
      [43, -16],
      [44, -12],
    ],
  },
  {
    name: 'Japan',
    coordinates: [
      [129, 33],
      [132, 35],
      [135, 37],
      [138, 39],
      [141, 43],
      [144, 45],
      [146, 44],
      [144, 40],
      [141, 36],
      [138, 34],
      [134, 33],
      [129, 33],
    ],
  },
  {
    name: 'Indonesia',
    coordinates: [
      [95, 5],
      [100, 2],
      [105, 0],
      [110, -2],
      [116, -4],
      [122, -4],
      [128, -2],
      [132, 2],
      [128, 6],
      [122, 8],
      [116, 7],
      [110, 6],
      [104, 6],
      [98, 6],
      [95, 5],
    ],
  },
  {
    name: 'Philippines',
    coordinates: [
      [118, 18],
      [120, 16],
      [122, 12],
      [122, 9],
      [120, 6],
      [118, 7],
      [116, 10],
      [116, 14],
      [118, 18],
    ],
  },
  {
    name: 'UnitedKingdom',
    coordinates: [
      [-8, 49],
      [-6, 52],
      [-5, 56],
      [-3, 58],
      [0, 59],
      [1, 56],
      [-1, 53],
      [-4, 51],
      [-8, 49],
    ],
  },
  {
    name: 'Iceland',
    coordinates: [
      [-24, 63],
      [-22, 65],
      [-18, 66],
      [-14, 65],
      [-16, 63],
      [-20, 62],
      [-24, 63],
    ],
  },
  {
    name: 'NewZealandNorth',
    coordinates: [
      [172, -34],
      [175, -35],
      [178, -38],
      [177, -40],
      [174, -41],
      [171, -39],
      [172, -34],
    ],
  },
  {
    name: 'NewZealandSouth',
    coordinates: [
      [166, -45],
      [168, -46],
      [172, -47],
      [174, -48],
      [172, -50],
      [168, -50],
      [166, -48],
      [166, -45],
    ],
  },
];

const ANTARCTIC_SEGMENTS = [
  {
    coordinates: [
      [-180, -74],
      [-150, -72],
      [-120, -72],
      [-90, -73],
      [-60, -75],
      [-30, -78],
      [0, -80],
    ],
  },
  {
    coordinates: [
      [0, -80],
      [30, -78],
      [60, -76],
      [90, -74],
      [120, -72],
      [150, -73],
      [180, -74],
    ],
  },
];

const DESERT_PATCHES = [
  {
    coordinates: [
      [-14, 30],
      [0, 30],
      [12, 28],
      [20, 26],
      [28, 24],
      [32, 20],
      [28, 16],
      [18, 18],
      [10, 20],
      [0, 22],
      [-8, 24],
      [-14, 30],
    ],
  },
  {
    coordinates: [
      [56, 26],
      [64, 24],
      [70, 22],
      [76, 20],
      [78, 16],
      [72, 14],
      [64, 16],
      [58, 20],
      [56, 24],
      [56, 26],
    ],
  },
  {
    coordinates: [
      [-70, -10],
      [-62, -6],
      [-56, -8],
      [-54, -14],
      [-58, -20],
      [-64, -22],
      [-70, -20],
      [-72, -14],
      [-70, -10],
    ],
  },
];

const HIGHLAND_PATCHES = [
  {
    coordinates: [
      [-80, 50],
      [-72, 48],
      [-66, 48],
      [-62, 52],
      [-66, 56],
      [-74, 56],
      [-80, 50],
    ],
  },
  {
    coordinates: [
      [86, 46],
      [94, 44],
      [100, 42],
      [106, 44],
      [104, 50],
      [96, 52],
      [90, 50],
      [86, 46],
    ],
  },
  {
    coordinates: [
      [12, 40],
      [16, 42],
      [22, 44],
      [26, 46],
      [22, 48],
      [16, 46],
      [12, 42],
      [12, 40],
    ],
  },
];

const CITY_LIGHTS = [
  { name: 'New York', lat: 40.7, lon: -74.0, radius: 20, intensity: 1.0 },
  { name: 'Chicago', lat: 41.8, lon: -87.6, radius: 16, intensity: 0.9 },
  { name: 'Los Angeles', lat: 34.0, lon: -118.2, radius: 18, intensity: 0.9 },
  { name: 'Houston', lat: 29.7, lon: -95.3, radius: 16, intensity: 0.85 },
  { name: 'Mexico City', lat: 19.4, lon: -99.1, radius: 18, intensity: 0.95 },
  { name: 'Sao Paulo', lat: -23.5, lon: -46.6, radius: 22, intensity: 1.0 },
  { name: 'Buenos Aires', lat: -34.6, lon: -58.4, radius: 18, intensity: 0.9 },
  { name: 'Lima', lat: -12.0, lon: -77.0, radius: 14, intensity: 0.75 },
  { name: 'London', lat: 51.5, lon: -0.1, radius: 18, intensity: 1.0 },
  { name: 'Paris', lat: 48.8, lon: 2.3, radius: 16, intensity: 0.95 },
  { name: 'Berlin', lat: 52.5, lon: 13.4, radius: 16, intensity: 0.85 },
  { name: 'Moscow', lat: 55.8, lon: 37.6, radius: 20, intensity: 1.0 },
  { name: 'Madrid', lat: 40.4, lon: -3.7, radius: 15, intensity: 0.8 },
  { name: 'Rome', lat: 41.9, lon: 12.5, radius: 14, intensity: 0.8 },
  { name: 'Cairo', lat: 30.0, lon: 31.2, radius: 18, intensity: 0.9 },
  { name: 'Lagos', lat: 6.5, lon: 3.4, radius: 16, intensity: 0.85 },
  { name: 'Johannesburg', lat: -26.2, lon: 28.0, radius: 16, intensity: 0.8 },
  { name: 'Dubai', lat: 25.2, lon: 55.3, radius: 14, intensity: 0.8 },
  { name: 'Mumbai', lat: 19.0, lon: 72.8, radius: 20, intensity: 1.0 },
  { name: 'Delhi', lat: 28.6, lon: 77.2, radius: 18, intensity: 0.95 },
  { name: 'Bangalore', lat: 12.9, lon: 77.6, radius: 14, intensity: 0.8 },
  { name: 'Beijing', lat: 39.9, lon: 116.4, radius: 20, intensity: 1.0 },
  { name: 'Shanghai', lat: 31.2, lon: 121.5, radius: 22, intensity: 1.0 },
  { name: 'Shenzhen', lat: 22.5, lon: 114.1, radius: 18, intensity: 0.95 },
  { name: 'Hong Kong', lat: 22.3, lon: 114.2, radius: 16, intensity: 0.9 },
  { name: 'Seoul', lat: 37.5, lon: 127.0, radius: 18, intensity: 1.0 },
  { name: 'Tokyo', lat: 35.7, lon: 139.7, radius: 22, intensity: 1.0 },
  { name: 'Osaka', lat: 34.7, lon: 135.5, radius: 18, intensity: 0.9 },
  { name: 'Sydney', lat: -33.9, lon: 151.2, radius: 16, intensity: 0.85 },
  { name: 'Melbourne', lat: -37.8, lon: 144.9, radius: 16, intensity: 0.8 },
  { name: 'Perth', lat: -31.9, lon: 115.9, radius: 14, intensity: 0.75 },
  { name: 'Auckland', lat: -36.8, lon: 174.7, radius: 14, intensity: 0.7 },
];

function createCanvas(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function projectLon(lon, width) {
  return ((lon + 180) / 360) * width;
}

function projectLat(lat, height) {
  return ((90 - lat) / 180) * height;
}

function tracePolygon(ctx, coordinates, width, height) {
  if (!coordinates?.length) return;
  let prevLon = coordinates[0][0];
  let unwrappedLon = prevLon;
  ctx.moveTo(projectLon(unwrappedLon, width), projectLat(coordinates[0][1], height));
  for (let i = 1; i < coordinates.length; i += 1) {
    const lon = coordinates[i][0];
    const lat = coordinates[i][1];
    let delta = lon - prevLon;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    unwrappedLon += delta;
    prevLon = lon;
    let x = projectLon(unwrappedLon, width);
    if (x < 0) x += width;
    if (x > width) x -= width;
    const y = projectLat(lat, height);
    ctx.lineTo(x, y);
  }
}

function drawLand(ctx, width, height) {
  ctx.save();
  ctx.fillStyle = LAND_MID;
  ctx.strokeStyle = LAND_SHADOW;
  ctx.lineWidth = 1.6;
  ctx.lineJoin = 'round';
  LAND_MASSES.forEach((mass) => {
    ctx.beginPath();
    tracePolygon(ctx, mass.coordinates, width, height);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  });
  ctx.restore();
}

function overlayPolygons(ctx, width, height, polygons, fillStyle) {
  if (!polygons?.length) return;
  ctx.save();
  ctx.fillStyle = fillStyle;
  polygons.forEach((poly) => {
    ctx.beginPath();
    tracePolygon(ctx, poly.coordinates, width, height);
    ctx.closePath();
    ctx.fill();
  });
  ctx.restore();
}

function drawAntarctica(ctx, width, height) {
  ctx.save();
  ctx.fillStyle = ICE_COLOR;
  ctx.strokeStyle = ICE_EDGE;
  ctx.lineWidth = 1.4;
  ANTARCTIC_SEGMENTS.forEach((segment) => {
    ctx.beginPath();
    tracePolygon(ctx, segment.coordinates, width, height);
    ctx.lineTo(width, projectLat(-85, height));
    ctx.lineTo(0, projectLat(-85, height));
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  });
  ctx.restore();
}

function drawIceCaps(ctx, width, height) {
  ctx.save();
  const northGradient = ctx.createRadialGradient(width / 2, projectLat(88, height), 120, width / 2, projectLat(88, height), height * 0.35);
  northGradient.addColorStop(0, ICE_COLOR);
  northGradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = northGradient;
  ctx.beginPath();
  ctx.arc(width / 2, projectLat(90, height), height * 0.36, 0, Math.PI * 2);
  ctx.fill();

  const southGradient = ctx.createRadialGradient(width / 2, projectLat(-90, height), 120, width / 2, projectLat(-90, height), height * 0.42);
  southGradient.addColorStop(0, 'rgba(240, 250, 255, 0.95)');
  southGradient.addColorStop(1, 'rgba(240, 250, 255, 0)');
  ctx.fillStyle = southGradient;
  ctx.beginPath();
  ctx.arc(width / 2, projectLat(-90, height), height * 0.45, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawGraticule(ctx, width, height) {
  ctx.save();
  ctx.strokeStyle = GRID_COLOR;
  ctx.lineWidth = 0.6;
  for (let lon = -150; lon <= 180; lon += 30) {
    const x = projectLon(lon, width);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const y = projectLat(lat, height);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.restore();
}

function addCoastalHighlight(ctx, width, height) {
  ctx.save();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
  ctx.lineWidth = 0.6;
  LAND_MASSES.forEach((mass) => {
    ctx.beginPath();
    tracePolygon(ctx, mass.coordinates, width, height);
    ctx.closePath();
    ctx.stroke();
  });
  ctx.restore();
}

function addOceanGradient(ctx, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, OCEAN_TOP);
  gradient.addColorStop(1, OCEAN_BOTTOM);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
}

function addNightOcean(ctx, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, NIGHT_OCEAN_TOP);
  gradient.addColorStop(1, NIGHT_OCEAN_BOTTOM);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
}

function addCityLights(ctx, width, height) {
  ctx.save();
  CITY_LIGHTS.forEach((city) => {
    const x = projectLon(city.lon, width);
    const y = projectLat(city.lat, height);
    const radius = city.radius * (width / CANVAS_WIDTH);
    const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
    gradient.addColorStop(0, NIGHT_GLOW);
    gradient.addColorStop(0.45, 'rgba(255, 176, 90, 0.45)');
    gradient.addColorStop(1, NIGHT_GLOW_EDGE);
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function addDiffuseGlow(ctx, width, height) {
  ctx.save();
  const glow = ctx.createRadialGradient(width * 0.3, projectLat(25, height), 0, width * 0.3, projectLat(25, height), width * 0.6);
  glow.addColorStop(0, 'rgba(255, 220, 180, 0.12)');
  glow.addColorStop(1, 'rgba(255, 220, 180, 0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, width, height);
  ctx.restore();
}

function createDayCanvas() {
  const canvas = createCanvas(CANVAS_WIDTH, CANVAS_HEIGHT);
  const ctx = canvas.getContext('2d');
  addOceanGradient(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  drawGraticule(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  drawLand(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  overlayPolygons(ctx, CANVAS_WIDTH, CANVAS_HEIGHT, DESERT_PATCHES, DESERT_TONE);
  overlayPolygons(ctx, CANVAS_WIDTH, CANVAS_HEIGHT, HIGHLAND_PATCHES, HIGHLAND_TONE);
  drawAntarctica(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  drawIceCaps(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  addCoastalHighlight(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  return canvas;
}

function createNightCanvas() {
  const canvas = createCanvas(CANVAS_WIDTH, CANVAS_HEIGHT);
  const ctx = canvas.getContext('2d');
  addNightOcean(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  ctx.save();
  ctx.fillStyle = NIGHT_LAND;
  LAND_MASSES.forEach((mass) => {
    ctx.beginPath();
    tracePolygon(ctx, mass.coordinates, CANVAS_WIDTH, CANVAS_HEIGHT);
    ctx.closePath();
    ctx.fill();
  });
  ctx.beginPath();
  tracePolygon(ctx, ANTARCTIC_SEGMENTS[0].coordinates, CANVAS_WIDTH, CANVAS_HEIGHT);
  ctx.lineTo(CANVAS_WIDTH, projectLat(-85, CANVAS_HEIGHT));
  ctx.lineTo(0, projectLat(-85, CANVAS_HEIGHT));
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  tracePolygon(ctx, ANTARCTIC_SEGMENTS[1].coordinates, CANVAS_WIDTH, CANVAS_HEIGHT);
  ctx.lineTo(CANVAS_WIDTH, projectLat(-85, CANVAS_HEIGHT));
  ctx.lineTo(0, projectLat(-85, CANVAS_HEIGHT));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  addCityLights(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  addDiffuseGlow(ctx, CANVAS_WIDTH, CANVAS_HEIGHT);
  return canvas;
}

let cachedTextures = null;
let cachedPromise = null;

function buildCanvasTextures(THREE) {
  const dayCanvas = createDayCanvas();
  const nightCanvas = createNightCanvas();
  const dayTexture = new THREE.CanvasTexture(dayCanvas);
  const nightTexture = new THREE.CanvasTexture(nightCanvas);
  [dayTexture, nightTexture].forEach((texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.needsUpdate = true;
  });
  return { day: dayTexture, night: nightTexture, source: 'procedural' };
}

async function loadTexturePair(THREE, source) {
  const loader = new THREE.TextureLoader();
  loader.setCrossOrigin('');
  const [day, night] = await Promise.all([
    loader.loadAsync(source.day),
    loader.loadAsync(source.night),
  ]);
  [day, night].forEach((texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
  });
  return { day, night, source: source.label };
}

async function loadEarthTexturesInternal(THREE) {
  for (const source of TEXTURE_SOURCES) {
    try {
      const textures = await loadTexturePair(THREE, source);
      return textures;
    } catch (error) {
      console.warn(`Fallo al cargar texturas ${source.label}`, error);
    }
  }
  console.warn('No se pudieron cargar texturas reales, usando versión procedimental.');
  return buildCanvasTextures(THREE);
}

async function createEarthTextures(THREE) {
  if (cachedTextures) {
    return cachedTextures;
  }
  if (!cachedPromise) {
    cachedPromise = loadEarthTexturesInternal(THREE)
      .then((textures) => {
        cachedTextures = textures;
        cachedPromise = null;
        return textures;
      })
      .catch((error) => {
        cachedPromise = null;
        throw error;
      });
  }
  return cachedPromise;
}

function disposeEarthTextures() {
  if (cachedTextures) {
    cachedTextures.day?.dispose?.();
    cachedTextures.night?.dispose?.();
  }
  cachedTextures = null;
  cachedPromise = null;
}

export const earthTexture = { createEarthTextures, disposeEarthTextures };

let map;
let orbitLayer;
let satelliteMarker;
let footprintLayer;
let linkLayer;
const stationMarkers = new Map();
const constellationLayers = new Map();
const constellationMarkers = new Map();
const constellationSatelliteMarkers = new Map(); // New: Specific markers for constellation satellites
const constellationOrbitLayers = new Map(); // New: For 2D ground tracks for each constellation satellite
let baseLayers;
let currentBase = 'standard';
const ORBIT_FIT_PADDING = [48, 48];
let stationPickerHandler = null;
let stationPickerMarker = null;
let weatherLayer = null;
let weatherLegend = null;

const TILE_STANDARD = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_SATELLITE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

const WEATHER_COLOR_STOPS = [
  { stop: 0.0, r: 44, g: 123, b: 182 },
  { stop: 0.25, r: 171, g: 217, b: 233 },
  { stop: 0.5, r: 255, g: 255, b: 191 },
  { stop: 0.75, r: 253, g: 174, b: 97 },
  { stop: 1.0, r: 215, g: 25, b: 28 },
];

// Helper to create a specific marker for constellation satellites
function createConstellationSatelliteMarker(satellite, color, groupId) {
  const key = `${groupId}-${satellite.id}`;
  let marker = constellationSatelliteMarkers.get(key);
  if (!marker) {
    marker = L.circleMarker([satellite.lat, satellite.lon], {
      radius: 6,
      color: color,
      weight: 2,
      fillColor: color,
      fillOpacity: 0.9,
      interactive: false,
    });
    if (satellite?.name) {
      marker.bindTooltip(satellite.name, { sticky: false });
    }
    constellationSatelliteMarkers.set(key, marker);
  }
  marker.setLatLng([satellite.lat, satellite.lon]);
  marker.setStyle({ color, fillColor: color });
  return marker;
}

// Helper to update/create 2D ground tracks for constellation satellites
function updateConstellationGroundTrack2D(satelliteId, groundTrackPoints, color, groupId) {
  const key = `${groupId}-${satelliteId}-track`;
  let polyline = constellationOrbitLayers.get(key);
  if (!polyline) {
    polyline = L.polyline([], {
      color: color,
      weight: 1.5,
      opacity: 0.6,
      interactive: false,
    });
    constellationOrbitLayers.set(key, polyline);
    map.addLayer(polyline); // Add to map here
  }
  const segments = [];
  let current = [];
  let prevLon = null;

  groundTrackPoints.forEach((point) => {
    if (!Number.isFinite(point?.lat) || !Number.isFinite(point?.lon)) {
      return;
    }
    const lon = ((point.lon + 540) % 360) - 180;
    if (prevLon !== null) {
      const delta = Math.abs(lon - prevLon);
      if (delta > 180) { // Wrap around dateline
        if (current.length) {
          segments.push(current);
        }
        current = [];
      }
    }
    current.push([point.lat, lon]);
    prevLon = lon;
    
  });

  if (current.length) {
    segments.push(current);
  }
  polyline.setLatLngs(segments);
  polyline.setStyle({ color });
  return polyline;
}

function interpolateWeatherColor(t) {
  const value = clamp(t, 0, 1);
  let left = WEATHER_COLOR_STOPS[0];
  let right = WEATHER_COLOR_STOPS[WEATHER_COLOR_STOPS.length - 1];


  for (let idx = 1; idx < WEATHER_COLOR_STOPS.length; idx += 1) {
    const candidate = WEATHER_COLOR_STOPS[idx];
    if (value <= candidate.stop) {
      right = candidate;
      left = WEATHER_COLOR_STOPS[idx - 1];
      break;
    }
  }
  const span = Math.max(1e-6, right.stop - left.stop);
  const localT = (value - left.stop) / span;
  const r = Math.round(left.r + (right.r - left.r) * localT);
  const g = Math.round(left.g + (right.g - left.g) * localT);
  const b = Math.round(left.b + (right.b - left.b) * localT);
  return `rgba(${r}, ${g}, ${b}, 0.78)`;
}

function computeEdges(samples) {
  if (!Array.isArray(samples) || samples.length === 0) return [];
  if (samples.length === 1) {
    const value = samples[0];
    return [value - 1, value + 1];
  }
  const edges = [];
  for (let idx = 0; idx < samples.length - 1; idx += 1) {
    const current = samples[idx];
    const next = samples[idx + 1];
    edges.push((current + next) / 2);
  }
  const firstGap = samples[1] - samples[0];
  const lastGap = samples[samples.length - 1] - samples[samples.length - 2];
  edges.unshift(samples[0] - firstGap / 2);
  edges.push(samples[samples.length - 1] + lastGap / 2);
  return edges;
}

function ensureWeatherLayer() {
  if (!map) return null;
  if (!weatherLayer) {
    weatherLayer = L.layerGroup();
  }
  if (!map.hasLayer(weatherLayer)) {
    weatherLayer.addTo(map);
  }
  return weatherLayer;
}

function initMap(container) {
  if (!container) return null;
  
  // Check if Leaflet is available
  if (typeof L === 'undefined') {
    console.error('Leaflet library not loaded - 2D map unavailable');
    const fallback = container.querySelector('#mapFallback');
    if (fallback) {
      fallback.hidden = false;
      fallback.querySelector('.fallback-reason').textContent = 'Leaflet library failed to load. Check your internet connection and ensure third-party scripts are allowed.';
    }
    return null;
  }
  
  try {
    map = L.map(container, {
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      minZoom: 0,
      maxZoom: 12,
      worldCopyJump: false,
      maxBounds: [
        [-85, -180],
        [85, 180],
      ],
    });

    const TRANSPARENT_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
    // Allow horizontal wrapping to avoid requesting invalid tile indices
    baseLayers = {
      standard: L.tileLayer(TILE_STANDARD, {
        attribution: '© OpenStreetMap contributors',
        // noWrap: false by default — allow wrap for global maps
        errorTileUrl: TRANSPARENT_PLACEHOLDER,
      }),
      satellite: L.tileLayer(TILE_SATELLITE, {
        attribution: 'Imagery © Esri & the GIS User Community',
        errorTileUrl: TRANSPARENT_PLACEHOLDER,
      }),
    };

    baseLayers.standard.addTo(map);

    orbitLayer = L.polyline([], {
      color: '#7c3aed',
      weight: 2.5,
      opacity: 0.85,
    }).addTo(map);

    linkLayer = L.polyline([], {
      color: '#38bdf8',
      weight: 1.5,
      dashArray: '6 6',
    }).addTo(map);

    satelliteMarker = L.circleMarker([0, 0], {
      radius: 6,
      color: '#f97316',
      weight: 2,
      fillColor: '#fb923c',
    fillOpacity: 0.9,
  }).addTo(map);

  footprintLayer = L.circle([0, 0], {
    radius: 0,
    color: '#22c55e',
    fillColor: '#22c55e',
    fillOpacity: 0.08,
    weight: 1,
  }).addTo(map);

  map.fitWorld({ animate: false, maxZoom: 2 });
  setTimeout(() => map.invalidateSize(), 150);
  return map;
  } catch (error) {
    console.error('Failed to initialize 2D map:', error);
    const fallback = container.querySelector('#mapFallback');
    if (fallback) {
      fallback.hidden = false;
      const reason = fallback.querySelector('.fallback-reason');
      if (reason) {
        reason.textContent = `Map initialization error: ${error.message || 'Unknown error'}`;
      }
    }
    return null;
  }
}

function setBaseLayer(mode) {
  if (!map || !baseLayers || !baseLayers[mode]) return;
  if (currentBase === mode) return;
  baseLayers[currentBase]?.removeFrom(map);
  baseLayers[mode].addTo(map);
  currentBase = mode;
  map.invalidateSize();
}

function toggleBaseLayer() {
  const next = currentBase === 'standard' ? 'satellite' : 'standard';
  setBaseLayer(next);
  return next;
}

function invalidateSize() {
  if (!map) return;
  map.invalidateSize();
}

function updateGroundTrack(points) {
  if (!orbitLayer) return;
  if (!Array.isArray(points) || points.length === 0) {
    orbitLayer.setLatLngs([]);
    return;
  }

  const segments = [];
  let current = [];
  let prevLon = null;

  points.forEach((point) => {
    if (!Number.isFinite(point?.lat) || !Number.isFinite(point?.lon)) {
      return;
    }
    const lon = ((point.lon + 540) % 360) - 180;
    if (prevLon !== null) {
      const delta = Math.abs(lon - prevLon);
      if (delta > 180) {
        if (current.length) {
          segments.push(current);
        }
        current = [];
      }
    }
    current.push([point.lat, lon]);
    prevLon = lon;
  });

  if (current.length) {
    segments.push(current);
  }

  const latLngs = segments.length > 1 ? segments : segments[0];
  orbitLayer.setLatLngs(latLngs ?? []);
}

function updateSatellitePosition(point, footprintKm = 0) {
  if (!map || !satelliteMarker || !footprintLayer) return;
  if (!point) {
    if (map.hasLayer(satelliteMarker)) satelliteMarker.removeFrom(map);
    if (map.hasLayer(footprintLayer)) footprintLayer.removeFrom(map);
    return;
  }
  if (!map.hasLayer(satelliteMarker)) satelliteMarker.addTo(map);
  if (!map.hasLayer(footprintLayer)) footprintLayer.addTo(map);
  satelliteMarker.setLatLng([point.lat, point.lon]);
  footprintLayer.setLatLng([point.lat, point.lon]);
  footprintLayer.setRadius(footprintKm * 1000);
}

function updateLinkLine(satPoint, station) {
  if (!linkLayer) return;
  if (!station) {
    linkLayer.setLatLngs([]);
    return;
  }
  linkLayer.setLatLngs([
    [station.lat, station.lon],
    [satPoint.lat, satPoint.lon],
  ]);
}

function renderStations(stations, selectedId) {
  if (!map) return;
  const newIds = new Set();
  stations.forEach((station) => {
    newIds.add(station.id);
    if (!stationMarkers.has(station.id)) {
      const marker = L.circleMarker([station.lat, station.lon], {
        radius: 5,
        color: '#0ea5e9',
        weight: 2,
        fillColor: '#38bdf8',
        fillOpacity: 0.85,
      }).addTo(map);
      marker.bindTooltip(`${station.name}<br>${station.lat.toFixed(2)}°, ${station.lon.toFixed(2)}°`);
      stationMarkers.set(station.id, marker);
    }
    const marker = stationMarkers.get(station.id);
    marker.setStyle({
      color: station.id === selectedId ? '#facc15' : '#0ea5e9',
      fillColor: station.id === selectedId ? '#fde68a' : '#38bdf8',
    });
  });

  Array.from(stationMarkers.keys()).forEach((id) => {
    if (!newIds.has(id)) {
      const marker = stationMarkers.get(id);
      map.removeLayer(marker);
      stationMarkers.delete(id);
    }
  });
}

function focusOnStation(station) {
  if (!map || !station) return;
  map.flyTo([station.lat, station.lon], Math.max(map.getZoom(), 5), {
    duration: 1.5,
  });
}

function flyToOrbit(points, options = {}) {
  if (!map) return;
  const {
    animate = true,
    padding = ORBIT_FIT_PADDING,
    maxZoom = 7,
  } = options;

  const resolvedPadding = Array.isArray(padding) && padding.length === 2
    ? padding
    : ORBIT_FIT_PADDING;

  const fallback = () => {
    map.fitWorld({
      animate,
      maxZoom: Math.min(maxZoom, typeof map.getMaxZoom === 'function' ? map.getMaxZoom() : maxZoom),
    });
  };

  if (!Array.isArray(points) || points.length === 0) {
    fallback();
    return;
  }

  const latLngs = points
    .filter((p) => Number.isFinite(p?.lat) && Number.isFinite(p?.lon))
    .map((p) => L.latLng(p.lat, p.lon));

  if (!latLngs.length) {
    fallback();
    return;
  }

  const bounds = L.latLngBounds(latLngs);
  if (!bounds.isValid()) {
    fallback();
    return;
  }

  const zoomCap = Math.min(maxZoom, typeof map.getMaxZoom === 'function' ? map.getMaxZoom() : maxZoom);
  map.flyToBounds(bounds, {
    padding: resolvedPadding,
    maxZoom: zoomCap,
    animate,
    duration: animate ? 1.2 : 0,
  });
}

function updateFootprint(distanceKm) {
  if (!footprintLayer) return;
  footprintLayer.setRadius(distanceKm * 1000);
}

function annotateStationTooltip(station, metrics) {
  if (!stationMarkers.has(station.id)) return;
  const marker = stationMarkers.get(station.id);
  marker.bindTooltip(
    `${station.name}<br>${station.lat.toFixed(2)}°, ${station.lon.toFixed(2)}°<br>${formatDistanceKm(metrics.distanceKm)}`,
    { sticky: true },
  );
}

function ensureStationPickerMarker() {
  if (!map) return null;
  if (!stationPickerMarker) {
    stationPickerMarker = L.marker([0, 0], {
      draggable: false,
      keyboard: false,
      interactive: false,
      zIndexOffset: 1000,
      icon: L.divIcon({
        className: 'station-picker-marker',
        html: '<div class="station-picker-marker-dot"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      }),
    });
  }
  if (!map.hasLayer(stationPickerMarker)) {
    stationPickerMarker.addTo(map);
  }
  return stationPickerMarker;
}

function removeStationPickerMarker() {
  if (stationPickerMarker && map && map.hasLayer(stationPickerMarker)) {
    map.removeLayer(stationPickerMarker);
  }
  stationPickerMarker = null;
}

function buildWeatherLegend(variable) {
  if (!map) return null;
  const legendControl = L.control({ position: 'bottomleft' });
  legendControl.onAdd = () => {
    const container = L.DomUtil.create('div', 'weather-legend');
    const title = L.DomUtil.create('div', 'weather-legend__title', container);
    title.textContent = `${variable?.label ?? 'Field'} (${variable?.units ?? ''})`;
    const gradient = L.DomUtil.create('div', 'weather-legend__gradient', container);
    gradient.style.background = `linear-gradient(90deg, ${WEATHER_GRADIENT_CSS})`;
    const scale = L.DomUtil.create('div', 'weather-legend__scale', container);
    scale.innerHTML = `
      <span>${variable?.minLabel ?? 'min'}</span>
      <span>${variable?.maxLabel ?? 'max'}</span>
    `;
    return container;
  };
  return legendControl;
}

function clearWeatherField() {
  if (weatherLayer && map) {
    weatherLayer.clearLayers();
    map.removeLayer(weatherLayer);
  }
  weatherLayer = null;
  if (weatherLegend) {
    weatherLegend.remove();
    weatherLegend = null;
  }
}

function renderWeatherField(fieldPayload) {
  if (!map || !fieldPayload || !fieldPayload.grid) {
    clearWeatherField();
    return;
  }

  const layerGroup = ensureWeatherLayer();
  if (!layerGroup) return;
  layerGroup.clearLayers();

  if (weatherLegend) {
    weatherLegend.remove();
    weatherLegend = null;
  }

  const { grid, variable } = fieldPayload;
  const { latitudes, longitudes, values, min, max } = grid;
  if (!Array.isArray(latitudes) || !Array.isArray(longitudes) || !Array.isArray(values)) {
    clearWeatherField();
    return;
  }

  const minValue = Number(min);
  const maxValue = Number(max);
  const latEdges = computeEdges(latitudes);
  const lonEdges = computeEdges(longitudes);

  // Render each lat/lon cell as a filled rectangle to approximate a smooth colour field.
  for (let row = 0; row < values.length; row += 1) {
    const rowValues = values[row];
    if (!Array.isArray(rowValues)) continue;
    for (let col = 0; col < rowValues.length; col += 1) {
      const cellValue = rowValues[col];
      const bounds = [
        [latEdges[row], lonEdges[col]],
        [latEdges[row + 1], lonEdges[col + 1]],
      ];
      if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || !Number.isFinite(cellValue)) {
        const emptyRect = L.rectangle(bounds, {
          weight: 0,
          fillOpacity: 0,
          interactive: false,
        });
        layerGroup.addLayer(emptyRect);
        continue;
      }
      const normalized = minValue === maxValue ? 0.5 : (cellValue - minValue) / (maxValue - minValue);
      const color = interpolateWeatherColor(normalized);
      const rect = L.rectangle(bounds, {
        weight: 0,
        fillColor: color,
        fillOpacity: 0.72,
        interactive: false,
      });
      layerGroup.addLayer(rect);
    }
  }

  weatherLegend = buildWeatherLegend({
    label: variable?.label,
    units: variable?.units,
    minLabel: Number.isFinite(minValue) ? minValue.toFixed(1) : 'min',
    maxLabel: Number.isFinite(maxValue) ? maxValue.toFixed(1) : 'max',
  });
  if (weatherLegend) {
    weatherLegend.addTo(map);
  }
}

function startStationPicker(onPick, initialPosition) {
  if (!map || typeof onPick !== 'function') return () => {};

  stopStationPicker();

  const container = map.getContainer();
  container.classList.add('station-pick-mode');

  if (initialPosition && Number.isFinite(initialPosition.lat) && Number.isFinite(initialPosition.lon)) {
    const marker = ensureStationPickerMarker();
    if (marker) marker.setLatLng([initialPosition.lat, initialPosition.lon]);
  }

  stationPickerHandler = (event) => {
    const { lat, lng } = event.latlng;
    const marker = ensureStationPickerMarker();
    if (marker) marker.setLatLng([lat, lng]);
    onPick({ lat, lon: lng });
  };

  map.on('click', stationPickerHandler);

  return () => stopStationPicker();
}

function stopStationPicker() {
  if (!map) return;
  const container = map.getContainer();
  container.classList.remove('station-pick-mode');
  if (stationPickerHandler) {
    map.off('click', stationPickerHandler);
    stationPickerHandler = null;
  }
  removeStationPickerMarker();
}

function ensureConstellationLayer(groupId) {
  if (!map) return null;
  let layer = constellationLayers.get(groupId);
  if (!layer) {
    layer = L.layerGroup();
    constellationLayers.set(groupId, layer);
  }
  if (!map.hasLayer(layer)) {
    layer.addTo(map);
  }
  return layer;
}

function renderConstellations2D(groupId, satellites, options = {}) {
  if (!map) return;
  if (!Array.isArray(satellites) || satellites.length === 0) {
    clearConstellationGroup(groupId);
    return;
  }
  const layer = ensureConstellationLayer(groupId);
  if (!layer) return;
  const color = options.color || '#38bdf8';
  
  const currentMarkers = new Set();
  const currentTracks = new Set();

  satellites.forEach((satellite, idx) => {
    if (!Number.isFinite(satellite?.lat) || !Number.isFinite(satellite?.lon)) return;
    const key = satellite.id || satellite.name || `${groupId}-${idx}`;
    
    // Update satellite marker
    const marker = createConstellationSatelliteMarker(satellite, color, groupId);
    if (!layer.hasLayer(marker)) {
      layer.addLayer(marker);
    }
    currentMarkers.add(key);

    // Update ground track for this satellite
    if (satellite.groundTrack && satellite.groundTrack.length > 0) {
      const track = updateConstellationGroundTrack2D(satellite.id, satellite.groundTrack, color, groupId);
      if (!layer.hasLayer(track)) {
        layer.addLayer(track);
      }
      currentTracks.add(`${groupId}-${satellite.id}-track`);
    }
  });

  // Cleanup old markers
  Array.from(constellationSatelliteMarkers.keys()).forEach((key) => {
    if (key.startsWith(`${groupId}-`) && !currentMarkers.has(key)) {
      const marker = constellationSatelliteMarkers.get(key);
      if (marker) {
        map.removeLayer(marker);
        constellationSatelliteMarkers.delete(key);
      }
    }
  });

  // Cleanup old ground tracks
  Array.from(constellationOrbitLayers.keys()).forEach((key) => {
    if (key.startsWith(`${groupId}-`) && !currentTracks.has(key)) {
      const polyline = constellationOrbitLayers.get(key);
      if (polyline) {
        map.removeLayer(polyline);
        constellationOrbitLayers.delete(key);
      }
    }
  });
}

function clearConstellationGroup(groupId) {
  const layer = constellationLayers.get(groupId);
  if (layer && map) {
    layer.clearLayers();
    map.removeLayer(layer);
  }
  constellationLayers.delete(groupId);
  // Also clear individual markers and tracks
  Array.from(constellationSatelliteMarkers.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const marker = constellationSatelliteMarkers.get(key);
      if (marker) map.removeLayer(marker);
      constellationSatelliteMarkers.delete(key);
    }
  });
  Array.from(constellationOrbitLayers.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const polyline = constellationOrbitLayers.get(key);
      if (polyline) map.removeLayer(polyline);
      constellationOrbitLayers.delete(key);
    }
  });
}

export const map2d = {
  initMap,
  setBaseLayer,
  toggleBaseLayer,
  invalidateSize,
  updateGroundTrack,
  updateSatellitePosition,
  updateLinkLine,
  renderStations,
  focusOnStation,
  flyToOrbit,
  updateFootprint,
  annotateStationTooltip,
  clearWeatherField,
  renderWeatherField,
  startStationPicker,
  stopStationPicker,
  renderConstellations: renderConstellations2D,
  clearConstellationGroup,
};

const { EARTH_RADIUS_KM } = orbitConstants;
const UNIT_SCALE = 1 / EARTH_RADIUS_KM;
const EARTH_BASE_ROTATION = 0;
const GROUND_TRACK_ALTITUDE_KM = 0.05;

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

function setupSliderSync(sliderConfig) {
  sliderConfig.forEach(({ sliderId, numberId, valueId }) => {
    const slider = document.getElementById(sliderId);
    const numberInput = document.getElementById(numberId);
    const valueDisplay = valueId ? document.getElementById(valueId) : null;

    if (!slider || !numberInput) return;

    slider.addEventListener('input', () => {
      numberInput.value = slider.value;
      if (valueDisplay) valueDisplay.textContent = slider.value;
    });

    numberInput.addEventListener('input', () => {
      slider.value = numberInput.value;
      if (valueDisplay) valueDisplay.textContent = numberInput.value;
    });

    numberInput.addEventListener('change', () => {
      const min = parseFloat(slider.min);
      const max = parseFloat(slider.max);
      let value = parseFloat(numberInput.value);
      if (isNaN(value)) {
        value = min;
      }
      value = Math.max(min, Math.min(max, value));
      numberInput.value = value;
      slider.value = value;
      if (valueDisplay) valueDisplay.textContent = value;
    });

    if (valueDisplay) {
      valueDisplay.textContent = numberInput.value;
    }
  });
}

export function initSliders() {
    const sliderConfigurations = [
        { sliderId: 'semiMajorSlider', numberId: 'semiMajor' },
        { sliderId: 'optToleranceSlider', numberId: 'optToleranceA' },
        { sliderId: 'optMinRotSlider', numberId: 'optMinRot' },
        { sliderId: 'optMaxRotSlider', numberId: 'optMaxRot' },
        { sliderId: 'optMinOrbSlider', numberId: 'optMinOrb' },
        { sliderId: 'optMaxOrbSlider', numberId: 'optMaxOrb' },
        { sliderId: 'eccentricitySlider', numberId: 'eccentricity' },
        { sliderId: 'inclinationSlider', numberId: 'inclination' },
        { sliderId: 'raanSlider', numberId: 'raan' },
        { sliderId: 'argPerigeeSlider', numberId: 'argPerigee' },
        { sliderId: 'satApertureSlider', numberId: 'satAperture' },
        { sliderId: 'groundApertureSlider', numberId: 'groundAperture' },
        { sliderId: 'wavelengthSlider', numberId: 'wavelength' },
        { sliderId: 'samplesPerOrbitSlider', numberId: 'samplesPerOrbit' },
        { sliderId: 'weatherSamplesSlider', numberId: 'weatherSamples' },
        { sliderId: 'photonRateSlider', numberId: 'photonRate' },
        { sliderId: 'detectorEfficiencySlider', numberId: 'detectorEfficiency' },
        { sliderId: 'darkCountRateSlider', numberId: 'darkCountRate' },
        { sliderId: 'opticalFilterBandwidthSlider', numberId: 'opticalFilterBandwidth' },
    ];
    setupSliderSync(sliderConfigurations);
}

// Turn panel headers into accordions (collapsible sections)
export function createPanelAccordions() {
  try {
    const panels = document.querySelectorAll('.panel-section');
    panels.forEach((panel) => {
      const hdr = panel.querySelector('header');
      if (!hdr) return;
      hdr.style.cursor = 'pointer';
      // add chevron
      let chev = hdr.querySelector('.accordion-chevron');
      if (!chev) {
        chev = document.createElement('span');
        chev.className = 'accordion-chevron';
        chev.textContent = '▾';
        chev.style.marginLeft = '8px';
        chev.style.opacity = '0.7';
        hdr.appendChild(chev);
      }
      // start expanded by default; collapse when clicked
      hdr.addEventListener('click', (ev) => {
        // ignore clicks on info buttons
        if (ev.target && ev.target.classList && ev.target.classList.contains('info-button')) return;
        panel.classList.toggle('collapsed');
        const collapsed = panel.classList.contains('collapsed');
        chev.textContent = collapsed ? '▸' : '▾';
        const contentChildren = Array.from(panel.children).filter((c) => c !== hdr);
        contentChildren.forEach((el) => { el.style.display = collapsed ? 'none' : ''; });
      });
    });
  } catch (e) { console.warn('Could not initialize panel accordions', e); }
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
  if (!satelliteMesh.visible) {
    groundTrackVectorLine.visible = false;
    return;
  }
  const satPosition = satelliteMesh.getWorldPosition(new THREE.Vector3());
  const satRadius = satPosition.length();
  if (!Number.isFinite(satRadius) || satRadius <= 0) {
    groundTrackVectorLine.visible = false;
    return;
  }

  const nadirPosition = satPosition.clone().normalize().multiplyScalar(1.0);

  groundTrackVectorLine.geometry.dispose();
  groundTrackVectorLine.geometry = new THREE.BufferGeometry().setFromPoints([
    satPosition,
    nadirPosition,
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
    const { initSolarScene } = await import('./solar.js');
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

function updateOrbitPath(points) {
  if (!isReady || !orbitLine) return;
  if (!points?.length) {
    orbitLine.visible = false;
    orbitLine.geometry.dispose();
    orbitLine.geometry = new THREE.BufferGeometry();
    return;
  }
  const vectors = points
    .map((p) => toVector3Eci(p.rEci))
    .filter((vec) => vec instanceof THREE.Vector3);
  if (!vectors.length) {
    orbitLine.visible = false;
    return;
  }
  const first = vectors[0];
  const last = vectors[vectors.length - 1];
  const closed = first.distanceTo(last) < 1e-3;
  const curve = new THREE.CatmullRomCurve3(vectors, closed, 'centripetal', 0.5);
  const segments = Math.min(2048, Math.max(120, vectors.length * 3));
  const smoothPoints = curve.getPoints(segments);
  orbitLine.geometry.dispose();
  orbitLine.geometry = new THREE.BufferGeometry().setFromPoints(smoothPoints);
  orbitLine.visible = true;
}

function updateSatellite(point) {
  if (!isReady || !satelliteMesh) return; // guard against not ready
  if (!point) {
    satelliteMesh.visible = false;
    return;
  }
  const pos = toVector3Eci(point.rEci);
  if (!pos) {
    satelliteMesh.visible = false; // ensure it is hidden if pos is bad
    return;
  }
  satelliteMesh.position.copy(pos);
  satelliteMesh.visible = true;
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
}

function updateLink3D(point, station, elevationDeg = null) {
  if (!isReady || !linkLine) return;
  if (!point || !station) {
    linkLine.visible = false;
    return;
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
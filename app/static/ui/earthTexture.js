// ---------------------------------------------------------------------------
// app/static/ui/earthTexture.js
// ---------------------------------------------------------------------------
// Purpose : Procedural Earth texture generation — geodata constants
//           (land masses, cities, colors) and day/night canvas builders.
// Exports : earthTexture, createEarthTextures, disposeEarthTextures
// Consumed by: ui/scene3d.js
// ---------------------------------------------------------------------------

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

export { createEarthTextures, disposeEarthTextures };
export const earthTexture = { createEarthTextures, disposeEarthTextures };

"""Constellation management using cosmica for real-world satellite constellations.

This module integrates TLE data with cosmica's orbital propagation capabilities
to provide professional satellite constellation analysis and visualization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

# Coverage calculation constants
VISIBILITY_DISTANCE_KM = 2000  # Maximum distance for satellite visibility
MIN_OPERATIONAL_ALTITUDE_KM = 200  # Minimum altitude for operational satellites

try:
    from cosmica.dynamics import (
        SatelliteConstellation,
        MultiOrbitalPlaneConstellation,
        make_satellite_orbit
    )
    from cosmica.models import (
        ConstellationSatellite,
        CircularSatelliteOrbitModel,
        EllipticalSatelliteOrbitModel
    )
    from sgp4.api import Satrec, jday
    COSMICA_AVAILABLE = True
except ImportError:
    COSMICA_AVAILABLE = False
    Satrec = None


@dataclass
class SatelliteState:
    """Satellite state at a specific time."""
    timestamp: datetime
    position_eci: Tuple[float, float, float]  # km
    velocity_eci: Tuple[float, float, float]  # km/s
    latitude: float  # degrees
    longitude: float  # degrees
    altitude: float  # km


@dataclass
class ConstellationAnalysis:
    """Analysis results for a constellation."""
    total_satellites: int
    operational_satellites: int
    planes: int
    coverage_area_km2: Optional[float]
    mean_altitude_km: float
    altitude_range_km: Tuple[float, float]
    mean_inclination_deg: float
    inclination_range_deg: Tuple[float, float]
    revisit_time_seconds: Optional[float]
    metadata: Dict[str, Any]


class TLEProcessor:
    """Process TLE (Two-Line Element) data for satellite propagation."""
    
    @staticmethod
    def parse_tle(name: str, line1: str, line2: str) -> Optional[Satrec]:
        """Parse TLE and create SGP4 satellite object.
        
        Args:
            name: Satellite name
            line1: First line of TLE
            line2: Second line of TLE
            
        Returns:
            Satrec object or None if parsing fails
        """
        if not COSMICA_AVAILABLE or Satrec is None:
            return None
        
        try:
            satellite = Satrec.twoline2rv(line1, line2)
            return satellite
        except (ValueError, RuntimeError) as e:
            # SGP4 parsing errors - invalid TLE format or checksum
            return None
        except Exception as e:
            # Unexpected error - log but don't mask
            import sys
            print(f"Unexpected error parsing TLE for {name}: {e}", file=sys.stderr)
            return None
    
    @staticmethod
    def propagate_tle(satellite: Satrec, target_time: datetime) -> Optional[SatelliteState]:
        """Propagate TLE to target time.
        
        Args:
            satellite: SGP4 satellite object
            target_time: Target datetime
            
        Returns:
            SatelliteState or None if propagation fails
        """
        if satellite is None:
            return None
        
        # Convert datetime to Julian date
        jd, fr = jday(
            target_time.year,
            target_time.month,
            target_time.day,
            target_time.hour,
            target_time.minute,
            target_time.second + target_time.microsecond / 1e6
        )
        
        # Propagate
        error_code, position, velocity = satellite.sgp4(jd, fr)
        
        if error_code != 0:
            return None
        
        # Convert to lat/lon/alt (simple approximation)
        x, y, z = position
        r = np.sqrt(x*x + y*y + z*z)
        lat = np.degrees(np.arcsin(z / r))
        lon = np.degrees(np.arctan2(y, x))
        alt = r - 6378.137  # Earth radius
        
        return SatelliteState(
            timestamp=target_time,
            position_eci=tuple(position),
            velocity_eci=tuple(velocity),
            latitude=float(lat),
            longitude=float(lon),
            altitude=float(alt)
        )


class ConstellationManager:
    """Manage and analyze satellite constellations using cosmica."""
    
    def __init__(self):
        self.constellations: Dict[str, List[Dict[str, Any]]] = {}
        self.tle_cache: Dict[str, Satrec] = {}
    
    def add_constellation_from_tle(
        self,
        constellation_id: str,
        tle_data: List[Dict[str, str]]
    ) -> int:
        """Add constellation from TLE data.
        
        Args:
            constellation_id: Unique identifier for constellation
            tle_data: List of dicts with keys: name, line1, line2
            
        Returns:
            Number of successfully parsed satellites
        """
        satellites = []
        
        for entry in tle_data:
            name = entry.get('name', 'Unknown')
            line1 = entry.get('line1', '')
            line2 = entry.get('line2', '')
            
            if not line1 or not line2:
                continue
            
            sat = TLEProcessor.parse_tle(name, line1, line2)
            if sat:
                cache_key = f"{constellation_id}:{name}"
                self.tle_cache[cache_key] = sat
                satellites.append({
                    'name': name,
                    'line1': line1,
                    'line2': line2,
                    'cache_key': cache_key
                })
        
        self.constellations[constellation_id] = satellites
        return len(satellites)
    
    def propagate_constellation(
        self,
        constellation_id: str,
        start_time: datetime,
        duration_seconds: float,
        time_step_seconds: float = 60.0
    ) -> Dict[str, List[SatelliteState]]:
        """Propagate entire constellation over time period.
        
        Args:
            constellation_id: Constellation identifier
            start_time: Start time for propagation
            duration_seconds: Duration of propagation
            time_step_seconds: Time step between samples
            
        Returns:
            Dict mapping satellite names to list of states
        """
        if constellation_id not in self.constellations:
            return {}
        
        satellites = self.constellations[constellation_id]
        num_steps = int(duration_seconds / time_step_seconds) + 1
        
        results = {}
        
        for sat_info in satellites:
            name = sat_info['name']
            cache_key = sat_info['cache_key']
            sat = self.tle_cache.get(cache_key)
            
            if not sat:
                continue
            
            states = []
            for step in range(num_steps):
                t = start_time + timedelta(seconds=step * time_step_seconds)
                state = TLEProcessor.propagate_tle(sat, t)
                if state:
                    states.append(state)
            
            if states:
                results[name] = states
        
        return results
    
    def analyze_constellation(
        self,
        constellation_id: str,
        sample_time: Optional[datetime] = None
    ) -> Optional[ConstellationAnalysis]:
        """Analyze constellation characteristics.
        
        Args:
            constellation_id: Constellation identifier
            sample_time: Time for analysis (default: now)
            
        Returns:
            ConstellationAnalysis or None if not found
        """
        if constellation_id not in self.constellations:
            return None
        
        sample_time = sample_time or datetime.utcnow()
        satellites = self.constellations[constellation_id]
        
        # Propagate all satellites to sample time
        states = []
        for sat_info in satellites:
            cache_key = sat_info['cache_key']
            sat = self.tle_cache.get(cache_key)
            if sat:
                state = TLEProcessor.propagate_tle(sat, sample_time)
                if state:
                    states.append(state)
        
        if not states:
            return None
        
        # Extract statistics
        altitudes = [s.altitude for s in states]
        latitudes = [s.latitude for s in states]
        
        # Simple plane detection (group by similar inclination)
        # This is a rough estimate
        estimated_planes = len(set(round(lat / 10) * 10 for lat in latitudes))
        
        return ConstellationAnalysis(
            total_satellites=len(satellites),
            operational_satellites=len(states),
            planes=estimated_planes,
            coverage_area_km2=None,  # Requires more complex calculation
            mean_altitude_km=float(np.mean(altitudes)),
            altitude_range_km=(float(np.min(altitudes)), float(np.max(altitudes))),
            mean_inclination_deg=float(np.mean([abs(lat) for lat in latitudes])),
            inclination_range_deg=(float(np.min([abs(lat) for lat in latitudes])), 
                                  float(np.max([abs(lat) for lat in latitudes]))),
            revisit_time_seconds=None,  # Requires coverage analysis
            metadata={
                'sample_time': sample_time.isoformat(),
                'constellation_id': constellation_id
            }
        )
    
    def get_ground_track(
        self,
        constellation_id: str,
        satellite_name: str,
        start_time: datetime,
        duration_seconds: float,
        samples: int = 100
    ) -> List[Tuple[float, float, float]]:
        """Get ground track for a specific satellite.
        
        Args:
            constellation_id: Constellation identifier
            satellite_name: Name of satellite
            start_time: Start time
            duration_seconds: Duration
            samples: Number of samples
            
        Returns:
            List of (lat, lon, alt) tuples
        """
        if constellation_id not in self.constellations:
            return []
        
        # Find satellite
        cache_key = f"{constellation_id}:{satellite_name}"
        sat = self.tle_cache.get(cache_key)
        
        if not sat:
            return []
        
        time_step = duration_seconds / max(samples - 1, 1)
        ground_track = []
        
        for i in range(samples):
            t = start_time + timedelta(seconds=i * time_step)
            state = TLEProcessor.propagate_tle(sat, t)
            if state:
                ground_track.append((state.latitude, state.longitude, state.altitude))
        
        return ground_track
    
    def compute_coverage_at_location(
        self,
        constellation_id: str,
        target_lat: float,
        target_lon: float,
        start_time: datetime,
        duration_seconds: float,
        elevation_threshold_deg: float = 10.0
    ) -> Dict[str, Any]:
        """Compute coverage statistics for a ground location.
        
        Args:
            constellation_id: Constellation identifier
            target_lat: Target latitude in degrees
            target_lon: Target longitude in degrees
            start_time: Start time
            duration_seconds: Duration
            elevation_threshold_deg: Minimum elevation angle
            
        Returns:
            Dict with coverage statistics
        """
        time_step = 60.0  # 1 minute
        results = self.propagate_constellation(
            constellation_id, start_time, duration_seconds, time_step
        )
        
        if not results:
            return {'error': 'No constellation data'}
        
        # Simple coverage calculation (approximation)
        # Check if any satellite is within visible range
        
        num_steps = int(duration_seconds / time_step) + 1
        covered_steps = 0
        visible_satellites = []
        
        for step in range(num_steps):
            step_covered = False
            for sat_name, states in results.items():
                if step >= len(states):
                    continue
                
                state = states[step]
                
                # Simple great circle distance check
                # More accurate would calculate elevation angle
                distance = self._great_circle_distance(
                    target_lat, target_lon,
                    state.latitude, state.longitude
                )
                
                # Check if satellite is visible from ground location
                if distance < VISIBILITY_DISTANCE_KM and state.altitude > MIN_OPERATIONAL_ALTITUDE_KM:
                    step_covered = True
                    if sat_name not in visible_satellites:
                        visible_satellites.append(sat_name)
            
            if step_covered:
                covered_steps += 1
        
        coverage_percent = (covered_steps / num_steps) * 100 if num_steps > 0 else 0
        
        return {
            'target': {'latitude': target_lat, 'longitude': target_lon},
            'coverage_percent': coverage_percent,
            'visible_satellites': len(visible_satellites),
            'duration_seconds': duration_seconds,
            'samples': num_steps
        }
    
    @staticmethod
    def _great_circle_distance(lat1, lon1, lat2, lon2):
        """Calculate great circle distance in km."""
        lat1_rad = np.radians(lat1)
        lat2_rad = np.radians(lat2)
        dlon = np.radians(lon2 - lon1)
        
        a = np.sin((lat2_rad - lat1_rad) / 2) ** 2
        a += np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))
        
        return 6371.0 * c  # Earth radius in km


def get_constellation_manager() -> ConstellationManager:
    """Get singleton constellation manager instance."""
    if not hasattr(get_constellation_manager, '_instance'):
        get_constellation_manager._instance = ConstellationManager()
    return get_constellation_manager._instance

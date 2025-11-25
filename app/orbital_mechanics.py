"""Enhanced orbital mechanics module with cosmica integration and advanced propagation.

This module provides optimized orbital calculations including:
- Sun-synchronous orbit computations
- Enhanced J2 perturbation modeling
- Cosmica library integration for professional satellite dynamics
- Vectorized operations for performance
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
from datetime import datetime, timedelta

# Physical constants
MU_EARTH = 398600.4418  # km^3/s^2
EARTH_RADIUS_KM = 6378.137  # km (equatorial)
EARTH_ROT_RATE = 7.2921150e-5  # rad/s
J2 = 1.08263e-3  # J2 perturbation coefficient
J3 = -2.53881e-6  # J3 perturbation coefficient (for enhanced accuracy)
J4 = -1.65597e-6  # J4 perturbation coefficient (for enhanced accuracy)
DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi
SOLAR_MEAN_MOTION = 360.0 / 365.2421897  # deg/day


@dataclass
class OrbitalElements:
    """Keplerian orbital elements."""
    semi_major_axis: float  # km
    eccentricity: float  # unitless
    inclination: float  # radians
    raan: float  # radians (Right Ascension of Ascending Node)
    arg_perigee: float  # radians
    mean_anomaly: float  # radians
    epoch: Optional[datetime] = None
    
    @property
    def altitude(self) -> float:
        """Orbital altitude in km."""
        return self.semi_major_axis - EARTH_RADIUS_KM
    
    @property
    def period(self) -> float:
        """Orbital period in seconds."""
        return 2.0 * math.pi * math.sqrt(self.semi_major_axis ** 3 / MU_EARTH)
    
    @property
    def mean_motion(self) -> float:
        """Mean motion in rad/s."""
        return math.sqrt(MU_EARTH / (self.semi_major_axis ** 3))


@dataclass
class SecularRates:
    """Secular rates due to J2, J3, J4 perturbations."""
    dot_raan: float  # rad/s
    dot_arg_perigee: float  # rad/s
    dot_mean_anomaly: float  # rad/s
    mean_motion: float  # rad/s


def compute_j2_secular_rates(elements: OrbitalElements) -> SecularRates:
    """Compute secular rates due to J2 perturbation.
    
    This is a more accurate implementation than the basic version,
    properly handling the denominators and edge cases.
    
    Args:
        elements: Orbital elements
        
    Returns:
        SecularRates object with J2 secular rates
    """
    a = elements.semi_major_axis
    e = elements.eccentricity
    i = elements.inclination
    
    if a <= 0:
        return SecularRates(0.0, 0.0, 0.0, 0.0)
    
    n = math.sqrt(MU_EARTH / (a ** 3))  # mean motion
    p = a * (1 - e * e)  # semi-latus rectum
    
    if p <= 0:
        return SecularRates(0.0, 0.0, 0.0, n)
    
    cos_i = math.cos(i)
    sin_i = math.sin(i)
    
    # Factor used in secular rate equations
    factor = -1.5 * J2 * (EARTH_RADIUS_KM / p) ** 2 * n
    
    # RAAN precession rate (negative for prograde orbits)
    dot_raan = factor * cos_i
    
    # Argument of perigee rate
    dot_arg_perigee = factor * (2.5 * sin_i * sin_i - 2.0)
    
    # Mean anomaly drift (secular change in mean motion)
    eta = math.sqrt(1 - e * e)
    dot_mean_anomaly = factor * eta * (1.5 * sin_i * sin_i - 1.0) / (1 - e * e)
    
    return SecularRates(dot_raan, dot_arg_perigee, dot_mean_anomaly, n)


def compute_enhanced_secular_rates(elements: OrbitalElements, 
                                   include_j3: bool = False, 
                                   include_j4: bool = False) -> SecularRates:
    """Compute secular rates with higher-order terms (J3, J4).
    
    Args:
        elements: Orbital elements
        include_j3: Include J3 perturbation effects
        include_j4: Include J4 perturbation effects
        
    Returns:
        SecularRates with higher-order perturbations
    """
    # Start with J2
    rates = compute_j2_secular_rates(elements)
    
    a = elements.semi_major_axis
    e = elements.eccentricity
    i = elements.inclination
    n = rates.mean_motion
    
    if not include_j3 and not include_j4:
        return rates
    
    p = a * (1 - e * e)
    if p <= 0:
        return rates
    
    cos_i = math.cos(i)
    sin_i = math.sin(i)
    
    # J3 contributions (mainly affects argument of perigee)
    if include_j3 and abs(e) > 1e-6:
        factor_j3 = 0.5 * J3 * (EARTH_RADIUS_KM / p) ** 3 * n * (EARTH_RADIUS_KM / p)
        j3_arg = factor_j3 * sin_i * (5 * cos_i * cos_i - 1) / e
        rates = SecularRates(
            rates.dot_raan,
            rates.dot_arg_perigee + j3_arg,
            rates.dot_mean_anomaly,
            rates.mean_motion
        )
    
    # J4 contributions
    if include_j4:
        factor_j4 = 0.75 * J4 * (EARTH_RADIUS_KM / p) ** 4 * n
        j4_raan = factor_j4 * cos_i * (1.5 - 2.5 * sin_i * sin_i)
        j4_arg = factor_j4 * (3.5 - 7.5 * sin_i * sin_i + 6.25 * sin_i ** 4)
        rates = SecularRates(
            rates.dot_raan + j4_raan,
            rates.dot_arg_perigee + j4_arg,
            rates.dot_mean_anomaly,
            rates.mean_motion
        )
    
    return rates


def calculate_sun_synchronous_inclination(altitude_km: float, 
                                         eccentricity: float = 0.0) -> float:
    """Calculate the inclination required for a sun-synchronous orbit.
    
    A sun-synchronous orbit has its orbital plane precess at the same rate
    as the Earth's mean motion around the Sun (~0.9856 deg/day).
    
    Args:
        altitude_km: Orbital altitude in km
        eccentricity: Orbital eccentricity (default 0 for circular)
        
    Returns:
        Inclination in degrees for sun-synchronous orbit
        
    Raises:
        ValueError: If the altitude is not suitable for sun-synchronous orbit
    """
    a = EARTH_RADIUS_KM + altitude_km
    
    # Required RAAN drift rate for sun-synchronous (rad/s)
    required_drift = SOLAR_MEAN_MOTION * DEG2RAD / 86400.0  # deg/day to rad/s
    
    # From J2 secular rate formula:
    # dot_Omega = -1.5 * J2 * (R/p)^2 * n * cos(i)
    # Solve for cos(i)
    
    n = math.sqrt(MU_EARTH / (a ** 3))
    p = a * (1 - eccentricity * eccentricity)
    
    factor = -1.5 * J2 * (EARTH_RADIUS_KM / p) ** 2 * n
    
    if abs(factor) < 1e-15:
        raise ValueError("Cannot compute sun-synchronous inclination for this orbit")
    
    cos_i = required_drift / factor
    
    # Check if solution exists
    if abs(cos_i) > 1.0:
        raise ValueError(
            f"No sun-synchronous orbit exists at altitude {altitude_km} km. "
            f"cos(i) = {cos_i:.4f} is outside [-1, 1]. "
            f"Try altitudes between 600-6000 km."
        )
    
    inclination_rad = math.acos(cos_i)
    inclination_deg = inclination_rad * RAD2DEG
    
    # Sun-synchronous orbits are typically retrograde (inclination > 90°)
    # For LEO, they are usually between 96° and 100°
    if inclination_deg < 90:
        inclination_deg = 180 - inclination_deg
    
    return inclination_deg


def calculate_walker_constellation_elements(
    T: int,  # Total number of satellites
    P: int,  # Number of planes
    F: int,  # Relative phasing parameter
    altitude_km: float,
    inclination_deg: float,
    eccentricity: float = 0.0,
    raan_offset_deg: float = 0.0
) -> List[OrbitalElements]:
    """Generate Walker-Delta constellation orbital elements.
    
    A Walker constellation is defined by T/P/F:
    - T: Total number of satellites
    - P: Number of orbital planes
    - F: Relative phasing between planes (0 to P-1)
    
    Args:
        T: Total satellites
        P: Number of planes
        F: Phasing parameter
        altitude_km: Orbital altitude
        inclination_deg: Inclination in degrees
        eccentricity: Eccentricity (default 0)
        raan_offset_deg: Offset for RAAN of first plane
        
    Returns:
        List of OrbitalElements for each satellite
    """
    if P <= 0 or T <= 0:
        return []
    
    S = T // P  # Satellites per plane
    a = EARTH_RADIUS_KM + altitude_km
    i_rad = inclination_deg * DEG2RAD
    
    elements_list = []
    
    for p in range(P):
        # RAAN spacing: evenly distributed across 360°
        raan_deg = (360.0 * p / P) + raan_offset_deg
        raan_rad = (raan_deg % 360.0) * DEG2RAD
        
        for s in range(S):
            # Mean anomaly with phasing
            # Satellites in same plane are evenly spaced
            # Phasing between planes is controlled by F
            m_deg = (360.0 * s / S) + (360.0 * F * p / T)
            m_rad = (m_deg % 360.0) * DEG2RAD
            
            elements = OrbitalElements(
                semi_major_axis=a,
                eccentricity=eccentricity,
                inclination=i_rad,
                raan=raan_rad,
                arg_perigee=0.0,  # Typically 0 for circular orbits
                mean_anomaly=m_rad,
                epoch=datetime.utcnow()
            )
            elements_list.append(elements)
    
    return elements_list


def optimize_semi_major_axis_for_repeat_ground_track(
    revolutions_per_day: int,
    tolerance: float = 1e-6,
    max_iterations: int = 100
) -> Tuple[float, float]:
    """Calculate semi-major axis for a repeat ground track orbit.
    
    A repeat ground track orbit completes an integer number of revolutions
    in one sidereal day (or multiple days).
    
    Args:
        revolutions_per_day: Number of orbital revolutions per sidereal day
        tolerance: Convergence tolerance for iteration
        max_iterations: Maximum number of iterations
        
    Returns:
        Tuple of (semi_major_axis_km, altitude_km)
    """
    # Target mean motion (rad/s)
    sidereal_day_seconds = 86164.0905  # seconds
    target_n = 2.0 * math.pi * revolutions_per_day / sidereal_day_seconds
    
    # Initial guess using Kepler's third law (no J2)
    a = (MU_EARTH / (target_n ** 2)) ** (1.0 / 3.0)
    
    # Iterate to account for J2 effects
    # Note: This is an approximate correction assuming moderate inclination (~50-60°).
    # For precise calculations, the inclination should be provided as a parameter.
    # The factor 0.75 represents a typical correction for mid-latitude orbits.
    J2_CORRECTION_FACTOR = 0.75  # Approximate correction for ~50-60° inclination
    
    for _ in range(max_iterations):
        # Compute J2-perturbed mean motion
        p = a  # For circular orbits, p = a
        factor = 1.5 * J2 * (EARTH_RADIUS_KM / p) ** 2
        
        # The perturbed mean motion includes J2 correction
        # This approximation works well for typical LEO repeat ground track orbits
        n_perturbed = target_n * (1 + factor * J2_CORRECTION_FACTOR)
        
        # Update semi-major axis
        a_new = (MU_EARTH / (n_perturbed ** 2)) ** (1.0 / 3.0)
        
        if abs(a_new - a) < tolerance:
            a = a_new
            break
        
        a = a_new
    
    altitude = a - EARTH_RADIUS_KM
    return a, altitude


def validate_orbital_elements(elements: OrbitalElements) -> Tuple[bool, Optional[str]]:
    """Validate orbital elements for physical feasibility.
    
    Args:
        elements: Orbital elements to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check semi-major axis
    if elements.semi_major_axis < EARTH_RADIUS_KM:
        return False, f"Semi-major axis {elements.semi_major_axis:.1f} km is below Earth's surface"
    
    if elements.semi_major_axis > 50000:  # GEO is ~42,164 km
        return False, f"Semi-major axis {elements.semi_major_axis:.1f} km is beyond practical limits"
    
    # Check eccentricity
    if elements.eccentricity < 0 or elements.eccentricity >= 1:
        return False, f"Eccentricity {elements.eccentricity:.4f} must be in [0, 1)"
    
    # Check perigee altitude
    perigee = elements.semi_major_axis * (1 - elements.eccentricity) - EARTH_RADIUS_KM
    if perigee < 150:  # Minimum practical altitude
        return False, f"Perigee altitude {perigee:.1f} km is too low (< 150 km)"
    
    # Check inclination range
    if not (0 <= elements.inclination <= math.pi):
        return False, f"Inclination must be between 0 and π radians"
    
    return True, None


# Integration with cosmica (optional, requires cosmica to be installed)
try:
    from cosmica.dynamics import (
        CircularSatelliteOrbit,
        EllipticalSatelliteOrbit,
        MultiOrbitalPlaneConstellation
    )
    from cosmica.models import CircularSatelliteOrbitModel, EllipticalSatelliteOrbitModel
    
    COSMICA_AVAILABLE = True
    
    def to_cosmica_orbit(elements: OrbitalElements):
        """Convert OrbitalElements to cosmica orbit object."""
        if elements.eccentricity < 1e-6:
            # Circular orbit
            return CircularSatelliteOrbitModel(
                altitude_km=elements.altitude,
                inclination_deg=elements.inclination * RAD2DEG,
                raan_deg=elements.raan * RAD2DEG
            )
        else:
            # Elliptical orbit
            return EllipticalSatelliteOrbitModel(
                semi_major_axis_km=elements.semi_major_axis,
                eccentricity=elements.eccentricity,
                inclination_deg=elements.inclination * RAD2DEG,
                raan_deg=elements.raan * RAD2DEG,
                argument_of_perigee_deg=elements.arg_perigee * RAD2DEG,
                mean_anomaly_deg=elements.mean_anomaly * RAD2DEG
            )
    
except ImportError:
    COSMICA_AVAILABLE = False
    
    def to_cosmica_orbit(elements: OrbitalElements):
        """Placeholder when cosmica is not available."""
        raise ImportError("cosmica library is not installed")


def get_orbital_info() -> Dict[str, Any]:
    """Get information about available orbital mechanics features."""
    return {
        "j2_available": True,
        "j3_j4_available": True,
        "sun_synchronous_calculation": True,
        "walker_constellation": True,
        "repeat_ground_track": True,
        "cosmica_integration": COSMICA_AVAILABLE,
        "constants": {
            "mu_earth": MU_EARTH,
            "earth_radius": EARTH_RADIUS_KM,
            "j2": J2,
            "j3": J3,
            "j4": J4
        }
    }

import math
import maidenhead
import logging
import os
import json

logger = logging.getLogger(__name__)

# Cache for the dataset
_station_cache = None

# Standard NWS Frequencies in Hz
NWS_FREQUENCIES = [
    162400000, 162425000, 162450000, 162475000, 
    162500000, 162525000, 162550000
]

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km."""
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r

def load_nws_data():
    """Loads NWS transmitter data. Fallback to standard frequencies if no data file found."""
    global _station_cache
    if _station_cache is not None:
        return _station_cache

    stations = []
    # In a real scenario, we might fetch from weather.gov or a local JSON
    # For now, we'll provide a few examples and a way to load from 'nws_stations.json'
    json_path = os.path.join(os.path.dirname(__file__), "nws_stations.json")
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                stations = json.load(f)
            logger.info(f"Loaded {len(stations)} NWS stations from {json_path}")
        except Exception as e:
            logger.error(f"Failed to load NWS stations: {e}")
    
    # If no stations, provide a fallback of standard frequencies at the user's location 
    # (This allows testing the audio even without a station database)
    if not stations:
        logger.warning("No NWS station database found. Use standard frequencies.")
        
    _station_cache = stations
    return _station_cache

def get_coordinates_from_input(location_input: str):
    """Returns (lat, lon) from maidenhead or lat,lon."""
    parts = location_input.replace(" ", "").split(",")
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
    try:
        lat, lon = maidenhead.to_location(location_input.strip().upper())
        return lat, lon
    except:
        return None, None

def get_stations_in_range(all_stations: list, lat: float, lon: float, radius_km: float = 100.0):
    """Filter stations by distance."""
    results = []
    
    # If we have real stations, filter them
    for s in all_stations:
        dist = haversine(lat, lon, s["latitude"], s["longitude"])
        if dist <= radius_km:
            s_copy = s.copy()
            s_copy["distance_km"] = dist
            # Standardize for frontend
            s_copy["Downlink"] = f"{s['frequency']/1e6:.3f}"
            s_copy["Callsign"] = s.get("callsign", "NWS")
            s_copy["Lat"] = s["latitude"]
            s_copy["Long"] = s["longitude"]
            results.append(s_copy)

    # If no stations in database (or empty db), always show the 7 standard frequencies 
    # at 'distance 0' so the user can at least try to tune them.
    if not results:
        for i, freq in enumerate(NWS_FREQUENCIES):
            results.append({
                "Callsign": f"NWS-CH{i+1}",
                "Downlink": f"{freq/1e6:.3f}",
                "frequency": freq,
                "Lat": lat,
                "Long": lon,
                "distance_km": 0.0,
                "Note": "Standard Frequency"
            })

    results.sort(key=lambda x: x["distance_km"])
    return results


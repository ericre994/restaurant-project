"""Curated NYC neighborhood centroids for `near=` resolution.

The Philly seed resolves neighborhoods from data (recommender._geo_index), but the
NYC launch market has no seed to derive from until the Google cache warms. This is
the offline, free, deterministic "hot path": a hand-curated set of well-known NYC
neighborhood (and borough) centroids to use as a search center. Anything not here
falls through to the Geocoding API (recommender._resolve_location).

Coordinates are approximate neighborhood centroids — good enough as a radius
center, not precise boundaries. Reuses the prototype's GeoIndex so name matching
(exact + fuzzy) and `place_names` behave exactly like the seed path.
"""
from ._proto import proto

#: neighborhood / borough name (lowercase) -> (lat, lon) centroid.
NYC_NEIGHBORHOODS = {
    # Manhattan
    "chinatown": (40.7158, -73.9970),
    "lower east side": (40.7150, -73.9843),
    "east village": (40.7265, -73.9815),
    "west village": (40.7358, -74.0036),
    "greenwich village": (40.7336, -74.0027),
    "soho": (40.7233, -74.0030),
    "nolita": (40.7222, -73.9954),
    "noho": (40.7290, -73.9925),
    "tribeca": (40.7163, -74.0086),
    "financial district": (40.7075, -74.0113),
    "fidi": (40.7075, -74.0113),
    "chelsea": (40.7465, -74.0014),
    "flatiron": (40.7411, -73.9897),
    "gramercy": (40.7368, -73.9845),
    "murray hill": (40.7479, -73.9756),
    "koreatown": (40.7476, -73.9866),
    "midtown": (40.7549, -73.9840),
    "times square": (40.7580, -73.9855),
    "hell's kitchen": (40.7638, -73.9918),
    "hells kitchen": (40.7638, -73.9918),
    "upper east side": (40.7736, -73.9566),
    "upper west side": (40.7870, -73.9754),
    "harlem": (40.8116, -73.9465),
    "east harlem": (40.7957, -73.9389),
    "washington heights": (40.8417, -73.9393),
    # Brooklyn
    "williamsburg": (40.7081, -73.9571),
    "greenpoint": (40.7304, -73.9515),
    "bushwick": (40.6944, -73.9213),
    "dumbo": (40.7033, -73.9881),
    "brooklyn heights": (40.6959, -73.9936),
    "cobble hill": (40.6864, -73.9959),
    "carroll gardens": (40.6795, -73.9976),
    "park slope": (40.6710, -73.9814),
    "fort greene": (40.6900, -73.9740),
    "prospect heights": (40.6774, -73.9688),
    "crown heights": (40.6694, -73.9442),
    "bedford-stuyvesant": (40.6872, -73.9418),
    "bed-stuy": (40.6872, -73.9418),
    "red hook": (40.6772, -74.0089),
    "sunset park": (40.6553, -74.0055),
    "coney island": (40.5755, -73.9707),
    # Queens
    "astoria": (40.7644, -73.9235),
    "long island city": (40.7447, -73.9485),
    "lic": (40.7447, -73.9485),
    "sunnyside": (40.7433, -73.9196),
    "jackson heights": (40.7557, -73.8831),
    "flushing": (40.7654, -73.8318),
    "forest hills": (40.7185, -73.8458),
    # Bronx
    "south bronx": (40.8138, -73.9229),
    "fordham": (40.8610, -73.8990),
    "riverdale": (40.8908, -73.9126),
    # Boroughs / city
    "manhattan": (40.7831, -73.9712),
    "brooklyn": (40.6782, -73.9442),
    "queens": (40.7282, -73.7949),
    "bronx": (40.8448, -73.8648),
    "the bronx": (40.8448, -73.8648),
    "nyc": (40.7549, -73.9840),
    "new york": (40.7549, -73.9840),
    "new york city": (40.7549, -73.9840),
}

#: A GeoIndex with no ZIP centroids (NYC ZIPs go to Geocoding) but the curated
#: neighborhoods — so `.resolve()` gets exact + fuzzy matching for free.
INDEX = proto.GeoIndex({}, NYC_NEIGHBORHOODS)

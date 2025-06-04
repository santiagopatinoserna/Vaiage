import os
import sys
import json
import hashlib
import googlemaps
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# Add the parent directory to sys.path to allow imports from services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.maps_api import POIApi
from services.weather_api import WeatherService
from services.car_rental_api import CarRentalService
from services.fuel_price_api import get_gas_price

def format_duration(seconds):
    """Format duration in seconds to a human-readable string (hours and minutes)."""
    if seconds is None:
        return "N/A"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    duration_str = ""
    if hours > 0:
        duration_str += f"{hours} hour{'s' if hours > 1 else ''} "
    if minutes > 0:
        duration_str += f"{minutes} min{'s' if minutes > 1 else ''}"
    if not duration_str: # Handle cases less than a minute
         duration_str = f"{sec} sec{'s' if sec > 1 else ''}"
    return duration_str.strip()

# Helper function for formatting distance
def format_distance(meters):
    """Format distance in meters to a string with kilometers and miles."""
    if meters is None:
        return "N/A"
    km = meters / 1000.0
    miles = meters / 1609.34
    return f"{km:.1f} km / {miles:.1f} miles"

class InformationAgent:
    def __init__(self, maps_api_key=None, car_api_key="101c26fdb2msh34c9d61906a2fd7p17131ajsn68eb8cc9ec7f", llm_model_name="gpt-4o"):
        """Initialize the InformationAgent with API keys and LLM model name."""
        self.maps_api_key = maps_api_key or os.getenv("MAPS_API_KEY")
        self.rapidapi_key = car_api_key or os.getenv("RAPIDAPI_KEY")
        
        if not self.maps_api_key:
            raise ValueError("MAPS_API_KEY is required for InformationAgent.")

        self.gmaps = googlemaps.Client(key=self.maps_api_key)
        self.poi_api = POIApi(self.maps_api_key)
        self.weather_service = WeatherService()
        self.car_rental_service = None
        if self.rapidapi_key and self.rapidapi_key != "YOUR_RAPIDAPI_KEY" and len(self.rapidapi_key) >= 30:
            try:
                self.car_rental_service = CarRentalService(rapidapi_key=self.rapidapi_key)
            except ValueError as e:
                print(f"Error initializing CarRentalService: {e}. Car rental will use mock data.")
                self.car_rental_service = None
        else:
            print("RAPIDAPI_KEY not configured correctly for CarRentalService. Car rental will use mock data.")

        try:
            self.llm = ChatOpenAI(model_name=llm_model_name, temperature=0.5)
        except Exception as e:
            print(f"Error initializing LLM ({llm_model_name}): {e}. LLM-dependent features might not work.")
            self.llm = None

        self.weather_summary_writer = self.llm 
        self.llm_rerank_cache = {}

    def _get_rerank_cache_key(self, user_prefs, attractions_ids_tuple, weather_summary):
        """Generate a cache key for LLM re-ranking based on user preferences, attraction IDs, and weather."""
        prefs_str = json.dumps(user_prefs, sort_keys=True)
        ids_str = json.dumps(attractions_ids_tuple, sort_keys=True)
        weather_str = weather_summary if weather_summary else ""
        hash_object = hashlib.sha256(f"{prefs_str}-{ids_str}-{weather_str}".encode())
        return hash_object.hexdigest()

    def _create_llm_rerank_prompt(self, user_prefs, attractions_for_llm, weather_summary):
        """Create a prompt for the LLM to re-rank attractions."""
        attractions_str = json.dumps(attractions_for_llm, indent=2, ensure_ascii=False)
        user_prefs_str = json.dumps(user_prefs, indent=2, ensure_ascii=False)
        weather_str = weather_summary if weather_summary else "No specific weather summary provided."

        prompt = f"""
        You are an expert travel recommender. Your task is to rank the provided list of attractions based on the user's preferences, the details of each attraction, and the current weather summary.

        User Preferences:
        {user_prefs_str}

        Weather Summary for the trip period:
        {weather_str}

        Attractions List (with details including their original 'id', 'name', 'category', 'estimated_duration', 'price_level', 'rating', and a brief 'description' if available):
        {attractions_str}

        Please consider the following factors for ranking:
        1.  **User Hobbies & Interests**: Match with user's hobbies (e.g., '{user_prefs.get('hobbies', 'general sightseeing')}').
        2.  **User Health & Accessibility**: Consider user's health (e.g., '{user_prefs.get('health', 'good')}') and attraction accessibility.
        3.  **Suitability for Children**: If traveling with kids (e.g., Kids: '{user_prefs.get('kids', 'no')}'), prioritize child-friendly options.
        4.  **Budget Constraints**: Align with budget (e.g., '{user_prefs.get('budget', 'medium')}').
        5.  **Weather Impact**: Prioritize indoor/outdoor activities based on the weather.
        6.  **Category Balance**: Aim for diversity in top recommendations. Also filter out duplicate attractions that are essentially the same place but listed differently.

        Return a JSON list of attraction IDs, ranked from MOST to LEAST recommended.
        The output MUST be a valid JSON list of strings (attraction IDs). For example:
        ["id1", "id2", "id3"]

        Only return the JSON list of IDs. Do not include any other text or explanation.
        """
        return prompt

    def _rerank_attractions_with_llm(self, attractions_list: list, user_prefs: dict, weather_summary: str = None):
        """Re-rank attractions using an LLM based on user preferences and weather."""
        if not self.llm:
            print("LLM not available for re-ranking. Returning original list.")
            return attractions_list
        if not attractions_list:
            return []
        if not user_prefs:
             print("User preferences not provided for LLM re-ranking. Returning original list.")
             return attractions_list

        attractions_for_llm = []
        for attr in attractions_list:
            attractions_for_llm.append({
                "id": attr.get("id"), "name": attr.get("name"), "category": attr.get("category"),
                "description": attr.get("description", attr.get("name","No description available.")),
                "estimated_duration": attr.get("estimated_duration"),
                "price_level": attr.get("price_level"), "rating": attr.get("rating"),
            })
        
        attraction_ids_tuple = tuple(sorted([attr.get('id', '') for attr in attractions_for_llm]))
        cache_key = self._get_rerank_cache_key(user_prefs, attraction_ids_tuple, weather_summary)

        if cache_key in self.llm_rerank_cache:
            print(f"Returning cached LLM re-ranking for key: {cache_key}")
            ranked_ids = self.llm_rerank_cache[cache_key]
        else:
            prompt_str = self._create_llm_rerank_prompt(user_prefs, attractions_for_llm, weather_summary)
            messages = [
                SystemMessage(content="You are an expert travel recommender. Your goal is to rank attractions based on user preferences, attraction details, and weather conditions. Ensure a good balance of attraction categories if appropriate."),
                HumanMessage(content=prompt_str)
            ]
            try:
                print(f"[INFO_AGENT_LLM] Requesting LLM re-ranking for {len(attractions_for_llm)} items. Cache key: {cache_key}")
                response = self.llm.invoke(messages)
                llm_output_content = response.content
                
                ranked_ids = []
                try:
                    if llm_output_content.strip().startswith("```json"):
                        llm_output_content = llm_output_content.strip()[7:]
                        if llm_output_content.strip().endswith("```"):
                            llm_output_content = llm_output_content.strip()[:-3]
                    
                    ranked_ids_data = json.loads(llm_output_content.strip())
                    if isinstance(ranked_ids_data, list) and all(isinstance(id_val, str) for id_val in ranked_ids_data):
                        ranked_ids = ranked_ids_data
                    else:
                        print(f"[INFO_AGENT_LLM_ERROR] LLM output was not a list of strings: {ranked_ids_data}")
                        raise ValueError("LLM output not in expected list of strings format.")

                except (json.JSONDecodeError, ValueError) as e:
                    print(f"[INFO_AGENT_LLM_ERROR] Parsing LLM re-ranking response: {e}. LLM Raw Output: '{llm_output_content}'")
                    return attractions_list 
                
                self.llm_rerank_cache[cache_key] = ranked_ids
                print(f"[INFO_AGENT_LLM] Cached LLM re-ranking for key: {cache_key}")

            except Exception as e:
                print(f"[INFO_AGENT_LLM_ERROR] Calling LLM for re-ranking: {e}")
                return attractions_list

        id_to_attraction_map = {attr['id']: attr for attr in attractions_list}
        ordered_attractions = []
        seen_ids = set()
        for id_ in ranked_ids:
            if id_ in id_to_attraction_map and id_ not in seen_ids:
                ordered_attractions.append(id_to_attraction_map[id_])
                seen_ids.add(id_)
        
        for attr in attractions_list:
            if attr.get('id') not in seen_ids: # Add any attractions not in the LLM's ranked list
                ordered_attractions.append(attr)
        
        print(f"[INFO_AGENT_LLM] Re-ranked list size: {len(ordered_attractions)}")
        return ordered_attractions

    def city2geocode(self, city: str):
        """Convert city name to geographic coordinates (latitude and longitude)."""
        try:
            coordinates = self.gmaps.geocode(city)
            if not coordinates: 
                # Fallback for common cities when API fails
                return self._get_fallback_coordinates(city)
            return coordinates[0]['geometry']['location']
        except Exception as e:
            print(f"Error in city2geocode for '{city}': {e}")
            # Return fallback coordinates for common cities
            return self._get_fallback_coordinates(city)
    
    def _get_fallback_coordinates(self, city: str):
        """Provide fallback coordinates for common cities when Google Maps API fails."""
        city_lower = city.lower()
        fallback_coords = {
            'medellin': {'lat': 6.2442, 'lng': -75.5812},
            'medellin colombia': {'lat': 6.2442, 'lng': -75.5812},
            'medellín': {'lat': 6.2442, 'lng': -75.5812},
            'medellín colombia': {'lat': 6.2442, 'lng': -75.5812},
            'santiago': {'lat': -33.4489, 'lng': -70.6693},
            'santiago chile': {'lat': -33.4489, 'lng': -70.6693},
            'bogota': {'lat': 4.7110, 'lng': -74.0721},
            'bogotá': {'lat': 4.7110, 'lng': -74.0721},
            'paris': {'lat': 48.8566, 'lng': 2.3522},
            'london': {'lat': 51.5074, 'lng': -0.1278},
            'new york': {'lat': 40.7128, 'lng': -74.0060},
            'madrid': {'lat': 40.4168, 'lng': -3.7038},
            'barcelona': {'lat': 41.3851, 'lng': 2.1734}
        }
        
        for key, coords in fallback_coords.items():
            if key in city_lower:
                print(f"[FALLBACK] Using fallback coordinates for {city}: {coords}")
                return coords
        
        # Default fallback if city not found
        print(f"[FALLBACK] City '{city}' not found in fallbacks, using Medellín coordinates")
        return {'lat': 6.2442, 'lng': -75.5812}

    def get_attractions(self, lat: float, lng: float, user_prefs: dict, weather_summary: str = None,
                        number: int = 20, 
                        poi_type: str = "tourist_attraction", 
                        sort_by: str = "rating", 
                        radius: int = 10000):
        """Get a list of attractions for a given location, ranked by LLM based on user preferences and weather."""
        location = (lat, lng)
        initial_fetch_limit = 30 # Fetch more initially to allow for better LLM ranking
        
        try:
            results = self.gmaps.places_nearby(
                location=location, radius=radius, type=poi_type, language='en'
            ).get('results', [])
        except Exception as e:
            print(f"Error fetching places_nearby: {e}")
            # Use fallback attractions when API fails
            results = self._get_fallback_attractions(lat, lng, user_prefs)

        if not results:
            # If no results from API, use fallback data
            results = self._get_fallback_attractions(lat, lng, user_prefs)

        initial_pois = []
        print(f"[INFO_AGENT] Fetched {len(results)} raw places. Processing up to {initial_fetch_limit} for details.")
        
        # If using fallback data, process it differently
        if hasattr(results, '__iter__') and len(results) > 0 and isinstance(results[0], dict) and 'fallback' in results[0]:
            # This is fallback data
            initial_pois = results
            print(f"[INFO_AGENT] Using {len(initial_pois)} fallback attractions.")
        else:
            # Process Google Maps API results normally
            place_details_fields = [
                'name', 'rating', 'price_level', 'opening_hours', 'formatted_address', 
                'geometry/location', 'place_id', 'user_ratings_total', 'website', 'editorial_summary', 
                'international_phone_number', 'permanently_closed', 'business_status'
            ]

            for place in results[:initial_fetch_limit]: 
                pid = place.get('place_id')
                if not pid: continue
                try:
                    place_types_list = place.get('types', ["unknown"])
                    primary_category_from_place = place_types_list[0] if place_types_list else "unknown"

                    photo_references_from_place = []
                    if place.get('photos'):
                        for photo_info_nearby in place['photos'][:1]:
                             if photo_info_nearby.get('photo_reference'):
                                photo_references_from_place.append(photo_info_nearby['photo_reference'])
                    
                    details_response = self.poi_api.get_poi_details(
                        place_id=pid,
                        fields=place_details_fields 
                    )
                    details = details_response.get('result', {})
                    if not details: 
                        print(f"[WARN] No details found for place_id {pid}. Skipping.")
                        continue

                    raw_location = details.get('geometry', {}).get('location', {})
                    location_data = {
                        'lat': raw_location.get('lat'),
                        'lng': raw_location.get('lng')
                    }
                    if not isinstance(location_data['lat'], (int, float)):
                        print(f"[WARN] Invalid or missing lat for place_id {pid}. Name: {details.get('name')}. Setting to None.")
                        location_data['lat'] = None
                    if not isinstance(location_data['lng'], (int, float)):
                        print(f"[WARN] Invalid or missing lng for place_id {pid}. Name: {details.get('name')}. Setting to None.")
                        location_data['lng'] = None
                    
                    description = details.get('editorial_summary', {}).get('overview', '')
                    if not description: description = details.get('name', 'No description available.')
                    
                    image_url = None
                    if photo_references_from_place and self.maps_api_key and photo_references_from_place[0]:
                        image_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_references_from_place[0]}&key={self.maps_api_key}"
                    elif not photo_references_from_place or not photo_references_from_place[0]:
                        print(f"[WARN] No photo reference for place_id {pid}. Name: {details.get('name')}. Image URL will be None.")

                    initial_pois.append({
                        'id': pid, 
                        'name': details.get('name'), 
                        'rating': details.get('rating'), 
                        'user_ratings_total': details.get('user_ratings_total'), 
                        'price_level': details.get('price_level'), 
                        'opening_hours': details.get('opening_hours', {}).get('weekday_text'), 
                        'address': details.get('formatted_address'), 
                        'location': location_data, 
                        'category': primary_category_from_place,
                        'types': place_types_list,
                        'estimated_duration': self.estimate_duration(primary_category_from_place, details),
                        'website': details.get('website'), 
                        'description': description,
                        'photo_references': photo_references_from_place,
                        'image_url': image_url 
                    })
                except Exception as e:
                    print(f"[ERROR] Exception during processing of place_id {pid} in get_attractions: {e}")
                    continue
        
        print(f"[INFO_AGENT] Processed details for {len(initial_pois)} POIs.")
        if not initial_pois:
            return []

        if sort_by == 'price':
            initial_pois.sort(key=lambda x: (x.get('price_level') is None, x.get('price_level', float('inf'))))
        elif sort_by == 'rating':
            initial_pois.sort(key=lambda x: (x.get('rating') is None, -(float(x.get('rating', 0.0) or 0.0))))

        if user_prefs and self.llm:
            print(f"[INFO_AGENT] Re-ranking {len(initial_pois)} attractions with LLM.")
            llm_ranked_pois = self._rerank_attractions_with_llm(initial_pois, user_prefs, weather_summary)
            return llm_ranked_pois[:number] 
        else:
            print(f"[INFO_AGENT] Skipping LLM re-ranking. Returning top {number} from initial sort.")
            return initial_pois[:number]

    def _get_fallback_attractions(self, lat: float, lng: float, user_prefs: dict):
        """Return fallback attractions for major cities when API fails."""
        city = user_prefs.get('city', '').lower() if user_prefs else ''
        
        # Medellín attractions
        if 'medellin' in city or 'medellín' in city:
            return [
                {
                    'id': 'comuna_13_medellin',
                    'name': 'Comuna 13 (Graffiti Tour)',
                    'rating': 4.8,
                    'user_ratings_total': 2500,
                    'price_level': 2,
                    'address': 'Comuna 13, Medellín, Colombia',
                    'location': {'lat': 6.2675, 'lng': -75.5950},
                    'category': 'tourist_attraction',
                    'types': ['tourist_attraction', 'point_of_interest'],
                    'estimated_duration': 3,
                    'description': 'Famous neighborhood transformation with colorful street art and outdoor escalators.',
                    'image_url': 'https://via.placeholder.com/400x200.png?text=Comuna+13',
                    'fallback': True
                },
                {
                    'id': 'plaza_botero_medellin',
                    'name': 'Plaza Botero',
                    'rating': 4.6,
                    'user_ratings_total': 1800,
                    'price_level': 0,
                    'address': 'Cra. 52 #52-43, La Candelaria, Medellín, Colombia',
                    'location': {'lat': 6.2518, 'lng': -75.5636},
                    'category': 'tourist_attraction',
                    'types': ['tourist_attraction', 'park'],
                    'estimated_duration': 2,
                    'description': 'Iconic plaza featuring 23 bronze sculptures by renowned artist Fernando Botero.',
                    'image_url': 'https://via.placeholder.com/400x200.png?text=Plaza+Botero',
                    'fallback': True
                },
                {
                    'id': 'guatape_day_trip',
                    'name': 'Guatapé & El Peñón Rock',
                    'rating': 4.9,
                    'user_ratings_total': 3200,
                    'price_level': 3,
                    'address': 'Guatapé, Antioquia, Colombia',
                    'location': {'lat': 6.2317, 'lng': -75.1581},
                    'category': 'tourist_attraction',
                    'types': ['tourist_attraction', 'natural_feature'],
                    'estimated_duration': 8,
                    'description': 'Colorful town and massive rock with 740 steps offering panoramic views.',
                    'image_url': 'https://via.placeholder.com/400x200.png?text=Guatape',
                    'fallback': True
                },
                {
                    'id': 'metro_cable_medellin',
                    'name': 'Metro Cable & Arví Park',
                    'rating': 4.7,
                    'user_ratings_total': 1500,
                    'price_level': 1,
                    'address': 'Medellín Metro Cable, Colombia',
                    'location': {'lat': 6.2308, 'lng': -75.5664},
                    'category': 'tourist_attraction',
                    'types': ['tourist_attraction', 'transportation'],
                    'estimated_duration': 4,
                    'description': 'Cable car system offering city views and access to Arví ecological park.',
                    'image_url': 'https://via.placeholder.com/400x200.png?text=Metro+Cable',
                    'fallback': True
                },
                {
                    'id': 'el_poblado_medellin',
                    'name': 'El Poblado District',
                    'rating': 4.5,
                    'user_ratings_total': 1200,
                    'price_level': 3,
                    'address': 'El Poblado, Medellín, Colombia',
                    'location': {'lat': 6.2077, 'lng': -75.5636},
                    'category': 'neighborhood',
                    'types': ['neighborhood', 'point_of_interest'],
                    'estimated_duration': 4,
                    'description': 'Upscale district with rooftop bars, restaurants, and vibrant nightlife.',
                    'image_url': 'https://via.placeholder.com/400x200.png?text=El+Poblado',
                    'fallback': True
                }
            ]
        
        # Default fallback for any city
        return [
            {
                'id': 'city_center_generic',
                'name': 'City Center',
                'rating': 4.2,
                'user_ratings_total': 800,
                'price_level': 1,
                'address': f'City Center, {user_prefs.get("city", "Unknown City")}',
                'location': {'lat': lat, 'lng': lng},
                'category': 'tourist_attraction',
                'types': ['tourist_attraction'],
                'estimated_duration': 3,
                'description': 'Historic city center with local culture and attractions.',
                'image_url': 'https://via.placeholder.com/400x200.png?text=City+Center',
                'fallback': True
            }
        ]

    def estimate_duration(self, category, details):
        """
        Estimate the duration for a given category and details.
        Returns duration in hours.
        """
        category_duration = {
            'restaurant': 2,
            'museum': 2,
            'park': 2,
            'tourist_attraction': 2,
            'night_club': 3,
            'shopping_mall': 3,
            'zoo': 3,
            'amusement_park': 6
        }
        

        # Default duration if category is not found
        default_duration = 2
        
        # Get duration based on category
        duration = category_duration.get(category, default_duration)
        
        # Adjust duration based on rating
        rating = details.get('rating', 0)
        if rating > 4.5:
            duration *= 1.5
        elif rating < 3:
            duration *= 0.75
        
        return duration

    def plan_routes(self, origin: str, destination: str):
        """
        Route Planning (Simple A to B for multiple modes).

        Args:
            origin: Starting point (address, place name, or lat/lng tuple/dict)
            destination: End point (address, place name, or lat/lng tuple/dict)

        Returns:
            List of dictionaries, each representing a travel mode, or an empty list.
            Example format:
            [
                {
                    'mode': str,                # e.g., 'driving', 'transit'
                    'distance': str,            # Formatted distance text (e.g., "10.2 miles")
                    'duration': str,            # Formatted duration text (e.g., "25 mins")
                    'distance_meters': int,     # Raw distance in meters
                    'duration_seconds': int,    # Raw duration in seconds
                    'fare': str | None          # Estimated fare text (mostly for transit)
                },
                ...
            ]
        """
        modes = ['driving', 'walking', 'bicycling', 'transit']
        routes = []
        for mode in modes:
            try:
                # Using 'en' for consistent address resolution and international compatibility
                directions = self.gmaps.directions(
                    origin, destination, mode=mode, language='en'
                )
                if not directions:
                    continue

                # Ensure legs exist and are not empty
                if not directions[0].get('legs'):
                    print(f"Warning: Route for mode '{mode}' from '{origin}' to '{destination}' lacks 'legs' data.")
                    continue
                leg = directions[0]['legs'][0]

                # Ensure distance and duration exist in the leg
                if 'distance' not in leg or 'duration' not in leg:
                     print(f"Warning: Leg for mode '{mode}' from '{origin}' to '{destination}' lacks distance or duration data.")
                     continue

                info = {
                    'mode': mode,
                    'distance': leg['distance']['text'],
                    'duration': leg['duration']['text'],
                    'distance_meters': leg['distance']['value'], # Raw distance in meters
                    'duration_seconds': leg['duration']['value']  # Raw duration in seconds
                }
                # Add fare info if available
                if 'fare' in directions[0]:
                    info['fare'] = directions[0]['fare'].get('text')
                routes.append(info)
            except googlemaps.exceptions.ApiError as e:
                 print(f"Error planning route for mode '{mode}' from '{origin}' to '{destination}': {e}")
            except IndexError:
                 print(f"Index error processing route result for mode '{mode}' from '{origin}' to '{destination}' (likely missing 'legs').")
            except KeyError as e:
                 print(f"Key error processing route result for mode '{mode}' from '{origin}' to '{destination}': {e} (likely missing 'distance' or 'duration').")
            except Exception as e:
                 print(f"An unexpected error occurred during route planning for mode '{mode}': {e}")
        return routes

    def plan_with_waypoints(self, origin: str, destination: str, waypoints: list,
                                            mode: str = 'driving', departure_time: datetime = None):
        """
        Plans an optimized route visiting a list of waypoints between an origin and destination.
        Uses the Google Maps Directions API with waypoint optimization (`optimize_waypoints=True`).

        Args:
            origin: Starting point (address, place name, or lat/lng tuple/dict)
            destination: End point (address, place name, or lat/lng tuple/dict)
            waypoints: List of intermediate points (list of strings, lat/lng tuples/dicts)
            mode: Travel mode (default: 'driving'). Optimization works best for 'driving'.
            departure_time: Optional datetime object (default: now) for traffic estimation.

        Returns:
            Dictionary with optimized route details, or None if no route is found.
            Example format:
            {
                'path_sequence': List[str],         # List of addresses in optimized order (Origin, WptX, WptY,..., Dest)
                'waypoint_original_indices': List[int], # Order original waypoints were visited (0-based index)
                'total_duration_text': str,         # Formatted total duration (e.g., "2 hours 30 mins")
                'total_duration_seconds': int,      # Raw total duration in seconds
                'total_duration_in_traffic_text': str | None, # Formatted duration with traffic (if available)
                'total_duration_in_traffic_seconds': int | None, # Raw duration with traffic (if available)
                'total_distance_text': str,         # Formatted total distance (e.g., "150.5 km / 93.5 miles")
                'total_distance_meters': int,       # Raw total distance in meters
                'fare': str | None                  # Estimated fare text (rare for driving)
            }
        """
        # Handle empty waypoints list by falling back to simple A-B route planning
        if not waypoints:
            print("Warning: No waypoints provided. Calling standard plan_routes for A-B.")
            simple_route_options = self.plan_routes(origin, destination)
            # Find the driving route from the simple options
            driving_route = next((r for r in simple_route_options if r['mode'] == 'driving'), None)
            if driving_route:
                 # Addresses from API are resolved; use original input if unavailable in fallback
                 start_addr = origin if isinstance(origin, str) else f"Coord: {origin}"
                 end_addr = destination if isinstance(destination, str) else f"Coord: {destination}"
                 return {
                    'path_sequence': [start_addr, end_addr], # Simplified path
                    'waypoint_original_indices': [],
                    'total_duration_text': driving_route['duration'],
                    'total_duration_seconds': driving_route['duration_seconds'],
                    'total_duration_in_traffic_text': None, # Not available from simple plan_routes call here
                    'total_duration_in_traffic_seconds': None,
                    'total_distance_text': driving_route['distance'],
                    'total_distance_meters': driving_route['distance_meters'],
                    'fare': driving_route.get('fare')
                 }
            else:
                print(f"Could not find a driving route from {origin} to {destination} in fallback.")
                return None

        # Set departure time to now if not specified
        if departure_time is None:
            departure_time = datetime.now()

        print(f"Planning optimized route: {origin} -> Waypoints -> {destination} for mode '{mode}'")

        try:
            # Call Google Maps Directions API
            # language='en' affects instruction text, addresses usually resolve globally
            directions_result = self.gmaps.directions(
                origin,
                destination,
                waypoints=waypoints,
                optimize_waypoints=True, # Key parameter for optimization
                mode=mode,
                departure_time=departure_time,
                language='en'
            )

            # Check if API returned a valid result
            if not directions_result:
                print("No route found for the given points and mode.")
                return None

            # Get the first recommended route
            route = directions_result[0]
            # 'legs' are the segments between points (origin->wpt1, wpt1->wpt2, ..., wptN->dest)
            legs = route['legs']

            # Calculate total duration and distance by summing up values from each leg
            total_duration_sec = sum(leg['duration']['value'] for leg in legs)
            total_distance_m = sum(leg['distance']['value'] for leg in legs)

            # Calculate duration with traffic if available for all legs
            total_duration_traffic_sec = None
            if all('duration_in_traffic' in leg for leg in legs):
                 total_duration_traffic_sec = sum(leg['duration_in_traffic']['value'] for leg in legs)

            # Reconstruct the path sequence using resolved addresses from the API response
            # Start address is from the first leg; end addresses are from each leg
            path_sequence = [legs[0]['start_address']] + [leg['end_address'] for leg in legs]

            # Get the optimized order of the *original* waypoints list (0-based indices)
            optimized_indices = route.get('waypoint_order', [])

            # Prepare the result dictionary
            result = {
                'path_sequence': path_sequence,
                'waypoint_original_indices': optimized_indices,
                'total_duration_text': format_duration(total_duration_sec),
                'total_duration_seconds': total_duration_sec,
                'total_distance_text': format_distance(total_distance_m),
                'total_distance_meters': total_distance_m,
                'fare': route.get('fare', {}).get('text') # Extract fare text if present
            }

            # Add traffic duration details if calculated
            if total_duration_traffic_sec is not None:
                result['total_duration_in_traffic_text'] = format_duration(total_duration_traffic_sec)
                result['total_duration_in_traffic_seconds'] = total_duration_traffic_sec
            else:
                 result['total_duration_in_traffic_text'] = None
                 result['total_duration_in_traffic_seconds'] = None

            return result

        # Handle potential API errors or other exceptions
        except googlemaps.exceptions.ApiError as e:
            print(f"Error planning optimized route: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred during optimized route planning: {e}")
            # Optionally re-raise or log the full traceback for debugging
            # import traceback
            # traceback.print_exc()
            return None

    def get_weather(self, lat: float, lng: float, start_date: str, duration: int, summary: bool = True):
        """
        Weather Forecast.
        
        Args:
            lat: Latitude
            lng: Longitude
            start_date: Start date (YYYY-MM-DD)
            duration: Number of days
            summary: Whether to include an LLM-generated summary.
            
        Returns:
            Dictionary containing detailed weather forecast and an optional summary.
            Example:
            {
                'detailed_forecast': [
                    {
                        "date": "2023-04-18",
                        "max_temp": "22 °C",
                        "min_temp": "15 °C",
                        "precipitation": "0 mm",
                        "wind_speed": "12 km/h",
                        "precipitation_probability": "5%",
                        "uv_index": "7"
                    },
                    ...
                ],
                'summary': "Concise weather summary..." # or None
            }
        """
        # Get detailed weather data first
        weather_data = self.weather_service.get_weather(lat, lng, start_date, duration)
        
        # If no weather data, return empty result
        if not weather_data:
            return {'detailed_forecast': [], 'summary': None}
        
        # Create result dictionary with detailed forecast
        result = {
            'detailed_forecast': weather_data,
            'summary': None
        }
        
        # Generate summary if requested
        if summary:
            # Create a prompt for the summary writer
            weather_info = json.dumps(weather_data, indent=2)
            prompt = f"""
            Summarize the following weather forecast in a concise paragraph (max 100 words).
            Include key information about temperature ranges, precipitation, and any notable weather conditions.
            Also mention any precautions travelers should take based on the forecast.
            
            Weather data:
            {weather_info}
            """
            
            # Generate the summary
            messages = [
                SystemMessage(content="You are a helpful weather assistant that provides concise summaries of weather forecasts for travelers."),
                HumanMessage(content=prompt)
            ]
            
            # Add the summary to the result
            result['summary'] = self.weather_summary_writer.invoke(messages)
        
        return result
            
        
    def search_car_rentals(self, location: str, start_date: str, end_date: str,
                           driver_age: int = 30, min_price: float = None, 
                           max_price: float = None, top_n: int = 5):
        """
        Car Rental Search.
        
        Args:
            location: Location (city name)
            start_date: Pickup date (YYYY-MM-DD)
            end_date: Return date (YYYY-MM-DD)
            driver_age: Driver's age (default: 30)
            min_price: Minimum price (optional)
            max_price: Maximum price (optional)
            top_n: Number of results to return (default: 5)
            
        Returns:
            Top N car rental options, including car type, price, pickup/return locations, links, etc.
            Uses mock data if API is not configured or fails.
            Example:
            [
                {
                    "car_model": "Mitsubishi Mirage",
                    "car_group": "Economy",
                    "price": 332.29,
                    "currency": "USD",
                    "pickup_location_name": "Los Angeles International Airport",
                    "supplier_name": "Enterprise",
                    "image_url": "https://cdn.rcstatic.com/images/car_images/web/mitsubishi/mirage_lrg.png"
                },
                ...
            ]
        """
        try:
            # Get location coordinates
            location_data = self.city2geocode(location)
            if not location_data:
                return self._get_mock_car_data(top_n)
            
            # Parse dates
            pickup_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            dropoff_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
            
            # Format dates and times for API
            pickup_date = pickup_date_obj.strftime("%Y-%m-%d")
            pickup_time = "10:00:00"  # Default pickup time
            dropoff_date = dropoff_date_obj.strftime("%Y-%m-%d")
            dropoff_time = "10:00:00"  # Default dropoff time
            
            # Call the car rental service
            cars = self.car_rental_service.find_available_cars(
                pickup_lat=location_data['lat'],
                pickup_lon=location_data['lng'],
                pickup_date=pickup_date,
                pickup_time=pickup_time,
                dropoff_lat=location_data['lat'],
                dropoff_lon=location_data['lng'],
                dropoff_date=dropoff_date,
                dropoff_time=dropoff_time,
                currency_code="USD",
                driver_age=driver_age,
            )
            
            # Filter by price if needed
            if cars and min_price is not None:
                cars = [c for c in cars if c.get('price', 0) >= min_price]
            if cars and max_price is not None:
                cars = [c for c in cars if c.get('price', 0) <= max_price]
                
            # Return top N results or mock data if API returned nothing
            return cars[:top_n] if cars else self._get_mock_car_data(top_n)
            
        except Exception as e:
            print(f"Error in search_car_rentals: {str(e)}")
            return self._get_mock_car_data()
            
            
    def _get_mock_car_data(self, top_n: int = 5):
        """Returns a list of mock car rental data."""
        mock_cars = [
            {
                "car_model": "Toyota Corolla",
                "car_group": "Economy",
                "price": 299.99,
                "currency": "USD",
                "pickup_location_name": "Sample Airport",
                "supplier_name": "Hertz",
                "image_url": "https://example.com/corolla.jpg"
            },
            {
                "car_model": "Honda Civic",
                "car_group": "Compact",
                "price": 349.99,
                "currency": "USD",
                "pickup_location_name": "Sample Airport",
                "supplier_name": "Avis",
                "image_url": "https://example.com/civic.jpg"
            },
            {
                "car_model": "Ford Mustang",
                "car_group": "Sports",
                "price": 599.99,
                "currency": "USD",
                "pickup_location_name": "Sample Airport",
                "supplier_name": "Enterprise",
                "image_url": "https://example.com/mustang.jpg"
            },
            {
                "car_model": "BMW 3 Series",
                "car_group": "Luxury",
                "price": 799.99,
                "currency": "USD",
                "pickup_location_name": "Sample Airport",
                "supplier_name": "Sixt",
                "image_url": "https://example.com/bmw.jpg"
            },
            {
                "car_model": "Mercedes-Benz C-Class",
                "car_group": "Premium",
                "price": 899.99,
                "currency": "USD",
                "pickup_location_name": "Sample Airport",
                "supplier_name": "Europcar",
                "image_url": "https://example.com/mercedes.jpg"
            }
        ]
        return mock_cars[:top_n]

    def search_nearby_places(self, lat: float, lng: float, radius: int = 500):
        """Search for nearby restaurants and provide their details.
        
        Args:
            lat (float): Latitude
            lng (float): Longitude
            radius (int): Search radius (meters)
        
        Returns:
            dict: Dictionary containing information about nearby restaurants (top 3 by rating).
                  Returns mock data if API calls fail.
        """
        try:
            # Check if POI API is available
            if not self.poi_api:
                raise Exception("POI API is not initialized")

            # Search for nearby restaurants
            restaurants_result = self.poi_api.get_nearby_places(
                location=(lat, lng),
                type='restaurant',
                radius=radius
            )
            
            # Process restaurant information
            processed_restaurants = []
            # Sort all fetched restaurants by rating (descending) before further processing
            # Handle cases where rating might be missing by defaulting to 0 for sorting
            all_fetched_restaurants = restaurants_result.get('results', [])
            all_fetched_restaurants.sort(key=lambda p: p.get('rating', 0), reverse=True)

            for place in all_fetched_restaurants[:3]:  # Only take the top 3 after sorting
                try:
                    # Get detailed information
                    place_details = self.poi_api.get_poi_details(
                        place_id=place['place_id'],
                        fields=['name', 'rating', 'price_level', 'formatted_address', 'photo', 'type', 'geometry']
                    )
                    
                    if not place_details or 'result' not in place_details:
                        continue
                        
                    place_details = place_details['result']
                    
                    # Get photos
                    photos = []
                    if 'photos' in place:  # Get photo info from the original search result
                        for photo in place['photos'][:3]:  # Up to 3 photos
                            photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference={photo['photo_reference']}&key={self.maps_api_key}"
                            photos.append({
                                'url': photo_url,
                                'width': photo.get('width', 800),
                                'height': photo.get('height', 600)
                            })
                    
                    restaurant = {
                        'name': place_details.get('name', 'Unknown Restaurant'),
                        'type': 'restaurant',
                        'rating': place_details.get('rating', 0),
                        'price_level': place_details.get('price_level', 0),
                        'address': place_details.get('formatted_address', 'Unknown address'),
                        'photos': photos,
                        'features': self._get_restaurant_features(place)  # Use type info from the original search result
                    }
                    processed_restaurants.append(restaurant)
                except Exception as e:
                    print(f"Error processing restaurant info: {str(e)}")
                    continue
            
            return {
                'restaurants': processed_restaurants
            }
            
        except Exception as e:
            print(f"Error searching nearby places: {str(e)}")
            # Return mock data
            return {
                'restaurants': [
                    {
                        'name': 'Sample Restaurant',
                        'type': 'restaurant',
                        'rating': 4.5,
                        'price_level': 2,
                        'address': 'Sample Address',
                        'photos': [
                            {
                                'url': 'https://example.com/photo1.jpg',
                                'width': 800,
                                'height': 600
                            }
                        ],
                        'features': 'Cuisine: Chinese, Western'
                    }
                ]
            }
    
    def _get_restaurant_features(self, place):
        """Get restaurant features (cuisine types) from place types."""
        features = []
        if 'types' in place:
            if 'chinese_restaurant' in place['types']:
                features.append('Chinese')
            if 'japanese_restaurant' in place['types']:
                features.append('Japanese')
            if 'italian_restaurant' in place['types']:
                features.append('Italian')
            if 'french_restaurant' in place['types']:
                features.append('French')
        return ', '.join(features) if features else 'Cuisine'

    def get_fuel_price(self, location: str):
        """
        Get fuel prices for a specific location.
        
        Args:
            location (str): Location name (city).
        
        Returns:
            float: Fuel price in USD per gallon, or None if not found.
        """
        try:
            return get_gas_price(location)
        except Exception as e:
            print(f"Error getting fuel prices: {str(e)}")
            return None
        





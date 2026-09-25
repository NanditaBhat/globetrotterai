# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from dotenv import load_dotenv
from google import genai
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory.base_memory_service import MemoryEntry
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.load_memory_tool import load_memory_tool
from google.adk.tools.preload_memory_tool import preload_memory_tool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

# Load environment variables from .env
load_dotenv()

# Hardcoded project ID and GCS Bucket name for Agent Platform compatibility
FIRESTORE_PROJECT = "qwiklabs-gcp-02-96832b3e79d0"
BUCKET_NAME = "globetrotter-ai-media-96832b3e79d0"
MEMORY_ENGINE_ID = "7472745016272617472"

db = firestore.Client(project=FIRESTORE_PROJECT)
storage_client = storage.Client(project=FIRESTORE_PROJECT)

# Configure Vertex AI Memory Bank service for deployment and local memory integration
memory_service = VertexAiMemoryBankService(
    project=FIRESTORE_PROJECT,
    location="us-east1",
    agent_engine_id=MEMORY_ENGINE_ID,
)

# Load Agent Platform Sandbox Code Execution configuration
DEPLOYMENT_METADATA_FILE = os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")

sandbox_resource_name = None
agent_engine_resource_name = None

if os.path.exists(DEPLOYMENT_METADATA_FILE):
    try:
        with open(DEPLOYMENT_METADATA_FILE, "r") as f:
            meta = json.load(f)
            sandbox_resource_name = meta.get("sandbox_resource_name")
            agent_engine_resource_name = meta.get("remote_agent_runtime_id")
    except Exception as e:
        print(f"Warning: Could not load deployment_metadata.json: {e}")

if sandbox_resource_name:
    code_executor = AgentEngineSandboxCodeExecutor(sandbox_resource_name=sandbox_resource_name)
elif agent_engine_resource_name:
    code_executor = AgentEngineSandboxCodeExecutor(agent_engine_resource_name=agent_engine_resource_name)
else:
    code_executor = AgentEngineSandboxCodeExecutor()


async def save_user_allergy(allergy: str, details: str = "", tool_context: ToolContext = None) -> dict[str, Any]:
    """Saves a user's food, environmental, or medical allergy/dietary restriction to long-term memory.

    Args:
        allergy: The specific allergy or dietary restriction (e.g., 'peanut allergy', 'shellfish allergy', 'lactose intolerance', 'gluten sensitivity').
        details: Additional details such as severity level, symptoms, or specific ingredients to avoid.

    Returns:
        A dictionary confirming the allergy was persistently saved to Memory Bank.
    """
    try:
        user_id = "default_user"
        if tool_context and hasattr(tool_context, "session") and tool_context.session:
            user_id = getattr(tool_context.session, "user_id", "default_user") or "default_user"

        allergy_text = f"User Allergy / Dietary Restriction: {allergy}."
        if details:
            allergy_text += f" Details: {details}."

        entry = MemoryEntry(
            content=types.Content(parts=[types.Part.from_text(text=allergy_text)])
        )
        await memory_service.add_memory(
            app_name="app",
            user_id=user_id,
            memories=[entry],
        )
        return {
            "status": "success",
            "allergy": allergy,
            "details": details,
            "message": f"Successfully saved user allergy '{allergy}' into long-term Memory Bank.",
        }
    except Exception as e:
        return {"error": f"Failed to save user allergy: {str(e)}"}


async def get_user_allergies(query: str = "allergy", tool_context: ToolContext = None) -> dict[str, Any]:
    """Retrieves remembered user allergies and dietary restrictions from long-term Memory Bank.

    Args:
        query: Specific allergy query or keyword to search memory for (default 'allergy').

    Returns:
        A dictionary containing list of matching remembered user allergies.
    """
    try:
        user_id = "default_user"
        if tool_context and hasattr(tool_context, "session") and tool_context.session:
            user_id = getattr(tool_context.session, "user_id", "default_user") or "default_user"

        search_res = await memory_service.search_memory(
            app_name="app",
            user_id=user_id,
            query=query,
        )

        found_memories = []
        for mem in search_res.memories:
            if mem.content and mem.content.parts:
                for p in mem.content.parts:
                    if p.text:
                        found_memories.append(p.text)

        return {
            "user_id": user_id,
            "query": query,
            "allergies_recalled": found_memories,
        }
    except Exception as e:
        return {"error": f"Failed to search user allergies in memory: {str(e)}"}


async def generate_destination_video(
    prompt: str,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Generates a short preview video for a travel destination, attraction, or experience using Google's Omni model (gemini-omni-flash-preview).

    Args:
        prompt: Detailed description of the video to generate (e.g. 'A short 5-second video clip of Eiffel Tower in Paris at sunset').
        tool_context: The execution tool context provided by ADK.

    Returns:
        A dictionary containing status, public_url, and artifact details.
    """
    try:
        # Initialize Google GenAI Client with location="global" for gemini-omni-flash-preview
        client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")

        res = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
            generation_config={"response_modalities": ["VIDEO"]},
        )

        raw_data = None
        if getattr(res, "output_video", None) and getattr(res.output_video, "data", None):
            raw_data = res.output_video.data
        elif getattr(res, "outputs", None):
            for out in res.outputs:
                for item in getattr(out, "content", []):
                    if getattr(item, "video", None):
                        v = item.video
                        raw_data = getattr(v, "data", None) or getattr(v, "bytes", None)
                        break

        if not raw_data:
            return {"error": "No video data returned from gemini-omni-flash-preview model."}

        if isinstance(raw_data, str):
            video_bytes = base64.b64decode(raw_data)
        else:
            video_bytes = raw_data

        filename = f"destination_video_{uuid.uuid4().hex[:8]}.mp4"

        # 1) Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
        if tool_context and hasattr(tool_context, "save_artifact"):
            await tool_context.save_artifact(filename, artifact_part)

        # 2) Upload video bytes directly to public Cloud Storage bucket (BUCKET_NAME = "globetrotter-ai-media-96832b3e79d0")
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type="video/mp4")

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "filename": filename,
            "public_url": public_url,
            "mime_type": "video/mp4",
            "bytes_count": len(video_bytes),
        }
    except Exception as e:
        return {"error": f"Failed to generate destination video: {str(e)}"}


async def generate_destination_image(prompt: str, tool_context: ToolContext) -> dict[str, Any]:
    """Generates a scenic preview or postcard image for a travel destination using gemini-3.1-flash-lite-image in the global region.

    Saves the image artifact to the Playground panel via tool_context and uploads the image bytes directly to Google Cloud Storage.

    Args:
        prompt: Detailed description of the travel scene or destination image to generate (e.g. 'A scenic view of Mt. Fuji with cherry blossoms in spring').

    Returns:
        A dictionary containing the public GCS HTTPS URL, filename, and description.
    """
    try:
        # Initialize GenAI Client using Vertex AI in the 'global' region
        genai_client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")

        # Generate image using gemini-3.1-flash-lite-image
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"]
            )
        )

        image_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                image_bytes = part.inline_data.data
                break

        if not image_bytes:
            return {"error": "No image data returned from gemini-3.1-flash-lite-image model."}

        # 1. Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
        filename = f"destination_{uuid.uuid4().hex[:8]}.jpg"
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        await tool_context.save_artifact(filename, artifact_part)

        # 2. Upload image bytes directly to the public Cloud Storage bucket
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        return {
            "public_url": public_url,
            "filename": filename,
            "description": f"Generated image for prompt: '{prompt}'",
        }
    except Exception as e:
        return {"error": f"Failed to generate image: {str(e)}"}


def geocode_address(address: str) -> dict[str, Any]:
    """Converts an address or location name into geographic coordinates (latitude & longitude).

    Uses Google Geocoding API if GOOGLE_MAPS_API_KEY is available, or Open-Meteo free geocoding as fallback.

    Args:
        address: The address or place name to geocode (e.g. 'San Francisco' or 'Eiffel Tower').

    Returns:
        A dictionary containing formatted address, latitude, longitude, and place_id.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if api_key and api_key != "PASTE_KEY_HERE":
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))

            if data.get("status") == "OK" and data.get("results"):
                first = data["results"][0]
                loc = first["geometry"]["location"]
                return {
                    "formatted_address": first.get("formatted_address"),
                    "location": {
                        "latitude": loc.get("lat"),
                        "longitude": loc.get("lng"),
                    },
                    "place_id": first.get("place_id"),
                }
        except Exception:
            pass

    # Fallback to Open-Meteo free geocoding API (no API key required)
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(address)}&count=1"
        req_geo = urllib.request.Request(geo_url, headers={"User-Agent": "GlobeTrotterAI/1.0"})
        with urllib.request.urlopen(req_geo, timeout=5) as resp_geo:
            geo_data = json.loads(resp_geo.read().decode("utf-8"))

        if geo_data.get("results"):
            loc = geo_data["results"][0]
            return {
                "formatted_address": f"{loc.get('name')}, {loc.get('country', '')}",
                "location": {
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                },
                "place_id": str(loc.get("id")),
            }
    except Exception as e:
        return {"error": f"Failed to geocode address '{address}': {str(e)}"}

    return {"error": f"Could not find coordinates for '{address}'."}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "tourist_attraction",
    radius_meters: float = 1000.0,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Finds nearby places of a given type around coordinates using Google Places API (New) or curated fallbacks.

    Args:
        latitude: Latitude of the center point.
        longitude: Longitude of the center point.
        place_type: Type of place to search for (e.g., 'tourist_attraction', 'restaurant', 'museum', 'hotel').
        radius_meters: Search radius in meters (default 1000.0m).

    Returns:
        A list of nearby places with name, formatted address, location, and rating.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if api_key and api_key != "PASTE_KEY_HERE":
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.types,places.rating",
        }
        payload = {
            "includedTypes": [place_type],
            "maxResultCount": 5,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": radius_meters,
                }
            },
        }

        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode("utf-8"))

            places = res_data.get("places", [])
            if places:
                results = []
                for p in places:
                    display_name = p.get("displayName", {}).get("text", "")
                    loc = p.get("location", {})
                    results.append({
                        "name": display_name,
                        "address": p.get("formattedAddress"),
                        "location": {
                            "latitude": loc.get("latitude"),
                            "longitude": loc.get("longitude"),
                        },
                        "types": p.get("types", []),
                        "rating": p.get("rating"),
                    })
                return results
        except Exception:
            pass

    # Fallback curated attractions if Google Places API key is unconfigured
    return [
        {"name": "Golden Gate Bridge", "address": "Golden Gate Bridge, San Francisco, CA", "location": {"latitude": 37.8199, "longitude": -122.4783}, "rating": 4.8},
        {"name": "Fisherman's Wharf", "address": "Fisherman's Wharf, San Francisco, CA", "location": {"latitude": 37.8080, "longitude": -122.4177}, "rating": 4.5},
        {"name": "Alcatraz Island", "address": "San Francisco Bay, CA", "location": {"latitude": 37.8267, "longitude": -122.4233}, "rating": 4.7},
        {"name": "Golden Gate Park", "address": "San Francisco, CA", "location": {"latitude": 37.7694, "longitude": -122.4862}, "rating": 4.8},
    ]


def fetch_live_weather(city: str) -> dict[str, Any]:
    """Fetches real-time weather forecast data for a given destination city using the free Open-Meteo public API.

    Args:
        city: Name of the destination city to lookup weather for (e.g. 'Tokyo', 'Paris', 'San Francisco').

    Returns:
        A dictionary containing real-time weather details including temperature, wind speed, and conditions.
    """
    api_key = os.getenv("WEATHER_API_KEY")  # Optional API key if using a paid weather service provider

    try:
        # Step 1: Geocode city name to lat/lon coordinates
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
        req_geo = urllib.request.Request(geo_url, headers={"User-Agent": "GlobeTrotterAI/1.0"})
        with urllib.request.urlopen(req_geo, timeout=5) as resp_geo:
            geo_data = json.loads(resp_geo.read().decode("utf-8"))

        if not geo_data.get("results"):
            return {"error": f"Could not find coordinates for destination city '{city}'."}

        loc = geo_data["results"][0]
        lat = loc["latitude"]
        lon = loc["longitude"]
        country = loc.get("country", "")
        name = loc.get("name", city)

        # Step 2: Fetch current weather forecast
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        req_w = urllib.request.Request(weather_url, headers={"User-Agent": "GlobeTrotterAI/1.0"})
        with urllib.request.urlopen(req_w, timeout=5) as resp_w:
            weather_data = json.loads(resp_w.read().decode("utf-8"))

        current = weather_data.get("current_weather", {})
        temp_c = current.get("temperature")
        temp_f = round((temp_c * 9 / 5) + 32, 1) if temp_c is not None else None

        return {
            "city": name,
            "country": country,
            "latitude": lat,
            "longitude": lon,
            "temperature_celsius": temp_c,
            "temperature_fahrenheit": temp_f,
            "windspeed_kmh": current.get("windspeed"),
            "is_daytime": bool(current.get("is_day", 1)),
        }
    except Exception as e:
        return {"error": f"Failed to fetch live weather for '{city}': {str(e)}"}


def calculate_trip_budget(
    destination: str,
    days: int,
    num_travelers: int = 1,
    tier: str = "mid-range",
    estimated_flight_cost: float = 0.0,
) -> dict[str, Any]:
    """Calculates an estimated trip budget breakdown.

    Args:
        destination: The destination city or country (e.g. 'Tokyo').
        days: Duration of the trip in days.
        num_travelers: Number of travelers sharing lodging costs. Default is 1.
        tier: Accommodation and dining tier ('budget', 'mid-range', 'luxury'). Default is 'mid-range'.
        estimated_flight_cost: Total estimated flight cost per person in USD.

    Returns:
        A dictionary containing the budget breakdown per category, total cost, and cost per person.
    """
    daily_rates = {
        "budget": {"lodging": 60, "food": 30, "activities": 25, "transport": 15},
        "mid-range": {"lodging": 150, "food": 70, "activities": 50, "transport": 30},
        "luxury": {"lodging": 400, "food": 180, "activities": 120, "transport": 80},
    }

    selected_tier = tier.lower() if tier.lower() in daily_rates else "mid-range"
    rates = daily_rates[selected_tier]

    lodging_total = rates["lodging"] * days
    food_total = rates["food"] * days * num_travelers
    activities_total = rates["activities"] * days * num_travelers
    transport_total = rates["transport"] * days * num_travelers
    flight_total = estimated_flight_cost * num_travelers

    grand_total = lodging_total + food_total + activities_total + transport_total + flight_total
    per_person = round(grand_total / max(1, num_travelers), 2)

    return {
        "destination": destination,
        "days": days,
        "num_travelers": num_travelers,
        "tier": selected_tier,
        "breakdown": {
            "lodging": lodging_total,
            "food": food_total,
            "activities": activities_total,
            "local_transport": transport_total,
            "flights": flight_total,
        },
        "total_cost_usd": grand_total,
        "cost_per_person_usd": per_person,
    }


def search_destinations(query: str = "") -> list[dict[str, Any]]:
    """Searches or lists destinations stored in the Firestore database.

    Args:
        query: Optional search keyword to filter by destination name, country, or category.

    Returns:
        A list of matching destination records from Firestore.
    """
    destinations_ref = db.collection("destinations")
    docs = destinations_ref.stream()

    results = []
    query_lower = query.lower()

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        if not query:
            results.append(data)
        else:
            name = data.get("name", "").lower()
            country = data.get("country", "").lower()
            category = data.get("category", "").lower()
            desc = data.get("description", "").lower()
            if (
                query_lower in name
                or query_lower in country
                or query_lower in category
                or query_lower in desc
            ):
                results.append(data)

    return results


def get_destination_details(destination_id: str) -> dict[str, Any]:
    """Retrieves full details for a specific destination by its ID.

    Args:
        destination_id: The unique document ID of the destination (e.g. 'tokyo-japan').

    Returns:
        A dictionary containing destination details or an error message if not found.
    """
    doc_ref = db.collection("destinations").document(destination_id)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return {"error": f"Destination '{destination_id}' not found."}


def add_destination(
    name: str,
    country: str,
    category: str,
    price_level: str,
    description: str,
    popular_activities: list[str],
) -> str:
    """Adds a new destination entry into the Firestore database.

    Args:
        name: Name of the city/destination (e.g., 'Barcelona').
        country: Country name (e.g., 'Spain').
        category: Category tag (e.g., 'Culture & Architecture').
        price_level: Price level indicator (e.g., '$$$', '$$').
        description: Brief description of the destination.
        popular_activities: List of top activities or attractions.

    Returns:
        A success message with the created document ID.
    """
    doc_id = f"{name.lower().replace(' ', '-')}-{country.lower().replace(' ', '-')}"
    doc_ref = db.collection("destinations").document(doc_id)
    doc_data = {
        "name": name,
        "country": country,
        "category": category,
        "price_level": price_level,
        "rating": 4.8,
        "description": description,
        "popular_activities": popular_activities,
    }
    doc_ref.set(doc_data)
    return f"Successfully added destination '{name}' ({doc_id}) to Firestore."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city or timezone query.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


# Build A2UI system prompt using A2uiSchemaManager version 0.8 and BasicCatalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are GlobeTrotter AI, an expert travel & experience concierge agent. "
        "You help users discover destinations, generate travel scene preview images, geocode addresses, "
        "find nearby points of interest, fetch real-time weather forecasts, calculate trip budgets, and save new destinations."
    ),
    workflow_description=(
        "Analyze travel requests, destination lookups, weather inquiries, and budget calculations, and return structured UI cards when appropriate. "
        "You MUST ensure that all user allergies, food intolerances, and dietary restrictions (e.g., peanuts, tree nuts, shellfish, gluten, dairy) are remembered. "
        "Whenever a user mentions any allergy or dietary restriction, immediately call the save_user_allergy tool to store it persistently in long-term memory. "
        "Before making food, restaurant, or experience recommendations, call get_user_allergies or load_memory_tool to recall stored allergies and ensure all recommendations strictly avoid allergen conflicts. "
        "Use your generate_destination_image, generate_destination_video, geocode_address, find_nearby_places, fetch_live_weather, search_destinations, "
        "get_destination_details, add_destination, calculate_trip_budget, save_user_allergy, get_user_allergies, load_memory_tool, and preload_memory_tool to assist the user."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        client_kwargs={
            "vertexai": True,
            "project": FIRESTORE_PROJECT,
            "location": "us-east1",
        },
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        save_user_allergy,
        get_user_allergies,
        generate_destination_image,
        generate_destination_video,
        geocode_address,
        find_nearby_places,
        fetch_live_weather,
        calculate_trip_budget,
        search_destinations,
        get_destination_details,
        add_destination,
        get_current_time,
        load_memory_tool,
        preload_memory_tool,
    ],
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)

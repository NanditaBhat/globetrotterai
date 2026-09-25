# Copyright 2026 Google LLC
# Seed script for GlobeTrotter AI Firestore backend

import sys
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-02-96832b3e79d0"


def seed_firestore():
    print(f"Connecting to Firestore with project ID: {PROJECT_ID}")
    db = firestore.Client(project=PROJECT_ID)

    destinations = [
        {
            "id": "tokyo-japan",
            "name": "Tokyo",
            "country": "Japan",
            "category": "Culture & Food",
            "price_level": "$$$",
            "rating": 4.9,
            "description": "A vibrant metropolis blending futuristic skyscrapers with traditional temples and world-class culinary experiences.",
            "popular_activities": ["Shibuya Crossing", "Senso-ji Temple", "Tsukiji Outer Market", "Akihabara"],
        },
        {
            "id": "kyoto-japan",
            "name": "Kyoto",
            "country": "Japan",
            "category": "Culture & History",
            "price_level": "$$",
            "rating": 4.8,
            "description": "Japan's ancient capital renowned for classical Buddhist temples, gardens, imperial palaces, and traditional wooden houses.",
            "popular_activities": ["Fushimi Inari Shrine", "Arashiyama Bamboo Grove", "Kinkaku-ji (Golden Pavilion)"],
        },
        {
            "id": "paris-france",
            "name": "Paris",
            "country": "France",
            "category": "Romance & Art",
            "price_level": "$$$$",
            "rating": 4.7,
            "description": "The City of Light, global center for art, fashion, gastronomy, and culture, with iconic landmarks like the Eiffel Tower.",
            "popular_activities": ["Louvre Museum", "Eiffel Tower", "Seine River Cruise", "Montmartre Walking Tour"],
        },
        {
            "id": "san-francisco-usa",
            "name": "San Francisco",
            "country": "USA",
            "category": "Nature & City",
            "price_level": "$$$",
            "rating": 4.6,
            "description": "Iconic Bay Area city known for Golden Gate Bridge, historic cable cars, colorful Victorian houses, and vibrant tech culture.",
            "popular_activities": ["Golden Gate Park", "Alcatraz Island", "Fisherman's Wharf", "Chinatown"],
        },
    ]

    collection_ref = db.collection("destinations")
    for dest in destinations:
        doc_id = dest["id"]
        doc_data = {k: v for k, v in dest.items() if k != "id"}
        collection_ref.document(doc_id).set(doc_data)
        print(f"Seeded destination: {dest['name']} ({doc_id})")

    print("Firestore seeding complete!")


if __name__ == "__main__":
    seed_firestore()

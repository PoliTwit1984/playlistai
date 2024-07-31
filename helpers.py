import os
import json
import random
import re
import time
import logging
from logging.handlers import RotatingFileHandler
from collections import Counter
from datetime import datetime, timedelta

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, HiddenField, TextAreaField
from tenacity import retry, stop_after_attempt, wait_random_exponential, wait_exponential
from openai import OpenAI

# Set up logging
log_directory = "logs"
if not os.path.exists(log_directory):
    os.makedirs(log_directory)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=os.path.join(log_directory, 'app.log'),
    filemode='w'
)
logger = logging.getLogger(__name__)

class PlaylistForm(FlaskForm):
    name = StringField('Name')
    mood = HiddenField('Current Mood')
    desired_mood = HiddenField('Desired Mood')
    activity = StringField('Activity')
    energy_level = SelectField('Energy Level', choices=[('Low', 'Low'), ('Medium', 'Medium'), ('High', 'High')])
    time_of_day = SelectField('Time of Day', choices=[('Morning', 'Morning'), ('Afternoon', 'Afternoon'), ('Evening', 'Evening'), ('Night', 'Night')])
    duration = StringField('Duration')
    discovery_level = StringField('Discovery Level')
    favorite_artists = StringField('Favorite Artists')
    favorite_genres = StringField('Favorite Genres')
    playlist_description = TextAreaField('Playlist Description')
    submit = SubmitField('Generate Playlist')

@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(5))
def make_spotify_request_with_retry(sp, method, *args, **kwargs):
    try:
        return getattr(sp, method)(*args, **kwargs)
    except SpotifyException as e:
        if e.http_status == 429:
            retry_after = int(e.headers.get('Retry-After', 1))
            logger.info(f"Rate limited. Waiting for {retry_after} seconds before retrying.")
            time.sleep(retry_after)
            raise
        else:
            raise
        
def get_openai_recommendations(client, user_preferences, tracks, num_tracks=30):
    try:
        familiar_tracks = [t for t in tracks if t.get('familiarity', 0) > 0.5]
        discovery_tracks = [t for t in tracks if t.get('familiarity', 0) <= 0.5]

        familiar_track_info = [f"{track['name']} by {', '.join([artist['name'] for artist in track['artists']])}" for track in familiar_tracks[:50]]
        discovery_track_info = [f"{track['name']} by {', '.join([artist['name'] for artist in track['artists']])}" for track in discovery_tracks[:50]]

        prompt = f"""
        Create a playlist in JSON format based on the following preferences:
        - Current mood: {user_preferences['current_mood']}
        - Desired mood: {user_preferences['desired_mood']}
        - Activity: {user_preferences['activity']}
        - Energy level: {user_preferences['energy_level']}
        - Time of day: {user_preferences['time_of_day']}
        - Discovery level: {user_preferences['discovery_level']} (0 = only familiar tracks, 1 = maximum discovery)
        - Playlist description: {user_preferences['playlist_description']}

        Provide a list of {num_tracks} tracks that best match these preferences.
        The response should be in the following format:

        ```json
        {{
            "playlist_description": "A brief description of the playlist",
            "tracks": [
                {{
                    "name": "Track Name",
                    "artist": "Artist Name"
                }},
                ...
            ]
        }}
        ```

        After the JSON, provide a brief explanation of why you chose these tracks, how they fit the user's preferences, and any other insights you'd like to share.
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a music expert AI assistant, skilled in creating personalized playlists."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error in get_openai_recommendations: {str(e)}")
        return None

def get_user_profile(sp):
    try:
        return make_spotify_request_with_retry(sp, 'current_user')
    except Exception as e:
        logger.error("Error fetching user profile: %s", e)
        return None

def get_user_top_artists(sp, limit=5):
    try:
        top_artists = make_spotify_request_with_retry(sp, 'current_user_top_artists', limit=limit)
        return [{"value": artist['name'], "name": artist['name']} for artist in top_artists['items']]
    except Exception as e:
        logger.error(f"Error fetching top artists: {e}")
        return []

def get_user_top_genres(sp, limit=5):
    try:
        top_artists = make_spotify_request_with_retry(sp, 'current_user_top_artists', limit=50)
        genres = [genre for artist in top_artists['items'] for genre in artist['genres']]
        unique_genres = list(set(genres))[:limit]
        return [{"value": genre, "name": genre} for genre in unique_genres]
    except Exception as e:
        logger.error(f"Error fetching top genres: {e}")
        return []

def get_tracks_from_favorites(sp, favorite_artists, favorite_genres, limit=50):
    tracks = []
    try:
        for artist in favorite_artists:
            results = make_spotify_request_with_retry(sp, 'search', q=f'artist:{artist["value"]}', type='track', limit=10)
            tracks.extend(results['tracks']['items'])
        for genre in favorite_genres:
            results = make_spotify_request_with_retry(sp, 'search', q=f'genre:{genre["value"]}', type='track', limit=10)
            tracks.extend(results['tracks']['items'])
        logger.debug(f"Fetched {len(tracks)} tracks from favorites")
        return tracks[:limit]
    except Exception as e:
        logger.error(f"Error in get_tracks_from_favorites: {str(e)}", exc_info=True)
        return []

def get_user_top_and_recent_tracks(sp, limit=50):
    tracks = []
    try:
        top_tracks = make_spotify_request_with_retry(sp, 'current_user_top_tracks', limit=limit)['items']
        recent_tracks = make_spotify_request_with_retry(sp, 'current_user_recently_played', limit=limit)['items']
        tracks = top_tracks + [item['track'] for item in recent_tracks]
        logger.debug(f"Fetched {len(tracks)} top and recent tracks")
        return tracks[:limit]
    except Exception as e:
        logger.error(f"Error in get_user_top_and_recent_tracks: {str(e)}", exc_info=True)
        return []

def get_new_releases(sp, limit=50):
    try:
        new_releases = make_spotify_request_with_retry(sp, 'new_releases', limit=limit)['albums']['items']
        tracks = []
        for album in new_releases:
            album_tracks = make_spotify_request_with_retry(sp, 'album_tracks', album['id'])['items']
            tracks.extend(album_tracks[:2])
        logger.debug(f"Fetched {len(tracks)} tracks from new releases")
        return tracks[:limit]
    except Exception as e:
        logger.error(f"Error in get_new_releases: {str(e)}", exc_info=True)
        return []

def get_new_artist_tracks(sp, limit=50):
    try:
        search_results = make_spotify_request_with_retry(sp, 'search', q='year:2023', type='artist', limit=10)
        tracks = []
        for artist in search_results['artists']['items']:
            artist_top_tracks = make_spotify_request_with_retry(sp, 'artist_top_tracks', artist['id'])['tracks']
            tracks.extend(artist_top_tracks[:2])
        logger.debug(f"Fetched {len(tracks)} tracks from new artists")
        return tracks[:limit]
    except Exception as e:
        logger.error(f"Error in get_new_artist_tracks: {str(e)}", exc_info=True)
        return []

def calculate_discovery_score(track, user_profile):
    # Implement your discovery score calculation here
    # For now, we'll just return a random score
    return random.random()

def get_expanded_track_pool(sp, favorite_artists, favorite_genres, user_profile, discovery_ratio=0.3):
    logger.debug(f"Starting get_expanded_track_pool with favorite_artists: {favorite_artists}, favorite_genres: {favorite_genres}")

    try:
        familiar_tracks = get_tracks_from_favorites(sp, favorite_artists, favorite_genres)
        logger.debug(f"Tracks from favorites: {len(familiar_tracks)}")

        top_and_recent = get_user_top_and_recent_tracks(sp)
        logger.debug(f"Top and recent tracks: {len(top_and_recent)}")
        familiar_tracks += top_and_recent

        new_releases = get_new_releases(sp)
        logger.debug(f"New releases: {len(new_releases)}")

        new_artist_tracks = get_new_artist_tracks(sp)
        logger.debug(f"New artist tracks: {len(new_artist_tracks)}")

        all_tracks = familiar_tracks + new_releases + new_artist_tracks
        logger.debug(f"Total tracks before deduplication: {len(all_tracks)}")

        # Deduplicate tracks
        all_tracks = list({track['id']: track for track in all_tracks}.values())
        logger.debug(f"Total tracks after deduplication: {len(all_tracks)}")

        # Check if user_profile is a dictionary
        if not isinstance(user_profile, dict):
            logger.warning(f"user_profile is not a dictionary. Type: {type(user_profile)}. Using empty dict.")
            user_profile = {}

        sorted_tracks = sorted(all_tracks, key=lambda track: calculate_discovery_score(track, user_profile), reverse=True)

        split_index = int(len(sorted_tracks) * (1 - discovery_ratio))
        familiar_tracks = sorted_tracks[split_index:]
        discovery_tracks = sorted_tracks[:split_index]

        logger.debug(f"Familiar tracks: {len(familiar_tracks)}, Discovery tracks: {len(discovery_tracks)}")

        return familiar_tracks, discovery_tracks

    except Exception as e:
        logger.error(f"Error in get_expanded_track_pool: {str(e)}", exc_info=True)
        raise

def parse_openai_response(response):
    logger.debug("Starting to parse OpenAI response")
    logger.debug(f"Raw OpenAI response: {response}")

    try:
        # Find the JSON content between ```json and ```
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)

        if json_match:
            json_content = json_match.group(1)
            logger.debug(f"Extracted JSON content: {json_content}")

            response_json = json.loads(json_content)

            # Extract the tracks and playlist description
            recommended_tracks = response_json.get("tracks", [])
            playlist_description = response_json.get("playlist_description", "")

            # Extract the explanation part (everything after the JSON block)
            explanation_match = re.search(r'```\s*([\s\S]*)$', response, re.DOTALL)
            explanation = explanation_match.group(1).strip() if explanation_match else ""

            logger.info(f"Parsed {len(recommended_tracks)} tracks from OpenAI response")
            logger.debug(f"Playlist description: {playlist_description}")
            logger.debug(f"Explanation: {explanation[:100]}...")  # Log first 100 chars of explanation

            return recommended_tracks, playlist_description, explanation
        else:
            logger.error("No JSON content found in the response")
            return [], "", ""
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON response: {str(e)}")
        return [], "", ""
    except Exception as e:
        logger.error(f"Unexpected error parsing response: {str(e)}")
        return [], "", ""

def find_tracks_on_spotify(sp, recommended_tracks):
    selected_tracks = []
    log_file = 'logs/search_queries.txt'

    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("Spotify Search Queries:\n\n")

    for track in recommended_tracks:
        try:
            track_name = track['name']
            artist_name = track['artist']

            # Exact match search
            exact_query = f"track:{track_name} artist:{artist_name}"
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"Searching - Track: '{track_name}', Artist: '{artist_name}'\n")

            result = make_spotify_request_with_retry(sp, 'search', q=exact_query, type='track', limit=1)
            if result['tracks']['items']:
                found_track = result['tracks']['items'][0]
                selected_tracks.append(found_track['id'])
                logger.debug(f"Found track: {found_track['name']} by {found_track['artists'][0]['name']}")
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"FOUND - Track: '{found_track['name']}', Artist: '{found_track['artists'][0]['name']}', ID: {found_track['id']}\n\n")
            else:
                # Relaxed search
                relaxed_query = f"{track_name} {artist_name}"
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"Relaxed search: {relaxed_query}\n")

                result = make_spotify_request_with_retry(sp, 'search', q=relaxed_query, type='track', limit=1)
                if result['tracks']['items']:
                    found_track = result['tracks']['items'][0]
                    selected_tracks.append(found_track['id'])
                    logger.debug(f"Found similar track: {found_track['name']} by {found_track['artists'][0]['name']}")
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"FOUND (Relaxed) - Track: '{found_track['name']}', Artist: '{found_track['artists'][0]['name']}', ID: {found_track['id']}\n\n")
                else:
                    logger.warning(f"Could not find track: {track_name} by {artist_name}")
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"NOT FOUND - Track: '{track_name}', Artist: '{artist_name}'\n\n")
        except SpotifyException as e:
            logger.error(f"Spotify API error searching for track {track_name} by {artist_name}: {str(e)}")
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"ERROR - Track: '{track_name}', Artist: '{artist_name}', Error: {str(e)}\n\n")
            if e.http_status == 429:  # Too Many Requests
                retry_after = int(e.headers.get('Retry-After', 30))
                logger.info(f"Rate limited. Waiting for {retry_after} seconds before retrying.")
                time.sleep(retry_after)
            else:
                raise
        except Exception as e:
            logger.error(f"Unexpected error searching for track {track_name} by {artist_name}: {str(e)}")
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"UNEXPECTED ERROR - Track: '{track_name}', Artist: '{artist_name}', Error: {str(e)}\n\n")

    logger.info(f"Total tracks found: {len(selected_tracks)}")
    return selected_tracks
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
from flask_wtf import FlaskForm
from wtforms import StringField, HiddenField, IntegerField, TextAreaField, SubmitField, SelectField
from wtforms.validators import DataRequired, NumberRange

# TODO: Break this function into smaller functions
#  This is a low priority task that involves refactoring the backend code.
#  Also, update the documentation accordingly.
#  labels: priority: low, area: backend, type: documentation

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
    energy_level = IntegerField('Energy Level', validators=[DataRequired(), NumberRange(min=0, max=100)])
    time_of_day = SelectField('Time of Day', choices=[('Morning', 'Morning'), ('Afternoon', 'Afternoon'), ('Evening', 'Evening'), ('Night', 'Night')])
    duration = IntegerField('Duration (minutes)', validators=[
        DataRequired(), NumberRange(min=1, max=300, message="Please enter a duration between 1 and 300 minutes.")
    ])
    
    discovery_level = StringField('Discovery Level')
    favorite_artists = StringField('Favorite Artists')
    favorite_genres = StringField('Favorite Genres')
    playlist_description = TextAreaField('Playlist Description')
    submit = SubmitField('Generate Playlist')
    
import random
from datetime import datetime, timedelta

def get_playlist_picks(sp, limit=10, max_playlist_age_days=365):
    """
    Retrieve tracks from the user's less frequently listened to playlists.
    
    :param sp: Spotify client object
    :param limit: Number of tracks to return
    :param max_playlist_age_days: Maximum age of playlists to consider
    :return: List of track picks from various playlists
    """
    playlist_picks = []
    playlists = sp.current_user_playlists(limit=50)['items']
    
    # Filter and sort playlists
    filtered_playlists = []
    for playlist in playlists:
        # Skip playlists that are too new
        if playlist['tracks']['total'] == 0:
            continue
        
        playlist_tracks = sp.playlist_tracks(playlist['id'], fields='items.added_at', limit=1)
        if playlist_tracks['items']:
            added_at = datetime.strptime(playlist_tracks['items'][0]['added_at'], "%Y-%m-%dT%H:%M:%SZ")
            if (datetime.utcnow() - added_at) <= timedelta(days=max_playlist_age_days):
                filtered_playlists.append({
                    'id': playlist['id'],
                    'name': playlist['name'],
                    'tracks_total': playlist['tracks']['total']
                })
    
    # Sort playlists by number of tracks (ascending) to favor less populated playlists
    filtered_playlists.sort(key=lambda x: x['tracks_total'])
    
    # Get tracks from playlists
    for playlist in filtered_playlists:
        if len(playlist_picks) >= limit:
            break
        
        offset = random.randint(0, max(0, playlist['tracks_total'] - 1))
        tracks = sp.playlist_tracks(playlist['id'], limit=1, offset=offset)
        
        if tracks['items']:
            track = tracks['items'][0]['track']
            # Ensure the track has a preview URL
            if track['preview_url']:
                playlist_picks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artists': [artist['name'] for artist in track['artists']],
                    'preview_url': track['preview_url'],
                    'playlist_name': playlist['name']
                })
    
    # If we don't have enough tracks, fill with random tracks from all playlists
    while len(playlist_picks) < limit and playlists:
        playlist = random.choice(playlists)
        offset = random.randint(0, max(0, playlist['tracks']['total'] - 1))
        tracks = sp.playlist_tracks(playlist['id'], limit=1, offset=offset)
        
        if tracks['items']:
            track = tracks['items'][0]['track']
            if track['preview_url'] and not any(pick['id'] == track['id'] for pick in playlist_picks):
                playlist_picks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artists': [artist['name'] for artist in track['artists']],
                    'preview_url': track['preview_url'],
                    'playlist_name': playlist['name']
                })
    
    return playlist_picks

@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(5))
def make_spotify_request_with_retry(sp, method, *args, **kwargs):
    """
    Makes a request to the Spotify API with retry logic in case of rate limiting.

    Args:
        sp (Spotify): The Spotify object used to make the request.
        method (str): The method to call on the Spotify object.
        *args: Variable length argument list to be passed to the method.
        **kwargs: Arbitrary keyword arguments to be passed to the method.

    Raises:
        SpotifyException: If an error occurs during the request.

    Returns:
        The result of the Spotify API request.

    """
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
    '''
    Generate personalized playlist recommendations based on user preferences.
    Args:
        client (OpenAI.Client): An instance of the OpenAI client.
        user_preferences (dict): A dictionary containing user preferences for the playlist.
        tracks (list): A list of tracks to choose from for the playlist.
        num_tracks (int, optional): The number of tracks to include in the playlist. Defaults to 30.
    Returns:
        str: The generated playlist recommendations in JSON format.
    Raises:
        Exception: If an error occurs during the recommendation generation process.
    Example:
        playlist = get_openai_recommendations(client, user_preferences, tracks, num_tracks=50)
    '''
    
    
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

        # Calculate discovery scores
        for track in all_tracks:
            track['discovery_score'] = calculate_discovery_score(track, user_profile, sp)

        # Sort tracks by discovery score
        sorted_tracks = sorted(all_tracks, key=lambda x: x['discovery_score'], reverse=True)

        split_index = int(len(sorted_tracks) * discovery_ratio)
        discovery_tracks = sorted_tracks[:split_index]
        familiar_tracks = sorted_tracks[split_index:]

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

from datetime import datetime, timedelta
import random

def get_wayback_tracks(sp, limit=5, max_recent_tracks=200, max_saved_tracks=500):
    """
    Retrieve tracks from the user's library that haven't been played recently.
    
    :param sp: Spotify client object
    :param limit: Number of "way back" tracks to return
    :param max_recent_tracks: Maximum number of recent tracks to fetch
    :param max_saved_tracks: Maximum number of saved tracks to fetch
    :return: List of "way back" tracks
    """
    # Get recently played tracks
    recent_tracks = []
    results = sp.current_user_recently_played(limit=50)
    while results['items'] and len(recent_tracks) < max_recent_tracks:
        recent_tracks.extend(results['items'])
        if results['next']:
            results = sp.next(results)
        else:
            break

    # Create a set of recently played track IDs
    recent_track_ids = {item['track']['id'] for item in recent_tracks}

    # Get user's saved tracks
    saved_tracks = []
    results = sp.current_user_saved_tracks(limit=50)
    while results['items'] and len(saved_tracks) < max_saved_tracks:
        saved_tracks.extend(results['items'])
        if results['next']:
            results = sp.next(results)
        else:
            break

    # Find tracks that are saved but not recently played
    wayback_candidates = [
        track for track in saved_tracks
        if track['track']['id'] not in recent_track_ids
    ]

    # Sort by date added (oldest first)
    wayback_candidates.sort(key=lambda x: x['added_at'])

    # Select a mix of old and relatively recent tracks
    num_old = min(limit // 2, len(wayback_candidates))
    num_recent = min(limit - num_old, len(wayback_candidates) - num_old)

    old_tracks = wayback_candidates[:num_old]
    recent_tracks = random.sample(wayback_candidates[num_old:], num_recent)

    wayback_tracks = old_tracks + recent_tracks
    random.shuffle(wayback_tracks)  # Shuffle to mix old and recent

    # Enrich track information
    for track in wayback_tracks:
        track['added_at_formatted'] = datetime.strptime(track['added_at'], "%Y-%m-%dT%H:%M:%SZ").strftime("%B %d, %Y")
        # You could add more track features here if needed

    return wayback_tracks[:limit]

def calculate_discovery_score(track, user_profile, sp):
    """
    Calculate a discovery score for a track based on the user's listening history and preferences.
    
    :param track: A dictionary containing track information
    :param user_profile: The user's Spotify profile
    :param sp: Spotify client object
    :return: A discovery score between 0 and 1, where 1 is the most discoverable
    """
    score = 0.5  # Start with a neutral score

    try:
        # Factor 1: Track popularity (less popular = more discoverable)
        popularity = track.get('popularity', 50)
        score += (100 - popularity) / 200  # Contributes up to 0.5 to the score

        # Factor 2: Artist familiarity
        artist_id = track['artists'][0]['id']
        try:
            artist_info = sp.artist(artist_id)
            artist_popularity = artist_info['popularity']
            score += (100 - artist_popularity) / 200  # Contributes up to 0.5 to the score
        except:
            pass  # If we can't get artist info, we'll skip this factor

        # Factor 3: Genre preference
        user_top_genres = get_user_top_genres(sp, limit=50)
        artist_genres = set(artist_info.get('genres', []))
        genre_overlap = len(set(genre['name'] for genre in user_top_genres) & artist_genres)
        score -= genre_overlap * 0.1  # Reduce score for each overlapping genre (max 0.5 reduction)

        # Factor 4: Recency of listening
        recent_tracks = sp.current_user_recently_played(limit=50)
        recent_track_ids = [item['track']['id'] for item in recent_tracks['items']]
        if track['id'] in recent_track_ids:
            score -= 0.3  # Significantly reduce score if recently played

        # Factor 5: Presence in user's playlists
        user_playlists = sp.current_user_playlists(limit=50)
        for playlist in user_playlists['items']:
            if sp.playlist_tracks(playlist['id'])['items']:
                playlist_track_ids = [item['track']['id'] for item in sp.playlist_tracks(playlist['id'])['items']]
                if track['id'] in playlist_track_ids:
                    score -= 0.2  # Reduce score if track is in user's playlist
                    break  # No need to check other playlists

    except Exception as e:
        logger.error(f"Error calculating discovery score: {str(e)}")
        return 0.5  # Return neutral score if there's an error

    # Ensure the score is between 0 and 1
    return max(0, min(score, 1))


def categorize_mood(audio_features):
    """
    Categorize the mood of a track based on its audio features.
    
    :param audio_features: A dictionary of audio features from Spotify's API
    :return: A string representing the mood category
    """
    valence = audio_features['valence']
    energy = audio_features['energy']
    
    if valence > 0.6 and energy > 0.6:
        return 'Happy'
    elif valence < 0.4 and energy < 0.4:
        return 'Sad'
    elif valence < 0.4 and energy > 0.6:
        return 'Angry'
    elif valence > 0.6 and energy < 0.4:
        return 'Relaxed'
    elif energy > 0.7:
        return 'Energetic'
    elif valence < 0.3:
        return 'Melancholic'
    else:
        return 'Neutral'


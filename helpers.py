import os
import json
import random
import re
import time
import logging
from collections import Counter
from datetime import datetime, timedelta

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, HiddenField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, NumberRange
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


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

# Set up logging for helpers
helper_logger = logging.getLogger('helpers')
helper_logger.setLevel(logging.DEBUG)

# Create a file handler
file_handler = logging.FileHandler('logs/helpers.log')
file_handler.setLevel(logging.DEBUG)

# Create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handlers to the logger
helper_logger.addHandler(file_handler)
helper_logger.addHandler(console_handler)

# Cache to store API responses
cache = {}

class PlaylistForm(FlaskForm):
    name = StringField('Name')
    mood = IntegerField('Current Mood')
    desired_mood = IntegerField('Desired Mood')
    activity = StringField('Activity')
    energy_level = IntegerField('Energy Level', validators=[DataRequired(), NumberRange(min=0, max=100)])
    time_of_day = SelectField('Time of Day', choices=[('Morning', 'Morning'), ('Afternoon', 'Afternoon'), ('Evening', 'Evening'), ('Night', 'Night')])
    duration = IntegerField('Duration (minutes)', validators=[DataRequired(), NumberRange(min=1, max=300, message="Please enter a duration between 1 and 300 minutes.")])
    discovery_level = IntegerField('Discovery Level')
    favorite_artists = StringField('Favorite Artists')
    favorite_genres = StringField('Favorite Genres')
    playlist_description = TextAreaField('Playlist Description')
    submit = SubmitField('Generate Playlist')

def cached_request(key, ttl_seconds, fetch_function, *args, **kwargs):
    """Cache the result of a function call for a specified time to reduce redundant API requests."""
    current_time = time.time()
    if key in cache and current_time - cache[key]['timestamp'] < ttl_seconds:
        return cache[key]['data']
    
    data = fetch_function(*args, **kwargs)
    cache[key] = {'data': data, 'timestamp': current_time}
    return data

def get_playlist_picks(sp, limit=10, max_playlist_age_days=365):
    """Retrieve tracks from the user's less frequently listened to playlists."""
    helper_logger.debug(f"Fetching playlist picks. Limit: {limit}, Max age: {max_playlist_age_days} days")
    
    return []
    
#     playlist_picks = []

#     def fetch_user_playlists():
#         helper_logger.debug("Fetching user playlists")
#         try:
#             cache_key = f"user_playlists_{sp.current_user()['id']}"
#             cached_playlists = cache.get(cache_key)
#             if cached_playlists and time.time() - cached_playlists['timestamp'] < 3600:  # Cache for 1 hour
#                 helper_logger.debug("Retrieved playlists from cache")
#                 return cached_playlists['data']

#             playlists = make_spotify_request_with_retry(sp, 'current_user_playlists', limit=50)['items']
#             helper_logger.debug(f"Successfully fetched {len(playlists)} user playlists")
            
#             # Cache the playlists
#             cache[cache_key] = {'data': playlists, 'timestamp': time.time()}
            
#             return playlists
#         except Exception as e:
#             helper_logger.error(f"Error fetching user playlists: {str(e)}")
#             raise

#     try:
#         playlists = fetch_user_playlists()
#         helper_logger.debug(f"Retrieved {len(playlists)} user playlists")
        
#         # Filter and sort playlists
#         filtered_playlists = []
#         for playlist in playlists:
#             if playlist['tracks']['total'] == 0:
#                 continue
            
#             try:
#                 playlist_tracks = make_spotify_request_with_retry(sp, 'playlist_tracks', playlist['id'], fields='items.added_at', limit=1)
#                 if playlist_tracks['items']:
#                     added_at = datetime.strptime(playlist_tracks['items'][0]['added_at'], "%Y-%m-%dT%H:%M:%SZ")
#                     if (datetime.utcnow() - added_at) <= timedelta(days=max_playlist_age_days):
#                         filtered_playlists.append({
#                             'id': playlist['id'],
#                             'name': playlist['name'],
#                             'tracks_total': playlist['tracks']['total']
#                         })
#             except Exception as e:
#                 helper_logger.error(f"Error processing playlist {playlist['id']}: {str(e)}")
        
#         helper_logger.debug(f"Filtered to {len(filtered_playlists)} playlists within age limit")
        
#         # Sort playlists by number of tracks (ascending) to favor less populated playlists
#         filtered_playlists.sort(key=lambda x: x['tracks_total'])
        
#         # Get tracks from playlists
#         for playlist in filtered_playlists:
#             if len(playlist_picks) >= limit:
#                 break
            
#             try:
#                 offset = random.randint(0, max(0, playlist['tracks_total'] - 1))
#                 tracks = make_spotify_request_with_retry(sp, 'playlist_tracks', playlist['id'], limit=1, offset=offset)
                
#                 if tracks['items']:
#                     track = tracks['items'][0]['track']
#                     if track['preview_url']:
#                         playlist_picks.append({
#                             'id': track['id'],
#                             'name': track['name'],
#                             'artists': [artist['name'] for artist in track['artists']],
#                             'preview_url': track['preview_url'],
#                             'playlist_name': playlist['name']
#                         })
#             except Exception as e:
#                 helper_logger.error(f"Error fetching tracks from playlist {playlist['id']}: {str(e)}")
        
#         helper_logger.debug(f"Fetched {len(playlist_picks)} tracks from filtered playlists")
        
#         # If we don't have enough tracks, fill with random tracks from all playlists
#         attempts = 0
#         while len(playlist_picks) < limit and playlists and attempts < 50:
#             attempts += 1
#             playlist = random.choice(playlists)
#             try:
#                 offset = random.randint(0, max(0, playlist['tracks']['total'] - 1))
#                 tracks = make_spotify_request_with_retry(sp, 'playlist_tracks', playlist['id'], limit=1, offset=offset)
                
#                 if tracks['items']:
#                     track = tracks['items'][0]['track']
#                     if track['preview_url'] and not any(pick['id'] == track['id'] for pick in playlist_picks):
#                         playlist_picks.append({
#                             'id': track['id'],
#                             'name': track['name'],
#                             'artists': [artist['name'] for artist in track['artists']],
#                             'preview_url': track['preview_url'],
#                             'playlist_name': playlist['name']
#                         })
#             except Exception as e:
#                 helper_logger.error(f"Error fetching random track from playlist {playlist['id']}: {str(e)}")
        
#         helper_logger.debug(f"Final number of playlist picks: {len(playlist_picks)}")

#     except Exception as e:
#         helper_logger.error(f"Unexpected error in get_playlist_picks: {str(e)}", exc_info=True)
#         return []

#     return playlist_picks
      

def filter_playlists_by_age(sp, playlists, max_playlist_age_days):
    """Filter playlists by age and sort by number of tracks."""
    filtered_playlists = []
    for playlist in playlists:
        if playlist['tracks']['total'] == 0:
            continue
        
        try:
            playlist_tracks = make_spotify_request_with_retry(sp, 'playlist_tracks', playlist['id'], fields='items.added_at', limit=1)
            if playlist_tracks['items']:
                added_at = datetime.strptime(playlist_tracks['items'][0]['added_at'], "%Y-%m-%dT%H:%M:%SZ")
                if (datetime.utcnow() - added_at) <= timedelta(days=max_playlist_age_days):
                    filtered_playlists.append({
                        'id': playlist['id'],
                        'name': playlist['name'],
                        'tracks_total': playlist['tracks']['total']
                    })
        except Exception as e:
            helper_logger.error(f"Error processing playlist {playlist['id']}: {str(e)}")
    
    filtered_playlists.sort(key=lambda x: x['tracks_total'])
    return filtered_playlists

def fetch_tracks_from_playlists(sp, playlists, limit):
    """Fetch tracks from a list of playlists."""
    playlist_picks = []
    for playlist in playlists:
        if len(playlist_picks) >= limit:
            break
        
        try:
            offset = random.randint(0, max(0, playlist['tracks_total'] - 1))
            tracks = make_spotify_request_with_retry(sp, 'playlist_tracks', playlist['id'], limit=1, offset=offset)
            
            if tracks['items']:
                track = tracks['items'][0]['track']
                if track['preview_url']:
                    playlist_picks.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artists': [artist['name'] for artist in track['artists']],
                        'preview_url': track['preview_url'],
                        'playlist_name': playlist['name']
                    })
        except Exception as e:
            helper_logger.error(f"Error fetching tracks from playlist {playlist['id']}: {str(e)}")
    
    return playlist_picks

def fill_with_random_tracks(sp, playlists, playlist_picks, limit):
    """Fill the list with random tracks if not enough tracks were found."""
    attempts = 0
    while len(playlist_picks) < limit and playlists and attempts < 50:
        attempts += 1
        playlist = random.choice(playlists)
        try:
            offset = random.randint(0, max(0, playlist['tracks']['total'] - 1))
            tracks = make_spotify_request_with_retry(sp, 'playlist_tracks', playlist['id'], limit=1, offset=offset)
            
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
        except Exception as e:
            helper_logger.error(f"Error fetching random track from playlist {playlist['id']}: {str(e)}")
    
    return playlist_picks

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(SpotifyException)
)
def make_spotify_request_with_retry(sp, method, *args, **kwargs):
    """Make a Spotify API request with retries and exponential backoff."""
    try:
        return getattr(sp, method)(*args, **kwargs)
    except SpotifyException as e:
        if e.http_status == 429:
            retry_after = int(e.headers.get('Retry-After', 1))
            helper_logger.warning(f"Rate limited. Waiting for {retry_after} seconds before retrying.")
            time.sleep(retry_after)
        helper_logger.error(f"Spotify API error: {e}")
        raise
    
def get_openai_recommendations(client, user_preferences, tracks, num_tracks=30):
    """Generate playlist recommendations using OpenAI based on user preferences and available tracks."""
    try:
        familiar_tracks = [t for t in tracks if t.get('familiarity', 0) > 0.5]
        discovery_tracks = [t for t in tracks if t.get('familiarity', 0) <= 0.5]

        familiar_track_info = [f"{track['name']} by {', '.join([artist['name'] for artist in track['artists']])}" for track in familiar_tracks[:50]]
        discovery_track_info = [f"{track['name']} by {', '.join([artist['name'] for artist in track['artists']])}" for track in discovery_tracks[:50]]

        prompt = f"""
        As a music expert AI assistant, create a personalized playlist based on the following preferences:
        - Current mood: {user_preferences['current_mood']} (0-100, where 0 is very negative and 100 is very positive)
        - Desired mood: {user_preferences['desired_mood']} (0-100, same scale as current mood)
        - Activity: {user_preferences['activity']}
        - Energy level: {user_preferences['energy_level']} (0-100, where 0 is very low energy and 100 is very high energy)
        - Time of day: {user_preferences['time_of_day']}
        - Discovery level: {user_preferences['discovery_level']} (0 = only familiar tracks, 1 = maximum discovery)
        - Playlist description: {user_preferences['playlist_description']}

        Provide a list of {num_tracks} tracks that best match these preferences, considering both familiar and discovery tracks.
        The response should be in the following JSON format:

        ```json
        {{
            "playlist_description": "A brief description of the playlist, explaining how it meets the user's preferences",
            "tracks": [
                {{
                    "name": "Track Name",
                    "artist": "Artist Name",
                    "reason": "A brief explanation of why this track was chosen and how it fits the playlist"
                }}
            ]
        }}
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
    """Fetch the user's Spotify profile."""
    try:
        helper_logger.debug("Fetching user profile")
        profile = sp.me()
        helper_logger.debug(f"User profile fetched successfully: {profile['id']}")
        return profile
    except Exception as e:
        helper_logger.error(f"Error fetching user profile: {str(e)}")
        return None

def get_user_top_artists(sp, limit=10):
    """Fetch the user's top artists."""
    try:
        helper_logger.debug(f"Fetching user's top {limit} artists")
        top_artists = sp.current_user_top_artists(limit=limit)
        helper_logger.debug(f"Successfully fetched {len(top_artists['items'])} top artists")
        return [{"name": artist['name'], "id": artist['id']} for artist in top_artists['items']]
    except Exception as e:
        helper_logger.error(f"Error fetching top artists: {str(e)}")
        return []

def get_user_top_genres(sp, limit=10):
    """Fetch the user's top genres."""
    try:
        helper_logger.debug("Fetching user's top genres")
        top_artists = sp.current_user_top_artists(limit=50)
        genres = [genre for artist in top_artists['items'] for genre in artist['genres']]
        genre_counts = Counter(genres)
        top_genres = [{"name": genre, "count": count} for genre, count in genre_counts.most_common(limit)]
        helper_logger.debug(f"Successfully fetched {len(top_genres)} top genres")
        return top_genres
    except Exception as e:
        helper_logger.error(f"Error fetching top genres: {str(e)}")
        return []

def get_tracks_from_favorites(sp, favorite_artists, favorite_genres, limit=50):
    """Fetch tracks based on the user's favorite artists and genres."""
    tracks = []
    try:
        for artist in favorite_artists:
            results = make_spotify_request_with_retry(sp, 'search', q=f'artist:{artist}', type='track', limit=10)
            if 'tracks' in results and 'items' in results['tracks']:
                tracks.extend(results['tracks']['items'])
        for genre in favorite_genres:
            results = make_spotify_request_with_retry(sp, 'search', q=f'genre:{genre}', type='track', limit=10)
            if 'tracks' in results and 'items' in results['tracks']:
                tracks.extend(results['tracks']['items'])
        logger.debug(f"Fetched {len(tracks)} tracks from favorites")
        return tracks[:limit]
    except Exception as e:
        logger.error(f"Error in get_tracks_from_favorites: {str(e)}", exc_info=True)
        return []

def get_user_top_and_recent_tracks(sp, limit=50):
    """Fetch the user's top and recent tracks."""
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
    """Fetch new releases from Spotify."""
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
    """Fetch tracks from new artists."""
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

def get_expanded_track_pool(sp, favorite_artists, favorite_genres, user_profile, discovery_ratio=0.3):
    """Expand the pool of tracks to include familiar and discovery tracks."""
    logger.debug(f"Starting get_expanded_track_pool with favorite_artists: {favorite_artists}, favorite_genres: {favorite_genres}")

    try:
        favorite_artists = [artist.strip() for artist in favorite_artists.split(',')] if isinstance(favorite_artists, str) else favorite_artists
        favorite_genres = [genre.strip() for genre in favorite_genres.split(',')] if isinstance(favorite_genres, str) else favorite_genres

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

        all_tracks = list({track['id']: track for track in all_tracks}.values())
        logger.debug(f"Total tracks after deduplication: {len(all_tracks)}")

        track_ids = [track['id'] for track in all_tracks]
        audio_features = []

        batch_size = 100
        for i in range(0, len(track_ids), batch_size):
            batch = track_ids[i:i+batch_size]
            try:
                batch_features = sp.audio_features(batch)
                audio_features.extend(batch_features)
                logger.debug(f"Fetched audio features for batch {i // batch_size + 1}")
            except Exception as e:
                logger.error(f"Error fetching audio features for batch {i // batch_size + 1}: {str(e)}")

        for track, features in zip(all_tracks, audio_features):
            if features:
                try:
                    logger.debug(f"Calculating discovery score for track: {track.get('name', 'Unknown')} (ID: {track.get('id', 'Unknown')})")
                    track['discovery_score'] = calculate_discovery_score(track, user_profile, sp)
                    logger.debug(f"Discovery score calculated: {track['discovery_score']}")
                    track['audio_analysis'] = analyze_audio_features(features)
                except Exception as e:
                    logger.error(f"Error calculating discovery score for track {track.get('id', 'Unknown')}: {str(e)}")
                    track['discovery_score'] = 0.5  # Assign a neutral score if calculation fails
            else:
                logger.warning(f"No audio features found for track {track.get('id', 'Unknown')}")
                track['discovery_score'] = 0.5  # Assign a neutral score if no features

        sorted_tracks = sorted(all_tracks, key=lambda x: x.get('discovery_score', 0), reverse=True)
        split_index = int(len(sorted_tracks) * discovery_ratio)
        discovery_tracks = sorted_tracks[:split_index]
        familiar_tracks = sorted_tracks[split_index:]

        logger.debug(f"Final track pool - Familiar tracks: {len(familiar_tracks)}, Discovery tracks: {len(discovery_tracks)}")

        return familiar_tracks, discovery_tracks

    except Exception as e:
        logger.error(f"Error in get_expanded_track_pool: {str(e)}", exc_info=True)
        raise

def parse_openai_response(response):
    """Parse the response from OpenAI to extract recommended tracks and explanations."""
    logger.debug("Starting to parse OpenAI response")
    logger.debug(f"Raw OpenAI response: {response}")

    try:
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)

        if json_match:
            json_content = json_match.group(1)
            logger.debug(f"Extracted JSON content: {json_content}")

            response_json = json.loads(json_content)

            recommended_tracks = response_json.get("tracks", [])
            playlist_description = response_json.get("playlist_description", "")

            explanation_match = re.search(r'```\s*([\s\S]*)$', response, re.DOTALL)
            explanation = explanation_match.group(1).strip() if explanation_match else ""

            logger.info(f"Parsed {len(recommended_tracks)} tracks from OpenAI response")
            logger.debug(f"Playlist description: {playlist_description}")
            logger.debug(f"Explanation: {explanation[:100]}...")

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
    """Find the recommended tracks on Spotify."""
    selected_tracks = []
    log_file = 'logs/search_queries.txt'

    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("Spotify Search Queries:\n\n")

    for track in recommended_tracks:
        try:
            track_name = track['name']
            artist_name = track['artist']

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
            if e.http_status == 429:
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

def get_wayback_tracks(sp, limit=5, max_recent_tracks=200, max_saved_tracks=500):
    """Retrieve tracks from the user's library that haven't been played recently."""
    helper_logger.debug(f"Fetching 'Way Back' tracks. Limit: {limit}, Max recent: {max_recent_tracks}, Max saved: {max_saved_tracks}")

    recent_tracks = []
    results = sp.current_user_recently_played(limit=50)
    while results['items'] and len(recent_tracks) < max_recent_tracks:
        recent_tracks.extend(results['items'])
        if results['next']:
            results = sp.next(results)
        else:
            break
    helper_logger.debug(f"Fetched {len(recent_tracks)} recent tracks")

    recent_track_ids = {item['track']['id'] for item in recent_tracks}

    saved_tracks = []
    results = sp.current_user_saved_tracks(limit=50)
    while results['items'] and len(saved_tracks) < max_saved_tracks:
        saved_tracks.extend(results['items'])
        if results['next']:
            results = sp.next(results)
        else:
            break
    helper_logger.debug(f"Fetched {len(saved_tracks)} saved tracks")

    wayback_candidates = [track for track in saved_tracks if track['track']['id'] not in recent_track_ids]
    helper_logger.debug(f"Found {len(wayback_candidates)} wayback candidates")

    wayback_candidates.sort(key=lambda x: x['added_at'])

    num_old = min(limit // 2, len(wayback_candidates))
    num_recent = min(limit - num_old, len(wayback_candidates) - num_old)

    old_tracks = wayback_candidates[:num_old]
    recent_tracks = random.sample(wayback_candidates[num_old:], num_recent) if num_recent > 0 else []

    wayback_tracks = old_tracks + recent_tracks
    random.shuffle(wayback_tracks)

    for track in wayback_tracks:
        track['added_at_formatted'] = datetime.strptime(track['added_at'], "%Y-%m-%dT%H:%M:%SZ").strftime("%B %d, %Y")

    final_tracks = wayback_tracks[:limit]
    helper_logger.debug(f"Returning {len(final_tracks)} 'Way Back' tracks")

    return final_tracks

def calculate_discovery_score(track, user_profile, sp):
    """Calculate a discovery score for a track based on the user's listening history and preferences."""
    logger.debug(f"Calculating discovery score for track: {track.get('id', 'Unknown ID')}")
    logger.debug(f"Track data: {track}")
    logger.debug(f"User profile: {user_profile}")

    score = 0.5

    try:
        popularity = track.get('popularity')
        if popularity is not None:
            score += (100 - popularity) / 200
            logger.debug(f"Adjusted score based on popularity: {score}")

        if track.get('artists') and len(track['artists']) > 0:
            artist_id = track['artists'][0].get('id')
            if artist_id:
                try:
                    artist_info = sp.artist(artist_id)
                    artist_popularity = artist_info.get('popularity')
                    if artist_popularity is not None:
                        score += (100 - artist_popularity) / 200
                        logger.debug(f"Adjusted score based on artist popularity: {score}")
                except Exception as e:
                    logger.warning(f"Error fetching artist info: {str(e)}")

        try:
            user_top_genres = get_user_top_genres(sp, limit=50)
            if track.get('artists') and track['artists']:
                artist_id = track['artists'][0].get('id')
                if artist_id:
                    artist_info = sp.artist(artist_id)
                    artist_genres = set(artist_info.get('genres', []))
                    genre_overlap = len(set(genre['name'] for genre in user_top_genres) & artist_genres)
                    score_adjustment = genre_overlap * 0.1
                    score -= score_adjustment
                    logger.debug(f"Adjusted score based on genre overlap: -{score_adjustment}")
        except Exception as e:
            logger.warning(f"Error in genre preference calculation: {str(e)}")

        try:
            recent_tracks = sp.current_user_recently_played(limit=50)
            recent_track_ids = [item['track']['id'] for item in recent_tracks['items'] if item.get('track')]
            if track.get('id') in recent_track_ids:
                score -= 0.3
                logger.debug("Reduced score by 0.3 due to recent play")
        except Exception as e:
            logger.warning(f"Error fetching recently played tracks: {str(e)}")

        try:
            user_playlists = sp.current_user_playlists(limit=50)
            for playlist in user_playlists['items']:
                if playlist.get('tracks', {}).get('total', 0) > 0:
                    playlist_tracks = sp.playlist_tracks(playlist['id'])
                    playlist_track_ids = [item['track']['id'] for item in playlist_tracks['items'] if item.get('track')]
                    if track.get('id') in playlist_track_ids:
                        score -= 0.2
                        logger.debug("Reduced score by 0.2 due to presence in user playlist")
                        break
        except Exception as e:
            logger.warning(f"Error checking user playlists: {str(e)}")

    except Exception as e:
        logger.error(f"Error calculating discovery score: {str(e)}", exc_info=True)
        return 0.5

    final_score = max(0, min(score, 1))
    logger.debug(f"Final discovery score: {final_score}")
    return final_score

def analyze_audio_features(audio_features):
    """Provide a comprehensive analysis of a track's audio features."""
    def calculate_happiness(features):
        return (features['valence'] * 0.6 + features['energy'] * 0.4) * 100

    def calculate_relaxation(features):
        return ((1 - features['energy']) * 0.5 + features['acousticness'] * 0.3 + (1 - features['loudness'] / -60) * 0.2) * 100

    def calculate_intensity(features):
        return (features['energy'] * 0.4 + features['loudness'] / -60 * 0.3 + features['tempo'] / 200 * 0.3) * 100

    def categorize_tempo(tempo):
        if tempo < 60:
            return "Very Slow"
        elif 60 <= tempo < 90:
            return "Slow"
        elif 90 <= tempo < 120:
            return "Moderate"
        elif 120 <= tempo < 150:
            return "Fast"
        else:
            return "Very Fast"

    def suggest_activities(features):
        activities = []
        if features['danceability'] > 0.7:
            activities.append("Dancing")
        if features['energy'] > 0.8:
            activities.append("Working Out")
        if features['acousticness'] > 0.7:
            activities.append("Relaxing")
        if features['instrumentalness'] > 0.5:
            activities.append("Studying")
        if features['valence'] > 0.7:
            activities.append("Partying")
        if not activities:
            activities.append("General Listening")
        return activities

    def suggest_time_of_day(features):
        energy = features['energy']
        valence = features['valence']
        if energy > 0.7 and valence > 0.7:
            return "Morning"
        elif energy > 0.5 and valence > 0.5:
            return "Afternoon"
        elif energy < 0.4 and valence < 0.4:
            return "Night"
        else:
            return "Evening"

    return {
        'mood_scores': {
            'happiness': calculate_happiness(audio_features),
            'energy': audio_features['energy'] * 100,
            'relaxation': calculate_relaxation(audio_features),
            'intensity': calculate_intensity(audio_features)
        },
        'suitable_activities': suggest_activities(audio_features),
        'best_time_of_day': suggest_time_of_day(audio_features),
        'danceability': audio_features['danceability'] * 100,
        'acousticness': audio_features['acousticness'] * 100,
        'instrumentalness': audio_features['instrumentalness'] * 100,
        'tempo_category': categorize_tempo(audio_features['tempo']),
        'tempo': audio_features['tempo'],
        'key': audio_features['key'],
        'mode': audio_features['mode'],
        'time_signature': audio_features['time_signature']
    }

